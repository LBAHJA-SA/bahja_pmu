"""Daily archive update, meant to be run once a night at 00:00.

The backtest needs two things per race: the press Synthese and the result. The
Synthese comes from the press collector, the result comes from the archive
collector, and both already exist as code but the archive collector only ever ran
inside the Flask process, so it stopped whenever the server was closed. That is
why the sample stopped at 29 September while the site kept showing 30 September.

This runs both, standalone, and then writes the report, so the tables can be
rebuilt without remembering a command. It is idempotent: re-running it on a day
that is already stored changes nothing and says so.

Run by hand the same way the scheduled task runs it:

    python daily_update.py
"""

import os
import sys
import traceback
from datetime import datetime, timedelta, date

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
os.chdir(HERE)

LOG = os.path.join(HERE, "logs", "daily_update.log")


def log(msg):
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = "[%s] %s" % (stamp, msg)
    print(line, flush=True)
    try:
        os.makedirs(os.path.dirname(LOG), exist_ok=True)
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def step_press():
    """The press list, and yesterday's result filed against yesterday."""
    from scraper.press_archive import save_today
    n = save_today(verbose=True)
    log("press collector: %d row(s) written" % n)
    return n


def step_archive():
    """Every race of today and yesterday whose result is out gets archived.

    This is the same work the server does every five minutes, called once here so
    it does not depend on the server being up.
    """
    import auto_maintenance
    auto_maintenance.PURGE_ENABLED = False      # never delete while collecting
    archived, purged, errors = auto_maintenance.run_once()
    log("archive collector: %d race(s) archived, %d error(s)"
        % (len(archived), len(errors)))
    for e in errors[:5]:
        log("  error: %s" % e)
    return len(archived)


def step_report():
    """Rebuild the scoring tables from what is stored, and print them."""
    import sqlite3
    from database import DB_PATH
    conn = sqlite3.connect("file:%s?mode=ro" % DB_PATH.replace("\\", "/"), uri=True)
    conn.row_factory = sqlite3.Row
    n_days = conn.execute("SELECT COUNT(*) FROM presse_synthese").fetchone()[0]
    n_res = conn.execute(
        "SELECT COUNT(*) FROM races r JOIN presse_synthese p ON p.date = r.date "
        " AND UPPER(SUBSTR(p.hippodrome,1,6)) = UPPER(SUBSTR(r.hippodrome,1,6)) "
        "WHERE r.quinte=1 AND r.arrivee IS NOT NULL AND r.arrivee<>'' "
        "AND p.synthese IS NOT NULL").fetchone()[0]
    last = conn.execute(
        "SELECT MAX(r.date) FROM races r JOIN presse_synthese p ON p.date = r.date "
        " AND UPPER(SUBSTR(p.hippodrome,1,6)) = UPPER(SUBSTR(r.hippodrome,1,6)) "
        "WHERE r.quinte=1 AND r.arrivee IS NOT NULL AND r.arrivee<>'' "
        "AND p.synthese IS NOT NULL").fetchone()[0]
    newest = conn.execute("SELECT MAX(date) FROM races").fetchone()[0]
    conn.close()
    log("press days stored: %d" % n_days)
    log("scorable races: %d, newest %s" % (n_res, last))
    log("newest race of any kind: %s" % newest)
    return n_res


def main():
    log("---- daily update starting ----")
    ok = True
    for name, fn in (("press", step_press), ("archive", step_archive),
                     ("report", step_report)):
        try:
            fn()
        except Exception as e:
            ok = False
            log("%s step FAILED: %s" % (name, e))
            log(traceback.format_exc().strip().replace("\n", " | "))
    log("---- daily update finished, %s ----" % ("clean" if ok else "with errors"))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
