import sys
import os
import time
import argparse
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper.turfomania_scraper import TurfomaniaScraper
from database import save_geny_race


def build_race_data(reunion, course, participants, results, date_str):
    """Build race_data in the same format as archive.py / geny _transform_race."""
    rnum = reunion.get("reunion_num")
    cnum = course.get("course_num")

    # merge results into participants (rang, cote)
    result_map = {}
    if results:
        for res in results:
            result_map[res["num"]] = res

    part_list = []
    for p in participants or []:
        num = p.get("num")
        res = result_map.get(num)
        p_copy = dict(p)
        if res:
            p_copy["rang"] = res["rang"]
            if not p_copy.get("cote_pmu"):
                p_copy["cote_pmu"] = res["cote"]
            p_copy["ecart"] = None
        part_list.append(p_copy)

    race_id = f"{date_str.replace('-', '')}{rnum:02d}{cnum:02d}"

    discipline = course.get("discipline")
    specialty = discipline
    if discipline == "Attel":
        discipline = "ATTELE"
    elif discipline in ("Galop", "Steeple", "Haies", "Cross"):
        discipline = "PLAT" if discipline == "Galop" else discipline.upper()

    runners = len(part_list) if part_list else reunion.get("n_courses")

    race_data = {
        "reunion": {
            "num": rnum,
            "hippodrome": reunion.get("hippodrome"),
            "organizer": "PMU",
            "date": date_str,
        },
        "course": {
            "id": course.get("idcourse"),
            "num": cnum,
            "prix": course.get("prix"),
            "time": course.get("time"),
            "specialty": specialty,
            "discipline": discipline,
            "distance": course.get("distance"),
            "surface": None,
            "going": None,
            "corde": None,
            "runners": runners,
            "quinte": reunion.get("quinte"),
            "classe": None,
            "condition": None,
            "depart": None,
            "penetrometer": None,
            "types_pari": [],
            "arrivee": None,
            "allocations": None,
        },
        "participants": part_list,
    }
    return race_id, race_data


def archive_day(scraper, date_str, dry_run=False, log=None):
    """Archive a full day from Turfomania. Returns (saved, errors)."""
    reunions = scraper.fetch_programme(date_str)
    if not reunions:
        return 0, ["no programme for " + date_str]

    saved = 0
    errors = []
    for reun in reunions:
        rid = reun["idreunion"]
        rep = scraper.fetch_reunion(rid)
        if not rep:
            errors.append(f"reunion {rid} fetch failed")
            continue
        courses = rep.get("courses", [])
        for course in courses:
            cid = course["idcourse"]
            slug = course.get("slug")
            try:
                participants = scraper.fetch_partants(cid, slug)
                results = scraper.fetch_rapports(cid, slug)
            except Exception as e:
                errors.append(f"course {cid}: {e}")
                continue
            if participants is None:
                errors.append(f"course {cid}: no partants")
                continue
            race_id, race_data = build_race_data(reun, course, participants, results, date_str)
            if dry_run:
                saved += 1
                continue
            try:
                save_geny_race(race_id, race_data)
                saved += 1
                if log:
                    log(f"  saved {race_id} {reun.get('hippodrome')} C{course['course_num']} ({len(participants)} partants)")
            except Exception as e:
                errors.append(f"save {race_id}: {e}")
    return saved, errors


def load_progress(progress_file):
    done = set()
    if os.path.exists(progress_file):
        with open(progress_file, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    done.add(line)
    return done


def save_progress(progress_file, done):
    with open(progress_file, "w", encoding="utf-8") as f:
        for ds in sorted(done):
            f.write(ds + "\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2020-01-01")
    parser.add_argument("--end", default=None)
    parser.add_argument("--delay", type=float, default=1.6)
    parser.add_argument("--logfile", default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--only-date", default=None)
    parser.add_argument("--progress", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "turfomania_progress.txt"))
    args = parser.parse_args()

    end = args.end or (args.only_date or (date.today() - timedelta(days=1)).isoformat())
    start = args.only_date or args.start

    scraper = TurfomaniaScraper(delay=args.delay)
    log = None
    if args.logfile:
        log = open(args.logfile, "a", encoding="utf-8")

    def log_line(msg):
        try:
            print(msg, flush=True)
        except OSError:
            pass  # stdout may be unavailable when launched hidden/detached
        if log:
            log.write(msg + "\n")
            log.flush()

    done = load_progress(args.progress)
    if done:
        log_line(f"resume: {len(done)} days already completed")

    d = date.fromisoformat(start)
    end_d = date.fromisoformat(end)
    total_saved = 0
    total_errors = 0
    errors_all = []

    while d <= end_d:
        ds = d.isoformat()
        if ds in done:
            d += timedelta(days=1)
            continue
        t0 = time.time()
        saved, errs = archive_day(scraper, ds, dry_run=args.dry_run, log=log_line)
        dt = time.time() - t0
        total_saved += saved
        total_errors += len(errs)
        errors_all.extend(errs)
        # mark as done only if no errors (so failed days are retried next run)
        if not errs:
            done.add(ds)
            save_progress(args.progress, done)
        status = f"{ds}: saved={saved} errors={len(errs)} ({dt:.1f}s) cumulative={total_saved}"
        log_line(status)
        if errs:
            for e in errs[:3]:
                log_line(f"    ERR {e}")
        d += timedelta(days=1)

    log_line(f"=== DONE. total_saved={total_saved} total_errors={total_errors} ===")
    if errors_all:
        log_line("sample errors:")
        for e in errors_all[:10]:
            log_line(f"  {e}")
    if log:
        log.close()


if __name__ == "__main__":
    main()
