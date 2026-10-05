"""Automatic archive maintenance.

Runs in a background thread and, on every cycle:
  1. Archives every race of today/yesterday whose scheduled end
     (start + buffer) is more than ARCHIVE_DELAY_AFTER_END_MIN in the past
     and whose results are available on Geny.
  2. Deletes every archived race from days older than RETENTION_DAYS
     (rolling window: the oldest day disappears automatically).
"""

import threading
import time
from datetime import datetime, timedelta, date

_CACHE_REBUILD_LOCK = threading.Lock()

def _rebuild_win_dna():
    if not _CACHE_REBUILD_LOCK.acquire(blocking=False):
        return
    def _do():
        try:
            from coupsur.win_dna import rebuild
            rebuild()
        except Exception:
            pass
        finally:
            _CACHE_REBUILD_LOCK.release()
    threading.Thread(target=_do, daemon=True).start()

# --- tunable settings ---
ARCHIVE_DELAY_AFTER_END_MIN = 60   # minutes after the race ends
RACE_END_BUFFER_MIN = 15           # estimated race duration before "end" is reached
RETENTION_DAYS = 7                 # only relevant once auto-purge is enabled
PURGE_ENABLED = False              # auto-purge is OFF by default (see purge below)
CYCLE_SECONDS = 300                # run every 5 minutes

_state = {
    "running": False,
    "cycle_seconds": CYCLE_SECONDS,
    "delay_after_end_min": ARCHIVE_DELAY_AFTER_END_MIN,
    "buffer_min": RACE_END_BUFFER_MIN,
    "retention_days": RETENTION_DAYS,
    "purge_enabled": PURGE_ENABLED,
    "last_run": None,
    "last_archived": [],
    "last_purged": 0,
    "last_error": None,
}


def _parse_time(d, t):
    t = (t or "").strip()
    if not t:
        return None
    parts = t.split(":")
    try:
        h = int(parts[0])
        m = int(parts[1]) if len(parts) > 1 else 0
        s = int(parts[2]) if len(parts) > 2 else 0
        return datetime.combine(d, datetime.min.time().replace(hour=h, minute=m, second=s))
    except ValueError:
        return None


def _has_results(race_data):
    course = race_data.get("course", {}) or {}
    if course.get("arrivee"):
        return True
    return any((p or {}).get("rang") for p in race_data.get("participants", []))


# --- Turfomania bulk archive watchdog --------------------------------
# Every cycle we verify the long-running turfomania_archive.py process is
# still alive and restart it if it died (it resumes via progress file).
TURFOMANIA_SCRIPT = "turfomania_archive.py"
TURFOMANIA_LOG = r"C:\bahja-pmu\backend\logs\turfomania_archive.log"
TURFOMANIA_PROGRESS = r"C:\bahja-pmu\backend\turfomania_progress.txt"
TURFOMANIA_START_DATE = "2020-01-01"
TURFOMANIA_DELAY = 1.6

_archive_state = {
    "enabled": False,
    "last_check": None,
    "pid": None,
    "restarted_count": 0,
    "last_error": None,
}


def set_turfomania_watchdog(enabled=True):
    """Enable/disable the auto-restart watchdog for the bulk download."""
    _archive_state["enabled"] = bool(enabled)


def _turfomania_pid():
    """Return the PID of a running turfomania_archive.py process, or None."""
    import subprocess
    try:
        out = subprocess.check_output(
            ["powershell", "-NoProfile", "-Command",
             "Get-CimInstance Win32_Process -Filter \"Name='python.exe'\" | "
             "Where-Object { $_.CommandLine -like '*turfomania_archive.py*' } | "
             "Select-Object -ExpandProperty ProcessId"],
            timeout=20,
        ).decode().strip()
    except Exception:
        return None
    for line in out.splitlines():
        line = line.strip()
        if line.isdigit():
            return int(line)
    return None


def _ensure_turfomania_archive():
    if not _archive_state["enabled"]:
        return
    import subprocess
    import os
    _archive_state["last_check"] = datetime.now().isoformat()
    pid = _turfomania_pid()
    if pid is not None:
        _archive_state["pid"] = pid
        return  # still running, nothing to do
    _archive_state["pid"] = None
    try:
        os.makedirs(os.path.dirname(TURFOMANIA_LOG), exist_ok=True)
        subprocess.Popen(
            [
                "C:\\Python314\\python.exe",
                TURFOMANIA_SCRIPT,
                "--start", TURFOMANIA_START_DATE,
                "--delay", str(TURFOMANIA_DELAY),
                "--logfile", TURFOMANIA_LOG,
            ],
            cwd=r"C:\bahja-pmu\backend",
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        _archive_state["restarted_count"] += 1
        _archive_state["last_error"] = None
    except Exception as e:
        _archive_state["last_error"] = str(e)


def run_once():
    from scraper.geny_scraper import get_scraper
    from database import get_archived_race, save_geny_race, purge_oldest_day

    scraper = get_scraper()
    today = date.today()
    archived_ok = []
    errors = []

    for d in {today, today - timedelta(days=1)}:
        try:
            prog = scraper.fetch_programme(d)
        except Exception as e:
            errors.append(f"programme {d}: {e}")
            continue
        for m in prog.get("meetings", []):
            for c in m.get("courses", []):
                cid = c.get("id")
                start = _parse_time(d, c.get("time"))
                if not cid or start is None:
                    continue
                if get_archived_race(cid) is not None:
                    continue
                end_plus_delay = start + timedelta(
                    minutes=ARCHIVE_DELAY_AFTER_END_MIN + RACE_END_BUFFER_MIN
                )
                if datetime.now() < end_plus_delay:
                    continue
                try:
                    race_data = scraper.fetch_race_details(cid)
                    if race_data is None or not _has_results(race_data):
                        continue
                    save_geny_race(cid, race_data)
                    archived_ok.append(cid)
                except Exception as e:
                    errors.append(f"race {cid}: {e}")

    if archived_ok:
        _rebuild_win_dna()

    # Safe purge: only ever remove the SINGLE oldest day of the archive,
    # and only when it is older than RETENTION_DAYS. Disabled by default.
    purged = 0
    if PURGE_ENABLED:
        try:
            from database import list_archive_dates
            dates = list_archive_dates()
            if dates:
                oldest = dates[-1]  # list is DESC, oldest is last
                try:
                    if (today - datetime.strptime(oldest, "%Y-%m-%d").date()) > timedelta(days=RETENTION_DAYS):
                        purged = purge_oldest_day()
                except ValueError:
                    errors.append(f"purge: bad date {oldest}")
        except Exception as e:
            errors.append(f"purge: {e}")

    _state.update({
        "last_run": datetime.now().isoformat(),
        "last_archived": archived_ok,
        "last_purged": purged,
        "last_error": errors[-1] if errors else None,
    })

    # Watchdog: restart the bulk Turfomania archive if it stopped.
    try:
        _ensure_turfomania_archive()
    except Exception as e:
        _archive_state["last_error"] = str(e)

    return archived_ok, purged, errors


def _loop():
    while True:
        try:
            run_once()
        except Exception as e:
            _state["last_error"] = str(e)
        time.sleep(CYCLE_SECONDS)


def start():
    if _state["running"]:
        return
    _state["running"] = True
    threading.Thread(target=_loop, daemon=True).start()


def status():
    st = dict(_state)
    st["turfomania_archive"] = dict(_archive_state)
    return st
