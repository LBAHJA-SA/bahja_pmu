"""
daily_archive.py — أرشفة يومية بعد نهاية اليوم (Task Scheduler كل 24 ساعة)
يحفظ كل سباقات الأمس التي لها نتائج في archive.db
"""
import sys, os
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from scraper.geny_scraper import get_scraper
from database import save_geny_race, get_archived_race
import time

def archive_date(target_date):
    scraper = get_scraper()
    try:
        prog = scraper.fetch_programme(target_date)
    except Exception as e:
        print(f"[{target_date}] programme error: {e}")
        return 0, 0

    saved = 0
    skipped = 0
    for m in prog.get("meetings", []):
        for c in m.get("courses", []):
            cid = c.get("id")
            if not cid:
                continue
            existing = get_archived_race(cid)
            if existing is not None:
                # skip only if it already has results; otherwise re-fetch to update
                _has = bool((existing.get("arrivee"))) or any(
                    (p or {}).get("rang") is not None for p in (existing.get("participants") or []))
                if _has:
                    skipped += 1
                    continue
            try:
                data = scraper.fetch_race_details(cid)
                if not data:
                    continue
                # تحقق من وجود نتيجة
                course = data.get("course", {})
                parts = data.get("participants", [])
                has_result = bool(course.get("arrivee")) or any(p.get("rang") for p in parts)
                if not has_result:
                    continue
                save_geny_race(cid, data)
                saved += 1
                print(f"  saved {cid} {m.get('hippodrome')} C{c.get('num')}")
                time.sleep(0.5)
            except Exception as e:
                print(f"  error {cid}: {e}")
    return saved, skipped


def update_missing_results(days_back=7):
    """Second pass: DB races from last N days without results -> re-fetch details.
    save_geny_race upserts (DELETE+INSERT), so finished races get their arrivee."""
    from database import get_db
    from datetime import datetime
    cutoff = (date.today() - timedelta(days=days_back)).isoformat()
    today = date.today().isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT race_id FROM races WHERE date >= ? AND date < ? AND (arrivee IS NULL OR arrivee = '')",
        (cutoff, today)).fetchall()
    conn.close()
    ids = [r["race_id"] for r in rows]
    # keep only those whose participants lack rang too
    conn = get_db()
    todo = []
    for rid in ids:
        n = conn.execute(
            "SELECT COUNT(*) c FROM participants WHERE race_id=? AND rang IS NOT NULL",
            (rid,)).fetchone()["c"]
        if not n:
            todo.append(rid)
    conn.close()
    print(f"[Update] {len(todo)} races without results (last {days_back}d)")
    scraper = get_scraper()
    updated = 0
    for cid in todo:
        try:
            data = scraper.fetch_race_details(cid)
            if not data:
                continue
            course = data.get("course", {})
            parts = data.get("participants", [])
            if not (bool(course.get("arrivee")) or any(p.get("rang") for p in parts)):
                continue
            save_geny_race(cid, data)
            updated += 1
            print(f"  updated {cid}")
            time.sleep(0.5)
        except Exception as e:
            print(f"  error {cid}: {e}")
    return updated

if __name__ == "__main__":
    # بعد نهاية اليوم بساعات (Task Scheduler ~06:30): النتائج نهائية.
    # PMU أولا (Geny محظور: 'Trop de requêtes')، Geny احتياط فقط.
    yesterday = date.today() - timedelta(days=1)
    # السماح بتمرير تاريخ يدوي: python daily_archive.py 2026-09-02
    if len(sys.argv) > 1:
        try:
            from datetime import datetime
            yesterday = datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        except ValueError:
            pass
    print(f"[Daily Archive] {yesterday.isoformat()} ...")
    used = "pmu"
    try:
        from pmu_archive import archive_date_pmu, update_missing_results_pmu, reverify_recent
        saved, with_results, skipped = archive_date_pmu(yesterday)
        print(f"Done (PMU): saved={saved} with_results={with_results} no_arrival_yet={skipped} for {yesterday}")
        try:
            print(f"Done: updated(results)={update_missing_results_pmu(7)}")
        except Exception as e:
            print(f"[Update] error: {e}")
        try:
            print(f"Done: corrected(enquete)={reverify_recent(3)}")
        except Exception as e:
            print(f"[Reverify] error: {e}")
    except Exception as e:
        print(f"[PMU] failed ({e}), fallback Geny ...")
        used = "geny"
        saved, skipped = archive_date(yesterday)
        print(f"Done (Geny): saved={saved} skipped(already)={skipped} for {yesterday}")
        try:
            updated = update_missing_results(7)
            print(f"Done: updated(results)={updated}")
        except Exception as e2:
            print(f"[Update] error: {e2}")
    print(f"Engine used: {used}")
    # Daily presse synthèse (pronostics-turf.info) — stored for /api/synthese
    try:
        from scraper.turfinfo_scraper import fetch_daily
        from database import get_db
        import json as _json
        d = fetch_daily()
        if d.get("date") and len(d.get("synthese", [])) >= 14:
            conn = get_db()
            conn.execute("""INSERT INTO presse_synthese (date, hippodrome, prix, synthese, resultat, fetched_at)
                VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)
                ON CONFLICT(date) DO UPDATE SET hippodrome=excluded.hippodrome, prix=excluded.prix,
                synthese=excluded.synthese, resultat=excluded.resultat, fetched_at=CURRENT_TIMESTAMP""",
                (d["date"], d.get("hippodrome"), d.get("prix"), _json.dumps(d["synthese"]),
                 "-".join(map(str, d["resultat"])) if d.get("resultat") else None))
            conn.commit()
            conn.close()
            print(f"[Presse] stored {d['date']} {d.get('hippodrome')} ({len(d['synthese'])} nums)")
        else:
            print("[Presse] nothing to store")
    except Exception as e:
        print(f"[Presse] error: {e}")
