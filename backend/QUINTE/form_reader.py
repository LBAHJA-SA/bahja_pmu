"""The raw material of the reading, per horse, inside each box.

The brief said it plainly: the shape of the form, NOT converted into points.
Collapsing five runs into a mean loses everything the professional actually
reads — a "1-2-3-1-1" and a "3-3-2-2-2" have the same mean and nothing else in
common, and one is a horse going forward while the other is going backwards.

So this returns, for every runner of a date, the last runs as a list: the
position, whether it was a disqualification, the date, the distance, the
surface, and whether the run was at the same distance and the same going as
today. The page prints the shape. It does not score it.
"""
import sqlite3
from collections import defaultdict
from datetime import date, timedelta

DNA = r"C:\turf\bahja-pmu\backend\dna_archive.db"


def _loads():
    d = sqlite3.connect(DNA)
    d.row_factory = sqlite3.Row
    races = {}
    for r in d.execute("SELECT rid, date, disc, dist, surf FROM races"):
        races[r["rid"]] = (r["date"], r["disc"], r["dist"], r["surf"])
    # keyed on the horse alone: the saddle number changes from race to race, so
    # including it would find almost nothing
    hist = defaultdict(list)
    for r in d.execute(
            "SELECT rid, hid, rang, dai FROM runners WHERE rang IS NOT NULL"):
        m = races.get(r["rid"])
        if not m:
            continue
        hist[r["hid"]].append((m[0], m[1], m[2], m[3], r["rang"], r["dai"]))
    d.close()
    for v in hist.values():
        v.sort(key=lambda x: x[0], reverse=True)
    return hist, races


_HIST, _RACES = None, None


def _hist():
    global _HIST, _RACES
    if _HIST is None:
        _HIST, _RACES = _loads()
    return _HIST, _RACES


ARC = r"C:\turf\bahja-pmu\backend\archive.db"


def _quinte_of(target):
    """The Quinté of that day, from archive.db: discipline, distance, field."""
    a = sqlite3.connect(ARC)
    a.row_factory = sqlite3.Row
    row = a.execute(
        """SELECT race_id, disc_canonical, discipline, distance, runners
           FROM races WHERE date=? AND quinte=1 ORDER BY runners DESC LIMIT 1""",
        (target,)).fetchone()
    a.close()
    if not row:
        return None
    return (row["disc_canonical"] or row["discipline"],
            row["distance"], row["runners"])


def rid_for_date(target):
    """The DNA race matching the Quinté of that day — not simply the biggest.

    Picking the largest field picks whichever race had eighteen runners, which
    on 24/09 was a 2850m monte instead of the 1600m plat that actually carried
    the Quinté.
    """
    q = _quinte_of(target)
    d = sqlite3.connect(DNA)
    d.row_factory = sqlite3.Row
    if not q:
        d.close()
        return None
    qdisc, qdist, qrun = q
    best = None
    for r in d.execute(
            "SELECT rid, disc, dist, surf, runners FROM races WHERE date=?",
            (target,)):
        same_disc = (r["disc"] == qdisc)
        near = abs((r["dist"] or 0) - (qdist or 0)) <= 150
        if not same_disc:
            continue
        score = (1 if near else 0, r["runners"] or 0)
        if best is None or score > best[0]:
            best = (score, (r["rid"], r["disc"], r["dist"], r["surf"], r["runners"]))
    d.close()
    return best[1] if best else None


def form_for(target, n=6, dist_tol=150):
    """{num: {...}} for the whole field of that date.

    only runs strictly before the date, so nothing from the race itself leaks
    into the reading.
    """
    hist, _ = _hist()
    rid = rid_for_date(target)
    if not rid:
        return {}
    rid_v, disc, dist, surf, _ = rid
    d = sqlite3.connect(DNA)
    d.row_factory = sqlite3.Row
    out = {}
    for r in d.execute(
            "SELECT num, hid, rang, dai FROM runners WHERE rid=? AND rang IS NOT NULL",
            (rid_v,)):
        key = r["hid"]
        runs = hist.get(key) or []
        runs = [x for x in runs if x[0] < target][:n]
        items = []
        for dt, dsc, dst, srf, rang, dai in runs:
            # a missing surface is unknown, not a mismatch: the archive only
            # carries it on a small share of races
            surf_ok = (srf == surf) or (srf is None or surf is None)
            dist_ok = abs((dst or 0) - (dist or 0)) <= dist_tol
            same = (dsc == disc) and surf_ok and dist_ok
            items.append({
                "date": dt,
                "pos": None if (rang or 0) >= 90 else int(rang),
                "dai": bool(dai) or (rang or 0) >= 90,
                "dist": dst,
                "surf": srf,
                "disc": dsc,
                "same": bool(same),
            })
        out[int(r["num"])] = {
            "runs": items,
            "n": len(items),
            "dai_in_form": sum(1 for x in items if x["dai"]),
            "n_same": sum(1 for x in items if x["same"]),
            "last": items[0] if items else None,
        }
    d.close()
    return out


if __name__ == "__main__":
    import json
    import sys
    for day in sys.argv[1:] or ["2026-09-25", "2026-09-24"]:
        f = form_for(day)
        print("=" * 70)
        print(day, "—", rid_for_date(day))
        for num in sorted(f):
            v = f[num]
            shape = " ".join(
                ("Da" if x["dai"] else str(x["pos"])) +
                ("" if x["same"] else "*")
                for x in v["runs"]) or "(aucune course)"
            print(f"  #{num:<3} n={v['n']}  meme-distance={v['n_same']}"
                  f"  DAI={v['dai_in_form']}   {shape}")
        print("  (* = distance ou terrain différent)")
