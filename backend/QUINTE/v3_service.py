"""ALFARAJ V3 DIAGNOSTIC — pattern-first Top3 (V2 untouched).

V2 gap (verified): current race is market-defined, targets are per-position
marginals (_vote_targets), assignment is greedy. V3 instead:

  HISTORICAL RACES -> COMPLETE TOP3 (joint family+fine triples, counted whole)
        -> current race enters WITHOUT market (context filter only)
        -> candidate triples scored JOINTLY (support first, intrinsic fit,
           market rank tiebreak ONLY)
        -> P1/P2/P3 assigned from the winning triple, never before.
"""
import itertools
import math
import threading
from collections import Counter
from database import get_db
from QUINTE.service import (
    _get_quinte_race_ids, _fetch_in_chunks, _market_layer, _layer_family,
    get_brave_archetypes, _brave_distance, _horse_intrinsic, _is_out,
)

_JOINT_CACHE = {}
_JOINT_LOCK = threading.Lock()
_JOINT_TTL = 3600


def get_joint_top3(limit=4054, before=None, disc=None, hippodrome=None,
                   distance=None, runners=None, min_count=3):
    """Joint (L1,L2,L3) counts — whole triples, never marginals."""
    import time
    key = ("v3joint", limit, before or "all", disc or "ALL", hippodrome or "ALL",
           distance or 0, runners or 0, min_count)
    now = time.time()
    with _JOINT_LOCK:
        if key in _JOINT_CACHE and now - _JOINT_CACHE[key]["ts"] < _JOINT_TTL:
            d = _JOINT_CACHE[key]["data"]
            return d[0], d[1]
    race_ids5, _ = _get_quinte_race_ids(limit=limit, before=before, disc=disc,
                                        hippodrome=hippodrome, distance=distance,
                                        runners=runners)
    if not race_ids5:
        return Counter(), {}
    conn = get_db()
    try:
        rows = _fetch_in_chunks(
            conn,
            "SELECT p.race_id, p.rang, p.cote_pmu FROM participants p "
            "WHERE p.race_id IN ({ph}) AND p.rang BETWEEN 1 AND 3 AND p.cote_pmu IS NOT NULL",
            race_ids5)
    finally:
        conn.close()
    by_race = {}
    for r in rows:
        try:
            by_race.setdefault(r["race_id"], {})[int(r["rang"])] = float(r["cote_pmu"])
        except (TypeError, ValueError, KeyError):
            continue
    fam_counter = Counter()
    fine_map = {}
    for rid, d in by_race.items():
        if not all(k in d for k in (1, 2, 3)):
            continue
        layers = [_market_layer(d[k]) for k in (1, 2, 3)]
        fams = tuple(_layer_family(L) for L in layers)
        fam_counter[fams] += 1
        fine_map.setdefault(fams, Counter())[tuple(layers)] += 1
    fam_counter = Counter({k: v for k, v in fam_counter.items() if v >= min_count})
    fine_map = {k: v for k, v in fine_map.items() if k in fam_counter}
    with _JOINT_LOCK:
        _JOINT_CACHE[key] = {"data": (fam_counter, fine_map), "ts": time.time()}
    return fam_counter, fine_map


def _intrinsic_fit(h, arch, selected, pos):
    r = _brave_distance(h, (arch.get("archetypes", {}) or {}).get(pos, {}), selected)
    return r[0] if r is not None else None


def v3_trio(participants, before=None, disc=None, distance=None, runners=None,
            top_pat=40):
    """Returns (trio, meta): trio = [P1, P2, P3 dicts] from ONE winning triple."""
    from database import get_db as _gdb
    valid = []
    for p in participants or []:
        if _is_out(p):
            continue
        c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
        try:
            if c is None or str(c).strip() == "" or float(c) <= 0:
                continue
        except (TypeError, ValueError, AttributeError):
            continue
        valid.append(p)
    if len(valid) < 5:
        return [], {"reason": "field<5"}
    fam_counter, fine_map = get_joint_top3(before=before, disc=disc,
                                           distance=distance, runners=runners)
    if not fam_counter:
        return [], {"reason": "no-joint-support"}
    try:
        _arch_full = get_brave_archetypes(disc=disc)
        _arch = _arch_full.get("archetypes", {})
        _sel = list(_arch_full.get("selected_features", {}).keys())
    except Exception:
        _arch, _sel = {}, []
    intrinsic = {}
    for p in valid:
        try:
            intrinsic[p.get("num")] = _horse_intrinsic(p)
        except Exception:
            intrinsic[p.get("num")] = {}
    layers_of = {}
    for p in valid:
        c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
        layers_of[p.get("num")] = _market_layer(c)
    rank_map = {}
    for i, p in enumerate(sorted(valid, key=lambda p: (float(p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")), p.get("num", 999)))):
        rank_map[p.get("num")] = i + 1
    best = None
    for famtrip, cnt in fam_counter.most_common(top_pat):
        # market compatibility ONLY (required slot family), never ranking
        for perm in itertools.permutations(valid, 3):
            ok = True
            for idx, p in enumerate(perm):
                if _layer_family(layers_of[p.get("num")]) != famtrip[idx]:
                    ok = False
                    break
            if not ok:
                continue
            fds = []
            for idx, p in enumerate(perm):
                fd = _intrinsic_fit(intrinsic.get(p.get("num"), {}), {"archetypes": _arch},
                                    _sel, str(idx + 1))
                fds.append(fd if fd is not None else 9.0)
            key = (math.log10(cnt + 1), -sum(fds) / 3.0,
                   -sum(rank_map.get(p.get("num"), 99) for p in perm))
            if best is None or key > best[0]:
                best = (key, perm, famtrip, cnt, fds)
    if best is None:
        return [], {"reason": "no-compatible-triple"}
    _, perm, famtrip, cnt, fds = best
    trio = []
    for idx, p in enumerate(perm):
        c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
        try:
            cote_f = float(c)
        except (TypeError, ValueError):
            cote_f = c
        trio.append({"num": p.get("num"), "horse": p.get("horse"), "cote": cote_f,
                     "market_rank": rank_map.get(p.get("num")), "target_pos": idx + 1,
                     "layer": layers_of[p.get("num")], "target_family": famtrip[idx],
                     "score": round(math.log10(cnt + 1), 3), "form_ecart": fds[idx],
                     "pattern": " → ".join(famtrip), "support": cnt,
                     "reasons": ["joint %s (%d×)" % (" → ".join(famtrip), cnt)]})
    return trio, {"pattern": " → ".join(famtrip), "support": cnt}
