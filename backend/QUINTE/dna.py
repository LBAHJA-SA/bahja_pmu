"""
QUINTE.dna — ADN reel du Quinté, GENERAL + DISCIPLINE.

=============================================================================
CE QUE CE MODULE FAIT (et ce qu'il ne fait pas)
=============================================================================
Il ne calcule PAS un score de cheval. Il EXTRAIT des règles de l'archive :

    poids = log-lift de la signature, mesuré contre le CHAMP COMPLET.

Pas de pénalité, pas de distance à un idéal, pas de W_RED / W_COTE / W_FORM.
Un cheval ne perd jamais de points parce qu'il a "0a" ou "cote 22" : il perd
parce que l'archive, sur des milliers de courses, dit que sa signature sort
moins souvent que la moyenne. Si l'archive ne dit rien, le poids est 0 et la
signature n'existe pas. Point.

=============================================================================
LE CONTRÔLE NÉGATIF — la seule chose qui rend ce module différent
=============================================================================
Une signature n'est un ADN que si elle est SUR-REPRÉSENTÉE dans le Top5 :

        P(Top5 | signature)  >>  P(Top5 | cheval quelconque) = 5/N

Sans la colonne `is_top5 = False` (le champ non-gagnant), rien n'est
honnête : "il y a toujours des DAI dans un Quinté" est VRAI et INUTILE.
C'est exactement le piège du scoring par points : la presse choisit des
chevaux DAI, ils courent, ils sont dans le champ, et la presse les
recommande — donc DAI "semble" toujours bon. Il faut le dénominateur.

=============================================================================
CE QUE LA MUSIQUE CONTIENT RÉELLEMENT (vérifié sur archive.db, 1.54M lignes)
=============================================================================
Format sans séparateurs, ex :
    "4a5a7a6aDa(25)4a7aDaDm"

  - <rang><lettre>  : la LETTRE EST LA DISCIPLINE de la course de CE run.
                       a=plat/galop  h=haies  s=steeple  c=cross
                       p=trot(pace)  m=monte
                       => l'historique de forme d'un cheval PORTE sa
                          discipline. Personne dans ce code ne l'utilise.
  - D+lettre         : DAI / disqualification
  - A+lettre         : arrêt        T+lettre : tombé       Q+lettre : divers
  - (NN)             : CHANGEMENT DE SAISON. Tout ce qui suit est la saison
                       courante, tout ce qui précède est l'an passé.
                       64% des chevaux portent ce marqueur.
                       => la forme "récente" est une question de 6 caractères,
                       et le scoring actuel l'ignore (voir note plus bas).

ORDRE DE LA CHAÎNE : du PLUS ANCIEN au PLUS RÉCENT.
  Preuve : "6p2p4p(25)9p7p" -> les 2 runs les plus récents sont ceux après
  le marqueur. Attention : _form_runs() de service.py prétend "newest first"
  mais renvoie l'ordre de la chaîne, donc l'INVERSE. Bug latent existant.

=============================================================================
CE QUE CE MODULE REFUSE DE FAIRE
=============================================================================
  - AUCUNE feature dérivée de market_rank / presse_rank / zone. Sinon on
    réintroduit la presse par la porte dérobée et on "découvre" la tautologie.
    Le marché n'entre QUE par COTE_BAND, qui est une prior MINÉE : donc
    mesurée, donc retirable si l'archive la refuse.
  - AUCUNE feature calculée sur une musique postérieure à la date de la
    course. `before` (LOO strict) est obligatoire côté appelant.
  - AUCUNE règle écrite en dur. Si DAI n'est pas retrouvé ici, DAI est
    FAUX pour ce contexte et doit disparaître du moteur.
"""

from __future__ import annotations

import math
import re
from collections import defaultdict

# --------------------------------------------------------------------------
# PARAMÈTRES DU MINEUR — seuils volontairement hauts. Une règle doit
# survivre à l'élimination des faux positifs : on teste ~50 hypothèses.
# --------------------------------------------------------------------------
MIN_TOP5 = 40        # chevaux gagnants portant la signature
MIN_FIELD = 150      # chevaux NON gagnants portant la signature
MIN_RACES = 15       # courses distinctes (une star ne fait pas une règle)
MIN_WEIGHT = 0.12    # |w| minimal
Z_SIG = 3.0          # seuil de significativité (1.96 serait trop permissif
                     # pour ~50 tests multiples)
SHRINK_K = 12.0      # rétrécissement empirique vers 0
MIN_DISC_FOR_GENERAL = 2

# Bandes de cote ABSOLUES : une course de 2019 et celle de dimanche doivent
# produire la même catégorie. C'est une prior, pas un verdict.
COTE_BANDS = ((1.0, 3.0, "c1-3"), (3.0, 7.0, "c7-7"), (7.0, 10.0, "c7-10"),
              (10.0, 18.0, "c10-18"), (18.0, 31.0, "c18-31"),
              (31.0, 50.0, "c31-50"), (50.0, 1e9, "c50+"))

# Familles de disciplines : pour "DISC_MIX" et "DAI_DISC", on compare la
# discipline du run à celle de la course qu'on joue.
_DISC_FAMILY = {
    "a": "GALOP", "h": "GALOP", "s": "GALOP", "c": "GALOP",
    "p": "TROT", "m": "TROT",
}

_FAIL_KINDS = {"D": "DAI", "Q": "Q", "A": "STOP", "T": "FALL"}


# --------------------------------------------------------------------------
# 1. TOKENIZER — calé sur le format réel, pas sur une supposition
# --------------------------------------------------------------------------
_TOK = re.compile(r"\(\d+[A-Za-z]?\)|\d+[A-Za-z]?|[A-Za-z]+")


def parse_musique(musique):
    """Chaîne brute -> liste de tokens, DU PLUS ANCIEN AU PLUS RÉCENT.

    Token = dict(rank=<int|None>, kind=<PLACE|DAI|STOP|FALL|Q|SEASON|UNK>,
                 disc=<lettre discipline|">", n=<numéro du token>)

    Ex: "4a5a7a6aDa(25)4a7aDaDm" -> 10 tokens, marqueur (25) en position 6,
        donc 4 tokens dans la saison courante.
    """
    if not musique:
        return []
    out = []
    for m in _TOK.finditer(str(musique)):
        t = m.group(0)
        if t.startswith("("):
            digits = re.sub(r"\D", "", t)
            out.append({"rank": None, "kind": "SEASON",
                        "disc": t[-1].lower() if t[-1].isalpha() else "",
                        "season": int(digits) if digits else None})
            continue
        if t[0].isdigit():
            i = 0
            while i < len(t) and t[i].isdigit():
                i += 1
            out.append({"rank": int(t[:i]), "kind": "PLACE",
                        "disc": t[i:].lower(), "season": None})
            continue
        kind = _FAIL_KINDS.get(t[0].upper(), "UNK")
        out.append({"rank": None, "kind": kind,
                    "disc": t[1:].lower(), "season": None})
    return out


def season_split(toks):
    """(saison_courante, anciennete) autour du DERNIER marqueur de saison.

    saison_courante = tokens après le marqueur (vide si pas de marqueur).
    anciennete       = le reste.
    """
    idx = -1
    for i, t in enumerate(toks):
        if t["kind"] == "SEASON":
            idx = i
    return toks[idx + 1:], toks[:idx]


def _last(toks, n):
    return toks[-n:] if len(toks) >= n else toks


def _bucket(n, edges):
    for i, hi in enumerate(edges):
        if n <= hi:
            return i
    return len(edges) - 1


def _bcount(n, labels):
    return labels[_bucket(n, tuple(range(len(labels))))]


# --------------------------------------------------------------------------
# 2. FEATURES — catégorielles. Aucun nombre signé, aucune distance.
# --------------------------------------------------------------------------
def cote_band(cote):
    if cote is None:
        return None
    try:
        v = float(cote)
    except (TypeError, ValueError):
        return None
    if v <= 0:
        return None
    for lo, hi, name in COTE_BANDS:
        if lo <= v < hi:
            return name
    return None


FEATURE_KEYS = (
    "DAI_COUNT", "DAI_PATTERN3", "DAI_NEXT1", "DAI_DISC",
    "FAIL_COUNT", "ZERO_COUNT", "TOP1_5", "TOP3_5",
    "TREND", "VOL", "SEASON_RUNS", "DISC_MATCH", "LAST_DISC",
    "COTE_BAND",
)


def form_features(musique, cote=None, target_disc=None, musique_is_loo=True):
    """Cheval -> {feature: valeur}. SEULE porte d'entrée du DNA.

    target_disc : 'a'/'p'/'m'... pour DISC_MATCH et DAI_DISC. Si None,
                   ces deux features sont absentes (elles ne se minent pas
                   hors contexte).
    """
    toks = parse_musique(musique)
    if not toks:
        return {}
    cur, old = season_split(toks)
    l5 = _last(toks, 5)
    f = {}

    dai = [i for i, t in enumerate(toks) if t["kind"] == "DAI"]
    f["DAI_COUNT"] = ("0", "1", "2", "3+")[_bucket(len(dai), (0, 1, 2))]

    # motif des 3 derniers runs : 1 = DAI, 0 = arrivé. Teste directement
    # "DAI puis 1a", "DAI puis 2a", "puis 1a puis DAI"...
    f["DAI_PATTERN3"] = "".join("1" if t["kind"] == "DAI" else "0" for t in _last(toks, 3))

    # rang IMMÉDIATEMENT après le dernier DAI : la question "DAI puis 1a"
    if not dai:
        f["DAI_NEXT1"] = "no_dai"
    else:
        nxt = toks[dai[-1] + 1:]
        if not nxt:
            f["DAI_NEXT1"] = "dai_is_last"
        elif nxt[0]["kind"] != "PLACE":
            f["DAI_NEXT1"] = "dai_then_" + nxt[0]["kind"].lower()
        else:
            f["DAI_NEXT1"] = "then_" + ("1" if nxt[0]["rank"] == 1 else
                                        "2" if nxt[0]["rank"] == 2 else
                                        "3" if nxt[0]["rank"] == 3 else "4+")

    if dai and target_disc:
        f["DAI_DISC"] = _disc_vs(toks[dai[-1]]["disc"], target_disc)

    fails = [t for t in l5 if t["kind"] in ("DAI", "Q", "STOP", "FALL")]
    f["FAIL_COUNT"] = ("0", "1", "2", "3+")[_bucket(len(fails), (0, 1, 2))]
    f["ZERO_COUNT"] = ("0", "1", "2", "3+")[
        _bucket(sum(1 for t in l5 if t["kind"] == "PLACE" and t["rank"] == 0), (0, 1, 2))]

    places = [t["rank"] for t in l5 if t["kind"] == "PLACE" and t["rank"]]
    f["TOP1_5"] = ("0", "1", "2+")[_bucket(sum(1 for r in places if r == 1), (0, 1))]
    f["TOP3_5"] = ("0", "1", "2", "3+")[_bucket(sum(1 for r in places if r <= 3), (0, 1, 2))]

    if len(places) >= 4:
        a = sum(places[-2:]) / 2.0
        b = sum(places[-4:-2]) / 2.0
        f["TREND"] = "up" if a < b - 0.5 else ("down" if a > b + 0.5 else "flat")
    else:
        f["TREND"] = "short"
    if len(places) >= 3:
        sp = max(places) - min(places)
        f["VOL"] = "low" if sp <= 3 else ("mid" if sp <= 7 else "high")
    else:
        f["VOL"] = "short"

    f["SEASON_RUNS"] = ("0", "1", "2", "3+")[_bucket(len(cur), (0, 1, 2))]

    if target_disc:
        fam = _DISC_FAMILY.get(target_disc)
        n_match = sum(1 for t in l5 if fam and _DISC_FAMILY.get(t["disc"]) == fam)
        f["DISC_MATCH"] = ("5", "3-4", "1-2", "0")[
            0 if n_match == 5 else 1 if n_match >= 3 else 2 if n_match >= 1 else 3]
        f["LAST_DISC"] = _disc_vs(toks[-1]["disc"], target_disc)
    f["COTE_BAND"] = cote_band(cote)
    return {k: v for k, v in f.items() if v is not None}


def _disc_vs(disc, target):
    """discipline d'un run vs discipline de la course jouée."""
    if not disc:
        return "unknown"
    a, b = _DISC_FAMILY.get(disc), _DISC_FAMILY.get(target)
    if b is None:
        return disc or "unknown"
    return "same_disc" if a == b else "other_disc"


# --------------------------------------------------------------------------
# 3. LE MINEUR
# --------------------------------------------------------------------------
class DnaRule:
    __slots__ = ("key", "value", "weight", "a", "b", "races", "lift",
                 "n_top5", "n_field")

    def __init__(self, key, value, weight, a, b, races, lift, n_top5, n_field):
        self.key, self.value, self.weight = key, value, weight
        self.a, self.b, self.races, self.lift = a, b, races, lift
        self.n_top5, self.n_field = n_top5, n_field

    def as_dict(self):
        return {k: getattr(self, k) for k in self.__slots__}

    def __repr__(self):
        return (f"<{self.key}={self.value} w={self.weight:+.3f} "
                f"lift={self.lift:.2f} top5={self.a}/{self.n_top5}>")


def mine_rules(rows, min_top5=MIN_TOP5, min_field=MIN_FIELD,
               min_races=MIN_RACES, min_weight=MIN_WEIGHT, k=SHRINK_K):
    """rows = (race_key, target_disc, cote, musique, is_top5).

    Le CHAMP COMPLET est obligatoire (is_top5=False compris).
    Renvoie les règles qui survivent. Une liste vide est un résultat
    valable, pas un bug : elle veut dire que l'archive ne dit rien.
    """
    races = defaultdict(lambda: [0, 0])      # race_key -> [n_top5, n]
    hits = defaultdict(lambda: {"a": 0, "b": 0, "races": set()})
    for race_key, target_disc, cote, musique, is_top5 in rows:
        r = races[race_key]
        r[1] += 1
        if is_top5:
            r[0] += 1
        feats = form_features(musique, cote=cote, target_disc=target_disc)
        for key, val in feats.items():
            h = hits[(key, val)]
            if is_top5:
                h["a"] += 1
                h["races"].add(race_key)
            else:
                h["b"] += 1

    n_top5 = sum(v[0] for v in races.values())
    n_field = sum(v[1] for v in races.values())
    if n_top5 < min_top5 or n_field < 2 * n_top5:
        return []

    base = min(max(n_top5 / n_field, 1e-4), 1 - 1e-4)
    rules = []
    for (key, val), h in hits.items():
        a, b = h["a"], h["b"]
        if a < min_top5 or b < min_field or len(h["races"]) < min_races:
            continue
        p = min(max((a + 0.5) / (a + b + 1.0), 1e-4), 1 - 1e-4)
        lift = math.log(p / base)
        se = math.sqrt(1.0 / (a + 0.5) + 1.0 / (b + 0.5))
        lo, hi = lift - Z_SIG * se, lift + Z_SIG * se
        if lo <= 0.0 <= hi:
            continue                       # IC à ~99.7% contient 0 -> rien
        w = lift * (a / (a + k))
        if abs(w) < min_weight:
            continue
        rules.append(DnaRule(key, val, w, a, b, len(h["races"]),
                             math.exp(lift), n_top5, n_field))
    rules.sort(key=lambda r: -abs(r.weight))
    return rules


def audit_rules(rows, min_top5=MIN_TOP5, min_field=MIN_FIELD,
                min_races=MIN_RACES, min_weight=MIN_WEIGHT, k=SHRINK_K):
    """Comme mine_rules, mais renvoie AUSSI ce qui a été rejeté et pourquoi.

    Indispensable pour un rapport honnête : une règle morte est un résultat,
    pas un oubli. Sans l'audit, on ne sait pas si DAI est "neutre" ou
    "jamais mesuré" — deux conclusions opposées.
    """
    races = defaultdict(lambda: [0, 0])
    hits = defaultdict(lambda: {"a": 0, "b": 0, "races": set()})
    for race_key, target_disc, cote, musique, is_top5 in rows:
        r = races[race_key]
        r[1] += 1
        if is_top5:
            r[0] += 1
        for key, val in form_features(musique, cote=cote,
                                      target_disc=target_disc).items():
            h = hits[(key, val)]
            if is_top5:
                h["a"] += 1
                h["races"].add(race_key)
            else:
                h["b"] += 1

    n_top5 = sum(v[0] for v in races.values())
    n_field = sum(v[1] for v in races.values())
    base = min(max(n_top5 / n_field, 1e-4), 1 - 1e-4) if n_field else 0.5
    alive, dead = [], []
    for (key, val), h in sorted(hits.items()):
        a, b = h["a"], h["b"]
        p = min(max((a + 0.5) / (a + b + 1.0), 1e-4), 1 - 1e-4)
        lift = math.log(p / base)
        se = math.sqrt(1.0 / (a + 0.5) + 1.0 / (b + 0.5))
        lo, hi = lift - Z_SIG * se, lift + Z_SIG * se
        w = lift * (a / (a + k))
        why = None
        if a < min_top5:
            why = f"support top5 {a}<{min_top5}"
        elif b < min_field:
            why = f"support champ {b}<{min_field}"
        elif len(h["races"]) < min_races:
            why = f"courses {len(h['races'])}<{min_races}"
        elif lo <= 0.0 <= hi:
            why = f"IC contient 0 [{lo:+.2f},{hi:+.2f}]"
        elif abs(w) < min_weight:
            why = f"|w|={abs(w):.3f}<{min_weight} (effet trop faible)"
        rec = (key, val, a, b, len(h["races"]), lift, w, p, why)
        (alive if why is None else dead).append(rec)
    alive.sort(key=lambda t: -abs(t[6]))
    dead.sort(key=lambda t: -abs(t[6]))
    return alive, dead, n_top5, n_field


# --------------------------------------------------------------------------
# 3c. TEST D'ADMISSION — la seule porte d'entrée des règles dans le moteur
# --------------------------------------------------------------------------
# Mesuré sur archive.db : ce que le DNA perd, ce n'est pas le SELECTEUR,
# c'est la STABILITE. Sur les mêmes features :
#     AUC in-sample 0.7332  ->  AUC hors-temps 0.5522
#     COTE seul hors-temps 0.5578 (signal)
#     FORME seule hors-temps 0.4422 (INVERSE, pire que le hasard)
# Autrement dit : les règles de forme qui semblaient vivantes (TOP3_5=0,
# ZERO_COUNT=2, DAI_DISC same_disc, DAI_NEXT1=then_1...) sont du bruit qui a
# changé de signe au 1er janvier 2025. Le max-over-positions et le
# DNA-first n'ont jamais été le problème : le problème est qu'on n'a jamais
# vérifié qu'une règle survit au temps.
#
# Règle d'admission, sans interprétation possible :
#     une signature est ADMISE si son signe est le même sur les deux moitiés
#     de la fenêtre, et si son poids dépasse le seuil sur les DEUX moitiés.
# Ce qui n'est pas admis n'entre pas dans le moteur.
# Aujourd'hui : seules les bandes de cote passent. Demain, peut-être DAI.

def admit_pair(rows_a, rows_b, min_abs=MIN_WEIGHT):
    """rows_a / rows_b = deux moitiés de la fenêtre (avant / après `cut`).
    Une signature n'entre dans le moteur que si son signe est stable ET que
    son poids passe le seuil sur les deux moitiés. Le poids retenu est celui
    de la MOITIÉ LA PLUS CONSERVATRICE (le plus petit |w| des deux), pas la
    moyenne : on ne veut pas qu'un effet réel dans une période soit
    amplifié par un effet inventé dans l'autre.
    Renvoie (admises, refusees) avec le motif du refus."""
    # ATTENTION : indexer par (key, VALUE), pas par key seul. Indexé par key,
    # les 7 bandes de cote s'écrasent en une seule entrée et le test
    # d'admission valide n'importe quoi. (Bug réel, attrapé en A/B.)
    ra = {(r.key, r.value): r for r in mine_rules(rows_a)}
    rb = {(r.key, r.value): r for r in mine_rules(rows_b)}
    ok, ko = [], []
    for k in sorted(set(ra) & set(rb)):
        a, b = ra[k], rb[k]
        same_sign = (a.weight > 0) == (b.weight > 0)
        strong = min(abs(a.weight), abs(b.weight)) >= min_abs
        if same_sign and strong:
            keep = a if abs(a.weight) <= abs(b.weight) else b
            ok.append(DnaRule(keep.key, keep.value, keep.weight,
                              keep.a, keep.b, keep.races, keep.lift,
                              keep.n_top5, keep.n_field))
        else:
            ko.append((a.key, a.value, round(a.weight, 3), round(b.weight, 3),
                       "signe instable" if not same_sign else
                       f"faible sur 1 moitie (|w|="
                       f"{min(abs(a.weight), abs(b.weight)):.3f})"))
    ok.sort(key=lambda r: -abs(r.weight))
    return ok, ko


# --------------------------------------------------------------------------
# 3d. ADMISSION PAR AUC HORS-TEMPS — la version qui tient
# --------------------------------------------------------------------------
# Le test "signe identique sur les deux moitiés" (admit_pair) est TROP
# FAIBLE : il valide des règles de forme qui, sur données vues, sont
# parfaitement stables, et qui sur 2025 sortent à AUC 0.44 — pire que le
# hasard. Stabilité n'est pas généralisation.
#
# La bonne question n'est pas "est-ce que le signe bouge ?" mais :
#     "est-ce que cette FAMILLE de features, entraînée sur la moitié
#      ancienne, classe mieux que le hasard sur la moitié récente ?"
#
# Granularité = la FAMILLE (COTE_BAND, DAI_*, ZERO_*, TOP*_5, DISC_*,
# TREND, VOL, SEASON_RUNS, ...) et non la valeur. Une bande de cote
# isolée est neutre par construction ; c'est l'ensemble des bandes qui
# porte le signal. Inversement, "0 top-3 en 5 courses" ne se juge pas
# seul.
#
# Mesuré aujourd'hui, fenêtre 2015-2025, test 2025 :
#     COTE_BAND  -> AUC 0.5578  ADMIS
#     tout le FORM -> AUC 0.4422  REFUSÉ
# On n'invente pas la porte : c'est la mesure qui la pose.

FEATURE_GROUPS = {
    "COTE_BAND": ("COTE_BAND",),
    "DAI": ("DAI_COUNT", "DAI_PATTERN3", "DAI_NEXT1", "DAI_DISC"),
    "ZERO_FAIL": ("ZERO_COUNT", "FAIL_COUNT"),
    "TOP": ("TOP1_5", "TOP3_5"),
    "DISC": ("DISC_MATCH", "LAST_DISC"),
    "TREND_VOL": ("TREND", "VOL"),
    "SEASON": ("SEASON_RUNS",),
}
_GROUP_OF = {k: g for g, keys in FEATURE_GROUPS.items() for k in keys}


def _group(name):
    return _GROUP_OF.get(name.split("=")[0], "OTHER")


def fit_dna(rows_a, rows_b, min_auc=0.52, iters=160, l2=1.0, verbose=False):
    """rows_a =训练的 moitié ancienne, rows_b = moitié récente (les DEUX
    strictement avant `before` — AUC mesuré sur données jamais vues).

    Renvoie (regles, rapport). `regles` = DnaRule pondérés par les
    coefficients LOGISTIQUES d'un modèle ajusté sur rows_a ∪ rows_b, limité
    aux groupes admis. Les groupes refusés n'ont aucun poids, donc aucune
    façon d'influencer le classement, même indirectement.
    """
    Xa, ya, idx = build_matrix(rows_a)
    Xb, yb, _ = build_matrix(rows_b)
    if not idx or len(Xb) < 300:
        return [], {"error": "insufficient", "n_a": len(Xa), "n_b": len(Xb)}

    # --- 1. AUC hors-temps par GROUPE -----------------------------------
    groups = sorted({_group(n) for n in idx})
    report = {}
    admitted = []
    for g in groups:
        cols = {n: c for n, c in idx.items() if _group(n) == g}
        # cols est {nom -> colonne} : il faut remapper la COLONNE, pas le nom.
        col2new = {cols[n]: i for i, n in enumerate(sorted(cols))}

        def proj(rows, _m=col2new):
            return [{_m[c]: v for c, v in d.items() if c in _m} for d in rows]
        pa, pb = proj(Xa), proj(Xb)
        if not any(pa) or not any(pb):
            report[g] = {"auc": 0.5, "n_cols": len(cols), "admitted": False,
                         "why": "aucune donnee"}
            continue
        w, b = fit_logistic(pa, ya, l2=l2, iters=iters)
        a = auc(pb, yb, w, b)
        ok = a >= min_auc
        report[g] = {"auc": round(a, 4), "n_cols": len(cols),
                     "admitted": ok,
                     "why": "" if ok else f"AUC {a:.4f} < {min_auc}"}
        if ok:
            admitted.append(g)
        if verbose:
            print(f"    groupe {g:<10} AUC={a:.4f}  {'ADMIS' if ok else 'REFUSE'}")

    if not admitted:
        return [], {"groups": report, "admitted": [], "error": "no_group_survives"}

    # --- 2. Poids finaux : ajustement sur TOUTE la fenêtre, groupes admis
    # seulement. Coefficients = log-odds, donc calibrés et comparables.
    keep = {c: n for n, c in idx.items() if _group(n) in admitted}
    col2new = {c: i for i, c in enumerate(sorted(keep))}
    allrows = rows_a + rows_b
    X, y, _ = build_matrix(allrows)
    w, b = fit_logistic([{col2new[c]: v for c, v in d.items() if c in col2new}
                         for d in X], y, l2=l2, iters=iters)
    rules = [DnaRule(n.split("=")[0], n.split("=", 1)[1], w[col2new[c]],
                     0, 0, 0, 1.0, sum(y), len(y))
             for c, n in keep.items() if abs(w[col2new[c]]) >= MIN_WEIGHT]
    rules.sort(key=lambda r: -abs(r.weight))
    report["_meta"] = {"admitted": admitted, "n_rules": len(rules),
                       "n_rows": len(y), "base_rate": round(sum(y) / max(len(y), 1), 4),
                       "n_cols": len(idx), "min_auc": min_auc}
    return rules, report


def general_rules(by_disc, min_disc=MIN_DISC_FOR_GENERAL, min_weight=MIN_WEIGHT):
    """ADN GÉNÉRAL = accord de signe dans >= min_disc disciplines.
    Poids = moyenne. Ce qui n'est pas général reste local."""
    buckets = defaultdict(list)
    for disc, rules in (by_disc or {}).items():
        for r in rules or []:
            buckets[(r.key, r.value)].append((disc, r))
    out = []
    for (key, val), lst in buckets.items():
        if len({d for d, _ in lst}) < min_disc:
            continue
        signs = {1 if r.weight > 0 else -1 for _, r in lst}
        if len(signs) != 1:
            continue
        w = sum(r.weight for _, r in lst) / len(lst)
        if abs(w) < min_weight:
            continue
        out.append(DnaRule(key, val, w, min(r.a for _, r in lst),
                           min(r.b for _, r in lst),
                           min(r.races for _, r in lst),
                           min(r.lift for _, r in lst),
                           min(r.n_top5 for _, r in lst),
                           min(r.n_field for _, r in lst)))
    out.sort(key=lambda r: -abs(r.weight))
    return out


def discipline_rules(general, disc_rules, min_weight=MIN_WEIGHT):
    """Résiduel local = w_disc - w_general : AUCUN double comptage.
    Une règle présente dans les deux ne pèse qu'une fois."""
    gmap = {(r.key, r.value): r.weight for r in (general or [])}
    out = []
    for r in disc_rules or []:
        gw = gmap.get((r.key, r.value))
        w = r.weight - gw if gw is not None else r.weight
        if abs(w) < min_weight:
            continue
        out.append(DnaRule(r.key, r.value, w, r.a, r.b, r.races, r.lift,
                           r.n_top5, r.n_field))
    out.sort(key=lambda r: -abs(r.weight))
    return out


# --------------------------------------------------------------------------
# 3b. POIDS PAR RÉGRESSION LOGISTIQUE — la Correction qui compte
# --------------------------------------------------------------------------
# Pourquoi : les features sont CORRÉLÉES. DAI_COUNT, DAI_PATTERN3,
# DAI_NEXT1, DAI_DISC, FAIL_COUNT et ZERO_COUNT mesurent tous la même chose
# (une forme dégradée). Additionner leurs log-lifts revient à punir le même
# défaut 5 fois : un cheval "mauvaise forme + DAI dans la bonne discipline"
# ramasse -0.23 -0.28 -0.34 -0.18 = -1.03, soit plus qu'une cote de 50+
# (-1.05)... alors que l'archive ne dit rien de tel. Naive Bayes sur des
# variables corrélées est exactement le mécanisme qui rend un moteur
# "saturé" : il amplifie la zone où les variables s'accordent, donc le bas.
#
# La régression logistique estime des coefficients qui, eux, tiennent compte
# de la corrélation. Elle rend aussi un score CALIBRÉ (log-odds), donc
# comparable d'un cheval à l'autre sans normalisation arbitraire.
#
# Aucune librarie externe :Gradient descent sparse + L2, 8 non-zeros/ligne.

def build_matrix(rows):
    """rows -> (X, y, index) ; X = liste de dicts {col: 1.0} (sparse)."""
    index = {}
    X, y = [], []
    for race_key, target_disc, cote, musique, is_top5 in rows:
        feats = form_features(musique, cote=cote, target_disc=target_disc)
        if not feats:
            X.append({})
            y.append(1 if is_top5 else 0)
            continue
        d = {}
        for k, v in feats.items():
            col = index.setdefault(f"{k}={v}", len(index))
            d[col] = 1.0
        X.append(d)
        y.append(1 if is_top5 else 0)
    return X, y, index


def fit_logistic(X, y, l2=1.0, iters=160, lr=0.5, seed=7):
    """Descente de gradient sur la log-perte + L2. Retourne (w, b, ordre)."""
    import random
    n, m = len(X), (max((max(d) for d in X if d), default=-1) + 1)
    w = [0.0] * m
    b = 0.0
    # ordre mélangé à chaque passe : évite les motifs deXGbatch
    order = list(range(n))
    rnd = random.Random(seed)
    for it in range(iters):
        rnd.shuffle(order)
        gw = [0.0] * m
        gb = 0.0
        for i in order:
            z = b
            d = X[i]
            for c, val in d.items():
                z += w[c] * val
            p = 1.0 / (1.0 + math.exp(-max(-30.0, min(30.0, z))))
            e = p - y[i]
            for c, val in d.items():
                gw[c] += e * val
            gb += e
        inv = 1.0 / n
        for c in range(m):
            w[c] -= lr * (gw[c] * inv + l2 * w[c] / n)
        b -= lr * gb * inv
    return w, b


def auc(X, y, w, b):
    """AUC par rang — la question 'le DNA a-t-il un signal ?' en un chiffre.
    0.5 = aucun signal. C'est LE test à passer avant tout le reste."""
    pts = []
    for d, t in zip(X, y):
        z = b + sum(w[c] * v for c, v in d.items())
        pts.append((z, t))
    pos = sorted(z for z, t in pts if t)
    neg = sorted(z for z, t in pts if not t)
    if not pos or not neg:
        return 0.5
    import bisect
    tot = 0.0
    for z in pos:
        lo = bisect.bisect_left(neg, z)      # combien de negatifs < z
        hi = bisect.bisect_right(neg, z)     # combien de negatifs <= z
        tot += lo + 0.5 * (hi - lo)          # les ex-aequo comptent 1/2
    return tot / (len(pos) * len(neg))


def rules_from_weights(w, index, min_abs=0.10, n_top5=0, n_field=0):
    """Colonnes one-hot -> DnaRule. Le poids est le coefficient LOGISTIQUE
    (log-odds), donc comparable et sign-correct, pas un log-lift empilé."""
    out = []
    for name, col in index.items():
        if abs(w[col]) < min_abs:
            continue
        key, _, val = name.partition("=")
        out.append(DnaRule(key, val, w[col], 0, 0, 0, 1.0, n_top5, n_field))
    out.sort(key=lambda r: -abs(r.weight))
    return out


# --------------------------------------------------------------------------
# 4. SCORING
# --------------------------------------------------------------------------
def dna_score(feats, rules, denom=None):
    """ADN d'un cheval. Somme de poids des règles qui FIRE. Pas de max,
    pas de distance, pas de pénalité : 0 = la règle ne parle pas.

    Normalisation par `denom` (masse de poids couverte, moyenne du champ).
    Sans elle un cheval avec 14 features connues marque plus haut qu'un
    cheval à 6 features connues : artefact de complétude, pas de mérite.
    Renvoie (score, règles_firees) pour l'explicabilité côté front.
    """
    total, known, fired = 0.0, 0.0, []
    for r in rules or []:
        v = feats.get(r.key)
        if v is None:
            continue
        known += abs(r.weight)
        if v == r.value:
            total += r.weight
            fired.append(r)
    if not denom:
        denom = known
    if denom <= 0:
        return 0.0, []
    return total / denom, fired


def explain(fired, limit=3):
    return [f"{r.key}={r.value} ({r.weight:+.2f}, {r.a}/{r.n_top5})"
            for r in fired[:limit]]
