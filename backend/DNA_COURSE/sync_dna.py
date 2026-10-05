"""Keep dna_archive.db in step with archive.db.

dna_archive.db was a one-off build and stopped on 2026-09-21, so the newest
races were never in it. Without it there is no form to read, because the form
is the runner history that lives in this file.

This appends whatever archive.db has and dna_archive.db does not. It is safe to
run twice: a date already present is skipped.

Two things about the existing data worth knowing:
  - the `dai` column is unreliable (a horse that finished second is flagged 1),
    so anything reading the form should treat a missing or >=90 `rang` as the
    disqualification, not this column
  - `d4` is all zero and carries nothing
Both are left untouched here rather than silently rewritten.
"""
import os
import sqlite3
import sys

ARC = r"C:\turf\bahja-pmu\backend\archive.db"
DNA = r"C:\turf\bahja-pmu\backend\dna_archive.db"

# the thresholds baked into dna_archive.bands
BANDS = [(5.0, 0), (10.0, 1), (20.0, 2), (30.0, 3), (float("inf"), 4)]


def band_of(cote):
    if cote is None:
        return None
    for cap, b in BANDS:
        if cote <= cap:
            return b
    return 4


def _norm(s):
    import unicodedata
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).strip().upper()


def sync(verbose=True, since=None):
    a = sqlite3.connect(ARC)
    a.row_factory = sqlite3.Row
    d = sqlite3.connect(DNA)
    d.row_factory = sqlite3.Row

    maxd = d.execute("SELECT MAX(date) FROM races").fetchone()[0]
    start = since or maxd
    if start:
        src = a.execute(
            "SELECT id, race_id, date, hippodrome, discipline, disc_canonical, "
            "       distance, surface, runners, specialty "
            "FROM races WHERE date > ? ORDER BY date", (start,)).fetchall()
    else:
        src = a.execute(
            "SELECT id, race_id, date, hippodrome, discipline, disc_canonical, "
            "       distance, surface, runners, specialty "
            "FROM races ORDER BY date").fetchall()

    if not src:
        if verbose:
            print(f"  dna_archive already current (max {maxd})")
        d.close()
        a.close()
        return 0

    next_rid = (d.execute("SELECT COALESCE(MAX(rid), 0) FROM races").fetchone()[0]
                or 0) + 1
    horses = {r["name"]: r["hid"] for r in d.execute("SELECT hid, name FROM horses")}
    trainers = {r["name"]: r["tid"] for r in d.execute("SELECT tid, name FROM trainers")}

    n_r = n_p = 0
    new_h = new_t = 0
    for r in src:
        disc = r["disc_canonical"] or r["discipline"] or ""
        parts = a.execute(
            """SELECT num, horse, trainer, age, poids, cote_pmu, rang
               FROM participants WHERE race_id=? AND rang IS NOT NULL""",
            (r["race_id"],)).fetchall()
        if len(parts) < 6:
            continue
        d.execute(
            """INSERT OR REPLACE INTO races
                 (rid, date, disc, hippo, dist, surf, runners, specialty)
               VALUES (?,?,?,?,?,?,?,?)""",
            (next_rid, r["date"], disc, r["hippodrome"], r["distance"],
             r["surface"], r["runners"], r["specialty"]))
        for p in parts:
            hn = _norm(p["horse"])
            hid = horses.get(hn)
            if hid is None:
                new_h += 1
                hid = 900000 + new_h
                horses[hn] = hid
                d.execute("INSERT OR IGNORE INTO horses (hid, name) VALUES (?,?)",
                          (hid, hn))
            tn = _norm(p["trainer"])
            tid = trainers.get(tn)
            if tid is None:
                new_t += 1
                tid = 90000 + new_t
                trainers[tn] = tid
                d.execute("INSERT OR IGNORE INTO trainers (tid, name) VALUES (?,?)",
                          (tid, tn))
            d.execute(
                """INSERT OR REPLACE INTO runners
                     (rid, num, hid, tid, cote, band, rang, age, poids, d4, dai)
                   VALUES (?,?,?,?,?,?,?,?,?,0,?)""",
                (next_rid, p["num"], hid, tid, p["cote_pmu"],
                 band_of(p["cote_pmu"]), p["rang"], p["age"], p["poids"],
                 1 if (p["rang"] or 0) >= 90 else 0))
            n_p += 1
        n_r += 1
        next_rid += 1

    d.commit()
    mx = d.execute("SELECT MAX(date) FROM races").fetchone()[0]
    tot = d.execute("SELECT COUNT(*) FROM races").fetchone()[0]
    d.close()
    a.close()
    if verbose:
        print(f"  dna_archive: +{n_r} races (+{n_p} runners, "
              f"+{new_h} horses, +{new_t} trainers) -> {tot} races, max {mx}")
    return n_r


if __name__ == "__main__":
    since = sys.argv[1] if len(sys.argv) > 1 else None
    print("syncing dna_archive.db ...")
    sync(since=since)
