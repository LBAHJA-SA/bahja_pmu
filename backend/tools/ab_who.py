"""
A/B : WHO ancien (weighted) vs WHO nouveau (ADN). WHERE identique.

Pour que la comparaison soit HONNÊTE :
  - les deux moteurs reçoivent EXACTEMENT le même cadre (presse=None ->
    les deux retombent sur le meme ordre marche, donc les memes zones) ;
  - les deux recoivent la meme fenetre d'historique (before) ;
  - les regles ADN sont minees UNE fois, strictement avant la borne
    haute de la fenetre de test. Aucune fuite.

Metrique : couverture Top5 = |ticket ∩ Top5| sur 5. C'est la meme chose que
le "22.6% on 500" du poids W_RED, donc directement comparable.

Usage :  py tools/ab_who.py --n 300
"""
import argparse
import os
import sys
import time
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from QUINTE import synthese_service as OLD  # noqa: E402
from QUINTE import synthese_who as NEW  # noqa: E402

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive.db")


def load_races(conn, before, after=None, n=300):
    where = ["r.quinte = 1"]
    params = []
    if before:
        where.append("r.date < ?")
        params.append(before)
    if after:
        where.append("r.date >= ?")
        params.append(after)
    params.append(n)
    return [r[0] for r in conn.execute(
        "SELECT p.race_id FROM participants p JOIN races r ON r.race_id=p.race_id "
        f"WHERE {' AND '.join(where)} GROUP BY p.race_id "
        "HAVING COUNT(*) >= 10 ORDER BY r.date DESC LIMIT ?", params)]


def field(conn, rid):
    ps = []
    for r in conn.execute(
            "SELECT num, cote_pmu, musique, red_km, rang, horse FROM participants "
            "WHERE race_id=? AND rang IS NOT NULL AND rang<=20 ORDER BY cote_pmu", (rid,)):
        ps.append({"num": r[0], "cote_pmu": r[1], "musique": r[2],
                   "red_km": r[3], "rang": r[4], "horse": r[5]})
    return ps


def disc_of(conn, rid):
    r = conn.execute("SELECT disc_canonical, hippodrome, distance, runners, date "
                     "FROM races WHERE race_id=?", (rid,)).fetchone()
    return r or (None, None, None, None, None)


def nums(ticket):
    """Le moteur renvoie des dicts ; le fallback historique renvoie des ints."""
    out = []
    for t in (ticket or []):
        out.append(t.get("num") if isinstance(t, dict) else t)
    return out


def hits(ticket, ps):
    top5 = {p["num"] for p in ps if 1 <= (p.get("rang") or 99) <= 5}
    return len(top5 & set(nums(ticket))), len(top5)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--before", default="2025-01-01",
                    help="borne haute du mineage ET de l'historique des 2 moteurs")
    ap.add_argument("--limit", type=int, default=400000)
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro", uri=True)
    t0 = time.time()
    print(f"mine + ADMISSION AUC (before={a.before}) ...", flush=True)
    rules, meta = NEW.mine_context(disc=None, before=a.before, limit=a.limit)
    adm = (meta.get("admission") or {})
    print(f"  groupes admis : {(adm.get('_meta') or {}).get('admitted')}")
    print(f"  refuses       : "
          f"{[g for g, r in (adm.get('groups') or {}).items() if isinstance(r, dict) and not r.get('admitted')]}")
    print(f"  general={meta.get('general')} residual={meta.get('residual')} "
          f"| champ={meta.get('n_field')} [{time.time() - t0:.0f}s]")
    for r in rules:
        print(f"    ADMIS  {r.key:<12} {r.value:<11} {r.weight:+.3f}")

    races = load_races(conn, None, after=a.before, n=a.n)
    print(f"\n{a.n} courses Quinté testees (>= {a.before})\n")

    tot_o = tot_n = tot_h = cnt_o = cnt_n = cnt_any_o = cnt_any_n = 0
    empty_n = 0
    t0 = time.time()
    for i, rid in enumerate(races, 1):
        ps = field(conn, rid)
        if len(ps) < 10:
            continue
        d, hip, dist, run, date = disc_of(conn, rid)
        ko = dict(hippodrome=hip, distance=dist, runners=run, disc=d,
                  before=a.before)
        try:
            ro, _so = OLD.synthese_match(ps, **ko)
        except Exception as e:
            ro = []
        try:
            rn, sn = NEW.synthese_match(ps, rules=rules, meta=meta, **ko)
        except Exception as e:
            rn, sn = [], {"error": str(e)}
        if sn.get("error"):
            empty_n += 1
        h_o, n5 = hits(ro, ps)
        h_n, _ = hits(rn, ps)
        tot_o += h_o
        tot_n += h_n
        tot_h += n5
        cnt_o += h_o > 0
        cnt_n += h_n > 0
        cnt_any_o += len(nums(ro))
        cnt_any_n += len(nums(rn))
        if i % 50 == 0:
            print(f"  {i}/{len(races)} ...", flush=True)

    c = max(len(races), 1)
    print(f"\n{'=' * 70}\nRESULTAT  ({len(races)} courses, {time.time() - t0:.0f}s)")
    print(f"{'=' * 70}")
    print(f"  {'':<22} {'ANCIEN (weighted)':>20} {'NOUVEAU (ADN)':>18}")
    print(f"  {'couverture Top5':<22} {tot_o / tot_h * 100:>19.1f}% "
          f"{tot_n / tot_h * 100:>17.1f}%")
    print(f"  {'coup(s) par course':<22} {tot_o / c:>20.2f} {tot_n / c:>18.2f}")
    print(f"  {'>=1 Top5':<22} {cnt_o / c * 100:>19.1f}% {cnt_n / c * 100:>17.1f}%")
    print(f"  {'tickets vides/erreurs':<22} {'-':>20} {empty_n:>18}")
    d = (tot_n - tot_o) / tot_h * 100
    print(f"\n  ecart couverture = {d:+.1f} points "
          f"({'ADN gagne' if d > 0 else 'ADN perd'})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
