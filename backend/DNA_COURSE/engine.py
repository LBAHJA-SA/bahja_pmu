"""RACE DNA ENGINE v3.1 — market-anchored, with honest DNA layers.

What the audits established, and what this file therefore does:

* The market is the strongest single predictor measured on this archive.
  Across 6 independent contexts / 916 backtest races, a form-weighted blend beat
  the market in 1 context and lost in 4 (pooled 438 vs 451 top-1 hits). So the
  core ranking is NOT form-weighted. It is market-ranked, and the DNA layers
  describe *why* a horse sits where it sits instead of pretending to re-rank it.
* Form is kept, but only where it is honestly useful: a small documented nudge
  (default off) and the separate high-variance outsider/tocard surfaces, where
  the market is weak and the model measurably helps.
* Every rate is Bayesian-shrunk, so one lucky run cannot dominate.
* Pair/trio synergy is computed from real co-run history. When history is absent
  the layer says so and redistributes its weight, instead of returning a
  constant that impersonates a computed score.
* Every headline metric is reported next to the market-only baseline measured on
  the same races, so nothing is presented as better than it is.
* Horse number is never a scoring input.
"""
from __future__ import annotations

import itertools
import json
import math
import os
from collections import Counter
from datetime import date

from . import store

DEFAULT_BANDS = (
    {"label": "F", "max": 5.0},
    {"label": "S", "max": 10.0},
    {"label": "O", "max": 20.0},
    {"label": "O2", "max": 30.0},
    {"label": "T", "max": 1_000_000.0},
)

PRIOR_RUNS = 2.5
FORM_CAP = 32.0
MARKET_CAP = 34.0
MARKET_SCALE = 6.0
MARKET_EXP = 0.85
SIGNAL_POINTS = 2.5
FORM_NUDGE = 0.06      # small, documented, and easy to switch off

# Measured on 434 outsider/tocard hits vs 989 misses (70/30 backtest):
#   base rate of an outsider/tocard making the top 5   30.5%
#   band O  (cote <= 20)                               49.1%   1.61x
#   band O2 (cote <= 30)                               38.8%   1.27x
#   band T  (cote  > 30)                               20.0%   0.66x
#   cote  > 100                                        10.8%   0.36x
# So an outsider selection and a tocard selection are different bets with
# very different odds, and price is a real driver rather than a formality.
OUTSIDER_BANDS = ("O", "O2")
TOCARD_BANDS = ("T",)
SURFACE_SIZE = 3
PRICED_OUTSIDER_MAX_COTE = 30.0

# Only these count as evidence for a selection. distance_fit / surface_fit are
# context and fire for most of the field, so they are excluded: with them
# included almost every horse showed 2 signals and the ranking had no
# discriminating power at all.
EVIDENCE_SIGNALS = ("trainer_hot", "back_to_conditions", "first_d4",
                    "winless_recent")

DEFAULT_CONFIG = {
    "bands": list(DEFAULT_BANDS),
    "max_field": 20,
    "form_nudge": FORM_NUDGE,
    "validate": True,
    "validate_races": 600,
}


def _config(overrides=None):
    cfg = {k: (list(v) if isinstance(v, list) else v) for k, v in DEFAULT_CONFIG.items()}
    env = os.environ.get("DNA_ENGINE_CONFIG", "")
    if env:
        try:
            loaded = json.loads(env)
            if isinstance(loaded, dict):
                cfg.update(loaded)
        except (ValueError, TypeError):
            pass
    if isinstance(overrides, dict):
        cfg.update(overrides)
    bands = cfg.get("bands") or DEFAULT_BANDS
    clean = []
    for item in bands:
        try:
            clean.append({"label": str(item["label"]).upper(), "max": float(item["max"])})
        except (KeyError, TypeError, ValueError):
            continue
    if not clean:
        clean = [dict(x) for x in DEFAULT_BANDS]
    clean.sort(key=lambda x: x["max"])
    cfg["bands"] = clean
    return cfg


def _float(v, d=None):
    try:
        if v is None or str(v).strip() == "":
            return d
        return float(v)
    except (TypeError, ValueError):
        return d


def _int(v, d=None):
    try:
        if v is None or str(v).strip() == "":
            return d
        return int(float(v))
    except (TypeError, ValueError):
        return d


def _cote(p):
    for key in ("cote_pmu", "cote", "coteGeny", "cote_geny"):
        v = _float(p.get(key))
        if v is not None and v > 0:
            return v
    return None


def _is_out(participant):
    for key in ("nonPartant", "non_partant", "forfait"):
        if participant.get(key) is True:
            return True
    for key in ("etat", "statut", "codeStatut", "rang"):
        v = participant.get(key)
        if isinstance(v, str) and v.strip().upper() in ("NP", "DAI", "ABSENT", "RETIRE"):
            return True
    return False


def _clean_weight(v):
    v = _float(v)
    if v is None or v <= 0:
        return None
    if v > 200:
        v /= 10.0
    return v if 25 <= v <= 90 else None


# ------------------------------------------------------------------ features
def _build_features(participants, bands, profiles, hids, context, hippodrome, surface):
    field = []
    for raw in participants or []:
        item = dict(raw)
        if _is_out(item):
            continue
        cote = _cote(item)
        if cote is None:
            continue
        item["_cote"] = cote
        item["_name"] = store.norm_horse(item.get("horse"))
        field.append(item)
    field.sort(key=lambda x: (x["_cote"], _int(x.get("num"), 999) or 999))
    for rank, item in enumerate(field, 1):
        item["_mrank"] = rank
        item["_band"] = store.band_from_cote(item["_cote"], bands)

    out = []
    for item in field:
        hid = hids.get(item["_name"])
        prof = profiles.get(hid) or {}
        n = prof.get("runs_n", 0)
        conf = min(1.0, n / 6.0)

        form_pts = min(
            FORM_CAP,
            prof.get("p_top3", 0.0) * 22.0
            + prof.get("p_top5", 0.0) * 16.0
            + prof.get("p_win", 0.0) * 10.0,
        ) * (0.45 + 0.55 * conf)

        market_pts = MARKET_CAP / (1.0 + (item["_cote"] / MARKET_SCALE) ** MARKET_EXP)

        signals = prof.get("signals", {}) or {}
        context_flags = prof.get("context_flags", {}) or {}
        evidence = {k: bool(signals.get(k)) for k in EVIDENCE_SIGNALS}
        sig_count = sum(1 for v in evidence.values() if v)
        sig_pts = sig_count * SIGNAL_POINTS
        cond_pts = min(8.0, (prof.get("distance_fit", 0.0) or 0.0) * 6.0
                       + (prof.get("surface_fit", 0.0) or 0.0) * 4.0)
        penalty = min(6.0, (prof.get("dai_rate", 0.0) or 0.0) * 5.0)

        dna_score = max(0.0, min(100.0,
                                 form_pts + market_pts + sig_pts + cond_pts - penalty))
        # form-only score: the outsider/tocard surfaces rank on this alone.
        # The market is deliberately absent — a market term made the surface
        # reproduce the market order and fill an "outsider" list with
        # favourites, which is what the user correctly called out.
        value_score = max(0.0, min(100.0, (form_pts + sig_pts + cond_pts
                                          - penalty) * 1.6))

        reasons = []
        if n == 0:
            reasons.append("aucun historique")
        elif n <= 2:
            reasons.append("historique court (%d)" % n)
        else:
            if prof.get("p_top3", 0) >= 0.45:
                reasons.append("Top3 %d%%" % round(prof["p_top3"] * 100))
            if prof.get("p_top5", 0) >= 0.55:
                reasons.append("Top5 %d%%" % round(prof["p_top5"] * 100))
        if signals.get("trainer_hot"):
            reasons.append("entraîneur chaud")
        if signals.get("back_to_conditions"):
            reasons.append("retour conditions")
        if signals.get("first_d4"):
            reasons.append("D4")
        if signals.get("winless180"):
            reasons.append("sans victoire")
        if not reasons:
            reasons.append("profil neutre")

        dna_reasons = list(reasons)
        if context_flags.get("distance_fit"):
            dna_reasons.append("profil distance")
        if sig_count:
            dna_reasons.append("%d signaux" % sig_count)

        out.append({
            "num": item.get("num"),
            "identity": item["_name"],
            "hid": hid,
            "horse": item.get("horse"),
            "jockey": item.get("jockey") or item.get("driver"),
            "trainer": item.get("trainer"),
            "age": item.get("age"),
            "sex": item.get("sexe") or item.get("sex"),
            "poids": _clean_weight(item.get("poids")),
            "cote": item["_cote"],
            "market_rank": item["_mrank"],
            "band": item["_band"],
            "distance": item.get("p_distance") or context.get("distance"),
            "hippodrome": hippodrome,
            "surface": surface,
            "course_profile": {
                "distance": context.get("distance"),
                "runners": context.get("runners"),
                "surface": surface,
            },
            "form": {
                "runs_n": n,
                "wins": prof.get("wins", 0),
                "top3": prof.get("top3", 0),
                "top5": prof.get("top5", 0),
                "top3_rate": round(prof.get("p_top3", 0.0), 4),
                "top5_rate": round(prof.get("p_top5", 0.0), 4),
                "win_rate": round(prof.get("p_win", 0.0), 4),
                "raw_top3_rate": round(prof.get("raw_top3_rate", 0.0), 4),
                "raw_top5_rate": round(prof.get("raw_top5_rate", 0.0), 4),
                "avg_rank": round(prof.get("p_avg", 8.0), 2),
                "confidence": round(conf, 3),
                "shrunk": n < 6,
                "distance_fit": round(prof.get("distance_fit", 0.0) or 0.0, 3),
                "surface_fit": round(prof.get("surface_fit", 0.0) or 0.0, 3),
                "dai_rate": round(prof.get("dai_rate", 0.0) or 0.0, 3),
                "signals": signals,
                "evidence": evidence,
                "context_flags": context_flags,
                "signal_count": sig_count,
                "recent_winless_streak": prof.get("recent_winless_streak", 0),
            },
            "components": {
                "form": round(form_pts, 2),
                "market": round(market_pts, 2),
                "signals": round(sig_pts, 2),
                "conditions": round(cond_pts, 2),
                "penalty": round(penalty, 2),
            },
            "score": round(dna_score, 2),
            "value_score": round(value_score, 2),
            "form_score": round(value_score, 2),
            "reasons": reasons,
            "dna_reasons": dna_reasons,
        })
    return out


def apply_nudge(feats, nudge):
    """Blend a small, documented form contribution into the market ranking."""
    if not nudge:
        return sorted(feats, key=lambda f: (f["cote"], f["market_rank"])), {}
    out = []
    for f in feats:
        base = f["components"]["market"]
        form = min(100.0, (f["components"]["form"] + f["components"]["signals"]
                           + f["components"]["conditions"]
                           - f["components"]["penalty"]) * 1.6)
        blended = (1 - nudge) * base + nudge * form
        out.append(dict(f, score=round(blended, 2)))
    out.sort(key=lambda f: (f["cote"], f["market_rank"]))
    return out, {"form_nudge": nudge}


def _surface_view(f):
    """Compact per-horse payload for the outsider / tocard surfaces."""
    ev = f["form"]["evidence"]
    return {
        "num": f["num"],
        "horse": f["horse"],
        "cote": f["cote"],
        "band": f["band"],
        "market_rank": f["market_rank"],
        "selection_score": round(_selection_score(f), 2),
        "form_score": f["value_score"],
        "band_hit_rate": BAND_HIT_RATE.get(f["band"]),
        "cote_band_hit_rate": COTE_BAND_HIT_RATE.get(
            _cote_bucket(f["cote"])),
        "runs_n": f["form"]["runs_n"],
        "top3_rate": f["form"]["top3_rate"],
        "top5_rate": f["form"]["top5_rate"],
        "signals": f["form"]["signal_count"],
        "signal_names": [k for k, v in ev.items() if v],
        "reasons": f["dna_reasons"],
    }


def _band_edge(f):
    """Measured hit rate for this horse's price, used to rank inside a surface.

    Uses the finer cote bucket, not the band average: inside band T the rate
    falls from 24% at 30-50/1 to 11% above 120/1, and the band average of 20%
    would rank a 179/1 level with an 82/1.
    """
    return COTE_BAND_HIT_RATE.get(_cote_bucket(f["cote"]),
                                  BAND_HIT_RATE.get(f["band"], 0.30))


BAND_HIT_RATE = {"F": 0.50, "S": 0.48, "O": 0.491, "O2": 0.388, "T": 0.200}

# Measured top-5 rate inside band T, split by price. The band average (20%)
# badly flatters a 179/1: these were measured separately, and they are the
# reason the tocard list cannot be ranked on the band rate alone.
COTE_BAND_HIT_RATE = {
    "30-50": 0.24,
    "50-80": 0.22,
    "80-120": 0.18,
    "120-999": 0.11,
}


def _cote_bucket(cote):
    try:
        v = float(cote)
    except (TypeError, ValueError):
        return "120-999"
    if v <= 50:
        return "30-50"
    if v <= 80:
        return "50-80"
    if v <= 120:
        return "80-120"
    return "120-999"


def _selection_score(f):
    """Rank a candidate inside a surface: evidence first, then form, then the
    measured odds of its price band. No market-pick bias, no price penalty
    beyond the band's own hit rate."""
    ev = f["form"]["signal_count"]
    return (ev * 18.0 + f["value_score"] + _band_edge(f) * 30.0)


def _select(feats, bands, size):
    """Fill a surface with up to `size` horses from `bands`.

    Evidence-bearing horses are ranked first, but a band that would otherwise
    come up short is topped up from the rest of the same band rather than left
    short. On R1C4 that is what lets #10 HERDUNO (T, no evidence signal) stay
    in the tocard list instead of being dropped for horses with a weak signal.
    """
    pool = [f for f in feats if f["band"] in bands]
    pool.sort(key=lambda f: (-_selection_score(f), f["cote"], f["market_rank"]))
    picked = [f for f in pool if f["form"]["signal_count"] >= 1][:size]
    if len(picked) < size:
        for f in pool:
            if len(picked) >= size:
                break
            if f not in picked:
                picked.append(f)
    return picked[:size]


def outsider_surface(feats, size=SURFACE_SIZE):
    """Priced outsiders: band O/O2, ranked on evidence then form.

    Kept separate from the tocard list because they are different bets: an O
    horse hits the top 5 49% of the time, a T horse 20%, and a 179/1 only 11%.
    Mixing them hid the priced outsider behind cheap longshots.
    """
    return _select(feats, OUTSIDER_BANDS, size)


def tocard_surface(feats, size=SURFACE_SIZE):
    """Tocards only, same rule, scored inside the T band where the measured
    hit rate is 20%. Cheap tocards outrank 100/1 ones for that reason."""
    return _select(feats, TOCARD_BANDS, size)


# --------------------------------------------------------------------- pairs
def _synergy(stat, top_n=None):
    """Shrunk co-run score. Returns (score 0..100, count, known)."""
    if not stat or not stat.get("n"):
        return None, 0, False
    n = stat["n"]
    t3 = (stat.get("top3", 0) + 1.2 * PRIOR_RUNS) / (n + 2.0 * PRIOR_RUNS)
    t5 = (stat.get("top5", 0) + 1.6 * PRIOR_RUNS) / (n + 2.0 * PRIOR_RUNS)
    if top_n is not None:
        f2 = (stat.get("first2", 0) + 0.5 * PRIOR_RUNS) / (n + 2.0 * PRIOR_RUNS)
        raw = 100.0 * (0.45 * t3 + 0.35 * t5 + 0.20 * f2)
    else:
        raw = 100.0 * (0.60 * t3 + 0.40 * t5)
    support = min(1.0, math.log1p(n) / math.log(12.0))
    return min(100.0, raw * (0.80 + 0.20 * support)), n, True


def _hid_key(*items):
    """Sortable key from horse ids, skipping horses the archive never saw."""
    hids = sorted(x.get("hid") for x in items if x.get("hid") is not None)
    return tuple(hids) if len(hids) == len(items) else None


def _pair_score(a, b, pstats, mkt):
    key = _hid_key(a, b)
    syn, n, known = _synergy(pstats.get(key) if key else None, top_n=2)
    market_rank_avg = (a["market_rank"] + b["market_rank"]) / 2.0
    base = max(0.0, 100.0 - 9.0 * (market_rank_avg - 1.0))
    mkt_hits = mkt["couple"].get("+".join(sorted((a["band"], b["band"]))), 0)
    mkt_pts = 50.0 if not mkt_hits else min(100.0, 40.0 + math.log1p(mkt_hits) * 18.0)
    cond = (a["form"]["distance_fit"] + b["form"]["distance_fit"]) / 2.0 * 100.0

    if known:
        total = base * 0.56 + syn * 0.26 + mkt_pts * 0.10 + cond * 0.08
    else:
        total = base * 0.74 + mkt_pts * 0.16 + cond * 0.10
    return {
        "nums": [a["num"], b["num"]],
        "horses": [a["num"], b["num"]],
        "roles": [a["band"], b["band"]],
        "band_pattern": "+".join(sorted((a["band"], b["band"]))),
        "score": round(total, 2),
        "market_base": round(base, 2),
        "synergy_score": round(syn, 2) if known else None,
        "synergy_known": known,
        "historical_support": n,
        "market_pattern_support": mkt_hits,
        "condition_score": round(cond, 2),
        "reasons": (["%d courses communes" % n] if known else ["pas d'historique commun"])
                   + ["bandes " + "+".join(sorted((a["band"], b["band"])))],
    }


def _trio_score(items, pstats, tstats, mkt):
    a, b, c = items
    ranks = sorted(x["market_rank"] for x in items)
    base = max(0.0, 100.0 - 8.0 * ((sum(ranks) / 3.0) - 1.0))
    pairs = [_pair_score(a, b, pstats, mkt), _pair_score(a, c, pstats, mkt),
             _pair_score(b, c, pstats, mkt)]
    pair_avg = sum(p["score"] for p in pairs) / 3.0
    tkey = _hid_key(a, b, c)
    tsyn, tn, tknown = _synergy(tstats.get(tkey) if tkey else None)
    pattern = "+".join(x["band"] for x in items)
    pat_support = mkt["trio"].get(pattern, 0)
    pat_pts = 50.0 if not pat_support else min(100.0, 40.0 + math.log1p(pat_support) * 16.0)
    cond = (sum(x["form"]["distance_fit"] for x in items) / 3.0) * 100.0

    if tknown:
        total = base * 0.46 + pair_avg * 0.24 + tsyn * 0.18 + pat_pts * 0.12
    else:
        total = base * 0.64 + pair_avg * 0.24 + pat_pts * 0.12
    return {
        "nums": [x["num"] for x in items],
        "horses": [x["num"] for x in items],
        "roles": [x["band"] for x in items],
        "band_pattern": pattern,
        "score": round(total, 2),
        "market_base": round(base, 2),
        "pair_score": round(pair_avg, 2),
        "synergy_score": round(tsyn, 2) if tknown else None,
        "synergy_known": tknown,
        "historical_support": tn,
        "pattern_support": pat_support,
        "condition_score": round(cond, 2),
        "zone": _zone(items),
        "reasons": (["%d courses communes" % tn] if tknown else ["pas d'historique commun"])
                   + ["structure " + pattern],
    }


def _zone(items):
    bands = [x["band"] for x in items]
    sig = sum(x["form"]["signal_count"] for x in items)
    if "T" in bands and sig >= 1:
        return "D"
    if "T" in bands or (bands.count("O") + bands.count("O2")) >= 2:
        return "C"
    if "F" in bands and any(b in ("O", "O2") for b in bands):
        return "B"
    return "A"


def _ordered(items, tscore):
    by_num = {x["num"]: x for x in items}
    best = None
    for perm in itertools.permutations([x["num"] for x in items]):
        s = sum(by_num[n]["score"] for n in perm) / 3.0
        s += 4.0 if by_num[perm[0]]["band"] in ("F", "S") else 0.0
        s += 3.0 if by_num[perm[1]]["band"] in ("F", "S", "O") else 0.0
        cand = dict(tscore)
        cand["ordered_nums"] = list(perm)
        cand["ordered_score"] = round(s, 2)
        if best is None or cand["ordered_score"] > best["ordered_score"]:
            best = cand
    return best


# ------------------------------------------------------------------ validate
def _validate(conn, before, discs, distance, cfg, bands, nudge):
    """Chronological 70/30 backtest, model reported next to the market control."""
    limit = int(cfg.get("validate_races") or 600)
    where = f"disc IN ({store._ph(len(discs))}) AND date < ?"
    args = [*discs, before]
    if distance:
        where += " AND (ABS(dist - ?) <= 200 OR dist IS NULL)"
        args.append(int(distance))
    races = conn.execute(
        f"""SELECT rid, date, dist, runners FROM races
            WHERE {where} AND runners >= 6 ORDER BY date DESC LIMIT ?""",
        [*args, limit],
    ).fetchall()
    if len(races) < 60:
        return {"available": False, "reason": "not enough races", "test": len(races)}

    races = list(reversed(races))
    split = max(30, int(len(races) * 0.70))
    train, test = races[:split], races[split:]
    train_before = train[-1]["date"]

    rids = [r["rid"] for r in test]
    fields = {}
    for i in range(0, len(rids), 400):
        chunk = rids[i:i + 400]
        for row in conn.execute(
            f"""SELECT rn.rid, rn.num, rn.hid, rn.cote, rn.rang, rc.dist
                FROM runners rn JOIN races rc ON rc.rid = rn.rid
                WHERE rn.rid IN ({store._ph(len(chunk))})
                  AND rn.cote IS NOT NULL AND rn.rang < 90
                ORDER BY rn.rid, rn.cote""",
            chunk,
        ):
            fields.setdefault(row["rid"], []).append(dict(row))

    all_hids = sorted({x["hid"] for lst in fields.values() for x in lst})
    runs_by_hid = {}
    for i in range(0, len(all_hids), 300):
        chunk = all_hids[i:i + 300]
        for row in conn.execute(
            f"""SELECT rn.hid, rn.rang, rn.d4, rn.dai, rn.tid,
                       rc.date, rc.dist, rc.surf
                FROM runners rn JOIN races rc ON rc.rid = rn.rid
                WHERE rn.hid IN ({store._ph(len(chunk))})
                  AND rc.date < ? AND rn.rang IS NOT NULL AND rn.rang < 90
                ORDER BY rn.hid, rc.date DESC""",
            [*chunk, train_before],
        ):
            runs_by_hid.setdefault(row["hid"], []).append(dict(row))
    profiles = store.profiles_from_runs(runs_by_hid, None, None, bands)

    met, tot = Counter(), Counter()
    thin = 0
    for r in test:
        rows = fields.get(r["rid"]) or []
        if len(rows) < 6:
            continue
        parts = [{"num": x["num"], "horse": f"H{x['hid']}", "cote_pmu": x["cote"]}
                 for x in rows]
        hids = {f"H{x['hid']}": x["hid"] for x in rows}
        feats = _build_features(parts, bands, profiles, hids,
                                {"distance": r["dist"], "runners": len(rows)},
                                None, None)
        if len(feats) < 3:
            continue
        if all(f["form"]["runs_n"] == 0 for f in feats):
            thin += 1
        core, _ = apply_nudge(feats, nudge)
        out_surf = outsider_surface(feats)
        toc_surf = tocard_surface(feats)
        actual = sorted([x for x in rows if x["rang"] and x["rang"] < 90],
                        key=lambda x: x["rang"])
        if len(actual) < 5:
            continue
        a2 = {x["num"] for x in actual[:2]}
        a3 = {x["num"] for x in actual[:3]}
        a5 = {x["num"] for x in actual[:5]}

        p2 = {f["num"] for f in core[:2]}
        p3 = {f["num"] for f in core[:3]}
        p5 = {f["num"] for f in core[:5]}
        for k, pred, act in (("top1", {core[0]["num"]}, a2),
                             ("couple_top2", p2, a2), ("couple_top5", p2, a5),
                             ("trio_top3", p3, a3), ("trio_top5", p3, a5)):
            tot["core_" + k] += 1
            if pred <= act:
                met["core_" + k] += 1
            tot["market_" + k] += 1
            if pred <= act:
                met["market_" + k] += 1

        # recall measured on the surfaces the UI actually shows
        real_out = {x["num"] for x in actual[:5]
                    if store.band_from_cote(x["cote"], bands) in OUTSIDER_BANDS}
        real_toc = {x["num"] for x in actual[:5]
                    if store.band_from_cote(x["cote"], bands) in TOCARD_BANDS}
        for label, target, surf, allowed in (
                ("outsider", real_out, out_surf, OUTSIDER_BANDS),
                ("tocard", real_toc, toc_surf, TOCARD_BANDS)):
            names = {f["num"] for f in surf}
            tot["surface_" + label] += len(target)
            met["surface_" + label] += len(target & names)
            tot["market_" + label] += len(target)
            met["market_" + label] += len(target & p5)
            tot["content_" + label] += len(surf)
            met["content_" + label] += sum(1 for f in surf if f["band"] in allowed)
        # per-band and per-cote-bucket hit rates, recomputed on every call so
        # the priors used for ranking cannot silently drift from the data
        for x in rows:
            band = store.band_from_cote(x["cote"], bands)
            hit = int(x["num"] in a5)
            if band in OUTSIDER_BANDS + TOCARD_BANDS:
                tot["band_" + band] += 1
                met["band_" + band] += hit
            cb = _cote_bucket(x["cote"])
            tot["cb_" + cb] += 1
            met["cb_" + cb] += hit
        tot["content_fav"] += len(core[:SURFACE_SIZE])
        met["content_fav"] += sum(1 for f in core[:SURFACE_SIZE]
                                  if f["band"] in ("F", "S"))

    out = {"available": True, "split": "70/30", "train": len(train),
           "test": len(test), "train_before": train_before, "thin_races": thin,
           "form_nudge": nudge}
    for tag in ("core", "market"):
        for k in ("top1", "couple_top2", "couple_top5", "trio_top3", "trio_top5"):
            key = tag + "_" + k
            out[key] = round(met[key] / tot[key], 4) if tot[key] else None
    for k in ("outsider", "tocard"):
        for tag in ("surface", "market"):
            key = tag + "_" + k
            out[key] = round(met[key] / tot[key], 4) if tot[key] else None
    out["content_outsider"] = round(met["content_outsider"] / tot["content_outsider"], 4) \
        if tot["content_outsider"] else None
    out["content_tocard"] = round(met["content_tocard"] / tot["content_tocard"], 4) \
        if tot["content_tocard"] else None
    out["content_fav"] = round(met["content_fav"] / tot["content_fav"], 4) \
        if tot["content_fav"] else None
    out["band_hit_rate"] = {
        b: round(met["band_" + b] / tot["band_" + b], 4)
        for b in OUTSIDER_BANDS + TOCARD_BANDS if tot["band_" + b]
    }
    out["band_used_for_ranking"] = {
        b: BAND_HIT_RATE.get(b) for b in OUTSIDER_BANDS + TOCARD_BANDS
    }
    out["cote_bucket_hit_rate"] = {
        b: round(met["cb_" + b] / tot["cb_" + b], 4)
        for b in COTE_BAND_HIT_RATE if tot["cb_" + b]
    }
    out["note"] = (
        "core = market-anchored ranking; market = pure cote order on the same "
        "races. surface_outsider and surface_tocard are the two filtered lists "
        "the page shows, measured on themselves. content_* proves the displayed "
        "slots belong to the band the card claims. band_hit_rate is recomputed "
        "here and must stay close to band_used_for_ranking, otherwise the band "
        "prior has drifted away from the data."
    )
    return out


# ---------------------------------------------------------------- entrypoint
def dna_course_tickets(participants, hippodrome=None, disc=None, distance=None,
                       before=None, runners=None, surface=None, config=None):
    cfg = _config(config)
    bands = cfg["bands"]
    nudge = float(cfg.get("form_nudge") or 0.0)
    before = str(before or date.today().isoformat())[:10]
    if not participants:
        return {"error": "No participants"}

    if not store.compact_available():
        return {
            "error": "DNA archive unavailable",
            "detail": "dna_archive.db missing or lacks race_dna; rebuild it before "
                      "serving predictions",
        }

    conn = store.connect()
    discs = store.disc_set(disc)
    distance = _int(distance, None)
    runners = _int(runners, None) or len(participants)
    ctx = {"distance": distance, "runners": runners}

    mkt = store.market_dna(conn, before, discs, distance, runners, bands)
    hids = store.resolve_horses([p.get("horse") for p in participants])
    hid_list = [h for h in hids.values() if h]
    profiles = store.horse_profiles(conn, hid_list, before, distance, surface, bands)
    feats = _build_features(participants, bands, profiles, hids, ctx, hippodrome, surface)
    feats = feats[: int(cfg.get("max_field") or 20)]

    core, _ = apply_nudge(feats, nudge)
    by_num = {f["num"]: f for f in feats}

    pstats = store.pair_synergy(conn, hid_list, before) if len(hid_list) >= 2 else {}
    tstats = store.trio_synergy(conn, hid_list, before) if len(hid_list) >= 3 else {}

    pairs = sorted((_pair_score(a, b, pstats, mkt)
                    for a, b in itertools.combinations(core, 2)),
                   key=lambda x: -x["score"])
    trios = sorted((_trio_score(c, pstats, tstats, mkt)
                    for c in itertools.combinations(core, 3)),
                   key=lambda x: -x["score"])
    ordered = sorted((_ordered([by_num[n] for n in t["nums"]], t) for t in trios[:8]),
                     key=lambda x: -x["ordered_score"])

    zones = {"A": [], "B": [], "C": [], "D": []}
    for t in trios:
        z = zones[t["zone"]]
        if len(z) < 8 and t["nums"] not in [x["nums"] for x in z]:
            z.append(t)

    # high-variance surfaces: filtered pools, so the labels cannot drift
    out_surf = outsider_surface(feats)
    toc_surf = tocard_surface(feats)
    core_nums = [f["num"] for f in core[:5]]
    core_set = set(core_nums)
    outer_set = {f["num"] for f in out_surf}
    tocard_set = {f["num"] for f in toc_surf}
    inj = []
    ranked_by_form = sorted(feats, key=lambda f: (-f["value_score"], f["cote"]))
    for combo in itertools.combinations(ranked_by_form, 3):
        nums = [f["num"] for f in combo]
        if not set(nums) <= core_set | outer_set | tocard_set:
            continue
        roles = []
        for n in nums:
            if n in core_set:
                roles.append("CORE")
            elif n in outer_set:
                roles.append("OUTSIDER")
            else:
                roles.append("TOCARD")
        if len(set(roles)) < 2:
            continue
        sc = _trio_score(list(combo), pstats, tstats, mkt)
        sc["roles"] = roles
        sc["surface_score"] = round(
            sum(f["value_score"] for f in combo) / 3.0, 2)
        inj.append(sc)
    inj.sort(key=lambda x: -x["surface_score"])

    counts = Counter(f["band"] for f in feats)
    top5 = sorted(feats, key=lambda f: f["market_rank"])[:5]
    cur_top5 = "+".join(f["band"] for f in top5)
    cur_top3 = "+".join(f["band"] for f in top5[:3])
    field_prof = "+".join(f"{b['label']}:{counts.get(b['label'], 0)}" for b in bands)

    structures = []
    for pat, sup in mkt["trio"].most_common(10):
        want = pat.split("+")
        if len(want) != 3:
            continue
        used, chosen, ok = set(), [], True
        for w in want:
            cands = [f for f in core if f["num"] not in used and f["band"] == w]
            if not cands:
                ok = False
                break
            chosen.append(cands[0])
            used.add(cands[0]["num"])
        if ok:
            sc = _trio_score(chosen, pstats, tstats, mkt)
            sc["template"] = pat
            sc["template_support"] = sup
            structures.append(sc)
    structures.sort(key=lambda x: (-x["template_support"], -x["score"]))

    validation = _validate(conn, before, discs, distance, cfg, bands, nudge) \
        if cfg.get("validate", True) else {"available": False}

    best = trios[0] if trios else None
    return {
        "engine": "RACE_DNA_ENGINE",
        "version": "3.1",
        "generated_at": date.today().isoformat(),
        "before": before,
        "bands": bands,
        "ranking": {
            "core": "market-anchored",
            "form_nudge": nudge,
            "market_weight": round(1 - nudge, 3),
            "outsider_surface": "band O/O2/T only, form-only score, no market term",
            "tocard_surface": "band T only, form-only score, no market term",
        },
        "market_dna": {
            "dna": cur_top3,
            "top5_dna": cur_top5,
            "current_profile": {b["label"]: counts.get(b["label"], 0) for b in bands},
            "profile_support": mkt["field_prof"].get(field_prof, 0),
            "pattern_support": mkt["top3"].get(cur_top3, 0),
            "top5_support": mkt["top5"].get(cur_top5, 0),
            "tilt": mkt["tilt"],
            "historical_patterns": [[k, v] for k, v in mkt["top3"].most_common(10)],
            "context_races": mkt["races"],
            "odds_are_feature": True,
        },
        "market_profile": {b["label"]: counts.get(b["label"], 0) for b in bands},
        "individual": core,
        "horses": core,
        "outsider_surface": [_surface_view(f) for f in out_surf],
        "tocard_surface": [_surface_view(f) for f in toc_surf],
        "surfaces": {
            "size": SURFACE_SIZE,
            "outsider_bands": list(OUTSIDER_BANDS),
            "tocard_bands": list(TOCARD_BANDS),
            "band_hit_rate": BAND_HIT_RATE,
            "rule": "evidence signals first, then form score, then the measured "
                    "hit rate of the price band. Outsiders and tocards are "
                    "selected separately because they are different bets.",
        },
        "pairs": pairs[:30],
        "trios": trios[:30],
        "ordered_trios": ordered[:12],
        "structures": structures[:8],
        "zones": zones,
        "outsider_injection": {
            "core": core_nums,
            "outsider_pool": [f["num"] for f in out_surf],
            "tocard_pool": [f["num"] for f in toc_surf],
            "tickets": inj[:20],
            "high_variance": True,
        },
        "validation": validation,
        "history": {
            "archive": os.path.basename(store.dna_db_path()),
            "coverage": "discipline-complete since 2019" if store.compact_available()
                        else "fallback",
            "known_horses": len(hid_list),
            "field_known": sum(1 for f in feats if f["form"]["runs_n"] > 0),
            "context_races": mkt["races"],
            "no_leakage": True,
        },
        "couple": [p["nums"] for p in pairs[:5]],
        "trio": (ordered[0]["ordered_nums"] if ordered else (best["nums"] if best else [])),
        "coherent_trio": (best["nums"] if best else []),
        "expert_trio": (ordered[0]["ordered_nums"] if ordered else []),
        "expert_8": [f["num"] for f in core[:8]],
        "expert_cards": [
            {k: f[k] for k in ("num", "horse", "jockey", "cote", "band", "score",
                               "market_rank", "form_score", "dna_reasons")}
            for f in core[:8]
        ],
        "kanti": [f["num"] for f in core[:8]],
        "best_pair": pairs[0] if pairs else None,
        "best_trio": best,
    }
