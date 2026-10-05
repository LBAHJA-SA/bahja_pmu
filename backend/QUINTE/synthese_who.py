"""
QUINTE.synthese_who — Synthèse Service, WHO = ADN. WHERE = TABLEAU.

=============================================================================
SÉPARATION STRICTE, ÉTABLIE UNE FOIS POUR TOUTES
=============================================================================
  WHERE  = le TABLEAU des places affichées. FIGÉ. Zéro ADN ici.
             A = P1..P4  (3)      <- 4 places disponibles, quota 3
             B = P5..P6  (1)
             C = P7..P8  (1)
             D = P9..P10 (1)
             E = P11..P18 (2)
             total 8
           WHERE est un CONTRAT D'AFFICHAGE. Le DNA n'a aucun droit dessus.

  WHO    = l'ADN, à 100 %. Uniquement lui.
           Ni cote, ni form, ni red_km ne sont lus comme un score.

=============================================================================
CE QUI A DISPARU DEPUIS synthese_service.py, ET LA MESURE QUI LE JUSTIFIE
=============================================================================
1. W_RED (0.987)  -> SUPPRIMÉ.
   `red_km` ne contient pas une distance, il contient un TEMPS
   ("1'41''4"). `_red_val()` fait float() dessus -> None, TOUJOURS.
   Terme mort à 100 %, sur 1.54M lignes. Amplitude mesurée : 0.0 point.

2. W_COTE (0.415) -> SUPPRIMÉ du score, REMPLACE par COTE_BAND minée.
   Amplitude mesurée dans un champ réel : 55.0 points contre 4.9 pour le
   form, soit 11:1. Et le top3 "weighted" est IDENTIQUE à celui qu'on
   obtiendrait par la cote seule dans 27.1% des champs.
   Ce n'était pas du scoring, c'était le marché, avec un décor.
   Et surtout il DISMENTAIT : l'archive dit que la bande 10-18 est
   FAVORABLE (lift 1.18, +0.16, 3312 courses) — le code lui met -5.81.
   La cote reste autorisée, mais comme PRIOR MINÉE, donc mesurée, donc
   retirable si l'archive la refuse.

3. W_FORM (0.967) -> SUPPRIMÉ du score, remplacé par la FORM SIGNATURE minée.
   L'archive est ASYMÉTRIQUE : elle ne sanctionne que le bas.
     TOP3_5=0   -> -0.230  (vivant)   <- zéro podium sur 5 courses
     TOP3_5=2   -> +0.091  (MORT, trop faible)
     TREND flat -> +0.100  (MORT)
     VOL low    -> +0.097  (MORT)
   Le form score actuel dépense toute sa dynamique sur le haut, là où
   l'archive ne distingue rien, et ferme les yeux sur le bas, où elle
   distingue. Il n'est pas seulement saturé par la presse : il place sa
   discrimination à l'envers.

4. Quotas adaptatifs (nfav -> need) -> SORTIS DU DÉCISIONNEL.
   C'était le SEUL endroit où l'ADN touchait la composition, et il ne
   comptait que des favoris : un compteur, pas une empreinte.
   WHERE est un contrat d'affichage, l'ADN n'y touche pas. `nfav` reste
   dans `support` comme diagnostic, plus rien d'autre.

5. `hidden_zones` (ctx qui re-trie C/D/E) -> FINI.
   Le profil caché devient CTX_BAND, feature minée comme les autres.
   Plus de switch qui décide "ici on sort du marché". Si le ctx vaut
   quelque chose, son poids le dira ; sinon il disparaît.

6. `_frequency_vote` / `target` / `per_rank` / `_dna_best_score` -> PARKÉS.
   Le max-across-P1..P5 est un test d'appartenance qui détruit le
   co-occurrence : deux chevaux "les plus proches de P1" est une
   contradiction, et rien n'interdit 3 fois la même famille.
   `family_counter` reste utilisé, mais pour ce qu'il sait faire : un
   prior de COMPOSITION (quelles familles sortent ensemble). Coefficient
   COMPO_ALPHA = 0.0, donc DÉSACTIVÉ, parce qu'il n'est pas mesuré et
   que je ne vends pas un gain inventé. Il ne s'active qu'après mesure.

=============================================================================
GARDE-FOU : AUCUN RETOUR AU MARCHÉ
=============================================================================
Si l'archive ne produit aucune règle (base trop mince, `before` trop
précoce, discipline inconnue), la fonction renvoie [] et
support["error"] = "no_dna_rules". Elle ne se rabat JAMAIS sur un ancien
score. Un moteur qui se dégrade silencieusement vers le marché est pire
qu'un moteur qui s'arrête : il continue de produire des tickets qui ont
l'air是对的.
"""

from __future__ import annotations

import sqlite3
import threading
from collections import defaultdict

from QUINTE.dna import (
    DnaRule, mine_rules, admit_pair, fit_dna, general_rules, discipline_rules,
    form_features, dna_score, explain, MIN_WEIGHT,
)
from QUINTE.service import (
    _valid_cotes, _is_out, _market_layer, _layer_family,
    get_quinte_top5_stats,
)

# ==========================================================================
# LE TABLEAU — source de vérité unique. Ne pas dupliquer ailleurs.
# (synthese_service.py contenait TROIS tableaux différents dans le même
#  fichier : le header, la docstring de france_zones et celle de
#  synthese_match. Le premier disait 3-1-1-1-2, le deuxième 4-1-1-2-1,
#  le troisième 1..6/7..8/9..10/11..18. Ici : 3-1-1-1-2, celui du header.)
# ==========================================================================
ZONE_PLACES = (("A", 1, 4, 3), ("B", 5, 6, 1), ("C", 7, 8, 1),
               ("D", 9, 10, 1), ("E", 11, 18, 2))
ZONE_QUOTA = {z: q for z, _lo, _hi, q in ZONE_PLACES}
TICKET_SIZE = sum(ZONE_QUOTA.values())          # 8

COMPO_ALPHA = 0.0     # prior de composition, OFF tant que non mesuré
MIN_RULES = 1         # en dessous, on ne rend pas de ticket
HIST_LIMIT = 400_000  # lignes d'historique par mine

# lettre de musique <-> disc_canonical
DISC_LETTER = {"PLAT": "a", "HAIE": "h", "STEEPLE": "s", "CROSS": "c",
               "ATTELE": "p", "MONTE": "m"}


# ==========================================================================
# SECRET — inchangé : doit rester aligné avec Synthese.jsx buildCells
# ==========================================================================
def _secret_display_order(nums):
    clean = []
    for n in (nums or []):
        if n is None:
            continue
        try:
            clean.append(int(n))
        except (TypeError, ValueError):
            continue
    if not clean:
        return []
    first_even = (clean[0] % 2 == 0)
    top = [n for n in clean if (n % 2 == 0) == first_even]
    bot = [n for n in clean if (n % 2 == 0) != first_even]
    cols = []
    for i in range(max(len(top), len(bot))):
        cols.append([(top[i] if i < len(top) else None),
                     (bot[i] if i < len(bot) else None)])
    out = []
    for col in cols:
        for n in col:
            if n is not None:
                out.append(n)
    return out


def france_zones(order):
    """Place affichée (1-based, ordre SECRET) -> zone. Uniquement ça."""
    zones = {}
    for idx, n in enumerate(order or [], start=1):
        if n is None:
            continue
        try:
            num = int(n)
        except (TypeError, ValueError):
            continue
        for z, lo, hi, _q in ZONE_PLACES:
            if lo <= idx <= hi:
                zones[num] = z
                break
    return zones


# ==========================================================================
# ADN : minage + cache
# ==========================================================================
_MINE_CACHE = {}
_MINE_LOCK = threading.Lock()

DDL = """
CREATE TABLE IF NOT EXISTS dna_rules (
  scope TEXT, disc TEXT, before TEXT, n_top5 INTEGER, n_field INTEGER,
  key TEXT, value TEXT, weight REAL, a INTEGER, b INTEGER, races INTEGER,
  lift REAL, PRIMARY KEY (scope, disc, before, key, value)
);
CREATE INDEX IF NOT EXISTS idx_dna_scope ON dna_rules(scope, disc, before);
"""


def _load_rows(conn, disc=None, before=None, after=None, limit=HIST_LIMIT):
    """(race_key, target_disc, cote, musique, is_top5) — CHAMP COMPLET."""
    where = ["r.quinte = 1"]
    params = []
    if disc:
        where.append("r.disc_canonical = ?")
        params.append(disc.upper())
    if before:
        where.append("r.date < ?")
        params.append(before)
    if after:
        where.append("r.date >= ?")
        params.append(after)
    params.append(int(limit))
    rows = conn.execute(
        "SELECT p.race_id, r.disc_canonical, p.cote_pmu, p.musique, p.rang "
        "FROM participants p JOIN races r ON r.race_id = p.race_id "
        f"WHERE {' AND '.join(where)} ORDER BY r.date DESC LIMIT ?",
        params).fetchall()
    letter = DISC_LETTER.get((disc or "").upper()) if disc else None
    out = []
    for rid, disc_c, cote, musique, rang in rows:
        tl = letter or DISC_LETTER.get((disc_c or "").upper())
        out.append((rid, tl, cote, musique,
                    rang is not None and 1 <= rang <= 5))
    return out


def mine_context(disc=None, before=None, limit=HIST_LIMIT, conn=None):
    """ADN du contexte : règles générales (accord disciplines) + résiduel local.

    Renvoie (regles, meta). Une liste vide est un résultat valable.
    """
    key = (disc or "*", before or "*", int(limit))
    with _MINE_LOCK:
        hit = _MINE_CACHE.get(key)
    if hit is not None:
        return hit

    own = None
    if conn is None:
        try:
            from database import get_db
            conn = get_db()
        except Exception:
            conn = None
    if conn is None:
        return [], {"error": "no_db", "disc": key[0], "before": key[1]}

    try:
        # ---- ADMISSION PAR AUC HORS-TEMPS ------------------------------
        # On coupe la fenêtre en deux par la date, on entraîne sur la
        # moitié ancienne et on exige que chaque FAMILLE de features classe
        # mieux que le hasard sur la moitié récente. Les familles refusées
        # n'ont aucun poids -> aucune façon d'influencer le classement.
        # Mesuré : COTE_BAND AUC 0.5578 (admis), toute la FORME AUC 0.4422
        # (refusée). C'est la mesure qui décide, pas une préférence.
        rows = _load_rows(conn, disc=disc, before=before, limit=limit)
        dates = sorted(d for d in (r[0] for r in conn.execute(
            "SELECT r.date FROM races r WHERE r.quinte=1"
            + (" AND r.date < ?" if before else "")
            + (" AND r.disc_canonical=?" if disc else "")
            + " ORDER BY r.date DESC LIMIT ?",
            tuple(x for x in ([before] if before else []) +
                  ([disc.upper()] if disc else []) + [int(limit)])).fetchall())
            if d)
        cut = dates[len(dates) // 2] if dates else None
        ra = _load_rows(conn, disc=disc, before=cut, limit=limit)
        rb = _load_rows(conn, disc=disc, before=before, after=cut, limit=limit)
        own, report = fit_dna(ra, rb, verbose=True)
        for g, r in sorted((report.get("groups") or {}).items()):
            if isinstance(r, dict) and not r.get("admitted"):
                print(f"    REFUSE {g:<10} {r.get('why', '')}")

        # ADN général : même pitch miné par discipline, seules les
        # signatures de signe concordant deviennent "générales" ; le reste
        # reste local. C'est la demande "ne pas mélanger Trot / Haies / Plat".
        by = {}
        if disc:
            by[disc] = own
        else:
            for d in ("PLAT", "ATTELE", "MONTE"):
                a = _load_rows(conn, disc=d, before=cut, limit=limit)
                b = _load_rows(conn, disc=d, before=before, after=cut, limit=limit)
                by[d], _rep = fit_dna(a, b)
        g_rules = general_rules(by)
        res = discipline_rules(g_rules, own)
        rules = list(g_rules) + res
        n5 = sum(1 for r in rows if r[4])
        meta = {
            "disc": key[0], "before": key[1], "cut": cut,
            "n_field": len(rows), "n_top5": n5,
            "base_rate": round(n5 / len(rows), 4) if rows else None,
            "admission": report,
            "general": len(g_rules), "residual": len(res),
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass

    with _MINE_LOCK:
        _MINE_CACHE[key] = (rules, meta)
    return rules, meta


# ==========================================================================
# WHO
# ==========================================================================
def _build_candidates(participants, zones, target_letter):
    cotes = {}
    for c, p in _valid_cotes(participants):
        cotes[p.get("num")] = c
    out = {}
    for p in participants or []:
        n = p.get("num")
        if n is None or n in out or zones.get(n) is None:
            continue
        try:
            if _is_out(p):
                continue
        except Exception:
            pass
        cote = cotes.get(n)
        if cote is None:
            c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
            try:
                cote = float(c) if c not in (None, "") else None
            except (TypeError, ValueError):
                cote = None
        out[n] = {
            "num": n, "horse": p.get("horse"), "cote": cote,
            "zone": zones[n],
            "layer": _market_layer(cote) if cote is not None else "UNK",
            "features": form_features(p.get("musique"), cote=cote,
                                       target_disc=target_letter),
        }
    for i, n in enumerate(sorted(cotes, key=lambda k: cotes[k]), start=1):
        if n in out:
            out[n]["market_rank"] = i
    for h in out.values():
        h.setdefault("market_rank", 999)
    return out


def _composition_prior(pool, disc):
    """P( Famille présente dans le Top5 ) depuis les signatures observées.

    Utilise `family_counter` pour ce qu'il sait : la STRUCTURE conjointe.
    Joint, pas marginal. COMPO_ALPHA = 0 => désactivé, cf. en-tête.
    """
    if not COMPO_ALPHA or not pool:
        return {}, {}
    per_rank, seen = defaultdict(float), defaultdict(float)
    races = sum(s["count"] for s in pool) or 1
    for s in pool:
        w = s["count"] / races
        for i, fam in enumerate(s.get("families") or [], start=1):
            per_rank[(str(i), _layer_family(fam))] += w
        for fam in s.get("families") or []:
            seen[_layer_family(fam)] += w
    return dict(per_rank), dict(seen)


def _nfav_diag(pool):
    """Diagnostic seul : nombre de positions P1..P5 dont la famille
    dominante est FAV. Servait à piloter les quotas adaptatifs.
    N'a plus aucun droit de vote — cf. en-tête, point 4."""
    if not pool:
        return 0
    votes = defaultdict(float)
    for s in pool:
        n = float(s.get("count") or 0)
        for i, fam in enumerate(s.get("families") or [], start=1):
            votes[(str(i), _layer_family(fam))] += n
    out = 0
    for p in ("1", "2", "3", "4", "5"):
        best = max(((v, k[1]) for k, v in votes.items() if k[0] == p),
                   default=(0.0, ""))
        if best[1] == "FAV" and best[0] > 0:
            out += 1
    return out


def synthese_match(participants, hippodrome=None, distance=None, runners=None,
                   presse=None, disc=None, before=None, debug=False,
                   rules=None, meta=None, conn=None):
    """Synthèse WHO=ADN. WHERE=TABLEAU. Retourne (results, support[, dbg]).

    `rules` : liste de DnaRule déjà minée. Si None, minage automatique
              (cache 1h en mémoire + possible re-minage en backtest).
    Aucun chemin ne mène au marché : pas de règles, pas de ticket.
    """
    cotes_all = _valid_cotes(participants)
    if not cotes_all:
        return [], -1

    # ---- WHERE ---------------------------------------------------------
    if presse and len([n for n in presse if n is not None]) >= 14:
        base = [int(n) for n in presse if n is not None][:18]
        presse_source = "presse"
    else:
        base = [p.get("num") for _, p in cotes_all[:18]]
        presse_source = "market_fallback"
    order = _secret_display_order(base)
    zones = france_zones(order)

    fp = _fingerprint(participants, hippodrome, distance, runners, disc, before)
    pool = fp["pool"]

    if rules is None:
        rules, meta = mine_context(disc=disc, before=before, conn=conn)

    support = {
        "who": "dna",
        "where": "tableau",
        "quota": "-".join(str(ZONE_QUOTA[z]) for z in ("A", "B", "C", "D", "E")),
        "presse_source": presse_source,
        "structures": len(pool),
        "races": sum(s["count"] for s in pool) if pool else 0,
        "scope": fp["scope"],
        "top": [{"signature": s["signature"], "count": s["count"]} for s in pool[:3]],
        "nfav_diag": _nfav_diag(pool),          # plus de pouvoir de decision
        "dna_rules": len(rules or []),
        "dna_meta": {k: v for k, v in (meta or {}).items() if k != "rules"},
    }
    if not pool:
        support["error"] = "no_structures"
        return [], support
    if not rules or len(rules) < MIN_RULES:
        support["error"] = "no_dna_rules"
        return [], support

    # ---- WHO -----------------------------------------------------------
    target_letter = DISC_LETTER.get((disc or "").upper())
    horses = _build_candidates(participants, zones, target_letter)
    if not horses:
        support["error"] = "empty_frame"
        return [], support

    # dénominateur = masse de poids couverte, moyenne du champ. Sans ça un
    # cheval avec 14 features connues marque plus haut qu'un cheval à 6.
    masses = [sum(abs(r.weight) for r in rules
                  if h["features"].get(r.key) is not None) for h in horses.values()]
    live = [m for m in masses if m > 0]
    denom = (sum(live) / len(live)) if live else 0.0
    support["feature_coverage"] = round(len(live) / max(len(masses), 1), 3)
    support["dna_denom"] = round(denom, 4)
    if denom <= 0:
        # aucune feature exploitable sur ce champ (ex. musique absente pour
        # toute la course). On ne retombe PAS sur l'ancien score : on
        # degrade explicitement, et le front doit pouvoir l'afficher.
        support["error"] = "no_features_in_frame"
        support["degraded"] = "musique_absente"
        return [], support

    for h in horses.values():
        h["dna"], h["fired"] = dna_score(h["features"], rules, denom=denom)

    per_rank_prior, set_prior = _composition_prior(pool, disc)
    seen = defaultdict(int)

    def compo(fam):
        if not COMPO_ALPHA:
            return 0.0
        want = COMPO_ALPHA * TICKET_SIZE * (set_prior.get(fam, 0.0) or 0.0)
        return -abs(seen[fam] - want) * COMPO_ALPHA

    dbg = {"ties": 0, "fill": 0, "compo": bool(COMPO_ALPHA),
           "coverage": support["feature_coverage"], "tiebreak": set()}
    results, picked = [], set()

    for z, _lo, _hi, quota in ZONE_PLACES:
        cand = sorted(
            ((h["dna"] + compo(_layer_family(h["layer"])), h["market_rank"], n)
             for n, h in horses.items()
             if h["zone"] == z and n not in picked),
            key=lambda t: (-t[0], t[1], t[2]))
        if not cand:
            continue
        chosen = [t[2] for t in cand[:quota]]
        # égalité au seuil : on le note, market_rank ne tranche JAMAIS seul
        if quota > 1 and len(chosen) > 1:
            cut = cand[quota - 1][0]
            ties = [t[2] for t in cand[:quota] if abs(t[0] - cut) < 1e-9]
            if len(ties) > 1:
                dbg["ties"] += 1
                dbg["tiebreak"].update(ties)
        # comblement : MÊME zone, MÊME cadre, tri ADN. Jamais le marché.
        if len(chosen) < quota:
            for _s, _r, n in cand:
                if n in chosen:
                    continue
                chosen.append(n)
                dbg["fill"] += 1
                if len(chosen) >= quota:
                    break
        for n in chosen:
            h = horses[n]
            picked.add(n)
            seen[_layer_family(h["layer"])] += 1
            results.append({
                "num": n, "horse": h["horse"], "cote": h["cote"],
                "market_rank": h["market_rank"],
                "presse_rank": order.index(n) + 1 if n in order else 999,
                "zone": z, "dna_pos": None, "layer": h["layer"],
                "score": round(h["dna"], 4),
                "target_family": None, "weak": h["dna"] <= 0,
                "source": "dna",
                "reasons": explain(h["fired"]),
            })

    # Garantit 8 : inter-zones, TOUJOURS dans le cadre affiché, TOUJOURS par ADN.
    if len(results) < TICKET_SIZE:
        have = {r["num"] for r in results}
        rest = sorted(
            ((horses[n]["dna"], horses[n]["market_rank"], n)
             for n, h in horses.items() if n not in have and n not in picked),
            key=lambda t: (-t[0], t[1], t[2]))
        for _s, _r, n in rest:
            if len(results) >= TICKET_SIZE:
                break
            h = horses[n]
            picked.add(n)
            results.append({
                "num": n, "horse": h["horse"], "cote": h["cote"],
                "market_rank": h["market_rank"],
                "presse_rank": order.index(n) + 1 if n in order else 999,
                "zone": h["zone"], "dna_pos": None, "layer": h["layer"],
                "score": round(h["dna"], 4), "target_family": None,
                "weak": h["dna"] <= 0, "source": "dna",
                "reasons": explain(h["fired"]),
            })
            dbg["fill"] += 1

    support["picked"] = [r["num"] for r in results]
    support["zone_map"] = {r["num"]: r["zone"] for r in results}
    if debug:
        dbg["tiebreak"] = sorted(dbg["tiebreak"])
        dbg["scores"] = {str(r["num"]): r["score"] for r in results}
        return results, support, dbg
    return results, support


# ==========================================================================
def _build_pool(hist, min_support=5):
    """Signatures JOINTES (family_counter = familles, pas layers)."""
    pool = []
    for sig, cnt in (hist.get("family_counter") or {}).items():
        try:
            n = int(cnt or 0)
        except (TypeError, ValueError):
            continue
        fams = [s.strip() for s in str(sig).split("→")]
        if n >= min_support and len(fams) == 5:
            pool.append({"signature": sig, "families": fams, "count": n})
    pool.sort(key=lambda x: -x["count"])
    return pool


def _fingerprint(participants, hippodrome=None, distance=None, runners=None,
                 disc=None, before=None):
    """PISCINE de structures observées, dans le contexte de la course.
    Narrow -> wide ; premier scope avec un pool non vide gagne."""
    scopes = [
        ("hippodrome+shape", dict(hippodrome=hippodrome, distance=distance,
                                  runners=runners)),
        ("hippodrome", dict(hippodrome=hippodrome)),
        ("discipline", dict(disc=disc)),
        ("global", {}),
    ]
    pool, scope, hist = [], "none", {}
    for name, kw in scopes:
        kw = {k: v for k, v in kw.items() if v is not None}
        if name.startswith("hippodrome") and not kw.get("hippodrome"):
            continue
        if name == "discipline" and not kw.get("disc"):
            continue
        h = get_quinte_top5_stats(limit=4054, before=before, **kw)
        p = _build_pool(h)
        if p:
            hist, pool, scope = h, p, name
            break
        hist = h
    return {"hist": hist, "pool": pool, "scope": scope}
