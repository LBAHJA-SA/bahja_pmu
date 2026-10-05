"""The engine behind the Synthèse page.

The page has five boxes and a quota per box. Until now the pick inside a box
came from a lookup table of cell positions, which cannot tell one horse from
another: two horses in the same cell scored the same, so the engine had no
opinion about the horses at all.

This gives it one. For every runner of the Quinté it reads the archive and
returns a strength, plus the evidence behind that strength, so the number can
be argued with rather than believed.

The strength is built from what the archive actually holds, each part shrunk
towards the field so a horse with one run cannot beat a horse with twenty:

  p_top5, p_top3, p_win     recent form, Bayesian shrunk
  p_avg                     mean finish, lower is better
  dai_rate                  disqualifications in the recent form
  surface_fit / distance_fit  runs at today's going and distance
  trainer_hot, back_to_conditions, winless_recent

Nothing here is a claim that any of it predicts a Quinté. It is the reading
material, per horse, with the numbers attached so the page shows the reason and
not just the verdict.
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from DNA_COURSE.store import (
    compact_available, dna_db_path as store_dna_path, connect, horse_profiles,
    STORE_DEFAULT_MAX)
from QUINTE.form_reader import form_for

ARC = r"C:\turf\bahja-pmu\backend\archive.db"

# the weights. Form carries the reading, disqualifications take away, the
# trainer and the return-to-conditions are small nudges. Nothing is large
# because nothing in the archive has been shown to be large.
W_FORM5 = 34.0
W_FORM3 = 20.0
W_AVG = 10.0
W_DAI = 22.0
W_SURF = 6.0
W_TRAINER = 4.0
W_BACK = 4.0
W_DIST = 2.0
# no runs at all: the horse is unknown, not bad
NOBODY = 24.0
NOBODY_AVG = 9.0


def _quinte(day):
    a = sqlite3.connect(ARC)
    a.row_factory = sqlite3.Row
    r = a.execute(
        """SELECT race_id, disc_canonical, discipline, distance, surface
           FROM races WHERE date=? AND quinte=1 ORDER BY runners DESC LIMIT 1""",
        (day,)).fetchone()
    if not r:
        a.close()
        return None
    parts = a.execute(
        """SELECT num, rang, cote_pmu, age, poids, jockey, trainer
           FROM participants WHERE race_id=? AND rang IS NOT NULL AND rang<90
           ORDER BY rang""", (r["race_id"],)).fetchall()
    a.close()
    if len(parts) < 8:
        return None
    return dict(r), [dict(p) for p in parts]


def _open():
    """A private read-only connection.

    store.connect() hands back a cached one, and a cached sqlite connection
    that anything has closed raises "Cannot operate on a closed database" on
    the next call. This page is read-only, so it opens its own and closes it.
    """
    if not compact_available():
        return None
    c = sqlite3.connect(store_dna_path(), timeout=30)
    c.row_factory = sqlite3.Row
    return c


def _hids(day, qdisc=None, qdist=None):
    """num -> hid for that day, from the DNA archive.

    The day carries many races — a meeting has twenty — so the first race of
    the date is almost never the Quinté. Matching on discipline and distance is
    what puts the horses on the runners of the race being analysed; picking the
    wrong one leaves most of the field with no history at all.
    """
    conn = _open()
    if conn is None:
        return {}, None
    try:
        rows = conn.execute(
            "SELECT rid, disc, dist, surf, runners FROM races WHERE date=?",
            (day,)).fetchall()
        best = None
        for r in rows:
            same_disc = (r["disc"] == qdisc)
            near = abs((r["dist"] or 0) - (qdist or 0)) <= 150
            score = (1 if (same_disc and near) else 0,
                     1 if same_disc else 0,
                     r["runners"] or 0)
            if best is None or score > best[0]:
                best = (score, r["rid"])
        out = {}
        if best:
            for r in conn.execute("SELECT num, hid FROM runners WHERE rid=?",
                                  (best[1],)):
                out[int(r["num"])] = r["hid"]
        return out, conn
    except Exception:
        conn.close()
        return {}, None


def strength(day, n_runs=40):
    """{num: {...}} — the strength of every runner, with its evidence."""
    q = _quinte(day)
    if not q:
        return {}
    meta, field = q
    dist = meta.get("distance")
    surf = meta.get("surface")
    hids, conn = _hids(day, meta.get("disc_canonical") or meta.get("discipline"),
                       dist)
    if conn is None:
        return {}
    try:
        want = [hids[p["num"]] for p in field if p["num"] in hids]
        profs = horse_profiles(
            conn, want, day, dist, surf,
            [{"label": lbl, "max": mx} for lbl, mx in
             zip(("F", "S", "O", "O2", "T"), STORE_DEFAULT_MAX + (1e9,))],
            limit=n_runs)
    finally:
        conn.close()

    forms = form_for(day) or {}
    out = {}
    for p in field:
        num = p["num"]
        pr = profs.get(hids.get(num))
        fv = forms.get(num) or {}
        same = [x for x in fv.get("runs", []) if x.get("same")]
        shape = " ".join(
            ("Da" if x["dai"] else (str(x["pos"]) if x["pos"] else "x"))
            for x in (same or fv.get("runs", []))[:6])
        if not pr or pr.get("runs_n", 0) < 2:
            s = NOBODY
            parts = {"form": 0.0, "dai": 0.0, "rest": 0.0}
            note = "pas d'historique"
        else:
            n = pr["runs_n"]
            f5 = (pr["p_top5"] - 0.30) * W_FORM5
            f3 = (pr["p_top3"] - 0.30) * W_FORM3
            fav = max(0.0, (8.0 - pr["p_avg"])) * W_AVG
            dai = -pr["dai_rate"] * W_DAI
            sf = (pr.get("surface_fit", 0) - 0.34) * W_SURF
            df = (pr.get("distance_fit", 0) - 0.34) * W_DIST
            sig = pr.get("signals", {})
            th = W_TRAINER if sig.get("trainer_hot") else 0.0
            bk = W_BACK if sig.get("back_to_conditions") else 0.0
            s = f5 + f3 + fav + dai + sf + df + th + bk
            parts = {
                "form": round(f5 + f3 + fav, 1),
                "dai": round(dai, 1),
                "rest": round(sf + df + th + bk, 1),
            }
            note = f"{n} courses"
        out[num] = {
            "score": round(s, 1),
            "parts": parts,
            "runs_n": (pr or {}).get("runs_n", 0),
            "p_top5": round((pr or {}).get("p_top5", 0), 3),
            "p_top3": round((pr or {}).get("p_top3", 0), 3),
            "p_avg": round((pr or {}).get("p_avg", 0), 2),
            "dai": (pr or {}).get("dai_rate", 0),
            "surface_fit": round((pr or {}).get("surface_fit", 0), 2),
            "distance_fit": round((pr or {}).get("distance_fit", 0), 2),
            "shape": shape or "(aucune course)",
            "same_runs": len(same),
            "note": note,
        }
    return out


if __name__ == "__main__":
    import json
    import sys
    for day in sys.argv[1:] or ["2026-09-25"]:
        st = strength(day)
        print("=" * 70)
        print(day, f"  {len(st)} runners")
        for num in sorted(st, key=lambda k: -st[k]["score"]):
            v = st[num]
            print(f"  #{num:<3} {v['score']:>6.1f}  {v['note']:<14}"
                  f" n={v['runs_n']:<3} top5={v['p_top5']:<5}"
                  f" dai={v['dai']:<5} {v['shape']}")
