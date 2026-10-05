import sqlite3
import json
import math
import re
import numpy as np
from datetime import datetime, timedelta
from database import get_db

import threading
_local = threading.local()

DISC_MAP = {
    "TROT": ["ATTELE", "MONTE", "TROT"],
    "ATTELE": ["ATTELE", "TROT"],
    "MONTE": ["MONTE", "TROT"],
    "GALOP": ["PLAT", "GALOP"],
    "PLAT": ["PLAT", "GALOP"],
    "HAIE": ["HAIE"],
    "STEEPLE": ["STEEPLE", "STEEPLECHASE"],
    "STEEPLECHASE": ["STEEPLECHASE", "STEEPLE"],
}
CAT_GF = "GF"
CAT_FC = "FC"
CAT_TOC = "TOC"
CAT_OUT = "OUT"
CAT_LABELS = [CAT_GF, CAT_FC, CAT_TOC, CAT_OUT]

# Les caractéristiques du DNA sont des RANGS relatifs dans le peloton
# (percentile intra-course), jamais des valeurs absolues.
FEATURE_KEYS = ["gain", "valeur", "age", "corde", "poids", "musique"]
POSITIONS = [1, 2, 3, 4, 5]


def _get_conn():
    if not hasattr(_local, 'conn') or _local.conn is None:
        _local.conn = get_db()
    return _local.conn


def _cleanup_conn():
    if hasattr(_local, 'conn') and _local.conn is not None:
        try:
            _local.conn.close()
        except:
            pass
        _local.conn = None


# ---- Helpers ----
def parse_musique(msq):
    if not msq:
        return []
    parts = []
    buf = ""
    for c in msq:
        if c in ('a', 'p', 'm'):
            if buf:
                parts.append(buf + c)
            buf = ""
        elif c == '(':
            if buf:
                parts.append(buf)
            buf = "("
        elif c == ')':
            buf += c
            parts.append(buf)
            buf = ""
        else:
            buf += c
    if buf:
        parts.append(buf)
    return parts


def _musique_avg_rang(msq):
    if not msq:
        return None
    rangs = []
    for m in parse_musique(msq):
        if m and m[0].isdigit() and not m.startswith("("):
            ns = ""
            for ch in m:
                if ch.isdigit():
                    ns += ch
                else:
                    break
            if ns:
                r = int(ns)
                if 1 <= r < 99:
                    rangs.append(r)
    if not rangs:
        return None
    return sum(rangs[:3]) / len(rangs[:3])


def _percentile(values, value):
    """Rang relatif (0..1) de `value` parmi `values`. Les égalités partagent le rang."""
    if not values:
        return 0.5
    less = sum(1 for v in values if v < value)
    eq = sum(1 for v in values if v == value)
    return (less + eq / 2.0) / len(values)


def _parse_prix(prix):
    if not prix:
        return None
    s = re.sub(r"\D", "", str(prix))
    return float(s) if s else None


def get_horse_history(horse_name, limit=20):
    conn = _get_conn()
    rows = conn.execute("""
        SELECT p.rang, p.musique, p.gain, p.poids, p.corde, p.valeur,
               p.cote_pmu, p.jockey, p.trainer, p.num,
               r.date, r.hippodrome, r.distance, r.discipline, r.prix,
               r.race_id, r.specialty, r.going, r.surface
        FROM participants p
        JOIN races r ON r.race_id = p.race_id
        WHERE p.horse = ? COLLATE NOCASE AND p.rang IS NOT NULL
        ORDER BY r.date DESC
        LIMIT ?
    """, (horse_name, limit))
    return [dict(r) for r in rows]


def compute_career_stats(history):
    if not history:
        return {}
    total = len(history)
    wins = sum(1 for h in history if h.get("rang") == 1)
    top3 = sum(1 for h in history if h.get("rang") and int(h["rang"]) <= 3)
    top5 = sum(1 for h in history if h.get("rang") and int(h["rang"]) <= 5)
    non_dq = [h for h in history if h.get("rang") and int(h["rang"]) < 99]
    avg_rang = sum(int(h["rang"]) for h in non_dq) / len(non_dq) if non_dq else 99
    return {
        "total": total,
        "wins": wins,
        "win_rate": wins / total if total else 0,
        "top3_rate": top3 / total if total else 0,
        "top5_rate": top5 / total if total else 0,
        "avg_rang": round(avg_rang, 1),
    }


def musique_form_score(msq):
    """Score de forme dérivé de la musique récente du cheval (pas de l'historique DB)."""
    rangs = []
    for m in parse_musique(msq):
        if not m:
            continue
        if m.startswith("(") and m[1].isdigit():
            ds = ""
            for ch in m[1:]:
                if ch.isdigit():
                    ds += ch
                else:
                    break
            if ds:
                rangs.append(int(ds))
        elif m[0].isdigit():
            ds = ""
            for ch in m:
                if ch.isdigit():
                    ds += ch
                else:
                    break
            if ds:
                v = int(ds)
                rangs.append(v if v != 0 else 12)
    if not rangs:
        return 10
    avg_r = sum(rangs[:3]) / len(rangs[:3])
    if avg_r <= 1:
        return 30
    if avg_r <= 1.5:
        return 27
    if avg_r <= 2:
        return 24
    if avg_r <= 3:
        return 20
    if avg_r <= 4:
        return 16
    if avg_r <= 5:
        return 13
    if avg_r <= 6.5:
        return 10
    if avg_r <= 8:
        return 7
    if avg_r <= 10:
        return 4
    return 2


def horse_history_probs(history, discipline="", distance=None, dist_band=250):
    """Probabilités de finir P1/P2/P3 calculées depuis l'historique réel du cheval
    dans les mêmes conditions (même famille de discipline, distance ± dist_band)."""
    disc_fam = set(DISC_MAP.get(discipline.upper(), [discipline.upper()])) if discipline else None

    def ranks(h):
        r = h.get("rang")
        if r is None:
            return None
        try:
            ri = int(r)
        except:
            return None
        if ri < 1 or ri >= 99:
            return None
        return ri

    similar = []
    for h in history:
        ri = ranks(h)
        if ri is None:
            continue
        if disc_fam is not None and (h.get("discipline") or "").upper() not in disc_fam:
            continue
        if distance:
            try:
                if abs(int(h.get("distance") or 0) - int(distance)) > dist_band:
                    continue
            except:
                pass
        similar.append(h)

    pool = similar if len(similar) >= 3 else [h for h in history if ranks(h) is not None]
    if not pool:
        return {"p1": 0.0, "p2": 0.0, "p3": 0.0, "top3": 0.0, "n": 0}
    n = len(pool)
    c1 = sum(1 for h in pool if ranks(h) == 1)
    c2 = sum(1 for h in pool if ranks(h) == 2)
    c3 = sum(1 for h in pool if ranks(h) == 3)
    return {
        "p1": c1 / n,
        "p2": c2 / n,
        "p3": c3 / n,
        "top3": (c1 + c2 + c3) / n,
        "n": n,
    }


# ---- Market Classification (couche indépendante, PAS intégrée au DNA) ----
# Utilisée uniquement pour AFFICHER le marché du jour quand les cotes réelles existent.
def classify_market_from_cotes(cote_list):
    items = [(num, float(c)) for num, c in cote_list if c is not None and float(c) > 0]
    items.sort(key=lambda x: x[1])
    n = len(items)
    if n == 0:
        return {}

    gaps = []
    for i in range(n - 1):
        r = items[i+1][1] / items[i][1]
        gaps.append((r, i))
    gaps.sort(key=lambda x: -x[0])

    if n <= 4:
        splits = [n // 2]
    elif n <= 8:
        splits = [max(1, int(n * 0.2)), int(n * 0.55)]
    else:
        splits = [max(1, int(n * 0.15)), int(n * 0.40), int(n * 0.70)]

    refined = []
    for sp in splits:
        best_gap, best_pos = -1, sp
        for cand in range(max(1, sp - 1), min(n - 1, sp + 2)):
            ratio = items[cand + 1][1] / items[cand][1]
            if ratio > best_gap:
                best_gap, best_pos = ratio, cand
        refined.append(best_pos)

    # Tailles minimales des groupes pour que le gabarit tienne toujours :
    # GF >= 2, FC >= 4, TOC >= 2 (positions cumulées).
    enforced = []
    prev_end = -1
    for i, sp in enumerate(refined):
        need = prev_end + [2, 4, 2][i]
        if sp < need:
            sp = need
        if sp >= n - 1:
            sp = n - 2
        enforced.append(sp)
        prev_end = sp
    refined = []
    for s in enforced:
        if refined and s <= refined[-1]:
            s = refined[-1] + 1
        if s < n - 1:
            refined.append(s)
    refined = sorted(set(refined))
    refined = [s for s in refined if 0 < s < n - 1]

    groups = []
    start = 0
    for sp in refined:
        groups.append(items[start:sp + 1])
        start = sp + 1
    groups.append(items[start:])

    result = {}
    for i, group in enumerate(groups):
        label = CAT_LABELS[min(i, 3)]
        for num, _ in group:
            result[num] = label
    return result


# ---- Race Fingerprint ----
# Transforme un peloton complet en rangs relatifs (percentiles) intra-course.
def race_fingerprint(participants):
    feats = {k: [] for k in FEATURE_KEYS}
    for p in participants:
        feats["gain"].append(p.get("gain"))
        feats["valeur"].append(p.get("valeur"))
        feats["age"].append(p.get("age"))
        feats["corde"].append(p.get("corde"))
        feats["poids"].append(p.get("poids"))
        feats["musique"].append(_musique_avg_rang(p.get("musique")))

    result = {}
    for p in participants:
        pct = {}
        for k in FEATURE_KEYS:
            if k == "musique":
                v = _musique_avg_rang(p.get("musique"))
            else:
                v = p.get(k)
            if v is None:
                pct[k] = None
                continue
            valid = [x for x in feats[k] if x is not None]
            pct[k] = _percentile(valid, v)
        result[p.get("num")] = pct
    return result


# ---- Race Loader (courses COMPLÈTES, pas seulement les gagnants) ----
def load_dna_races(hippodrome, distance, discipline, limit=60, min_finishers=3):
    conn = _get_conn()
    try:
        dist_int = int(distance)
    except:
        dist_int = 0

    disc_values = [discipline.upper()] if discipline else []
    if discipline:
        for m in DISC_MAP.get(discipline.upper(), []):
            if m not in disc_values:
                disc_values.append(m)

    if disc_values:
        placeholders = ",".join("?" for _ in disc_values)
        races = conn.execute("""
            SELECT r.race_id, r.hippodrome, r.distance, r.discipline,
                   r.prix, r.classe, r.condition, r.runners,
                   r.surface, r.going, r.penetrometer, r.corde, r.date
            FROM races r
            WHERE (r.discipline IN ({}) OR r.specialty IN ({}))
              AND r.hippodrome = ? AND r.distance = ?
            ORDER BY r.date DESC
            LIMIT ?
        """.format(placeholders, placeholders),
            disc_values * 2 + [hippodrome.upper(), dist_int, limit]).fetchall()
    else:
        races = conn.execute("""
            SELECT r.race_id, r.hippodrome, r.distance, r.discipline,
                   r.prix, r.classe, r.condition, r.runners,
                   r.surface, r.going, r.penetrometer, r.corde, r.date
            FROM races r
            WHERE r.hippodrome = ? AND r.distance = ?
            ORDER BY r.date DESC
            LIMIT ?
        """, [hippodrome.upper(), dist_int, limit]).fetchall()

    result = []
    for race in races:
        parts = conn.execute("""
            SELECT num, horse, age, sexe, gain, poids, corde, valeur, musique, rang
            FROM participants WHERE race_id=? ORDER BY num
        """, (race["race_id"],)).fetchall()
        parts = [dict(p) for p in parts]
        finishers = [p for p in parts if p.get("rang") and 1 <= int(p["rang"]) <= max(POSITIONS)]
        if len(finishers) < min_finishers:
            continue
        row = dict(race)
        row["participants"] = parts
        result.append(row)
        if len(result) >= limit:
            break
    return result


# ---- DNA Builder ----
# الـDNA مبني فقط على بيانات حقيقية (نتائج كاملة)، بدون أي نموذج تنبؤي.
# بدل "بروفايل متوسط" لكل مركز (الذي يتقارب مع 0.5)، نستخدم الاحتمالات الشرطية:
#   لكل خاصية وكل ربع داخل السباق، ما نسبة وصول الحصان للمراكز P1/P2/P3؟
def _quartile(v):
    if v is None:
        return None
    if v < 0.25:
        return 1
    if v < 0.5:
        return 2
    if v < 0.75:
        return 3
    return 4


def build_race_dna(hippodrome, distance, discipline, max_samples=60):
    races = load_dna_races(hippodrome, distance, discipline, limit=max_samples)
    if len(races) < 3:
        return None

    q_counts = {
        f: {q: {"P1": 0, "P2": 0, "P3": 0, "N": 0} for q in range(1, 5)}
        for f in FEATURE_KEYS
    }
    pos_counts = {1: 0, 2: 0, 3: 0}
    total_horses = 0
    n_races = len(races)

    for race in races:
        fp = race_fingerprint(race["participants"])
        for p in race["participants"]:
            total_horses += 1
            r = p.get("rang")
            if r is not None and 1 <= int(r) <= 3:
                pos_counts[int(r)] += 1
            pct = fp.get(p.get("num")) or {}
            for f in FEATURE_KEYS:
                v = pct.get(f)
                q = _quartile(v)
                if q is None:
                    continue
                q_counts[f][q]["N"] += 1
                if r is not None and 1 <= int(r) <= 3:
                    q_counts[f][q]["P%d" % int(r)] += 1

    base = {
        "P1": round(pos_counts[1] / total_horses, 3) if total_horses else None,
        "P2": round(pos_counts[2] / total_horses, 3) if total_horses else None,
        "P3": round(pos_counts[3] / total_horses, 3) if total_horses else None,
        "n": total_horses,
    }
    base["top3"] = round((base["P1"] or 0) + (base["P2"] or 0) + (base["P3"] or 0), 3)

    features = {}
    for f in FEATURE_KEYS:
        qu = {}
        for q in range(1, 5):
            c = q_counts[f][q]
            n = c["N"]
            qu["Q%d" % q] = {
                "P1": round(c["P1"] / n, 3) if n else None,
                "P2": round(c["P2"] / n, 3) if n else None,
                "P3": round(c["P3"] / n, 3) if n else None,
                "top3": round((c["P1"] + c["P2"] + c["P3"]) / n, 3) if n else None,
                "n": n,
            }
        rates = [qu["Q%d" % q]["top3"] for q in range(1, 5) if qu["Q%d" % q]["top3"] is not None]
        weight = float(np.std(rates)) if len(rates) >= 2 else 0.0
        features[f] = {"weight": round(weight, 4), "quartiles": qu}

    wsum = sum(f["weight"] for f in features.values()) or 1.0
    for f in features:
        features[f]["weight"] = round(features[f]["weight"] / wsum, 3)

    # أوزان المراكز (مستخرجة من البيانات): مدى تأثير الخصائص على كل مركز
    pos_weights = {}
    for pos in (1, 2, 3):
        spread = 0.0
        for f in FEATURE_KEYS:
            w = features[f]["weight"]
            rates_p = [qu["Q%d" % q]["P%d" % pos] for q in range(1, 5) if qu["Q%d" % q]["P%d" % pos] is not None]
            if rates_p:
                spread += w * float(np.std(rates_p))
        pos_weights["P%d" % pos] = spread
    pwsum = sum(pos_weights.values()) or 1.0
    pos_weights = {k: round(v / pwsum, 3) for k, v in pos_weights.items()}

    classes = [r.get("classe") for r in races if r.get("classe")]
    goings = [r.get("going") for r in races if r.get("going")]
    surfaces = [r.get("surface") for r in races if r.get("surface")]
    prizes = [p for p in (_parse_prix(r.get("prix")) for r in races) if p]

    def mode(vals):
        if not vals:
            return None
        from collections import Counter
        return Counter(vals).most_common(1)[0][0]

    context = {
        "n_races": n_races,
        "date_min": min(r.get("date") for r in races),
        "date_max": max(r.get("date") for r in races),
        "runners_avg": round(float(np.mean([r.get("runners") or 0 for r in races])), 1),
        "classe": mode(classes),
        "going": mode(goings),
        "surface": mode(surfaces),
        "prix_avg": round(float(np.mean(prizes)), 0) if prizes else None,
    }

    return {
        "hippodrome": hippodrome,
        "distance": distance,
        "discipline": discipline,
        "n_samples": n_races,
        "context": context,
        "base": base,
        "features": features,
        "pos_weights": pos_weights,
    }


# ---- Horse Selector (مطابقة رتب الحصان النسبية مع الاحتمالات الشرطية للـDNA) ----
def score_dna_match(pct, dna):
    if not dna:
        return {"match": None, "p1": None, "p2": None, "p3": None, "base_top3": None}
    features = dna.get("features", {})
    base = dna.get("base", {})
    base_top3 = base.get("top3") or 0.0
    base_p1 = base.get("P1") or 0.0
    base_p2 = base.get("P2") or 0.0
    base_p3 = base.get("P3") or 0.0

    lift_top3 = 0.0
    lift_p1 = 0.0
    lift_p2 = 0.0
    lift_p3 = 0.0
    wsum = 0.0
    for f, meta in features.items():
        w = meta.get("weight") or 0.0
        if w <= 0 or not pct:
            continue
        q = _quartile(pct.get(f))
        if q is None:
            continue
        qd = meta.get("quartiles", {}).get("Q%d" % q)
        if not qd or qd.get("top3") is None:
            continue
        lift_top3 += w * (qd["top3"] - base_top3)
        lift_p1 += w * ((qd.get("P1") or base_p1) - base_p1)
        lift_p2 += w * ((qd.get("P2") or base_p2) - base_p2)
        lift_p3 += w * ((qd.get("P3") or base_p3) - base_p3)
        wsum += w

    if wsum == 0:
        return {"match": base_top3, "p1": base_p1, "p2": base_p2, "p3": base_p3, "base_top3": base_top3}

    match = base_top3 + lift_top3 / wsum
    return {
        "match": match,
        "p1": base_p1 + lift_p1 / wsum,
        "p2": base_p2 + lift_p2 / wsum,
        "p3": base_p3 + lift_p3 / wsum,
        "base_top3": base_top3,
    }


# ---- Market DNA (طبقة السوق: أسعار حقيقية فقط، لا نموذج) ----
# تُبنى من سباقات الأرشيف التي لها أسعار حقيقية. تنمو مع أرشفة السباقات الحية.
def build_market_dna():
    conn = _get_conn()
    rows = conn.execute("""
        SELECT race_id, num, cote_pmu, rang FROM participants
        WHERE cote_pmu IS NOT NULL ORDER BY race_id
    """).fetchall()
    by_race = {}
    for r in rows:
        by_race.setdefault(r["race_id"], []).append(r)
    if len(by_race) < 3:
        return None

    cnt = {c: {"P1": 0, "P2": 0, "P3": 0, "N": 0} for c in CAT_LABELS}
    pos_tot = {1: 0, 2: 0, 3: 0}
    total = 0
    for rid, parts in by_race.items():
        market = classify_market_from_cotes([(p["num"], p["cote_pmu"]) for p in parts])
        for p in parts:
            cat = market.get(p["num"])
            if not cat:
                continue
            total += 1
            r = p["rang"]
            cnt[cat]["N"] += 1
            if r and 1 <= int(r) <= 3:
                cnt[cat]["P%d" % int(r)] += 1
                pos_tot[int(r)] += 1

    categories = {}
    for c in CAT_LABELS:
        d = cnt[c]
        n = d["N"]
        categories[c] = {
            "P1": round(d["P1"] / n, 3) if n else None,
            "P2": round(d["P2"] / n, 3) if n else None,
            "P3": round(d["P3"] / n, 3) if n else None,
            "top3": round((d["P1"] + d["P2"] + d["P3"]) / n, 3) if n else None,
            "n": n,
        }

    base = {
        "P1": round(pos_tot[1] / total, 3) if total else None,
        "P2": round(pos_tot[2] / total, 3) if total else None,
        "P3": round(pos_tot[3] / total, 3) if total else None,
        "top3": round((pos_tot[1] + pos_tot[2] + pos_tot[3]) / total, 3) if total else None,
        "n": total,
        "n_races": len(by_race),
    }
    return {"categories": categories, "base": base}


def market_estimate(cat, mkt_dna):
    if not mkt_dna or not cat:
        return None
    base = mkt_dna.get("base", {})
    d = mkt_dna.get("categories", {}).get(cat)
    if not d or d.get("top3") is None:
        return {
            "p1": base.get("P1") or 0.0,
            "p2": base.get("P2") or 0.0,
            "p3": base.get("P3") or 0.0,
            "top3": base.get("top3") or 0.0,
        }
    return {"p1": d["P1"], "p2": d["P2"], "p3": d["P3"], "top3": d["top3"]}


# ---- Main Analysis ----
def analyze_race(race_data):
    try:
        race_id = race_data.get("course", {}).get("id") or race_data.get("race_id")
        participants = race_data.get("participants", [])
        course = race_data.get("course", {})
        reunion = race_data.get("reunion", {})
        discipline = course.get("discipline", "")
        hippodrome = reunion.get("hippodrome", race_data.get("hippodrome", ""))
        distance = course.get("distance", "")

        # Step 1: marché du jour (cotes réelles)
        current_cotes = [(p.get("num"), p.get("cote_pmu")) for p in participants]
        current_market = classify_market_from_cotes(current_cotes)
        coted = [c for _, c in current_cotes if c is not None and float(c) > 0]
        has_market = len(coted) >= 6

        # Step 2: DNA layers (données réelles, sans modèle)
        dna = build_race_dna(hippodrome, distance, discipline)
        mkt_dna = build_market_dna() if has_market else None
        fp = race_fingerprint(participants)

        # Step 3: Score each horse
        analyzed = []
        for p in participants:
            horse = p.get("horse", "")
            history = get_horse_history(horse, 20)
            num = p.get("num")

            cat = current_market.get(num, "UNKNOWN")

            form_score = musique_form_score(p.get("musique", ""))
            his = horse_history_probs(history, discipline, distance)

            pct_est = score_dna_match(fp.get(num), dna)
            mkt_est = market_estimate(cat, mkt_dna) if mkt_dna else None

            if mkt_est:
                # Probabilités ANCRÉES au marché : la catégorie fixe le niveau
                # (GF 39%, FC 26%, TOC 16%, OUT 7%), la forme/ADN/sagesse ne font
                # qu'un ajustement borné (±30%). Un TOC ne peut pas dépasser un GF.
                blended = 0.5 * (pct_est["match"] or 0.0) + 0.5 * his["top3"]
                top3_prob = mkt_est["top3"] + 0.7 * (blended - mkt_est["top3"])
                b1 = 0.5 * (pct_est["p1"] or 0.0) + 0.5 * his["p1"]
                b2 = 0.5 * (pct_est["p2"] or 0.0) + 0.5 * his["p2"]
                b3 = 0.5 * (pct_est["p3"] or 0.0) + 0.5 * his["p3"]
                p1 = mkt_est["p1"] + 0.7 * (b1 - mkt_est["p1"])
                p2 = mkt_est["p2"] + 0.7 * (b2 - mkt_est["p2"])
                p3 = mkt_est["p3"] + 0.7 * (b3 - mkt_est["p3"])
                p1 = max(0.0, min(1.0, p1))
                p2 = max(0.0, min(1.0, p2))
                p3 = max(0.0, min(1.0, p3))
                top3_prob = min(1.0, p1 + p2 + p3)
                base_top3 = mkt_dna["base"]["top3"] or 0.0
            else:
                w_pct = 0.55
                w_his = 0.45
                top3_prob = w_pct * (pct_est["match"] or 0.0) + w_his * his["top3"]
                p1 = w_pct * (pct_est["p1"] or 0.0) + w_his * his["p1"]
                p2 = w_pct * (pct_est["p2"] or 0.0) + w_his * his["p2"]
                p3 = w_pct * (pct_est["p3"] or 0.0) + w_his * his["p3"]
                base_top3 = pct_est["base_top3"] or 0.0

            if base_top3 > 0:
                dna_score = round(min(top3_prob / base_top3, 2.0) * 15, 1)
            else:
                dna_score = 0.0

            total = round(form_score + dna_score, 1)

            analyzed.append({
                "num": num,
                "horse": horse,
                "jockey": p.get("jockey", ""),
                "trainer": p.get("trainer", ""),
                "age": p.get("age"),
                "sexe": p.get("sexe"),
                "corde": p.get("corde"),
                "valeur": p.get("valeur"),
                "cote_pmu": p.get("cote_pmu"),
                "categorie": cat,
                "musique": p.get("musique", ""),
                "scores": {
                    "total": total,
                    "form": form_score,
                    "dna": dna_score,
                    "p1": round(p1 * 100, 0),
                    "p2": round(p2 * 100, 0),
                    "p3": round(p3 * 100, 0),
                },
                "history_summary": compute_career_stats(history),
                "rank_prob": top3_prob,
            })

        n = len(analyzed)
        if n <= 3:
            return {"bases": analyzed[:n], "complementaires": [], "regret": []}

        if mkt_dna:
            # Gabarit fixe global (seulement quand les cotes réelles existent) :
            #   Bases = FC FC GF, Complémentaires = FC FC GF, Regret = 2 meilleurs TOC.
            # L'allocation est globale : on réserve 4 FC + 2 GF répartis entre les
            # deux sections, puis les 2 meilleurs TOC restants pour le Regret.
            pools = {}
            for a in analyzed:
                pools.setdefault(a["categorie"], []).append(a)
            for c in pools:
                pools[c].sort(key=lambda x: -x["rank_prob"])

            def take(cat, used):
                for cand in pools.get(cat, []):
                    if cand["num"] not in used:
                        used.add(cand["num"])
                        return cand
                # Repli : priorité au marché (GF puis FC puis TOC puis OUT)
                for c in [CAT_GF, CAT_FC, CAT_TOC, CAT_OUT]:
                    for cand in pools.get(c, []):
                        if cand["num"] not in used:
                            used.add(cand["num"])
                            return cand
                return None

            used = set()
            sections = [["FC", "FC", "GF"], ["FC", "FC", "GF"]]
            filled = []
            for template in sections:
                sec = []
                for cat in template:
                    choice = take(cat, used)
                    if choice:
                        sec.append(choice)
                filled.append(sec)
            bases, complementaires = filled
            rest = [a for a in analyzed if a["num"] not in used]
            tocs = sorted([a for a in rest if a.get("categorie") == CAT_TOC],
                          key=lambda x: -x["rank_prob"])
            regret = tocs[:2]
            if len(regret) < 2:
                more = sorted([a for a in rest if a not in regret],
                              key=lambda x: -x["rank_prob"])
                for a in more:
                    if len(regret) >= 2:
                        break
                    regret.append(a)
        else:
            analyzed.sort(key=lambda x: -x["scores"]["total"])
            bases = analyzed[:3]
            leftovers = analyzed[3:]
            complementaires = leftovers[:3]
            regret_candidates = [a for a in analyzed if a not in bases and a not in complementaires]
            regret = regret_candidates[0] if regret_candidates else None

        return {
            "race_id": race_id,
            "hippodrome": hippodrome,
            "date": course.get("time"),
            "discipline": discipline,
            "distance": distance,
            "prix": course.get("prix", ""),
            "n_runners": len(participants),
            "dna": dna,
            "market_dna": mkt_dna,
            "market": current_market,
            "has_market": has_market,
            "bases": bases,
            "complementaires": complementaires,
            "regret": regret,
        }
    finally:
        _cleanup_conn()
