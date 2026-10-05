"""
Le test qui décide de tout : le DNA a-t-il un SIGNAL, et c'est le
NOUVEAU ou l'ANCIEN qui en a ?

Deux mesures, dans cet ordre, parce qu'elles ne répondent pas à la même
question :

  1. AUC in-sample / hors-temps, par fenetre de date, par discipline.
     -> "est-ce que la Form Signature predit le Top5 ?"
        AUC = 0.50 => le DNA est decoratif, tout le reste est litterature.

  2. Couverture Top5 du ticket, WHO ancien vs WHO nouveau, meme cadre.
     -> "est-ce que carapporte ?"

Le point 1 est decide : si le signal existe, le point 2 se joue sur le
moteur. Si le signal n'existe pas, aucun reglage de selecteur ne le
creera, et il faut le dire.

Usage :  py tools/dna_signal.py
"""
import os
import sqlite3
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from QUINTE.dna import (  # noqa: E402
    build_matrix, fit_logistic, auc, mine_rules, FEATURE_KEYS,
)
from tools.ab_who import DB  # noqa: E402

_SPLIT = ("2023-01-01", "2025-01-01", "2026-01-01")   # train / test / futur


def rows_between(conn, lo, hi, disc=None):
    where = ["r.quinte = 1"]
    params = []
    if disc:
        where.append("r.disc_canonical = ?")
        params.append(disc.upper())
    if lo:
        where.append("r.date >= ?")
        params.append(lo)
    if hi:
        where.append("r.date < ?")
        params.append(hi)
    params.append(400000)
    rows = conn.execute(
        "SELECT p.race_id, r.disc_canonical, p.cote_pmu, p.musique, p.rang "
        "FROM participants p JOIN races r ON r.race_id = p.race_id "
        f"WHERE {' AND '.join(where)} ORDER BY r.date DESC LIMIT ?",
        params).fetchall()
    from QUINTE.synthese_who import DISC_LETTER
    out = []
    for rid, dc, cote, mus, rang in rows:
        out.append((rid, DISC_LETTER.get((dc or "").upper()), cote, mus,
                    rang is not None and 1 <= rang <= 5))
    return out


def _auc_of(X, y, w, b, keep=None, drop=None):
    """AUC restreint a un sous-ensemble de colonnes (keep = prefixes)."""
    if keep is not None:
        cols = [c for n, c in keep.items() if n.split("=")[0] in keep[0]
                or True] if False else None
    return None


def run(conn, disc=None, label="TOUTES"):
    tr = rows_between(conn, None, _SPLIT[1], disc)
    te = rows_between(conn, _SPLIT[1], _SPLIT[2], disc)
    if len(tr) < 5000 or len(te) < 800:
        print(f"  {label:<10} donnees insuffisantes (train={len(tr)} test={len(te)})")
        return
    Xtr, ytr, idx = build_matrix(tr)
    Xte, yte, _ = build_matrix(te)
    w, b = fit_logistic(Xtr, ytr)
    a_in, a_out = auc(Xtr, ytr, w, b), auc(Xte, yte, w, b)
    print(f"  {label:<10} train={len(ytr):>6}  test={len(yte):>6}  "
          f"colonnes={len(idx):>3}")
    print(f"             AUC in-sample ={a_in:>7.4f}   "
          f"AUC HORS-TEMPS ={a_out:>7.4f}   "
          f"{'SIGNAL' if a_out > 0.53 else ('CHANCE' if a_out > 0.47 else 'INVERSE')}")

    # --- LA DÉCOMPOSITION QUI DÉCIDE -----------------------------------
    # COTE seul vs FORME seule, même ajustement, hors temps.
    cote_cols = {n: c for n, c in idx.items() if n.startswith("COTE_BAND=")}
    form_cols = {n: c for n, c in idx.items() if not n.startswith("COTE_BAND=")}

    for name, cols in (("COTE seul  ", cote_cols), ("FORME seule", form_cols)):
        if not cols:
            print(f"             {name}: aucune colonne")
            continue
        names = list(cols)
        col2new = {cols[n]: i for i, n in enumerate(names)}

        def proj(rows, _m=col2new):
            return [{_m[c]: v for c, v in d.items() if c in _m} for d in rows]
        w2, b2 = fit_logistic(proj(Xtr), ytr)
        a2 = auc(proj(Xte), yte, w2, b2)
        verdict = ("SIGNAL" if a2 > 0.53 else
                   "CHANCE" if a2 > 0.47 else "INVERSE")
        print(f"             AUC {name} = {a2:.4f}   {verdict}")

    print("     plus forts coefficients (entraines) :")
    for name, col in sorted(idx.items(), key=lambda kv: -abs(w[kv[1]]))[:8]:
        print(f"       {name:<22} {w[col]:+.3f}")


def main():
    conn = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro", uri=True)
    print("FENETRES : train < %s | test %s..%s\n"
          % (_SPLIT[1], _SPLIT[1], _SPLIT[2]))
    run(conn, None, "TOUTES")
    for d in ("PLAT", "ATTELE", "MONTE", "HAIE"):
        run(conn, d, d)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
