"""
Rapport ADN — mine l'archive REELLE et affiche ce qui survit.

C'est l'outil qui tranche la question DAI / cote / outsiders avec des
nombres, pas avec des convictions. Si une hypothèse n'apparait pas ici,
elle est fausse pour ce contexte et le moteur doit l'ignorer.

Usage :
    py tools/dna_report.py                     # global, 6000 Quintés
    py tools/dna_report.py --disc PLAT
    py tools/dna_report.py --limit 2000 --before 2026-01-01
    py tools/dna_report.py --key DAI
"""
import argparse
import math
import os
import sys
import sqlite3
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from QUINTE.dna import (  # noqa: E402
    mine_rules, general_rules, discipline_rules, FEATURE_KEYS,
)

DB = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "archive.db")

# lettre de musique -> disc_canonical. La lettre EST la discipline du run.
_DISC_LETTER = {"PLAT": "a", "HAIE": "h", "STEEPLE": "s", "CROSS": "c",
                "ATTELE": "p", "MONTE": "m"}


def load_rows(conn, limit, disc=None, before=None, order="DESC"):
    """(race_key, target_disc, cote, musique, is_top5) — CHAMP COMPLET."""
    where = ["r.quinte=1"]
    params = []
    if disc:
        where.append("r.disc_canonical=?")
        params.append(disc.upper())
    if before:
        where.append("r.date < ?")
        params.append(before)
    sql = (
        "SELECT p.race_id, r.disc_canonical, p.cote_pmu, p.musique, p.rang "
        "FROM participants p JOIN races r ON r.race_id = p.race_id "
        f"WHERE {' AND '.join(where)} "
        f"ORDER BY r.date {order} LIMIT ?")
    params.append(limit)
    # On prend les N DERNIERS participants (pas courses) : le ratio top5/champ
    # reste correct tant qu'on ne découpe pas au milieu d'une course.
    rows = conn.execute(sql, params).fetchall()
    out = []
    for rid, disc_c, cote, musique, rang in rows:
        out.append((rid, _DISC_LETTER.get((disc_c or "").upper()), cote,
                    musique, (rang is not None and 1 <= rang <= 5)))
    return out


def report(rows, title, keys=None, show_dead=False):
    from QUINTE.dna import audit_rules
    alive, dead, n5, nf = audit_rules(rows)
    print(f"\n{'=' * 92}\n{title}")
    print(f"{'=' * 92}")
    print(f"champ : {nf} chevaux  |  Top5 : {n5}  |  base rate P(top5) = "
          f"{n5 / nf if nf else 0:.3f}")
    keys = keys or FEATURE_KEYS
    print(f"\n  {'feature':<12} {'valeur':<11} {'poids':>7} {'lift':>6} "
          f"{'P(top5)':>8} {'top5':>6} {'champs':>7} {'cours':>6}  STATUT")
    for key, val, a, b, nr, lift, w, p, _ in alive:
        if key not in keys:
            continue
        print(f"  {key:<12} {val:<11} {w:>+7.3f} {math.exp(lift):>6.2f} "
              f"{p:>8.3f} {a:>6} {b:>7} {nr:>6}  VIVANTE")
    if not [r for r in alive if r[0] in keys]:
        print("  (aucune regle sur ces cles)")
    if show_dead:
        print(f"\n  --- MORTES (les plus proches) ---")
        shown = 0
        for key, val, a, b, nr, lift, w, p, why in dead:
            if key not in keys:
                continue
            print(f"  {key:<12} {val:<11} {w:>+7.3f} {math.exp(lift):>6.2f} "
                  f"{p:>8.3f} {a:>6} {b:>7} {nr:>6}  {why}")
            shown += 1
            if shown >= 22:
                break
    return alive


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=400000)
    ap.add_argument("--disc", default=None)
    ap.add_argument("--before", default=None)
    ap.add_argument("--key", default=None, help="filtre une feature")
    ap.add_argument("--general", action="store_true",
                    help="extrait l'ADN general (accord disciplines) + residus")
    ap.add_argument("--dead", action="store_true",
                    help="affiche aussi les regles rejetees et pourquoi")
    a = ap.parse_args()

    conn = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro", uri=True)
    keys = [a.key] if a.key else None

    if a.general:
        by = {}
        for d in ("PLAT", "ATTELE", "MONTE"):
            by[d] = mine_rules(load_rows(conn, a.limit, disc=d, before=a.before))
        g = general_rules(by)
        print(f"\n{'=' * 92}\nADN GENERAL (signe agree dans >= 2 disciplines)")
        print(f"{'=' * 92}")
        print(f"  {'feature':<12} {'valeur':<11} {'poids':>7} {'lift':>6}  accords")
        for r in g:
            where = [d for d, rr in by.items()
                     if any(x.key == r.key and x.value == r.value for x in rr)]
            print(f"  {r.key:<12} {r.value:<11} {r.weight:>+7.3f} {r.lift:>6.2f}  "
                  f"{','.join(where)}")
        if not g:
            print("  (rien) - aucun motif de forme ne se transporte entre disciplines")
        for d in ("PLAT", "ATTELE", "MONTE"):
            res = discipline_rules(g, by[d])
            print(f"\n  --- residuel {d} (ADN propre a la discipline) ---")
            if not res:
                print(f"    (rien : ce que vaut {d} ne vaut QUE pour {d})")
            for r in res:
                print(f"    {r.key:<12} {r.value:<11} {r.weight:>+7.3f} "
                      f"lift={r.lift:.2f} top5={r.a}/{r.n_top5}")
        return 0

    rows = load_rows(conn, a.limit, disc=a.disc, before=a.before)
    if not rows:
        print("aucune course")
        return 1
    title = f"ADN Quinte - disc={a.disc or 'ALL'} before={a.before or 'all'}"
    report(rows, title, keys, show_dead=a.dead)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
