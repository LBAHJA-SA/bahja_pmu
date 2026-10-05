"""
ALFARAJ V2 — Race DNA first, Market lens second, no forced favorite protection.

Methodology:
  Layer A (RACE DNA): historical P1..P5 structure is kept separate from
      the market lens. The market is used only as a secondary constraint.
  Layer B (FINISHER DNA): per-position archetype over enriched horse
      profile (form + valeur/poids/age/corde/gain/distance/track). No cote.
  Layer C (CONTRADICTION): disabled as a forced outsider mechanism.
  Layer D (SELECTION): historical target + existing Finisher tiebreak.
      No protected favorites and no forced OUT/TOC slot.
"""
from typing import Any, Dict, List
import time
import threading
import math
from collections import Counter, defaultdict
from database import get_db
from signals.plot_signals import compute_field_plot, plot_bonus_for_quinte, trap_of_fav

ODDS_LAYER_BOUNDS = [
    ("FAV1", 0, 3.0),
    ("FAV2", 3.1, 7.0),
    ("FAV3", 7.1, 10.0),
    ("OUT1", 10.1, 13.0),
    ("OUT2", 13.1, 16.0),
    ("OUT3", 16.1, 18.0),
    ("TOC1", 18.1, 21.0),
    ("TOC2", 21.1, 25.0),
    ("TOC3", 25.1, 28.0),
    ("TOC4", 28.1, 31),
    ("TOC5", 31.1, 36),
    ("TOC6", 36.1, 40),
    ("TOC7", 40.1, 50),
    ("TOC8", 50.1, 100),
]

_CACHE = {}
_CACHE_LOCK = threading.Lock()
_CACHE_TTL = 3600


def _market_layer(cote: Any) -> str:
    """Odds -> market layer via ODDS_LAYER_BOUNDS (ordered upper bounds).

    Odds-only by design; market rank is kept separately (market_rank field),
    not folded into the layer.
    """
    try:
        v = float(cote)
    except (TypeError, ValueError):
        return "UNK"
    if v <= 0:
        return "UNK"
    for label, _lo, hi in ODDS_LAYER_BOUNDS:
        if v <= float(hi):
            return label
    return ODDS_LAYER_BOUNDS[-1][0]


def _layer_family(layer: str) -> str:
    if not layer:
        return "UNK"
    if layer.startswith("FAV"):
        return "FAV"
    if layer.startswith("OUT"):
        return "OUT"
    if layer.startswith("TOC"):
        return "TOC"
    return layer


_LAYER_ORDER = [label for label, _lo, _hi in ODDS_LAYER_BOUNDS]


def _layer_distance(a: str, b: str) -> int:
    """Distance between two layers on the ordered odds scale."""
    try:
        return abs(_LAYER_ORDER.index(a) - _LAYER_ORDER.index(b))
    except ValueError:
        return 99


def _distance_score(dist: int) -> int:
    if dist == 0:
        return 10
    if dist == 1:
        return 7
    if dist == 2:
        return 4
    return 1


FORM_TIEBREAK_MIN = 0.3

_NP_VALUES = {"NP", "NON PARTANT", "NON-PARTANT", "NON_PARTANT", "NONPARTANT",
              "FORFAIT", "RETIRE", "RETIRÉ", "SCRATCHED", "OUT", "ABSENT"}


def _is_out(p: Dict) -> bool:
    """Non-runner guard across payload variants (PMU/Geny/archive)."""
    if str(p.get("rang")) == "NP":
        return True
    for k in ("etat", "statut", "status"):
        v = p.get(k)
        if isinstance(v, str) and v.strip().upper() in _NP_VALUES:
            return True
    for k in ("nonPartant", "non_partant", "forfait", "retire"):
        if p.get(k) is True:
            return True
    return False


def _valid_cotes(participants: List[Dict]) -> List[tuple]:
    """[(cote_float, participant)] sorted ascending, NP excluded."""
    out = []
    for p in participants:
        if _is_out(p):
            continue
        c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
        try:
            if c is None or str(c).strip() == "":
                continue
            v = float(c)
            if v <= 0:
                continue
        except (TypeError, ValueError, AttributeError):
            continue
        out.append((v, p))
    out.sort(key=lambda x: x[0])
    return out


def _fetch_in_chunks(conn, sql_prefix: str, ids: List[Any], chunk: int = 1000) -> List:
    """Big IN-lists defeat the index (7.8s for 4000 ids); chunks stay fast."""
    rows = []
    for i in range(0, len(ids), chunk):
        part = ids[i:i + chunk]
        ph = ",".join("?" * len(part))
        rows.extend(conn.execute(sql_prefix.format(ph=ph), part).fetchall())
    return rows


def _get_quinte_race_ids(limit: int = 4054, before: str = None,
                         disc: str = None, hippodrome: str = None,
                         distance: int = None, runners: int = None) -> List[Any]:
    """Global / discipline / hippodrome + optional shape (distance/runners)."""
    from database import hippodrome_in_clause
    conn = get_db()
    where_disc = ""
    params_disc: List[Any] = []
    if disc:
        d = str(disc).strip().upper()
        if d in ("TROT", "GALOP"):
            where_disc = " AND disc_canonical IN (%s)" % ",".join("?" * (2 if d == "TROT" else 4))
            params_disc = ["ATTELE", "MONTE"] if d == "TROT" else ["PLAT", "HAIE", "STEEPLE", "CROSS"]
        elif d in ("ATTELE", "MONTE", "PLAT", "HAIE", "STEEPLE", "CROSS"):
            where_disc = " AND disc_canonical=?"
            params_disc = [d]
    where_hip = ""
    params_hip: List[Any] = []
    if hippodrome:
        hclause, hparams = hippodrome_in_clause(conn, "hippodrome", hippodrome)
        if hclause != "1=1":
            where_hip = " AND (%s)" % hclause
            params_hip = hparams
    where_shape = ""
    params_shape: List[Any] = []
    if distance:
        try:
            where_shape += " AND ABS(distance - ?) <= 200"
            params_shape.append(int(distance))
        except (TypeError, ValueError):
            pass
    if runners:
        try:
            where_shape += " AND ABS(runners - ?) <= 2"
            params_shape.append(int(runners))
        except (TypeError, ValueError):
            pass
    if before:
        rows = conn.execute(
            "SELECT race_id FROM races WHERE quinte=1 AND date < ?" + where_disc + where_hip + where_shape + " ORDER BY date DESC LIMIT ?",
            (before, *params_disc, *params_hip, *params_shape, limit * 2,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT race_id FROM races WHERE quinte=1" + where_disc + where_hip + where_shape + " ORDER BY date DESC LIMIT ?",
            (*params_disc, *params_hip, *params_shape, limit * 2,),
        ).fetchall()
    conn.close()
    candidates = [r["race_id"] for r in rows]
    conn = get_db()
    complete5 = set()
    complete7 = set()
    for i in range(0, len(candidates), 2000):
        chunk = candidates[i:i + 2000]
        ph = ",".join("?" * len(chunk))
        rows = conn.execute(
            f"SELECT race_id FROM participants WHERE race_id IN ({ph}) "
            f"AND rang BETWEEN 1 AND 5 AND cote_pmu IS NOT NULL "
            f"GROUP BY race_id HAVING COUNT(*) = 5",
            chunk,
        ).fetchall()
        complete5.update(r["race_id"] for r in rows)
        rows7 = conn.execute(
            f"SELECT race_id FROM participants WHERE race_id IN ({ph}) "
            f"AND rang BETWEEN 1 AND 7 AND cote_pmu IS NOT NULL "
            f"GROUP BY race_id HAVING COUNT(*) = 7",
            chunk,
        ).fetchall()
        complete7.update(r["race_id"] for r in rows7)
    conn.close()
    # preserve date-DESC order, cap at limit
    valid5 = [rid for rid in candidates if rid in complete5][:limit]
    valid7 = [rid for rid in candidates if rid in complete7][:limit]
    return valid5, valid7


def get_quinte_top5_stats(hippodrome: str = None, limit: int = 4054,
                          before: str = None, disc: str = None,
                          distance: int = None, runners: int = None) -> Dict:
    """Phase A — global / discipline / hippodrome + shape Race DNA.

    Tries hippodrome+shape first; if <80, relaxes shape, then hippodrome.
    """
    key = f"alfaraj_race_dna_global_v7_{limit}_{before or 'all'}_{disc or 'ALL'}_{hippodrome or 'ALL'}_{distance or 0}_{runners or 0}"
    now = time.time()
    with _CACHE_LOCK:
        if key in _CACHE and now - _CACHE[key]["ts"] < _CACHE_TTL:
            data = dict(_CACHE[key]["data"])
            data["requested_hippodrome"] = hippodrome
            return data
    # try hippodrome+shape first, fall back stepwise if thin (<80)
    shape_tried = False
    if hippodrome and (distance or runners):
        shape_tried = True
        hip_ids5, hip_ids7 = _get_quinte_race_ids(limit=limit, before=before, disc=disc,
                                                  hippodrome=hippodrome, distance=distance, runners=runners)
        if len(hip_ids5) >= 80:
            race_ids5, race_ids7 = hip_ids5, hip_ids7
            hip_used = hippodrome
            shape_used = True
        else:
            # relax shape, keep hippodrome
            hip_ids5, hip_ids7 = _get_quinte_race_ids(limit=limit, before=before, disc=disc, hippodrome=hippodrome)
            if len(hip_ids5) >= 80:
                race_ids5, race_ids7 = hip_ids5, hip_ids7
                hip_used = hippodrome
                shape_used = False
            else:
                race_ids5, race_ids7 = _get_quinte_race_ids(limit=limit, before=before, disc=disc)
                hip_used = None
                shape_used = False
    elif hippodrome:
        hip_ids5, hip_ids7 = _get_quinte_race_ids(limit=limit, before=before, disc=disc, hippodrome=hippodrome)
        if len(hip_ids5) >= 80:
            race_ids5, race_ids7 = hip_ids5, hip_ids7
            hip_used = hippodrome
        else:
            race_ids5, race_ids7 = _get_quinte_race_ids(limit=limit, before=before, disc=disc)
            hip_used = None
        shape_used = False
        shape_tried = False
    else:
        race_ids5, race_ids7 = _get_quinte_race_ids(limit=limit, before=before, disc=disc)
        hip_used = None
        shape_used = False
    race_ids = race_ids5
    if not race_ids:
        data = {
            "scope": "global",
            "requested_hippodrome": hippodrome,
            "total_quinte_races": 0,
            "total_top5_races": 0,
            "race_dna_counter": {},
            "per_rank": {},
        }
        with _CACHE_LOCK:
            _CACHE[key] = {"data": data, "ts": now}
        return dict(data)
    conn = get_db()
    rows = _fetch_in_chunks(
        conn,
        "SELECT p.race_id, p.rang, p.cote_pmu, p.num, p.horse, p.musique "
        "FROM participants p WHERE p.race_id IN ({ph}) "
        "AND p.rang BETWEEN 1 AND 5 AND p.cote_pmu IS NOT NULL",
        race_ids,
    )
    # complement Top7: P6/P7 when available
    rows7 = _fetch_in_chunks(
        conn,
        "SELECT p.race_id, p.rang, p.cote_pmu, p.num, p.horse, p.musique "
        "FROM participants p WHERE p.race_id IN ({ph}) "
        "AND p.rang BETWEEN 6 AND 7 AND p.cote_pmu IS NOT NULL",
        race_ids,
    ) if race_ids7 else []
    conn.close()
    by_race = defaultdict(list)
    for r in rows:
        by_race[r["race_id"]].append(dict(r))
    race_dna_counter = Counter()
    # Diagnostic market composition only. This is NOT the Race DNA.
    # It records how many FAV (<7) actually occupied P1..P5 historically.
    fav_count_counter = Counter()
    per_rank_layers = defaultdict(list)
    for rid, parts in by_race.items():
        by_rang = {p["rang"]: p for p in parts}
        if not all(k in by_rang for k in (1, 2, 3, 4, 5)):
            continue
        # market rank of each finisher among the 5 finishers by cote
        fin_sorted = sorted(parts, key=lambda x: float(x["cote_pmu"]))
        _rank_map = {p["num"]: idx + 1 for idx, p in enumerate(fin_sorted)}
        layers = []
        fav_count = 0
        for pos in [1, 2, 3, 4, 5]:
            p = by_rang[pos]
            layer = _market_layer(p["cote_pmu"])
            if _layer_family(layer) == "FAV":
                fav_count += 1
            layers.append(layer)
            per_rank_layers[str(pos)].append(layer)
        race_dna_counter[" → ".join(layers)] += 1
        fav_count_counter[fav_count] += 1
    per_rank = {}
    for pos in ["1", "2", "3", "4", "5"]:
        cnt = Counter(per_rank_layers[pos])
        most = cnt.most_common(5)
        per_rank[pos] = {
            "counter": dict(cnt),
            "most": most,
            "top_layer": most[0][0] if most else "—",
            "count": len(per_rank_layers[pos]),
        }
    most_race_dna = race_dna_counter.most_common(12)
    fam_counter: Counter = Counter()
    for sig, cnt in race_dna_counter.items():
        try:
            fam = " → ".join(_layer_family(s.strip()) for s in str(sig).split("→"))
        except ValueError:
            continue
        fam_counter[fam] += cnt
    fam_top = fam_counter.most_common(12)
    # Top7 complement
    by_race7 = defaultdict(list)
    for r in rows7:
        by_race7[r["race_id"]].append(dict(r))
    per_rank_67 = defaultdict(list)
    for rid, parts in by_race7.items():
        by_r = {p["rang"]: p for p in parts}
        for pos in (6, 7):
            if pos in by_r:
                per_rank_67[str(pos)].append(_market_layer(by_r[pos]["cote_pmu"]))
    per_rank7 = {}
    for pos in ("6", "7"):
        cnt = Counter(per_rank_67[pos])
        most = cnt.most_common(5)
        per_rank7[str(pos)] = {"counter": dict(cnt), "most": most,
                               "top_layer": most[0][0] if most else "—",
                               "count": len(per_rank_67[pos])}
    data = {
        "scope": "hippodrome+shape" if locals().get("shape_used") else ("hippodrome" if 'hip_used' in locals() and hip_used else ("disc:%s" % disc if disc else "global")),
        "requested_hippodrome": hippodrome,
        "used_hippodrome": locals().get("hip_used"),
        "shape_used": locals().get("shape_used", False),
        "total_quinte_races": len(race_ids),
        "total_top5_races": len(by_race),
        "total_top7_races": len(race_ids7),
        # FULL distribution for similarity search (display uses race_dna_top)
        "race_dna_counter": {str(k): int(v) for k, v in race_dna_counter.items()},
        "race_dna_top": [[k, v] for k, v in most_race_dna],
        "n_signatures": len(race_dna_counter),
        # family level (<=243 combos): support counts for pattern selection
        "family_counter": {str(k): int(v) for k, v in fam_counter.items()},
        "family_top": [[k, v] for k, v in fam_top],
        "race_dna_most": most_race_dna[0] if most_race_dna else ("—", 0),
        # Market composition diagnostic. Used only to prevent the selector
        # from blindly placing too many favorites when history does not support it.
        "fav_count_distribution": {str(k): int(v) for k, v in sorted(fav_count_counter.items())},
        "fav_count_mode": (max(fav_count_counter.items(), key=lambda x: (x[1], -x[0]))[0]
                           if fav_count_counter else None),
        "per_rank": per_rank,
        "per_rank67": per_rank7,
        "limit_requested": limit,
        "limit_effective": len(race_ids),
    }
    with _CACHE_LOCK:
        _CACHE[key] = {"data": data, "ts": now}
    return dict(data)


def current_market_dna(participants: List[Dict], k: int = 5) -> Dict:
    """Phase B — market DNA of the current race: layers of the k favorites."""
    cotes = _valid_cotes(participants)
    favs = cotes[:k]
    layers = [_market_layer(v) for v, _p in favs]
    horses = [
        {
            "num": p.get("num"),
            "horse": p.get("horse"),
            "cote": v,
            "market_rank": idx + 1,
            "layer": _market_layer(v),
        }
        for idx, (v, p) in enumerate(favs)
    ]
    return {
        "dna": " → ".join(layers) if layers else "—",
        "layers": layers,
        "horses": horses,
        "n_valid_cotes": len(cotes),
    }


def _form_runs(musique: Any) -> List[int]:
    """Recent finish ranks, newest first, parsed from musique."""
    if not musique:
        return []
    s = str(musique)
    rangs = []
    buf = ""
    parts = []
    for c in s:
        if c in ("a", "p", "m"):
            if buf:
                parts.append(buf + c)
            buf = ""
        elif c == "(":
            if buf:
                parts.append(buf)
            buf = "("
        elif c == ")":
            buf += c
            parts.append(buf)
            buf = ""
        else:
            buf += c
    if buf:
        parts.append(buf)
    for m in parts:
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
    return rangs


def _form_avg(musique: Any) -> Any:
    """Average finish rank over the last 3 runs (lower = sharper)."""
    rangs = _form_runs(musique)
    if not rangs:
        return None
    sel = rangs[:3]
    return sum(sel) / len(sel)


def _clean_poids(v: Any) -> Any:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f > 200:
        f /= 10.0
    if not (30 <= f <= 80):
        return None
    return f


def _clean_valeur(v: Any) -> Any:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not (0 < f < 120):
        return None
    return f


def _clean_age(v: Any) -> Any:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if not (2 <= f <= 15):
        return None
    return f


def _clean_corde(v: Any) -> Any:
    try:
        return int(float(v))
    except (TypeError, ValueError):
        return None


def _clean_gain_log(v: Any) -> Any:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f < 0:
        return None
    return math.log10(f + 1)


_BRAVE_CANDIDATES = ["form_avg", "form_trend", "top3_4", "last_rank",
                     "valeur", "poids", "age", "gain_log"]
_BRAVE_SEP_MIN = 0.12
_BRAVE_N_MIN = 20


def _form_features(musique: Any) -> Dict[str, Any]:
    """Form-only fingerprint signals. Lower rank numbers = better."""
    rangs = _form_runs(musique)
    if not rangs:
        return {"form_avg": None, "form_trend": None, "top3_4": None, "last_rank": None}
    avg = sum(rangs[:3]) / len(rangs[:3])
    if len(rangs) >= 3:
        trend = rangs[0] - (sum(rangs[1:3]) / 2.0)  # negative = improving
    else:
        trend = None
    return {
        "form_avg": avg,
        "form_trend": trend,
        "top3_4": sum(1 for r in rangs[:4] if r <= 3),
        "last_rank": rangs[0],
    }


def _horse_intrinsic(p: Dict) -> Dict:
    """Enriched Finisher DNA: form + valeur/poids/age/gain/corde (weighted by separation)."""
    base = _form_features(p.get("musique"))
    base["valeur"] = _clean_valeur(p.get("valeur"))
    base["poids"] = _clean_poids(p.get("poids"))
    base["age"] = _clean_age(p.get("age"))
    base["gain_log"] = _clean_gain_log(p.get("gain"))
    base["corde"] = _clean_corde(p.get("corde"))
    return base


def _separation(per_pos: Dict[str, Dict[str, List]], feat: str) -> Any:
    stats = {}
    for pos in ["1", "2", "3", "4", "5"]:
        vals = per_pos[pos][feat]
        if len(vals) < _BRAVE_N_MIN:
            return None
        mean = sum(vals) / len(vals)
        var = sum((v - mean) ** 2 for v in vals) / len(vals)
        stats[pos] = (mean, max(math.sqrt(var), 0.2), len(vals))
    means = [stats[p][0] for p in stats]
    avg_std = sum(stats[p][1] for p in stats) / len(stats)
    if avg_std <= 0:
        return None
    return round((max(means) - min(means)) / avg_std, 3), stats


def get_brave_archetypes(limit: int = 4054, before: str = None, disc: str = None) -> Dict:
    """Market-blind archetypes of P1..P5 finishers, all Quinte.

    Only features that actually separate positions (separation >= 0.12,
    n>=20) are kept. No cote enters this table. Cached 1h.
    """
    key = f"alfaraj_brave_arch_v3_{limit}_{before or 'all'}_{disc or 'ALL'}"
    now = time.time()
    with _CACHE_LOCK:
        if key in _CACHE and now - _CACHE[key]["ts"] < _CACHE_TTL:
            return _CACHE[key]["data"]
    race_ids5, _ = _get_quinte_race_ids(limit=limit, before=before, disc=disc)
    race_ids = race_ids5
    per_pos: Dict[str, Dict[str, List]] = {str(i): defaultdict(list) for i in range(1, 6)}
    if race_ids:
        conn = get_db()
        rows = _fetch_in_chunks(
            conn,
            "SELECT p.rang, p.musique, p.valeur, p.poids, p.age, p.gain, p.corde FROM participants p "
            "WHERE p.race_id IN ({ph}) AND p.rang BETWEEN 1 AND 5",
            race_ids,
        )
        conn.close()
        for r in rows:
            pos = str(r["rang"])
            if pos not in per_pos:
                continue
            h = _horse_intrinsic(dict(r))
            for feat in _BRAVE_CANDIDATES:
                if h[feat] is not None:
                    per_pos[pos][feat].append(h[feat])
    selected = {}
    arch = {}
    for feat in _BRAVE_CANDIDATES:
        res = _separation(per_pos, feat)
        if res is None:
            continue
        sep, stats = res
        if sep >= _BRAVE_SEP_MIN:
            selected[feat] = sep
    for pos in ["1", "2", "3", "4", "5"]:
        feats = {}
        for feat in selected:
            vals = per_pos[pos][feat]
            mean = sum(vals) / len(vals)
            var = sum((v - mean) ** 2 for v in vals) / len(vals)
            std = max(math.sqrt(var), 0.2)
            feats[feat] = {"mean": round(mean, 2), "std": round(std, 3), "n": len(vals)}
        arch[pos] = {"features": feats}
    data = {"scope": "global-tranche", "market_blind": True,
            "total_quinte_races": len(race_ids),
            "selected_features": selected, "archetypes": arch}
    with _CACHE_LOCK:
        _CACHE[key] = {"data": data, "ts": now}
    return data


def _brave_distance(h: Dict, arch_pos: Dict, selected: List[str]) -> Any:
    """Mean |z| to the position archetype over selected fingerprint features."""
    feats = arch_pos.get("features", {})
    total, n, ev = 0.0, 0, []
    for feat in selected:
        hv = h.get(feat)
        a = feats.get(feat)
        if hv is None or a is None:
            continue
        z = abs(hv - a["mean"]) / a["std"]
        total += z
        n += 1
        ev.append((z, feat, hv, a["mean"]))
    if n == 0:
        return None
    ev.sort(key=lambda x: x[0])

    def _fmt(v):
        return round(v, 2) if isinstance(v, float) else v
    evidence = [f"{f} {_fmt(hv)} (≈{mean})" for z, f, hv, mean in ev[:2]]
    return round(total / n, 3), evidence


def brave_ticket(participants: List[Dict], disc: str = None) -> List[Dict]:
    """Form-based positional archetype ticket. Cote is never read.

    Each finishing position P1..P5 goes to the unassigned horse closest
    to that position's historical archetype, over auto-selected features.
    Honest label: form archetype, not a universal fingerprint. It also
    serves as the tiebreaker inside match_alfaraj_current when several
    horses share the same layer for one position.
    """
    full = get_brave_archetypes(disc=disc)
    arch = full.get("archetypes", {})
    selected = list(full.get("selected_features", {}).keys())
    if not selected:
        return []
    cands = []
    for p in participants:
        if _is_out(p):
            continue
        h = _horse_intrinsic(p)
        if all(h.get(f) is None for f in selected):
            continue
        cands.append((p, h))
    if len(cands) < 5:
        return []
    assigned = set()
    results = []
    fav_used = 0
    for pos in ["1", "2", "3", "4", "5"]:
        best, best_d, best_ev = None, None, []
        for p, h in cands:
            if p.get("num") in assigned:
                continue
            r = _brave_distance(h, arch.get(pos, {}), selected)
            if r is None:
                continue
            d, ev = r
            if best_d is None or d < best_d:
                best_d, best, best_ev = d, p, ev
        if best is None:
            continue
        assigned.add(best.get("num"))
        results.append({
            "num": best.get("num"),
            "horse": best.get("horse"),
            "target_pos": int(pos),
            "ecart": best_d,
            "weak": best_d is not None and best_d > 1.5,
            "reasons": best_ev,
        })
    results.sort(key=lambda x: x["target_pos"])
    return results


def _fam_vector(layers: List[str]) -> List[str]:
    return [_layer_family(L) for L in layers]


def _similar_signatures(cur_fam: List[str], family_counter: Dict, top: int = 8,
                        min_exact: int = 2, min_count: int = 5) -> List[Dict]:
    """Phase C — family-level similarity. Only patterns with real support
    (count >= min_count) can drive a ticket. 1x singletons are display-only.
    Returns (pool, level); level relaxes 2 -> 1 -> 0, never below support.
    """
    scored = []
    for sig, cnt in (family_counter or {}).items():
        try:
            n = int(cnt or 0)
        except (TypeError, ValueError):
            continue
        if n < min_count:
            continue
        try:
            sig_fam = [s.strip() for s in str(sig).split("→")]
        except ValueError:
            continue
        if len(sig_fam) != len(cur_fam):
            continue
        exact = sum(1 for a, b in zip(sig_fam, cur_fam) if a == b)
        try:
            tiebreak = math.log10(n + 1) * 0.1
        except ValueError:
            tiebreak = 0.0
        w = exact * 5 + tiebreak
        scored.append(
            {"signature": sig, "layers": sig_fam, "count": n,
             "exact": exact, "family": exact, "weight": round(w, 2)}
        )
    scored.sort(key=lambda x: (-x["exact"], -x["count"]))
    for level in (min_exact, 1, 0):
        pool = [s for s in scored if s["exact"] >= level]
        if pool:
            for s in pool:
                s["match_level"] = level
            return pool[:top], level
    return [], -1


def _fine_subtarget(per_rank_pos: Dict, family: str) -> Any:
    """Most common fine layer of this family at this position (precision
    detail; the family carries the statistical support)."""
    counter = (per_rank_pos or {}).get("counter", {})
    best, best_n = None, 0
    for layer, n in counter.items():
        if _layer_family(str(layer)) != family:
            continue
        try:
            n = int(n)
        except (TypeError, ValueError):
            continue
        if n > best_n:
            best, best_n = layer, n
    return best


def match_alfaraj_trio_coherent(participants: List[Dict], hist: Dict, disc: str = None) -> tuple:
    """Diagnostic NEW — trio as one unit A→B→C."""
    import itertools
    cotes = _valid_cotes(participants)
    if len(cotes) < 5:
        return [], -1
    rank_map = {p.get("num"): idx + 1 for idx, (_v, p) in enumerate(cotes)}
    cur_layers = [_market_layer(v) for v, _p in cotes[:5]]
    cur_fam = _fam_vector(cur_layers)
    similar, level = _similar_signatures(cur_fam, hist.get("family_counter", {}))
    if not similar:
        return [], -1
    best_trio = None
    best_score = -1
    best_sig = None
    per_rank = hist.get("per_rank", {})
    for sig in similar[:5]:
        fam_pattern = sig["layers"][:3]
        candidates = [p for _, p in cotes]
        for combo in itertools.combinations(candidates, 3):
            for perm in itertools.permutations(combo, 3):
                score = 0
                ok = True
                for idx, p in enumerate(perm):
                    c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
                    layer = _market_layer(c)
                    target_fam = fam_pattern[idx]
                    sub = _fine_subtarget(per_rank.get(str(idx + 1), {}), target_fam)
                    ref = sub if sub is not None else target_fam
                    if layer == ref:
                        s = 10
                    elif _layer_family(layer) == target_fam:
                        s = 7
                    else:
                        try:
                            dist = _layer_distance(layer, ref)
                        except ValueError:
                            dist = 99
                        s = _distance_score(dist)
                    if s < 4:
                        ok = False
                        break
                    score += s
                if not ok:
                    continue
                score += 3
                try:
                    _arch_full = get_brave_archetypes(disc=disc)
                    _arch = _arch_full.get("archetypes", {})
                    _sel = list(_arch_full.get("selected_features", {}).keys())
                    fds = []
                    for idx, p in enumerate(perm):
                        h = _horse_intrinsic(p)
                        r = _brave_distance(h, _arch.get(str(idx + 1), {}), _sel)
                        if r:
                            fds.append(r[0])
                    if fds:
                        avg_fd = sum(fds) / len(fds)
                        if avg_fd < 1.0:
                            score += 2
                        elif avg_fd < 1.5:
                            score += 1
                except Exception:
                    pass
                if score > best_score:
                    best_score = score
                    best_trio = perm
                    best_sig = sig
    if not best_trio:
        return [], -1
    results = []
    for idx, p in enumerate(best_trio):
        c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
        try:
            cote_f = float(c)
        except (TypeError, ValueError):
            cote_f = c
        results.append({
            "num": p.get("num"), "horse": p.get("horse"), "cote": cote_f,
            "market_rank": rank_map.get(p.get("num")), "target_pos": idx + 1,
            "layer": _market_layer(c), "target_layer": best_sig["layers"][idx] if best_sig else None,
            "target_family": best_sig["layers"][idx] if best_sig else None,
            "score": 10, "coherent": True, "signature": best_sig["signature"] if best_sig else None,
            "reasons": [best_sig["signature"] + " (%d×)" % best_sig["count"]] if best_sig else []
        })
    return results, level


def match_alfaraj_current(participants: List[Dict], hist: Dict, disc: str = None,
                           audit: Dict = None, before: str = None, distance=None) -> tuple:
    """Phase C — family targets with support, fine detail for precision.

    Returns (results, match_level). Honesty lives in the score
    (10 exact fine … 7 family … 1 far), the weak flag, and cited counts.
    audit (optional dict): filled with per-position scored candidates.
    before: race date (YYYY-MM-DD) — plot signals use strictly older history.
    """
    cotes = _valid_cotes(participants)
    if len(cotes) < 5:
        return [], -1
    rank_map = {p.get("num"): idx + 1 for idx, (_v, p) in enumerate(cotes)}
    cur_layers = [_market_layer(v) for v, _p in cotes[:5]]
    cur_fam = _fam_vector(cur_layers)
    similar, level = _similar_signatures(cur_fam, hist.get("family_counter", {}))
    if not similar:
        return [], -1
    target, evidence = _vote_targets(similar)
    fav_cap = _historical_fav_cap(hist)
    try:
        _pconn = get_db()
        try:
            plot_map = compute_field_plot(_pconn, participants, before=before, cur_dist=distance)
        finally:
            _pconn.close()
    except Exception:
        plot_map = {}
    results = _assign_positions(
        cotes, rank_map, target, hist.get("per_rank", {}), evidence,
        disc=disc, max_fav_count=fav_cap, audit=audit, plot_map=plot_map,
        cur_dist=distance
    )
    # 3 réserves: meilleurs restants pour le Top5 (les négligés par le meilleur)
    # (3e réserve = 8e cheval pour le suivi Kanti-8: Top5 dans 8)
    already = {r["num"] for r in results}
    try:
        _arch_full = get_brave_archetypes(disc=disc)
        _arch = _arch_full.get("archetypes", {})
        _sel = list(_arch_full.get("selected_features", {}).keys())
    except Exception:
        _arch, _sel = {}, []
    reserves = []
    for _v, p in cotes:
        if p.get("num") in already:
            continue
        c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
        layer = _market_layer(c)
        # meilleur score parmi les 5 cibles P1→P5
        best_s = 0
        for pos in ("1", "2", "3", "4", "5"):
            tl = target.get(pos)
            if not tl:
                continue
            # family target carries support; fine detail via per_rank
            sub = _fine_subtarget(hist.get("per_rank", {}).get(pos, {}), tl)
            ref = sub if sub is not None else tl
            if layer == ref:
                s = 10
            elif _layer_family(layer) == tl:
                s = 7
            else:
                try:
                    dist = _layer_distance(layer, ref)
                except ValueError:
                    dist = 99
                s = _distance_score(dist)
            if s > best_s:
                best_s = s
        if plot_map:
            _pb, _ = plot_bonus_for_quinte(plot_map.get(p.get("num")), _layer_family(layer))
            best_s += _pb
        # form distance moyenne comme départage (plus petit = mieux)
        try:
            h = _horse_intrinsic(p)
            # moyenne sur P1→P5
            ds = []
            for pos in ("1", "2", "3", "4", "5"):
                r = _brave_distance(h, _arch.get(pos, {}), _sel) if _sel else None
                if r is not None:
                    ds.append(r[0])
            fd = sum(ds) / len(ds) if ds else None
        except Exception:
            fd = None
        try:
            cote_f = float(c)
        except (TypeError, ValueError):
            cote_f = c
        reserves.append((best_s, -(fd if fd is not None else float("inf")), p, layer, cote_f, fd))
    reserves.sort(key=lambda x: (x[0], x[1]), reverse=True)
    for best_s, _neg_fd, p, layer, cote_f, fd in reserves[:3]:
        results.append({"num": p.get("num"), "horse": p.get("horse"), "cote": cote_f,
                        "market_rank": rank_map.get(p.get("num")), "target_pos": None,
                        "layer": layer, "target_layer": None,
                        "target_family": None, "score": best_s, "form_ecart": fd,
                        "weak": best_s < 5, "reserve": True,
                        "reasons": ["réserve Top5 — proche d'une cible"]})
    results.sort(key=lambda x: (x["target_pos"] is None, x["target_pos"] or 99))
    return results, level


def _vote_targets(similar: List[Dict]) -> tuple:
    """Weighted vote per finishing position across similar signatures."""
    votes: Dict[str, Dict[str, float]] = {str(i): defaultdict(float) for i in range(1, 6)}
    for s in similar:
        for i, layer in enumerate(s["layers"][:5], start=1):
            votes[str(i)][layer] += s["weight"] * (1 + math.log10(float(s["count"] or 1) + 1))
    target = {}
    for pos in ["1", "2", "3", "4", "5"]:
        if votes[pos]:
            target[pos] = max(votes[pos].items(), key=lambda x: x[1])[0]
    evidence = [f"{s['signature']} ({s['count']}×)" for s in similar[:3]]
    return target, evidence


def _historical_fav_cap(hist: Dict) -> Any:
    """Return the historically most common number of FAVs in P1..P5.

    This is a market-composition guard only. It is deliberately not part of
    the Race DNA signature and it never forces a favorite into the ticket.
    If history is unavailable, no cap is applied.
    """
    try:
        dist = hist.get("fav_count_distribution") or {}
        pairs = [(int(k), int(v)) for k, v in dist.items()]
        if not pairs:
            return None
        # Deterministic: highest historical frequency, then lower FAV count.
        return max(pairs, key=lambda x: (x[1], -x[0]))[0]
    except (TypeError, ValueError, AttributeError):
        return None


def _assign_positions(cotes: List[tuple], rank_map: Dict, target: Dict,
                      per_rank: Dict, evidence: List[str],
                      require_family_for: tuple = (), disc: str = None,
                      max_fav_count: int = None, audit: Dict = None,
                      plot_map: Dict = None, cur_dist=None) -> List[Dict]:
    """Family target carries support; fine sub-target carries precision.

    Score: 10 exact fine layer, 7 same family, else odds-scale distance
    to the fine sub-target (fallback: to any layer of the target family).
    Form archetype breaks equal-score ties ONLY past FORM_TIEBREAK_MIN;
    otherwise the lowest cote keeps the seat.
    """
    try:
        _arch_full = get_brave_archetypes(disc=disc)
        _arch = _arch_full.get("archetypes", {})
        _sel = list(_arch_full.get("selected_features", {}).keys())
    except Exception:
        _arch, _sel = {}, []
    _intrinsic = {}
    for _v, p in cotes:
        try:
            _intrinsic[p.get("num")] = _horse_intrinsic(p)
        except Exception:
            _intrinsic[p.get("num")] = {}

    def _form_of(num, pos):
        if not _sel:
            return None
        r = _brave_distance(_intrinsic.get(num, {}), _arch.get(pos, {}), _sel)
        return r[0] if r is not None else None

    assigned = set()
    results = []
    plot_reasons = {}
    fav_used = 0
    # Trap: favorite with 2 red flags never takes P1 (measured 23% vs 35%).
    trap_fav = None
    if plot_map:
        try:
            _rn = [p.get("num") for _, p in cotes]
            _tc, _tl = trap_of_fav(plot_map, _rn, cur_dist)
            if _tc >= 2 and _rn:
                trap_fav = _rn[0]
                plot_reasons.setdefault(trap_fav, []).append("trap2 exclu P1 [%s]" % "+".join(_tl))
        except Exception:
            trap_fav = None
    for pos in ["1", "2", "3", "4", "5"]:
        target_fam = target.get(pos)
        if not target_fam:
            continue
        sub = _fine_subtarget((per_rank or {}).get(pos, {}), target_fam)
        locked = pos in (require_family_for or ())
        scored = []
        for _v, p in cotes:
            if p.get("num") in assigned:
                continue
            c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
            layer = _market_layer(c)
            # Hard historical composition guard. Once the historical FAV
            # capacity is reached, FAV candidates are not allowed to occupy
            # another position. This does NOT require any FAV to be selected.
            if (max_fav_count is not None and fav_used >= max_fav_count
                    and _layer_family(layer) == "FAV"):
                continue
            if pos == "1" and trap_fav is not None and p.get("num") == trap_fav:
                continue
            if sub is not None and layer == sub:
                score = 10
            elif _layer_family(layer) == target_fam:
                score = 7
            else:
                ref = sub if sub is not None else target_fam + "1"
                try:
                    dist = _layer_distance(layer, ref)
                except ValueError:
                    dist = 99
                score = _distance_score(dist)
            if plot_map:
                _pb, _prs = plot_bonus_for_quinte(plot_map.get(p.get("num")), _layer_family(layer))
                if _pb:
                    score += _pb
                    plot_reasons.setdefault(p.get("num"), []).extend(_prs)
            scored.append((p, score, _form_of(p.get("num"), pos), layer, sub))
        if locked:
            # outsider P1: only horses OF the target family may headline —
            # a FAV can never front this ticket, even with a close score
            scored = [t for t in scored if _layer_family(t[3]) == target_fam]
            if not scored:
                continue
        if not scored:
            continue
        # Contradiction bonus: market neglected + strong Finisher DNA = hidden value
        for i, (p, s, fd, layer, sub) in enumerate(scored):
            fam = _layer_family(layer)
            if fam in ("OUT", "TOC") and fd is not None and fd <= 0.6:
                scored[i] = (p, min(10, s + 2), fd, layer, sub)
        top_score = max(s for _, s, _, _, _ in scored)
        if audit is not None:
            audit.setdefault("positions", {})[pos] = [
                {"num": p.get("num"), "score": s, "layer": layer,
                 "family": _layer_family(layer),
                 "rank": rank_map.get(p.get("num")),
                 "form": fd} for p, s, fd, layer, sub in
                sorted(scored, key=lambda t: (-t[1], t[0].get("num", 999)))]
        contenders = [t for t in scored if t[1] == top_score]
        # Form tiebreak applies to ALL positions including P1 (no market-pure protection)
        pick = contenders[0]
        if len(contenders) > 1:
            base_fd = contenders[0][2]
            for t in contenders[1:]:
                fd = t[2]
                if fd is None:
                    continue
                if base_fd is None or fd + FORM_TIEBREAK_MIN <= base_fd:
                    pick = t
                    base_fd = fd
        p, score, form_d, layer, sub = pick
        c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
        assigned.add(p.get("num"))
        if _layer_family(layer) == "FAV":
            fav_used += 1
        try:
            cote_f = float(c)
        except (TypeError, ValueError):
            cote_f = c
        results.append({
            "num": p.get("num"),
            "horse": p.get("horse"),
            "cote": cote_f,
            "market_rank": rank_map.get(p.get("num")),
            "target_pos": int(pos),
            "layer": layer,
            "target_layer": sub if sub is not None else target_fam,
            "target_family": target_fam,
            "score": score,
            "form_ecart": form_d,
            "weak": score < 5,
            "reasons": (evidence[:2] + plot_reasons.get(p.get("num"), []))[:4],
        })
    return results


def _similar_upset(cur_fam: List[str], family_counter: Dict, top: int = 8,
                   min_count: int = 3) -> tuple:
    """Upset pool: family signatures with P1 in OUT/TOC and real support
    (count >= min_count). Ranked by family similarity to the current market
    DNA. An outsider endorsed here can score 10 for P1 — no cap.
    """
    scored = []
    for sig, cnt in (family_counter or {}).items():
        try:
            n = int(cnt or 0)
        except (TypeError, ValueError):
            continue
        if n < min_count:
            continue
        try:
            fam = [s.strip() for s in str(sig).split("→")]
        except ValueError:
            continue
        if len(fam) != len(cur_fam):
            continue
        # Do not force the "unexpected" horse to P1 or to OUT/TOC.
        # A surprise can occupy any P1..P5 position.
        exact = sum(1 for a, b in zip(fam, cur_fam) if a == b)
        try:
            tiebreak = math.log10(n + 1) * 0.1
        except ValueError:
            tiebreak = 0.0
        w = exact * 5 + tiebreak
        scored.append(
            {"signature": sig, "layers": fam, "count": n,
             "exact": exact, "family": exact, "weight": round(w, 2)}
        )
    scored.sort(key=lambda x: (-x["exact"], -x["count"]))
    if not scored:
        return [], -1
    best = scored[0]["exact"]
    pool = [s for s in scored if s["exact"] >= best]
    for s in pool:
        s["match_level"] = best
    return pool[:top], best


def outsider_ticket(participants: List[Dict], hist: Dict, disc: str = None,
                    before: str = None, distance=None) -> tuple:
    """The 25% ticket: P1 endorsed from OUT/TOC histories similar to this race.

    Same machinery as the market ticket, but the candidate pool is upset
    signatures — so an outsider can take P1 with score 10 when endorsed.
    Returns (results, match_level).
    """
    cotes = _valid_cotes(participants)
    if len(cotes) < 5:
        return [], -1
    rank_map = {p.get("num"): idx + 1 for idx, (_v, p) in enumerate(cotes)}
    cur_layers = [_market_layer(v) for v, _p in cotes[:5]]
    cur_fam = _fam_vector(cur_layers)
    similar, level = _similar_upset(cur_fam, hist.get("family_counter", {}))
    if not similar:
        return [], -1
    target, evidence = _vote_targets(similar)
    fav_cap = _historical_fav_cap(hist)
    try:
        _pconn = get_db()
        try:
            plot_map = compute_field_plot(_pconn, participants, before=before, cur_dist=distance)
        finally:
            _pconn.close()
    except Exception:
        plot_map = {}
    results = _assign_positions(
        cotes, rank_map, target, hist.get("per_rank", {}), evidence,
        disc=disc, max_fav_count=fav_cap, plot_map=plot_map, cur_dist=distance
    )
    # This function is retained for API compatibility. It no longer forces
    # an outsider into P1: the historical pattern decides the position.
    # 2 réserves for alternative Top5
    already = {r["num"] for r in results}
    try:
        _arch_full = get_brave_archetypes(disc=disc)
        _arch = _arch_full.get("archetypes", {})
        _sel = list(_arch_full.get("selected_features", {}).keys())
    except Exception:
        _arch, _sel = {}, []
    reserves = []
    for _v, p in cotes:
        if p.get("num") in already:
            continue
        c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
        layer = _market_layer(c)
        best_s = 0
        for pos in ("1", "2", "3", "4", "5"):
            tl = target.get(pos)
            if not tl:
                continue
            sub = _fine_subtarget(hist.get("per_rank", {}).get(pos, {}), tl)
            ref = sub if sub is not None else tl
            if layer == ref:
                s = 10
            elif _layer_family(layer) == tl:
                s = 7
            else:
                try:
                    dist = _layer_distance(layer, ref)
                except ValueError:
                    dist = 99
                s = _distance_score(dist)
            if s > best_s:
                best_s = s
        try:
            h = _horse_intrinsic(p)
            ds = []
            for pos in ("1", "2", "3", "4", "5"):
                r = _brave_distance(h, _arch.get(pos, {}), _sel) if _sel else None
                if r is not None:
                    ds.append(r[0])
            fd = sum(ds) / len(ds) if ds else None
        except Exception:
            fd = None
        try:
            cote_f = float(c)
        except (TypeError, ValueError):
            cote_f = c
        reserves.append((best_s, -(fd if fd is not None else float("inf")), p, layer, cote_f, fd))
    reserves.sort(key=lambda x: (x[0], x[1]), reverse=True)
    for best_s, _neg_fd, p, layer, cote_f, fd in reserves[:2]:
        results.append({"num": p.get("num"), "horse": p.get("horse"), "cote": cote_f,
                        "market_rank": rank_map.get(p.get("num")), "target_pos": None,
                        "layer": layer, "target_layer": None,
                        "target_family": None, "score": best_s, "form_ecart": fd,
                        "weak": best_s < 5, "reserve": True,
                        "reasons": ["réserve Top5 alternative"]})
    results.sort(key=lambda x: (x["target_pos"] is None, x["target_pos"] or 99))
    return results, level


# Measured sweep (220 Quinté): thr=0.10 ties baseline (1.29 vs 1.31, 11 cases),
# looser thresholds degrade monotonically to 1.00. Experimental pending
# out-of-sample confirmation — see Suivi.
TRIO_INFILTRE_MAX_ECART = 0.10


def trio_infiltre(participants: List[Dict], hist: Dict, disc: str = None,
                  before: str = None, distance=None) -> tuple:
    """Compatibility wrapper.

    The old implementation forcibly replaced a structural horse with a
    market-rank >5 outsider. That is contrary to the Race DNA rule:
    an unexpected horse may be P1, P2, P3, P4 or P5 and must emerge from
    the historical structure, not from a hard-coded outsider slot.

    The function therefore returns the structural P1..P3 unchanged.
    """
    m, level = match_alfaraj_current(participants, hist, disc=disc, before=before, distance=distance)
    trio = [x for x in m if x.get("target_pos") in (1, 2, 3) and not x.get("reserve")]
    trio.sort(key=lambda x: x.get("target_pos", 99))
    return trio, level


def trio_coherent(participants: List[Dict], hist: Dict, disc: str = None) -> tuple:
    """Whole-triple ticket: the Top3 is searched as ONE coherent pattern
    (historical family triple -> candidate horses), never assembled from
    independent P1/P2/P3 picks. Falls back to [] when no triple coheres."""
    m, level = match_alfaraj_trio_coherent(participants, hist, disc=disc)
    trio = [x for x in (m or []) if x.get("target_pos") in (1, 2, 3)]
    trio.sort(key=lambda x: x.get("target_pos", 99))
    return trio, level
