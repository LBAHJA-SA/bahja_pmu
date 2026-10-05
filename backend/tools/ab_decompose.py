"""
Décomposition de la valeur : QUI apporte quoi, dans le WHO actuel.

4 bras, même WHERE (mêmes zones), même fenêtre, mêmes courses :

  A  ANCIEN      : W_RED(mort) + W_COTE*cote + W_FORM*form, quotas adaptatifs
  B  MARCHE      : cote seul, quotas adaptatifs        -> isole le terme FORM
  C  ANCIEN-FIXE : idem A, quotas fixes 3-1-1-1-2     -> isole les quotas
  D  MARCHE-FIXE : cote seul, quotas fixes             -> le plus simple possible

Ce qu'on cherche : quel COMPOSANT du moteur actuel porte la couverture,
et lesquels ne sont que du bruit. Réponse connue d'avance pour le form
(AUC hors-temps 0.44, DAI 0.48 stable sur 4 ans) — mais il faut le mesurer
dans la sélection, pas seulement en classification.

Usage :  py tools/ab_decompose.py --n 300
"""
import argparse
import os
import sys
import sqlite3
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))

from QUINTE import synthese_service as S  # noqa: E402
from QUINTE.service import _valid_cotes, _market_layer, _layer_family  # noqa: E402
from tools.ab_who import DB, load_races, field, disc_of  # noqa: E402

W_RED, W_COTE, W_FORM = 0.9870174151944342, 0.4148605763544888, 0.9674345543146796
FIXED = {"A": 3, "B": 1, "C": 1, "D": 1, "E": 2}
ZONE_PLACES = (("A", 1, 4, 3), ("B", 5, 6, 1), ("C", 7, 8, 1),
               ("D", 9, 10, 1), ("E", 11, 18, 2))


_PTS = {1: 10.0, 2: 7.0, 3: 5.0, 4: 3.0, 5: 2.0, 6: 1.0, 7: 1.0, 8: 1.0, 9: 1.0}


def form_fixed(musique):
    """Form Score CORRIGE. Deux defauts de _form_score_shadow :
      (a) runs[:6] prend les PLUS ANCIENS (la chaine est ancien->recent,
          prouvé par le marqueur de saison) -> c'est la forme de l'an dernier ;
      (b) la moyenne est divisee par le NOMBRE de runs -> un cheval avec
          une seule 1re place marque 10.0, le maximum. Le score mesure
          donc surtout la LONGUEUR DE CARRIERE, pas la forme.
    Ici : on prend les 5 runs les PLUS RECENTS, on exclut les DAI de la
    moyenne (et on les compte a part), et on divise par un denominateur
    FIXE. Plus aucune dependance a la longueur de carriere.
    """
    from QUINTE.dna import parse_musique
    t = parse_musique(musique)
    if not t:
        return None
    last5 = t[-5:]
    places = [x["rank"] for x in last5 if x["kind"] == "PLACE" and 1 <= x["rank"] <= 20]
    if not places:
        return None
    return sum(_PTS.get(p, 0.0) for p in places) / 5.0


def career_len(musique):
    """HYPOTHESE CONCURRENTE : le +7.1 vient du nombre de courses, pas de
    la forme. On le teste tout seul."""
    from QUINTE.dna import parse_musique
    t = parse_musique(musique)
    if not t:
        return None
    n = len([x for x in t if x["kind"] in ("PLACE", "DAI", "STOP", "FALL")])
    if n == 0:
        return None
    return 1.0 / (1.0 + n)      # court = score haut, comme le defaut actuel


def score(kind, red, form, cote):
    if kind == "cote":
        return -cote
    s = 0.0
    if red is not None:
        s += W_RED * (-red)
    if form is not None:
        s += W_FORM * form
    if cote is not None:
        s += W_COTE * (-cote)
    return s


def pick(ps, use_form, adaptive, target_hist=None, form_fn=None):
    cotes = _valid_cotes(ps)
    if not cotes:
        return []
    order = S._secret_display_order([p.get("num") for _, p in cotes[:18]])
    zones = S.france_zones(order)
    horses = {}
    for i, (c, p) in enumerate(cotes):
        n = p.get("num")
        if zones.get(n) is None:
            continue
        red = S._red_val(p.get("red_km"))
        if not use_form:
            form = None
        elif form_fn is not None:
            form = form_fn(p.get("musique"))
        else:
            form = S._form_score_for_tie(p.get("musique"))
        horses[n] = {"n": n, "c": c, "m": i + 1, "z": zones[n],
                     "s": score("full" if use_form else "cote", red, form, c)}
    if adaptive:
        tl = {}
        if target_hist:
            for s_ in (target_hist or {}).get("family_counter", {}):
                pass
        nfav = 0
        need = {"A": 2, "B": 1, "C": 1, "D": 1, "E": 3}
        # le moteur productif calcule nfav depuis son propre fingerprint ;
        # on reproduit les 3 splits pour ne pas dependre de lui ici
        hist = target_hist or {}
        votes = defaultdict(float)
        for s_, cnt in (hist.get("family_counter") or {}).items():
            for i, fam in enumerate(str(s_).split("→")):
                votes[(str(i + 1), _layer_family(fam.strip()))] += float(cnt or 0)
        for p in "12345":
            best = max(((v, k[1]) for k, v in votes.items() if k[0] == p),
                       default=(0, ""))
            if best[1] == "FAV" and best[0] > 0:
                nfav += 1
        need = ({"A": 4, "B": 1, "C": 1, "D": 1, "E": 1} if nfav >= 4 else
                {"A": 3, "B": 1, "C": 1, "D": 1, "E": 2} if nfav == 3 else
                {"A": 2, "B": 1, "C": 1, "D": 1, "E": 3})
    else:
        need = FIXED
    out, picked = [], set()
    for z, _lo, _hi, quota in ZONE_PLACES:
        pool = sorted((h for h in horses.values()
                       if h["z"] == z and h["n"] not in picked),
                      key=lambda h: (-h["s"], h["m"]))
        for h in pool[:quota]:
            picked.add(h["n"])
            out.append(h["n"])
    if len(out) < 8:
        rest = sorted((h for h in horses.values() if h["n"] not in picked),
                      key=lambda h: (-h["s"], h["m"]))
        for h in rest:
            if len(out) >= 8:
                break
            out.append(h["n"])
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--before", default="2025-01-01")
    a = ap.parse_args()
    conn = sqlite3.connect(f"file:{os.path.abspath(DB)}?mode=ro", uri=True)

    races = load_races(conn, None, after=a.before, n=a.n)
    acc = defaultdict(int)
    tot = 0
    for rid in races:
        ps = field(conn, rid)
        if len(ps) < 10:
            continue
        d, hip, dist, run, date = disc_of(conn, rid)
        hist = S.synthese_fingerprint(ps, hip, dist, run, d, before=a.before)
        top5 = {p["num"] for p in ps if 1 <= (p.get("rang") or 99) <= 5}
        tot += len(top5)
        acc["A"] += len(top5 & set(pick(ps, True, True, hist["hist"])))
        acc["B"] += len(top5 & set(pick(ps, False, True, hist["hist"])))
        acc["C"] += len(top5 & set(pick(ps, True, False, hist["hist"])))
        acc["D"] += len(top5 & set(pick(ps, False, False, hist["hist"])))
        acc["E"] += len(top5 & set(pick(ps, True, True, hist["hist"], form_fixed)))
        acc["F"] += len(top5 & set(pick(ps, True, True, hist["hist"], career_len)))
        acc["G"] += len(top5 & set(pick(ps, True, True, hist["hist"],
                                       lambda m: (form_fixed(m) or 0.0)
                                       + (career_len(m) or 0.0))))

    names = {
        "A": "ANCIEN      form actuel (_form_score_shadow)",
        "B": "SANS FORM   cote seul",
        "C": "ANCIEN      quotas fixes (au lieu d'adaptatifs)",
        "D": "SANS FORM   quotas fixes",
        "E": "FORM CORRIGE  5 runs les plus recents, denom fixe",
        "F": "LONGUEUR DE CARRIERE seule (1/(1+n))",
        "G": "FORM CORRIGE + longueur de carriere",
    }
    print(f"\n{'=' * 78}\nCOUVERTURE Top5 — {len(races)} courses, "
          f"test >= {a.before}\n{'=' * 78}")
    base = acc["A"] / tot * 100
    for k in "ABCDEFG":
        v = acc[k] / tot * 100
        print(f"  {names[k]:<52} {v:>6.1f}%   {v - base:>+6.1f}")
    print(f"\n  gain du terme FORM actuel        : "
          f"{(acc['A'] - acc['B']) / tot * 100:+.1f} points")
    print(f"  gain de la longueur de carriere   : "
          f"{(acc['F'] - acc['B']) / tot * 100:+.1f} points   <-- hypothese")
    print(f"  gain du form CORRIGE              : "
          f"{(acc['E'] - acc['B']) / tot * 100:+.1f} points")
    print(f"  effet des quotas adaptatifs       : "
          f"{(acc['A'] - acc['C']) / tot * 100:+.1f} points")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
