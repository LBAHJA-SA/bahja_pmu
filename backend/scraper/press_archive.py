"""Save the press synthesis every day, before it disappears.

The site serves the public only the last three days. After that a synthesis is
gone for good unless somebody kept it. That is why the archive held nine days
and every earlier measurement had to fall back on the market order.

This module is the fix:

  backfill_wayback()   recover the ~215 snapshots the Wayback Machine has,
                       from 2019 onwards, and store each ordered list
  save_today()         fetch the live page and store today's and tomorrow's
                       synthesis, with the result once it is published
  run()                both, and report what was gained

Storage goes to presse_synthese in archive.db, keyed by date, with the source
recorded so a real press list is never confused with a fallback.
"""
import json
import re
import sqlite3
import sys
import time
import urllib.request
from datetime import datetime, timedelta

sys.path.insert(0, r"C:\turf\bahja-pmu\backend")
from scraper.turfinfo_scraper import (
    fetch_daily, parse_synthese, parse_quinte_label)

DB = r"C:\turf\bahja-pmu\backend\archive.db"
HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                     "AppleWebKit/537.36 (KHTML, like Gecko) "
                     "Chrome/120.0.0.0 Safari/537.36"}
CDX = ("http://web.archive.org/cdx/search/cdx"
       "?url=pronostics-turf.info/&from=20190101&to={today}"
       "&output=json&filter=statuscode:200&fl=timestamp,original"
       "&collapse=digest")


def conn():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    return c


def get(url, timeout=90, tries=6):
    """The Wayback CDX answers 503 under load, so back off and keep going."""
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=HDRS)
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.read()
        except Exception as e:
            last = e
            time.sleep(min(30, 3 * (i + 1)))
    if last:
        print(f"    give up {url[:80]}: {last}")
    return None


def upsert(c, date, nums, hippo=None, prix=None, resultat=None,
           source="pronostics-turf.info"):
    """Never overwrite a stored synthesis with a shorter or empty one."""
    nums = [int(x) for x in nums if x is not None]
    if len(nums) < 14:
        return False
    nums = nums[:18]
    row = c.execute("SELECT synthese FROM presse_synthese WHERE date=?",
                    (date,)).fetchone()
    if row and row["synthese"]:
        old = json.loads(row["synthese"])
        if len(old) > len(nums):
            return False
    c.execute(
        """INSERT INTO presse_synthese
             (date, hippodrome, prix, synthese, resultat, source, fetched_at)
           VALUES (?,?,?,?,?,?,?)
           ON CONFLICT(date) DO UPDATE SET
             hippodrome=COALESCE(excluded.hippodrome, presse_synthese.hippodrome),
             prix=COALESCE(excluded.prix, presse_synthese.prix),
             synthese=excluded.synthese,
             resultat=COALESCE(excluded.resultat, presse_synthese.resultat),
             source=excluded.source,
             fetched_at=excluded.fetched_at""",
        (date, hippo, prix, json.dumps(nums),
         json.dumps(resultat) if resultat else None, source,
         datetime.utcnow().isoformat()))
    return True


# --------------------------------------------------------------- live save --
def save_today(verbose=True):
    """The live page carries tomorrow's Quinté plus today's result."""
    d = fetch_daily()
    got = 0
    if d.get("date") and len(d.get("synthese") or []) >= 14:
        if upsert(c_ := conn(), d["date"], d["synthese"],
                  d.get("hippodrome"), d.get("prix")):
            c_.commit()
            got += 1
            if verbose:
                print(f"  live  {d['date']}  {d.get('hippodrome') or '':<14}"
                      f" {len(d['synthese'])} nums")
        c_.close()
    # today's result, filed against the date it belongs to
    if d.get("resultat_date") and d.get("resultat"):
        c_ = conn()
        if upsert(c_, d["resultat_date"], d.get("synthese") or [0] * 18,
                  resultat=d["resultat"],
                  source=d.get("synthese") and "pronostics-turf.info" or "x"):
            pass
        else:
            c_.execute(
                """UPDATE presse_synthese SET resultat=?, fetched_at=?
                   WHERE date=?""",
                (json.dumps(d["resultat"]),
                 datetime.utcnow().isoformat(), d["resultat_date"]))
        c_.commit()
        c_.close()
        if verbose:
            print(f"  live  result {d['resultat_date']}  "
                  f"{'-'.join(map(str, d['resultat']))}")
        got += 1
    return got


# ----------------------------------------------------------- wayback fill --
def backfill_wayback(verbose=True, limit=None):
    today = datetime.utcnow().strftime("%Y%m%d")
    raw = get(CDX.format(today=today), timeout=120)
    if not raw:
        if verbose:
            print("  wayback: CDX unreachable")
        return 0
    rows = json.loads(raw.decode())[1:]
    if limit:
        rows = rows[-limit:]
    c = conn()
    have = {r["date"] for r in c.execute("SELECT date FROM presse_synthese")}
    stored = skipped = failed = 0
    for ts, orig in rows:
        body = get(f"http://web.archive.org/web/{ts}id_/{orig}", timeout=90)
        if not body:
            failed += 1
            continue
        html = body.decode("utf-8", "replace")
        label = parse_quinte_label(html)
        nums = parse_synthese(html)
        date = label.get("date")
        if not date or len(nums) < 14:
            skipped += 1
            continue
        if date in have:
            continue
        if upsert(c, date, nums, label.get("hippodrome"), label.get("prix"),
                  source="wayback"):
            stored += 1
            have.add(date)
            if verbose and stored % 25 == 0:
                print(f"    ... {stored} stored")
        else:
            skipped += 1
    c.commit()
    total = c.execute("SELECT COUNT(*) FROM presse_synthese").fetchone()[0]
    span = c.execute("SELECT MIN(date), MAX(date) FROM presse_synthese").fetchone()
    c.close()
    if verbose:
        print(f"  wayback: {stored} stored, {skipped} skipped, "
              f"{failed} unreachable")
        print(f"  table now: {total} days, {span[0]} .. {span[1]}")
    return stored


def run(limit=None):
    print("=" * 70)
    print(f"press archive save — {datetime.utcnow().isoformat(timespec='seconds')}")
    print("=" * 70)
    try:
        print("[1] live")
        save_today()
    except Exception as e:
        print(f"  live failed: {e}")
    try:
        print("[2] wayback backfill")
        backfill_wayback(limit=limit)
    except Exception as e:
        print(f"  backfill failed: {e}")
    c = conn()
    n = c.execute("SELECT COUNT(*) FROM presse_synthese").fetchone()[0]
    by = c.execute("""SELECT source, COUNT(*) n FROM presse_synthese
                      GROUP BY source ORDER BY n DESC""").fetchall()
    span = c.execute("SELECT MIN(date), MAX(date) FROM presse_synthese").fetchone()
    c.close()
    print()
    print(f"  total {n} days   {span[0]} .. {span[1]}")
    for r in by:
        print(f"    {r['source'] or '?':<28} {r['n']:>5}")


if __name__ == "__main__":
    lim = int(sys.argv[1]) if len(sys.argv) > 1 else None
    run(limit=lim)
