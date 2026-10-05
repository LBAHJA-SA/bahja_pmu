"""The daily job. Nothing here is clever, it just has to run every day.

The archive stopped on 2026-09-21 because nothing was scheduled to continue
it. Five days of Quinté, and the two races the user had written out by hand,
were simply absent. This is the job that stops that happening.

  1. archive yesterday's races, and repair any recent race still missing a
     result
  2. save the press synthesis, which the site only serves for three days
  3. report both, and write a line to scraper/press_daily.log

Run it by hand:   python daily_job.py
Run it on a date: python daily_job.py 2026-09-25
"""
import os
import sys
import traceback
from datetime import date, datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
os.chdir(os.path.dirname(os.path.abspath(__file__)))

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                   "scraper", "press_daily.log")


def say(msg):
    line = f"{datetime.now().isoformat(timespec='seconds')}  {msg}"
    print(line, flush=True)
    try:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(line + "\n")
    except Exception:
        pass


def archive_races(target):
    try:
        from pmu_archive import (archive_date_pmu,
                                 update_missing_results_pmu,
                                 reverify_recent)
        saved, with_res, skipped = archive_date_pmu(target)
        say(f"races {target}: saved={saved} with_result={with_res} "
            f"pending={skipped}")
        try:
            say(f"  repaired results: {update_missing_results_pmu(8)}")
        except Exception as e:
            say(f"  repair pass failed: {e}")
        try:
            say(f"  reverified: {reverify_recent(3)}")
        except Exception as e:
            say(f"  reverify failed: {e}")
        return saved
    except Exception as e:
        say(f"races {target} FAILED: {e}")
        say(traceback.format_exc().strip().replace("\n", " | "))
        return 0


def save_press():
    try:
        from scraper.turfinfo_scraper import fetch_daily
        d = fetch_daily()
        if not d.get("date") or len(d.get("synthese") or []) < 14:
            say(f"press: nothing usable on the page "
                f"(label={d.get('date')}, n={len(d.get('synthese') or [])})")
            return 0
        from database import get_db
        conn = get_db()
        import json
        conn.execute(
            """INSERT INTO presse_synthese
                 (date, hippodrome, prix, synthese, resultat, source, fetched_at)
               VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP)
               ON CONFLICT(date) DO UPDATE SET
                 hippodrome=COALESCE(excluded.hippodrome, presse_synthese.hippodrome),
                 prix=COALESCE(excluded.prix, presse_synthese.prix),
                 synthese=excluded.synthese,
                 resultat=COALESCE(excluded.resultat, presse_synthese.resultat),
                 fetched_at=excluded.fetched_at""",
            (d["date"], d.get("hippodrome"), d.get("prix"),
             json.dumps(d["synthese"]),
             json.dumps(d["resultat"]) if d.get("resultat") else None,
             "pronostics-turf.info"))
        conn.commit()
        conn.close()
        say(f"press: saved {d['date']} {d.get('hippodrome')} "
            f"({len(d['synthese'])} numbers)"
            + (f" result {'-'.join(map(str, d['resultat']))}"
               if d.get("resultat") else ""))
        return 1
    except Exception as e:
        say(f"press FAILED: {e}")
        say(traceback.format_exc().strip().replace("\n", " | "))
        return 0


def main():
    say("=" * 64)
    if len(sys.argv) > 1:
        try:
            target = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        except ValueError:
            target = date.today() - timedelta(days=1)
    else:
        target = date.today() - timedelta(days=1)
    say(f"daily job, target {target}")

    archive_races(target)
    save_press()
    try:
        # the engine reads dna_archive.db, and that file was a one-off build:
        # without this step it falls a day behind every single day
        from DNA_COURSE.sync_dna import sync
        sync(verbose=True)
    except Exception as e:
        say(f"dna_archive sync failed: {e}")

    # a short, honest health line
    try:
        from database import get_db
        conn = get_db()
        n_r = conn.execute("SELECT COUNT(*) c FROM races").fetchone()["c"]
        mx = conn.execute("SELECT MAX(date) d FROM races").fetchone()["d"]
        n_p = conn.execute("SELECT COUNT(*) c FROM presse_synthese").fetchone()["c"]
        n_pm = conn.execute(
            "SELECT COUNT(*) c FROM presse_synthese WHERE date >= date('now','-30 day')"
        ).fetchone()["c"]
        gap = (date.today() - date.fromisoformat(mx)).days if mx else -1
        say(f"health: races={n_r} latest={mx} ({gap}d ago) "
            f"press_days={n_p} last30={n_pm}")
        conn.close()
    except Exception as e:
        say(f"health check failed: {e}")
    say("done")


if __name__ == "__main__":
    main()
