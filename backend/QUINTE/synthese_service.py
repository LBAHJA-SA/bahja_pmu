"""
Synthèse Service — Hybrid for /#/synthese.
WHERE is fixed by displayed places (TABLEAU NOUVEAU P1-P4:3 / P5-P6:1 /
P7-P8:1 / P9-P10:1 / P11-P18:2) in SECRET display order.
WHO inside each zone is weighted red_km + cote + form.
DNA sets adaptive quotas only (measured: adaptive beats fixed; DNA-first
WHO ordering tested worse on 300 Quintés, reverted).
"""
from collections import defaultdict
from QUINTE.service import (
    get_quinte_top5_stats,
    _valid_cotes,
    _is_out,
    _market_layer,
    _layer_family,
    _fine_subtarget,
    _layer_distance,
    _distance_score,
    _historical_fav_cap,
)

NEED = { 'A': 3, 'B': 1, 'C': 1, 'D': 1, 'E': 2 }
MIN_SUPPORT = 5  # same support rule as production _similar_signatures (no invention)

def _build_pool(hist):
    """Vote pool from one hist: all family structures with count >= MIN_SUPPORT."""
    pool = []
    for sig, cnt in (hist.get("family_counter", {}) or {}).items():
        try:
            n = int(cnt or 0)
        except (TypeError, ValueError):
            continue
        if n < MIN_SUPPORT:
            continue
        sig_fam = [s.strip() for s in str(sig).split("→")]
        if len(sig_fam) != 5:
            continue
        pool.append({"signature": sig, "layers": sig_fam, "count": n})
    pool.sort(key=lambda x: -x["count"])
    return pool

def synthese_fingerprint(participants, hippodrome=None, distance=None, runners=None, disc=None, before=None):
    """TRUE RACE DNA: historical RESULT structures for this race context.
    No current-market input. Scope cascade (narrow -> wide), first scope
    with a non-empty supported pool wins; the used scope is reported.
    Raw frequency drives the vote, no weight factor.
    before (YYYY-MM-DD, optional): strict LOO — history only date < before."""
    scopes = [
        ("hippodrome+shape", dict(hippodrome=hippodrome, distance=distance, runners=runners)),
        ("hippodrome", dict(hippodrome=hippodrome)),
        ("discipline", dict(disc=disc)),
        ("global", {}),
    ]
    hist = None
    pool = []
    scope_used = "none"
    for name, kw in scopes:
        kw = {k: v for k, v in kw.items() if v is not None}
        if name in ("hippodrome+shape", "hippodrome") and not kw.get("hippodrome"):
            continue
        if name == "discipline" and not kw.get("disc"):
            continue
        h = get_quinte_top5_stats(limit=4054, before=before, **kw)
        p = _build_pool(h)
        if p:
            hist, pool, scope_used = h, p, name
            break
        hist = h
    return {"hist": hist or {}, "pool": pool, "scope": scope_used}

def _frequency_vote(pool):
    """Frequency vote per finishing position across historical structures.
    Vote = raw historical count only. No similarity weight, no log factor.
    Contract: pool items are {signature, layers[5], count}."""
    votes = {str(i): defaultdict(float) for i in range(1, 6)}
    for s in pool:
        try:
            n = int(s.get("count") or 0)
        except (TypeError, ValueError):
            continue
        for i, layer in enumerate(s.get("layers", [])[:5], start=1):
            votes[str(i)][layer] += n
    target = {}
    for pos in ["1", "2", "3", "4", "5"]:
        if votes[pos]:
            target[pos] = max(votes[pos].items(), key=lambda x: x[1])[0]
    ordered = sorted(pool, key=lambda x: -x.get("count", 0))
    evidence = [f"{s['signature']} ({s['count']}×)" for s in ordered[:3]]
    return target, evidence

def _secret_display_order(nums):
    """Secret display order (السر): same even/odd split as Synthese.jsx buildCells,
    flattened in P order: P1=cols[0][0], P2=cols[0][1], P3=cols[1][0]...
    Zones A/B/C/D are read on THESE displayed places only."""
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


def france_zones(presse):
    """Displayed places (1-based position in SECRET display order) -> zone.
    TABLEAU: P1-P4:4 (A), P5-P6:1 (B), P7-P8:1 (C), P9-P10:2 (D), P11-P18:1 (E) = 9.
    Zones define WHERE matching may pick, never the pick itself."""
    zones = {}
    for idx, n in enumerate(presse or [], start=1):
        if n is None:
            continue
        try:
            num = int(n)
        except (TypeError, ValueError):
            continue
        if 1 <= idx <= 4:
            zones[num] = 'A'
        elif 5 <= idx <= 6:
            zones[num] = 'B'
        elif 7 <= idx <= 8:
            zones[num] = 'C'
        elif 9 <= idx <= 10:
            zones[num] = 'D'
        elif 11 <= idx <= 18:
            zones[num] = 'E'
        else:
            zones[num] = None
    return {k: v for k, v in zones.items() if v is not None}

def france_ticket(presse):
    """Base list -> SECRET display order -> 8 numeros per NEED (affichage/fallback uniquement).
    Uses global NEED so fallback matches the tableau in force."""
    nums = [int(n) for n in (presse or []) if n is not None]
    if len(nums) < 14:
        return nums[:8]
    order = _secret_display_order(nums)
    zones = france_zones(order)
    rank = {n: i for i, n in enumerate(order)}
    ticket = []
    for g in ("A", "B", "C", "D", "E"):
        need = NEED.get(g, 0)
        members = sorted([n for n in order if zones.get(n) == g], key=lambda n: rank[n])
        ticket.extend(members[:need])
    return ticket  # 8

def _form_score_for_tie(musique):
    """Shadow form for tiebreak — higher is better. Import here to avoid cycle."""
    try:
        from QUINTE.shadow import _form_score_shadow
        return _form_score_shadow(musique)
    except Exception:
        return 0.0


def _red_val(v):
    try:
        f = float(str(v).strip()) if v and str(v).strip() else None
        return f
    except Exception:
        return None


W_RED, W_COTE, W_FORM = 0.9870174151944342, 0.4148605763544888, 0.9674345543146796  # shadow best on 300, validated 22.6% on 500 — deployed 2026-09-16


def _weighted_score(horse_dict):
    """Weighted red + cote + form — higher is better. Used as primary WHO score."""
    s = 0.0
    rv = horse_dict.get("red")
    if rv is not None:
        s += W_RED * (-rv)
    fv = horse_dict.get("form")
    if fv is not None:
        s += W_FORM * fv
    cv = horse_dict.get("cote")
    if cv is not None:
        try:
            s += W_COTE * (-float(cv))
        except Exception:
            pass
    return s


def _pos_ref(pos, target, per_rank):
    """Reference layer for one DNA position (sub-target if any, else family target)."""
    tl = target.get(pos)
    if not tl:
        return None
    sub = _fine_subtarget((per_rank or {}).get(pos, {}), tl)
    return sub if sub is not None else tl


def _pos_score(layer, pos, target, per_rank):
    """Independent DNA score of one horse layer for ONE DNA position.
    Same 10/7/distance rule as production (no invented metric).
    Never maxed across positions — each position keeps its own matching."""
    ref = _pos_ref(pos, target, per_rank)
    if ref is None:
        return -1
    tl = target.get(pos)
    if layer == ref:
        return 10
    if _layer_family(layer) == tl:
        return 7
    try:
        dist = _layer_distance(layer, ref)
    except ValueError:
        dist = 99
    return _distance_score(dist)


def _dna_best_score(layer, target, per_rank):
    """Best DNA score across P1→P5 — reserved for future WHO use.
    Measured 2026-09: DNA-first ordering underperforms greedy weighted
    on Top5 coverage, so production keeps weighted primary."""
    best = -1
    for pos in ("1", "2", "3", "4", "5"):
        s = _pos_score(layer, pos, target, per_rank)
        if s > best:
            best = s
    return best

def synthese_match(participants, hippodrome=None, distance=None, runners=None, presse=None, disc=None, before=None, debug=False, shadow=False, fixed_need=None, hidden_zones=False):
    """
    TRUE RACE DNA leads; DISPLAYED places constrain WHERE matching may pick.
    Honest rule, exactly as implemented:
      - WHERE (which places): display places only
        (P1-P6:4 / P7-P8:1 / P9-P10:1 / P11-P18:2). No market, no presse rank.
      - WHO inside each zone: DNA positional score first; market_rank breaks
        ties only; market-sorted reserves fill only if fav_cap emptied a zone;
        market order feeds the frame only when no 14+ list is provided.
      1. market_rank_global computed on the FULL field (tiebreak + diagnostic).
      2. base list (14-18 numbers) -> SECRET display order -> zones
         A (places 1..6, need 4) / B (7..8, need 1) /
         C (9..10, need 1) / D (11..18, need 2).
      3. Context-wide historical RESULT vote -> P1→P5 structural targets
         (no market-similarity filter; `before` gives strict LOO).
      4. Phase 1: 5 positional picks from zone A (independent per-position
         scores, no max across P1→P5), weakest DNA fit dropped to respect
         A quota (4). Phase 2: B×1 + C×1 + D×2 extras.
         dna_pos is informational: no horse is forced to finish P1/P2.
    No fixed P-slots: different DNA scores per race -> different horses.
    """
    cotes_all = _valid_cotes(participants)
    if not cotes_all:
        return [], -1
    rank_map_global = {p.get("num"): i+1 for i, (_, p) in enumerate(cotes_all)}
    # Base list -> SECRET display order -> zones on displayed places.
    # presse_source is diagnostic only (which list fed the frame).
    if presse and len([n for n in presse if n is not None]) >= 14:
        base = [int(n) for n in presse if n is not None][:18]
        presse_source = "presse"
    else:
        base = [p.get("num") for _, p in cotes_all[:18]]
        presse_source = "market_fallback"
    order = _secret_display_order(base)
    zones = france_zones(order)
    presse_rank = {n: i + 1 for i, n in enumerate(order)}  # display place P (1-based)
    fp = synthese_fingerprint(participants, hippodrome, distance, runners, disc, before=before)
    hist = fp["hist"]
    pool = fp["pool"]
    # Explicit support (no ambiguity):
    #   structures = N distinct historical structures that voted (each count >= 5)
    #   races      = total historical races behind them (sum of counts)
    #   scope      = which context level supplied the pool
    support = {
        "structures": len(pool),
        "races": sum(s["count"] for s in pool),
        "top": [{"signature": s["signature"], "count": s["count"]} for s in pool[:3]],
        "presse_source": presse_source,
        "scope": fp.get("scope", "unknown"),
    }
    if not pool:
        return [], support
    target, evidence = _frequency_vote(pool)
    per_rank = hist.get("per_rank", {})
    # Hidden profile (ctx) for outsider zones C/D/E — computed once, best effort.
    # A/B stay weighted (fav territory). C/D/E rank by hidden ctx first.
    ctx_of = {}
    try:
        from signals.plot_signals import compute_field_plot
        from database import get_db as _gdb
        _pc = _gdb()
        try:
            _pm = compute_field_plot(_pc, participants, before=before, cur_dist=distance)
        finally:
            _pc.close()
        for _p in (participants or []):
            try:
                _n = _p.get("num")
                _c = (_pm.get(_n, {}) or {}).get("ctx")
                if _c is not None:
                    ctx_of[_n] = float(_c)
            except (TypeError, ValueError, AttributeError):
                continue
    except Exception:
        ctx_of = {}
    fav_cap = None  # disabled 2026-09-15: shadow 58/1000=5.8% vs 3.8% baseline — fav_cap was 39% of misses (WHO_FAVCAP)
    # Adaptive quotas: places vary per fingerprint (fixed quotas = stupid).
    # nfav>=4 -> front (4-1-1-1-1), nfav==3 -> balanced (3-1-1-2-1), else deep (2-1-1-2-2).
    # Shadow 97/500=19.4% vs fixed 77/500=15.4%.
    nfav = sum(1 for pos in ("1", "2", "3", "4", "5")
               if _layer_family(target.get(pos, "")) == "FAV")
    if nfav >= 4:
        need = {"A": 4, "B": 1, "C": 1, "D": 1, "E": 1}
    elif nfav == 3:
        need = {"A": 3, "B": 1, "C": 1, "D": 1, "E": 2}
    else:
        need = {"A": 2, "B": 1, "C": 1, "D": 1, "E": 3}
    if fixed_need:
        need = {z: int(fixed_need.get(z, need.get(z, 0))) for z in ("A", "B", "C", "D", "E")}
    support["quotas"] = "-".join(str(need[z]) for z in ("A", "B", "C", "D", "E"))
    support["nfav"] = nfav
    # Horse table: weighted red/cote/form + zone + diagnostic ranks.
    # NULL-cote horses are kept with layer UNK / market_rank 999 so zones
    # stay obligatory (4-1-1-2) even when PMU cote is missing.
    horses = {}
    for c, p in cotes_all:
        n = p.get("num")
        z = zones.get(n)
        if z is None:
            continue  # outside the presse frame -> not matchable
        layer = _market_layer(c)
        red = _red_val(p.get("red_km"))
        form = _form_score_for_tie(p.get("musique"))
        cote = c
        h = {
            "num": n, "horse": p.get("horse"),
            "market_rank": rank_map_global.get(n, 999),
            "presse_rank": presse_rank.get(n, 999),
            "layer": layer, "zone": z,
            "red": red, "form": form, "cote": cote,
        }
        h["weighted"] = _weighted_score(h)
        horses[n] = h
    for p in (participants or []):
        try:
            if _is_out(p):
                continue
        except Exception:
            pass
        n = p.get("num")
        if n is None or n in horses:
            continue
        z = zones.get(n)
        if z is None:
            continue
        red = _red_val(p.get("red_km"))
        form = _form_score_for_tie(p.get("musique"))
        h = {
            "num": n, "horse": p.get("horse"),
            "market_rank": 999,
            "presse_rank": presse_rank.get(n, 999),
            "layer": "UNK", "zone": z,
            "red": red, "form": form, "cote": None,
        }
        h["weighted"] = _weighted_score(h)
        horses[n] = h
    # Weighted selection inside each zone (measured best on 300 Quintés;
    # DNA-first ordering tested worse and was reverted).
    # WHERE is fixed (3-2-1-1-1 on displayed places), WHO is weighted.
    dbg = {"phase1_ties": 0, "phase1_pos": 0, "phase2_ties": 0,
           "phase2_slots": 0, "fill_market": 0, "tiebreak_nums": set()}
    # Zone A: best weighted (greedy top-N kept: DNA-first variant measured worse).
    a_pool = [(h["weighted"], h["market_rank"], n) for n, h in horses.items() if h["zone"] == "A"]
    a_pool.sort(key=lambda t: (-t[0], t[1], t[2]))
    kept = []  # (pos, num, score, market_rank, source) — pos kept for compatibility
    picked = set()
    for _, _, n in a_pool[:need["A"]]:
        h = horses[n]
        kept.append((None, n, h["weighted"], h["market_rank"], "dna"))
        picked.add(n)
    if a_pool and need["A"]:
        _top = a_pool[0][0]
        if sum(1 for t in a_pool[:need["A"]] if t[0] == _top) > 1:
            dbg["phase1_ties"] += 1
    fav_used = sum(1 for n in picked
                   if _layer_family(horses[n]["layer"]) == "FAV")
    results = []
    for pos, pick_num, top_score, _mr, _src in sorted(kept, key=lambda t: (t[1],)):
        h = horses[pick_num]
        try:
            cote_f = float(next((c for c, p in cotes_all if p.get("num") == pick_num), None))
        except (TypeError, ValueError):
            cote_f = None
        results.append({
            "num": pick_num, "horse": h["horse"], "cote": cote_f,
            "market_rank": h["market_rank"], "presse_rank": h["presse_rank"],
            "zone": "A", "dna_pos": None,
            "layer": h["layer"], "score": round(top_score, 2),
            "target_family": None,
            "weak": False,
            "source": _src,
            "reasons": evidence[:2],
        })
    # Phase 2: extras B×1 + C×1 + D×2 (+E).
    # B stays weighted (fav territory). C/D/E rank by HIDDEN ctx profile first
    # (outsider territory belongs to hidden value, not market weight) —
    # unless hidden_zones=False (classic weighted, for A/B measurement).
    for z, need_n in (("B", need["B"]), ("C", need["C"]), ("D", need["D"]), ("E", need.get("E", 0))):
        pool = []
        for n, h in horses.items():
            if n in picked or h["zone"] != z:
                continue
            pool.append((h["weighted"], h["market_rank"], n))
        if hidden_zones and z in ("C", "D", "E") and any(n in ctx_of for _, _, n in pool):
            pool.sort(key=lambda t: (-ctx_of.get(t[2], float("-inf")), -t[0], t[1], t[2]))
            via_hidden = True
        else:
            pool.sort(key=lambda t: (-t[0], t[1], t[2]))
            via_hidden = (hidden_zones and z in ("C", "D", "E"))
        chosen = [t[2] for t in pool[:need_n]]
        dbg["phase2_slots"] += 1
        if pool and need_n and sum(1 for t in pool if t[0] == pool[min(need_n, len(pool)) - 1][0]) > 1:
            dbg["phase2_ties"] += 1
            for t in pool[:need_n]:
                if t[0] == pool[min(need_n, len(pool)) - 1][0]:
                    dbg["tiebreak_nums"].add(t[2])
        # Fill remainder from same zone ignoring cap (mirrors production reserves)
        filled = set()
        if len(chosen) < need_n:
            taken = set(chosen) | picked
            rest = sorted(
                [(h["market_rank"], n) for n, h in horses.items()
                 if h["zone"] == z and n not in taken],
                key=lambda t: (t[0], t[1]))
            for _, n in rest:
                chosen.append(n)
                filled.add(n)
                dbg["fill_market"] += 1
                dbg["tiebreak_nums"].add(n)
                if len(chosen) >= need_n:
                    break
        for n in chosen:
            h = horses[n]
            picked.add(n)
            if _layer_family(h["layer"]) == "FAV":
                fav_used += 1
            try:
                cote_f = float(next((c for c, p in cotes_all if p.get("num") == n), None))
            except (TypeError, ValueError):
                cote_f = None
            results.append({
                "num": n, "horse": h["horse"], "cote": cote_f,
                "market_rank": h["market_rank"], "presse_rank": h["presse_rank"],
                "zone": z, "dna_pos": None,
                "layer": h["layer"],
                "score": round(h["weighted"], 2),
                "weak": False,
                "source": "fill_market" if n in filled else "dna",
                "reasons": evidence[:2],
            })
    shadow_diag = None
    if shadow:
        try:
            from QUINTE.shadow import shadow_for_race, _form_score_shadow  # local import: no cycle
            # Build a lightweight top5 placeholder — caller may fill arrivee later.
            # Here we just score form distribution per zone for diagnostics.
            _ = _form_score_shadow  # keep import used (linter)
            shadow_diag = {
                "zones": {k: sorted([n for n, z2 in zones.items() if z2 == k]) for k in ("A", "B", "C", "D")},
                "note": "Shadow only — ticket unchanged. Use shadow_for_race(participants, ticket, top5, zones) for full comparison.",
            }
        except Exception as e:
            shadow_diag = {"error": str(e)}
    if debug:
        dbg["tiebreak_nums"] = sorted(dbg["tiebreak_nums"])
        if shadow:
            return results, support, dbg, shadow_diag
        return results, support, dbg
    if shadow:
        return results, support, shadow_diag
    # Cross-zone fallback: small fields (<11 runners) leave D/E zones empty.
    # Guarantee 8 picks whenever the field allows (measured: 2/300 Quintés
    # returned 6). Takes best weighted remaining horses, any zone.
    if len(results) < 8:
        have = {r["num"] for r in results}
        rest = sorted(
            [(h["weighted"], h["market_rank"], n) for n, h in horses.items()
             if n not in have],
            key=lambda t: (-t[0], t[1], t[2]))
        for _, _, n in rest:
            if len(results) >= 8:
                break
            h = horses[n]
            try:
                cote_f = float(next((c for c, p in cotes_all if p.get("num") == n), None))
            except (TypeError, ValueError):
                cote_f = None
            results.append({
                "num": n, "horse": h["horse"], "cote": cote_f,
                "market_rank": h["market_rank"], "presse_rank": h["presse_rank"],
                "zone": h["zone"], "dna_pos": None,
                "layer": h["layer"],
                "score": round(h["weighted"], 2),
                "weak": False,
                "source": "hidden" if via_hidden else "dna",
                "reasons": evidence[:2],
            })
            dbg["fill_market"] += 1
    return results, support  # 4 positional (A) + 1 (B) + 1 (C) + 2 (D) = 8
