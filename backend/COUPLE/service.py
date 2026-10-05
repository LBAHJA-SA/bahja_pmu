"""
COUPLE DNA V3 — full-Top3 pattern matching (complete signatures).

History stores COMPLETE Top3 signatures (P1/P2/P3 profiles + relations).
Matching scores whole candidate Top3s against recurring COMPLETE patterns:

  1. support FIRST: how many times did this whole pattern recur?
     (full pattern = fam triple + rank triple, then fam triple, then coarse)
  2. coherence: rank/median deviation, profile deviation, relation frequency
     computed WITHIN the same-pattern group (never global).

Ranking tuple (lexicographic, no invented weights):
  (level, support, -rank_dev, -prof_dev, rel_freq)
Level first: a specific recurred pattern (full > exact > coarse) always
beats a vaguer one — support is only compared WITHIN the same level.
(Test 4: level-first = favorite level P1 40.4% vs support-first 16.8%.)

Same public API as V2: get_small_top3_stats(limit), match_small_couple(participants, hist).
"""
from typing import Any, Dict, List
import time, threading, statistics
from collections import Counter, defaultdict
from database import get_db

_CACHE = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 3600

# Max signatures kept (most recent first). Counters are computed on the kept set.
MAX_SIGNATURES = 8000

# Approved market DNA, fine scale (do NOT change without approval).
_FAM_SCALE = [
    ("FAV1", 0, 3.0), ("FAV2", 3.1, 7.0), ("FAV3", 7.1, 10.0),
    ("OUT1", 10.1, 13.0), ("OUT2", 13.1, 16.0), ("OUT3", 16.1, 18.0),
    ("TOC1", 18.1, 21.0), ("TOC2", 21.1, 25.0), ("TOC3", 25.1, 28.0),
    ("TOC4", 28.1, 31), ("TOC5", 31.1, 36), ("TOC6", 36.1, 40),
    ("TOC7", 40.1, 50), ("TOC8", 50.1, 100),
]

def _market_family(cote):
    try:
        c = float(cote)
    except Exception:
        return "UNK"
    for name, lo, hi in _FAM_SCALE:
        if lo <= c <= hi:
            return name
    return "TOC8" if c > 100 else "UNK"


def _coarse(fam):
    if fam.startswith("FAV"):
        return "FAV"
    if fam.startswith("OUT"):
        return "OUT"
    if fam.startswith("TOC"):
        return "TOC"
    return "UNK"


def _get_total_small():
    conn = get_db()
    c = conn.execute("SELECT COUNT(*) as c FROM races WHERE runners < 12 AND runners > 0").fetchone()["c"]
    conn.close()
    return c


def _norm_poids(v):
    try:
        fv = float(v)
        if fv > 200:
            fv /= 10
        return fv if 30 < fv < 80 else None
    except Exception:
        return None


def _norm_cote(v):
    try:
        return float(v) if v is not None else None
    except Exception:
        return None


def _gap(a, b):
    if a is None or b is None:
        return None
    try:
        return abs(float(a) - float(b))
    except Exception:
        return None


def _rel_signature(pa, pb, ra, rb):
    """Relation signature between two horses (directed: a finished ahead of b)."""
    fa = _market_family(pa.get("cote_pmu"))
    fb = _market_family(pb.get("cote_pmu"))
    return {
        "fam_pair": f"{fa}-{fb}",
        "rank_pair": [ra, rb],
        "cote_gap": _gap(pa.get("cote_pmu"), pb.get("cote_pmu")),
        "poids_gap": _gap(_norm_poids(pa.get("poids")), _norm_poids(pb.get("poids"))),
        "valeur_gap": _gap(pa.get("valeur"), pb.get("valeur")),
        "age_gap": _gap(pa.get("age"), pb.get("age")),
        "corde_gap": _gap(pa.get("corde"), pb.get("corde")),
        "gain_gap": _gap(pa.get("gain"), pb.get("gain")),
    }


def _horse_profile(p, rank):
    return {
        "market_rank": rank,
        "family": _market_family(p.get("cote_pmu")),
        "cote": _norm_cote(p.get("cote_pmu")),
        "poids": _norm_poids(p.get("poids")),
        "valeur": p.get("valeur"),
        "age": p.get("age"),
        "corde": p.get("corde"),
    }


def _median_or_none(vals):
    vals = [v for v in vals if v is not None]
    if not vals:
        return None
    try:
        return statistics.median(vals)
    except Exception:
        return None


def _group_aggregates(sigs):
    """Aggregate medians + relation distributions WITHIN one pattern group."""
    n = len(sigs)
    med_ranks = [_median_or_none([s["ranks"][i] for s in sigs]) for i in range(3)]
    med_prof = []
    for i in range(3):
        med_prof.append({
            "cote": _median_or_none([s["profiles"][i].get("cote") for s in sigs]),
            "poids": _median_or_none([s["profiles"][i].get("poids") for s in sigs]),
            "valeur": _median_or_none([s["profiles"][i].get("valeur") for s in sigs]),
        })
    rel_dists = {}
    rel_coarse_dists = {}
    for rel in ("P1-P2", "P1-P3", "P2-P3"):
        rel_dists[rel] = dict(Counter(s["rels"][rel]["fam_pair"] for s in sigs))
        rel_coarse_dists[rel] = dict(
            Counter("-".join(_coarse(f) for f in s["rels"][rel]["fam_pair"].split("-"))
                    for s in sigs))
    return {"n": n, "med_ranks": med_ranks, "med_prof": med_prof, "rel_dists": rel_dists,
            "rel_coarse_dists": rel_coarse_dists}


def get_small_top3_stats(limit: int = None, before: str = None) -> Dict:
    total_small = _get_total_small()
    use_limit = total_small if limit is None or limit > total_small else limit
    if limit is None:
        use_limit = total_small
    key = f"small_couple_v3_{use_limit}_{before or 'all'}"
    now = time.time()
    with _CACHE_LOCK:
        if key in _CACHE and now - _CACHE[key]["ts"] < _CACHE_TTL:
            return _CACHE[key]["data"]
    conn = get_db()
    if before:
        race_rows = conn.execute(
            "SELECT race_id FROM races WHERE runners < 12 AND runners > 0 AND date < ? ORDER BY date DESC LIMIT ?",
            (before, use_limit,)).fetchall()
    else:
        race_rows = conn.execute(
            "SELECT race_id FROM races WHERE runners < 12 AND runners > 0 ORDER BY date DESC LIMIT ?",
            (use_limit,)).fetchall()
    race_ids = [r["race_id"] for r in race_rows]
    if not race_ids:
        data = {"total_petites_races": 0, "total_top3_races": 0, "total_top3": 0,
                "top3_signatures": [], "fam_triple_counter": {},
                "fam_triple_coarse_counter": {}, "full_pattern_counter": {},
                "rel_distributions": {}, "rel_coarse_distributions": {},
                "pattern_groups": {}, "couple_details": {}, "couple_counter": {}}
        with _CACHE_LOCK:
            _CACHE[key] = {"data": data, "ts": now}
        conn.close()
        return data
    # Cap stored signatures (most recent first) so the payload stays sane.
    kept_ids = race_ids[:MAX_SIGNATURES]
    ph = ",".join("?" * len(kept_ids))
    rows = conn.execute(
        f"SELECT r.race_id, r.runners, r.hippodrome, r.distance, p.num, p.horse, "
        f"p.age, p.poids, p.valeur, p.cote_pmu, p.musique, p.rang, p.corde, p.sexe, p.gain "
        f"FROM races r JOIN participants p ON p.race_id=r.race_id "
        f"WHERE r.race_id IN ({ph})", kept_ids).fetchall()
    conn.close()
    by_race = defaultdict(list)
    for r in rows:
        by_race[r["race_id"]].append(dict(r))

    top3_signatures = []
    n_top3_races = 0
    all_top3 = []
    # legacy aggregates (kept for compatibility, computed with V3 families)
    couple_stats = defaultdict(list)
    for rid, parts in by_race.items():
        with_cote = [p for p in parts if p.get("cote_pmu") is not None]
        if len(with_cote) < 3:
            continue
        with_cote_sorted = sorted(with_cote, key=lambda x: float(x["cote_pmu"]))
        rank_map = {p["num"]: idx + 1 for idx, p in enumerate(with_cote_sorted)}
        by_rang = {p["rang"]: p for p in parts if p.get("rang") in (1, 2, 3)}
        if not all(k in by_rang for k in (1, 2, 3)):
            continue
        n_top3_races += 1
        p1, p2, p3 = by_rang[1], by_rang[2], by_rang[3]
        r1, r2, r3 = (rank_map.get(p1["num"], 99), rank_map.get(p2["num"], 99),
                      rank_map.get(p3["num"], 99))
        sig = {
            "ranks": [r1, r2, r3],
            "fams": [_market_family(p1.get("cote_pmu")),
                     _market_family(p2.get("cote_pmu")),
                     _market_family(p3.get("cote_pmu"))],
            "profiles": [_horse_profile(p1, r1), _horse_profile(p2, r2),
                         _horse_profile(p3, r3)],
            "rels": {
                "P1-P2": _rel_signature(p1, p2, r1, r2),
                "P1-P3": _rel_signature(p1, p3, r1, r3),
                "P2-P3": _rel_signature(p2, p3, r2, r3),
            },
        }
        top3_signatures.append(sig)
        all_top3.extend([p1, p2, p3])
        for a_rank, b_rank in [(1, 2), (1, 3), (2, 3)]:
            pa = by_rang[a_rank]
            pb = by_rang[b_rank]
            k = f"P{a_rank}-P{b_rank}"
            ra = rank_map.get(pa["num"], 99)
            rb = rank_map.get(pb["num"], 99)
            couple_stats[k].append({
                "ra": ra, "rb": rb,
                "fam_a": _market_family(pa.get("cote_pmu")),
                "fam_b": _market_family(pb.get("cote_pmu")),
                "poids_gap": _gap(_norm_poids(pa.get("poids")), _norm_poids(pb.get("poids"))),
                "age_gap": _gap(pa.get("age"), pb.get("age")),
                "valeur_gap": _gap(pa.get("valeur"), pb.get("valeur")),
                "cote_gap": _gap(pa.get("cote_pmu"), pb.get("cote_pmu")),
                "corde_gap": _gap(pa.get("corde"), pb.get("corde")),
                "gain_gap": _gap(pa.get("gain"), pb.get("gain")),
            })

    # Full distributions (never reduced to a single top value).
    fam_triple_counter = dict(Counter("-".join(s["fams"]) for s in top3_signatures))
    fam_triple_coarse_counter = dict(
        Counter("-".join(_coarse(f) for f in s["fams"]) for s in top3_signatures))
    full_pattern_counter = dict(
        Counter("-".join(s["fams"]) + "|" + "-".join(str(r) for r in s["ranks"])
                for s in top3_signatures))
    rel_distributions = {}
    rel_coarse_distributions = {}
    for rel in ("P1-P2", "P1-P3", "P2-P3"):
        rel_distributions[rel] = dict(Counter(s["rels"][rel]["fam_pair"] for s in top3_signatures))
        rel_coarse_distributions[rel] = dict(
            Counter("-".join(_coarse(f) for f in s["rels"][rel]["fam_pair"].split("-"))
                    for s in top3_signatures))
    # Pattern groups: aggregates computed WITHIN each recurring pattern,
    # at all three granularities (full = fams+ranks, fam, coarse).
    _by_full = defaultdict(list)
    _by_fam = defaultdict(list)
    _by_coarse = defaultdict(list)
    for s in top3_signatures:
        fkey = "-".join(s["fams"])
        rkey = "-".join(str(r) for r in s["ranks"])
        _by_full[fkey + "|" + rkey].append(s)
        _by_fam[fkey].append(s)
        _by_coarse["-".join(_coarse(f) for f in s["fams"])].append(s)
    pattern_groups = {k: _group_aggregates(v) for k, v in _by_full.items()}
    fam_groups = {k: _group_aggregates(v) for k, v in _by_fam.items()}
    coarse_groups = {k: _group_aggregates(v) for k, v in _by_coarse.items()}

    def vals(k):
        return [p[k] for p in all_top3 if p.get(k) is not None]

    def mk(vs):
        if not vs:
            return {}
        try:
            return {"mean": round(statistics.mean(vs), 2),
                    "median": round(statistics.median(vs), 2),
                    "std": round(statistics.pstdev(vs), 2) if len(vs) > 1 else 0}
        except Exception:
            return {}

    poids_vals = []
    for p in all_top3:
        v = _norm_poids(p.get("poids"))
        if v:
            poids_vals.append(v)
    per_rank = {}
    for rank in [1, 2, 3]:
        sub = [p for p in all_top3 if p.get("rang") == rank]
        per_rank[str(rank)] = {
            "count": len(sub),
            "cote": mk([float(p["cote_pmu"]) for p in sub if p.get("cote_pmu") is not None]),
            "age": mk([int(p["age"]) for p in sub if p.get("age") is not None]),
        }
    couple_details = {}
    for ckey, lst in couple_stats.items():
        fam_pair = Counter(f"{x['fam_a']}-{x['fam_b']}" for x in lst).most_common(1)[0][0] if lst else "UNK"

        def avg_gap(field):
            gs = [x[field] for x in lst if x[field] is not None]
            return round(statistics.mean(gs), 2) if gs else None

        couple_details[ckey] = {
            "count": len(lst),
            "freq": len(lst),
            "top_fam_pair": fam_pair,
            "avg_poids_gap": avg_gap("poids_gap"),
            "avg_valeur_gap": avg_gap("valeur_gap"),
            "avg_age_gap": avg_gap("age_gap"),
            "avg_cote_gap": avg_gap("cote_gap"),
            "avg_corde_gap": avg_gap("corde_gap"),
        }
    data = {
        "version": "v3",
        "total_petites_races": len(race_ids),
        # Transparency (point 6): counters below are computed on the KEPT
        # signatures only (most recent first), which may be fewer than
        # total_petites_races when capped by MAX_SIGNATURES.
        "signatures_kept": len(top3_signatures),
        "signatures_capped": len(race_ids) > MAX_SIGNATURES,
        "max_signatures": MAX_SIGNATURES,
        "total_top3_races": n_top3_races,
        "top3_signatures": top3_signatures,
        "fam_triple_counter": fam_triple_counter,
        "fam_triple_coarse_counter": fam_triple_coarse_counter,
        "full_pattern_counter": full_pattern_counter,
        "pattern_groups": pattern_groups,
        "fam_groups": fam_groups,
        "coarse_groups": coarse_groups,
        "rel_distributions": rel_distributions,
        "rel_coarse_distributions": rel_coarse_distributions,
        "cote": mk([float(p.get("cote_pmu")) for p in all_top3 if p.get("cote_pmu") is not None]),
        "age": mk([int(p.get("age")) for p in all_top3 if p.get("age") is not None]),
        "poids": mk(poids_vals),
        "per_rank": per_rank,
        "couple_details": couple_details,
        "couple_counter": {k: len(v) for k, v in couple_stats.items()},
        "sample_profiles": [dict(p) for p in all_top3[:8]],
        "total_top3": len(all_top3),
    }
    with _CACHE_LOCK:
        _CACHE[key] = {"data": data, "ts": now}
    return data


def _profile_deviation(cand_profiles, group_med_prof):
    """Unitless deviation of a candidate's profiles vs the pattern medians.
    Skipped fields contribute 0 (documented, no invented weights)."""
    dev = 0.0
    for cprof, mprof in zip(cand_profiles, group_med_prof):
        for field in ("cote", "poids", "valeur"):
            cv = cprof.get(field)
            mv = (mprof or {}).get(field)
            if cv is None or mv in (None, 0):
                continue
            try:
                dev += abs(float(cv) - float(mv)) / abs(float(mv))
            except Exception:
                continue
    return dev


def _ranked_candidates(cotes, rank_map, score_candidate, fam_of):
    """All ordered Top3 candidates, sorted best-first.

    Each entry carries the full ranking tuple plus transparency fields
    (nums, pattern, support, level, deviations). Used by
    match_small_couple (takes #1) and by explain_candidates (#1..N)."""
    import itertools
    # order: level desc, support desc, rank_dev asc, prof_dev asc, rel_freq desc
    scored = []
    for triple in itertools.permutations([p for _, p in cotes], 3):
        s = score_candidate(triple)
        if s is None:
            continue  # pattern never recurred: not a DNA pattern
        support, level, neg_rank, neg_prof, relf = s
        scored.append({
            "support": support,
            "level": ("full" if level == 2 else "exact" if level == 1 else "coarse"),
            "level_num": level,
            "rank_dev": round(-neg_rank, 3),
            "prof_dev": round(-neg_prof, 4),
            "rel_freq": round(relf, 4),
            "pattern": "-".join(fam_of(p) for p in triple),
            "nums": [p.get("num") for p in triple],
            "triple": triple,
            "_sort": (-level, -support, -neg_rank, -neg_prof, -relf),
        })
    scored.sort(key=lambda e: e["_sort"])
    for e in scored:
        del e["_sort"]
    return scored


def explain_candidates(participants: List[Dict], hist: Dict, top_n: int = 3) -> List[Dict]:
    """Top-N ranked candidate Top3s with WHY they rank there.

    Lets testers distinguish: DNA missing ([]) vs wrong pattern chosen
    (right pattern lower) vs right pattern but different horses
    (same pattern, other nums ranked below)."""
    built = _build_match_context(participants, hist)
    if built is None:
        return []
    cotes, rank_map, score_candidate, fam_of = built
    out = []
    for e in _ranked_candidates(cotes, rank_map, score_candidate, fam_of)[:max(1, top_n)]:
        out.append({k: v for k, v in e.items() if k != "triple"})
    return out


def _build_match_context(participants: List[Dict], hist: Dict):
    """Shared setup for match_small_couple / explain_candidates.

    Returns (cotes, rank_map, score_candidate, fam_of) or None when
    matching is impossible (too few priced horses or empty history)."""
    # TRUE market rank over the whole current field (unchanged from V2).
    cotes = []
    for p in participants:
        if str(p.get("rang")) == "NP" or str(p.get("etat")) == "NP":
            continue
        c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
        try:
            v = float(c)
        except Exception:
            continue
        cotes.append((v, p))
    if len(cotes) < 3:
        return None
    cotes.sort(key=lambda x: x[0])
    rank_map = {p.get("num"): idx + 1 for idx, (v, p) in enumerate(cotes)}
    for p in participants:
        if p.get("num") not in rank_map:
            rank_map[p.get("num")] = 99

    groups = hist.get("pattern_groups") or {}
    fam_groups = hist.get("fam_groups") or {}
    coarse_groups = hist.get("coarse_groups") or {}
    if not groups and not fam_groups:
        return None

    def fam_of(p):
        c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
        return _market_family(c)

    def cand_profiles(triple):
        return [{"cote": _norm_cote(p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")),
                 "poids": _norm_poids(p.get("poids")),
                 "valeur": p.get("valeur")} for p in triple]

    def coherence(triple, ranks, cfams, g, coarse):
        """Coherence WITHIN one pattern group: rank/profile deviation +
        relation frequency. Returns (-rank_dev, -prof_dev, rel_freq)."""
        med = g.get("med_ranks") or [None, None, None]
        rank_dev = sum(abs(a - b) for a, b in zip(ranks, med)) if all(
            m is not None for m in med) else float("inf")
        prof_dev = _profile_deviation(cand_profiles(triple), g.get("med_prof") or [])
        rel_freq = 0.0
        for rel, (i, j) in zip(("P1-P2", "P1-P3", "P2-P3"), ((0, 1), (0, 2), (1, 2))):
            if coarse:
                a, b = _coarse(cfams[i]), _coarse(cfams[j])
                dist = (g.get("rel_coarse_dists") or {}).get(rel) or {}
            else:
                a, b = cfams[i], cfams[j]
                dist = (g.get("rel_dists") or {}).get(rel) or {}
            tot = sum(dist.values()) or 1
            rel_freq += dist.get(f"{a}-{b}", 0) / tot
        return (-rank_dev, -prof_dev, rel_freq)

    def score_candidate(triple):
        """Ranking tuple: (level, support, -rank_dev, -prof_dev, rel_freq).

        Level FIRST (full=2 > exact=1 > coarse=0): support is only
        comparable within the same granularity. Coherence is measured
        WITHIN the same pattern group, never globally."""
        cfams = [fam_of(p) for p in triple]
        ranks = [rank_map.get(p.get("num"), 99) for p in triple]
        fkey = "-".join(cfams)
        rkey = "-".join(str(r) for r in ranks)
        ckey = "-".join(_coarse(f) for f in cfams)
        # Level 2: the COMPLETE pattern recurred.
        g = groups.get(fkey + "|" + rkey)
        if g and g["n"] > 0:
            rd, pd, rf = coherence(triple, ranks, cfams, g, False)
            return (g["n"], 2, rd, pd, rf)
        # Level 1: fam triple recurred.
        gf = fam_groups.get(fkey)
        if gf and gf["n"] > 0:
            rd, pd, rf = coherence(triple, ranks, cfams, gf, False)
            return (gf["n"], 1, rd, pd, rf)
        # Level 0: coarse fam triple recurred.
        gc = coarse_groups.get(ckey)
        if gc and gc["n"] > 0:
            rd, pd, rf = coherence(triple, ranks, cfams, gc, True)
            return (gc["n"], 0, rd, pd, rf)
        return None

    return cotes, rank_map, score_candidate, fam_of


def _red_km_of(p: Dict):
    """Best-effort red_km (record time, lower = faster) across payload variants."""
    for k in ("red_km", "redKm", "record_km", "recordKm", "red"):
        v = p.get(k)
        if v is None:
            continue
        try:
            s = str(v).strip()
            if not s:
                continue
            f = float(s)
            if f > 0:
                return f
        except Exception:
            continue
    return None


def match_small_couple(participants: List[Dict], hist: Dict) -> List[Dict]:
    built = _build_match_context(participants, hist)
    if built is None:
        return []
    cotes, rank_map, score_candidate, fam_of = built
    # Every possible ordered Top3, scored as ONE coherent pattern.
    ranked = _ranked_candidates(cotes, rank_map, score_candidate, fam_of)
    if not ranked:
        return []
    best = ranked[0]

    (p1, p2, p3) = best["triple"]
    # P2 override: 2nd-fastest red_km wins P2 at 31% alone (test 7b, n=175:
    # ordre 8.0% -> 35.4%, desordre 14.3% -> 49.1%). Falls back to engine
    # triple when red_km data is missing (<2 timed horses) or clashes.
    try:
        reds = sorted(
            (( _red_km_of(p), p) for _, p in cotes if _red_km_of(p) is not None),
            key=lambda t: (t[0], (t[1].get("num") or 999)))
        if len(reds) >= 2:
            r2 = reds[1][1]
            if (r2.get("num") == p1.get("num")) and len(reds) >= 1:
                r2 = reds[0][1]
            nums = {p1.get("num"), p3.get("num")}
            if r2.get("num") not in nums:
                p2 = r2
    except Exception:
        pass
    support = best["support"]
    level = best["level_num"]
    results = []
    for rel, (pa, pb) in (("P1-P2", (p1, p2)), ("P1-P3", (p1, p3)), ("P2-P3", (p2, p3))):
        fa, fb = fam_of(pa), fam_of(pb)
        ra, rb = rank_map.get(pa.get("num"), 99), rank_map.get(pb.get("num"), 99)
        results.append({
            "type": "Couple", "key": rel, "sub_key": f"{fa}-{fb}",
            "horses": [
                {"num": pa.get("num"), "horse": pa.get("horse"),
                 "market_rank": ra, "fam": fa},
                {"num": pb.get("num"), "horse": pb.get("horse"),
                 "market_rank": rb, "fam": fb},
            ],
            # score = historical support of the whole Top3 pattern (transparent).
            "score": support, "count": support,
            "details": {"pattern_support": support,
                        "level": ("full" if level == 2 else "exact" if level == 1 else "coarse"),
                        "pattern": "-".join(fam_of(p) for p in (p1, p2, p3))},
        })
    return results
