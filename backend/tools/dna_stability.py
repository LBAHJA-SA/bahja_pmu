"""
LA QUESTION FINALE : un signal existe-t-il, ou est-ce du bruit ?

On entraîne sur tout ce qui précède une date, on teste sur l'année qui
suit, et on répète sur 4 fenêtres indépendantes. Pour chaque FAMILLE de
features.

Un signal VRAI se lit dans les 4 colonnes : même signe, même ordre
difficulty. Du bruit change de colonne en colonne — et c'est exactement ce
qui s'est produit sur une première passe, où COTE_BAND était "signal" en
2025 et "chance" en 2020-2025.

C'est le test qui tranche, et il est volontairement impitoyable : on
regarde la tenue dans le temps, pas la brillance d'un seul échantillon.

Usage :  py tools/dna_stability.py
"""
import os
import sys
import sqlite3

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from QUINTE.dna import (  # noqa: E402
    build_matrix, fit_logistic, auc, FEATURE_GROUPS, _group,
)
from tools.ab_who import DB  # noqa: E402

# (fin d'entraînement, début de test, fin de test)
WINDOWS = [
    ("2019-01-01", "2019-01-01", "2020-01-01"),
    ("2021-01-01", "2021-01-01", "2022-01-01"),
    ("2023-01-01", "2023-01-01", "2024-01-01"),
    ("2024-01-01", "2024-01-01", "2025-01-01"),
]


def rows_between(conn, lo, hi):
    where, params = ["r.quinte = 1"], []
    if lo:
        where.append("r.date >= ?")
        params.append(lo)
    if hi:
        where.append("r.date < ?")
        params.append(hi)
    params.append(400000)
    rs = conn.execute(
        "SELECT p.race_id, r.disc_canonical, p.cote_pmu, p.musique, p.rang "
        "FROM participants p JOIN races r ON r.race_id = p.race_id "
        f"WHERE {' AND '.join(where)} ORDER BY r.date DESC LIMIT ?",
        params).fetchall()
    from QUINTE.synthese_who import DISC_LETTER
    return [(rid, DISC_LETTER.get((dc or "").upper()), cote, mus,
             rang is not None and 1 <= rang <= 5)
            for rid, dc, cote, mus, rang in rs]


def main():
    conn = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro", uri=True)
    groups = list(FEATURE_GROUPS)
    table = {}

    for tr_end, te_lo, te_hi in WINDOWS:
        tr = rows_between(conn, None, tr_end)
        te = rows_between(conn, te_lo, te_hi)
        if len(tr) < 5000 or len(te) < 800:
            print(f"  {te_lo[:4]} : donnees insuffisantes "
                  f"(train={len(tr)} test={len(te)})")
            continue
        Xtr, ytr, idx = build_matrix(tr)
        Xte, yte, _ = build_matrix(te)
        # toutes les familles ensemble : le ranking relatif est ce qui compte
        w, b = fit_logistic(Xtr, ytr)
        table.setdefault("TOUTES (ensemble)", []).append(auc(Xte, yte, w, b))
        for g in groups:
            cols = {n: c for n, c in idx.items() if _group(n) == g}
            if not cols:
                continue
            col2new = {cols[n]: i for i, n in enumerate(sorted(cols))}
            proj = lambda rows, _m=col2new: [
                {_m[c]: v for c, v in d.items() if c in _m} for d in rows]
            w2, b2 = fit_logistic(proj(Xtr), ytr)
            table.setdefault(g, []).append(auc(proj(Xte), yte, w2, b2))
        print(f"  fenetre {te_lo[:4]} -> {te_hi[:4]} : "
              f"train={len(ytr)} test={len(yte)}", flush=True)

    years = [w[1][:4] for w in WINDOWS if w[1][:4] in
             {str(len(table.get(g, []))) for g in ()} or True]
    print(f"\n{'=' * 88}")
    print("AUC HORS-TEMPS PAR FAMILLE DE FEATURES  (>0.5 = signal)")
    print("=" * 88)
    cols_w = len(WINDOWS)
    head = "".join(f"{w[1][:4]:>9}" for w in WINDOWS)
    print(f"  {'famille':<20}{head}   VERDICT")
    print(f"  {'':<20}" + "-" * (9 * cols_w) + "   " + "-" * 26)
    for g, vals in sorted(table.items(), key=lambda kv: -sum(kv[1]) / len(kv[1])):
        mean = sum(vals) / len(vals)
        pos = sum(1 for v in vals if v > 0.5)
        if pos == len(vals) and min(vals) > 0.51:
            v = "SIGNAL STABLE"
        elif pos == 0:
            v = "INVERSE STABLE"
        elif pos <= len(vals) / 2:
            v = "bruit (aucun signe fixe)"
        else:
            v = "instable"
        cells = "".join(f"{x:>9.4f}" for x in vals)
        print(f"  {g:<20}{cells}   {v:<26} moy={mean:.4f}")
    print(f"\n  LECTURE : une seule ligne 'SIGNAL STABLE' vaut quelque chose.")
    print(f"  Une ligne qui change de colonne d'une annee a l'autre est du bruit,")
    print(f"  quelle que soit la taille de l'ecart affiche sur UNE fenetre.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
