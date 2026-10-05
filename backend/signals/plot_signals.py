"""Plot (intent) signals — measured edges on 3126 archive races, applied as small
bonuses that never overturn structure (cap +3).

Measured (P1 vs base):
- T2 trainer hot 14d (>=25%, >=8 runners): 22.2% vs 9.0%  -> +2
- T4 back to winning distance/surface:      17.3% vs 8.8%  -> +2
- first-time D4:                             15.5% vs ~8%   -> +1
- T3 winless 180d+ (3+ runs):                14.6% vs 8.8%  -> +1
- hidden outsider (best contextual, rank>=6): top3 15% vs 12.5% -> regret tiebreak only

Rule: plot confirms contenders (FAV family, cote<=10), never manufactures
outsiders (outsider+signal underperforms except hidden-rank/firstD4).
All history is strictly before `before` (YYYY-MM-DD) — no leakage.
"""
import re
import unicodedata
from datetime import date as _date


def norm_horse(h):
    s = unicodedata.normalize("NFD", str(h or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s)
    return " ".join(s.split())


def canon_def(s):
    u = (s or "").upper().replace(" ", "")
    if not u:
        return None
    if u in ("-", "FF", "FERRE"):
        return "FERRE"
    if u.startswith("PROTEGE"):
        return "PLAQUE"
    if u == "D4" or ("ANTERIEURS" in u and "POSTERIEURS" in u):
        return "D4"
    if u in ("DA", "DD"):
        return u
    if "ANTERIEURS" in u:
        return "DA"
    if u == "DP" or "POSTERIEURS" in u:
        return "DP"
    return "OTHER"


def poids_kg(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    if f <= 0 or f > 900:
        return None
    return f / 10.0 if f > 200 else f


def surname(tr):
    toks = [t for t in str(tr or "").upper().replace(".", " ").split() if len(t) > 1]
    return max(toks, key=len) if toks else None


def _pts_place(rang):
    return {1: 5, 2: 4, 3: 3, 4: 2, 5: 1}.get(rang, 0)


def compute_field_plot(conn, participants, before=None, cur_dist=None, cur_surf=None):
    """Batched plot signals for a whole field. Returns {num: sig-dict}."""
    if not before:
        before = _date.today().isoformat()
    before = str(before)[:10]
    try:
        cur_dist_f = float(cur_dist) if cur_dist else None
    except (TypeError, ValueError):
        cur_dist_f = None

    # distinct horses in field
    elig = []
    for p in participants or []:
        try:
            num = p.get("num")
        except AttributeError:
            continue
        if num is None:
            continue
        elig.append((num, p.get("horse"), p.get("trainer"), p.get("deferre")))
    by_norm = {}
    for num, horse, trainer, deferre in elig:
        by_norm.setdefault(norm_horse(horse), []).append((num, horse, trainer, deferre))

    # one indexed query per spelling group, merged by normalized name
    runs = {}
    for nh, group in by_norm.items():
        spellings = list({g[1] for g in group if g[1]})
        if not spellings:
            continue
        ph = ",".join("?" * len(spellings))
        try:
            rows = conn.execute(
                "SELECT p.horse, r.date, p.race_id, p.rang, p.deferre, p.poids, "
                "r.distance, r.surface, r.going, r.corde FROM participants p "
                "JOIN races r ON r.race_id=p.race_id "
                "WHERE p.horse IN (%s) AND p.rang IS NOT NULL AND r.date < ?" % ph,
                (*spellings, before)).fetchall()
        except Exception:
            rows = []
        for r in rows:
            try:
                runs.setdefault(nh, []).append(dict(r))
            except (TypeError, ValueError):
                runs.setdefault(nh, []).append(
                    {"horse": r[0], "date": r[1], "race_id": r[2], "rang": r[3],
                     "deferre": r[4], "poids": r[5], "distance": r[6],
                     "surface": r[7], "going": r[8], "corde": r[9]})

    # trainer form, last 14d before `before` (single range query)
    tform = {}
    try:
        rows = conn.execute(
            "SELECT p.trainer, p.rang FROM participants p JOIN races r ON r.race_id=p.race_id "
            "WHERE r.date >= date(?, '-14 days') AND r.date < ? AND p.rang IS NOT NULL "
            "AND p.trainer IS NOT NULL AND TRIM(p.trainer) <> ''", (before, before)).fetchall()
        agg = {}
        for x in rows:
            try:
                s = surname(x[0])
                rk = x[1]
            except (TypeError, ValueError, IndexError):
                continue
            if not s:
                continue
            a = agg.setdefault(s, [0, 0])
            a[0] += 1
            if rk == 1:
                a[1] += 1
        for s, (n, w) in agg.items():
            if n >= 8:
                tform[s] = (round(w / n, 3), n)
    except Exception:
        pass

    out = {}
    for nh, group in by_norm.items():
        hrs = sorted(runs.get(nh, []), key=lambda r: r.get("date", ""), reverse=True)
        for num, horse, trainer, deferre in group:
            sig = {"runs_n": len(hrs), "trainer_rate": None, "trainer_n": 0,
                   "days_since_win": None, "back_to_win": False,
                   "first_d4": False, "cur_cfg": canon_def(deferre),
                   "winless180": False, "ctx": None}
            s = surname(trainer)
            if s and s in tform:
                sig["trainer_rate"], sig["trainer_n"] = tform[s]
            wins = [r for r in hrs if r.get("rang") == 1]
            if wins:
                try:
                    from datetime import date as _d
                    lastw = max(r.get("date", "") for r in wins)
                    sig["days_since_win"] = (_d.fromisoformat(before) - _d.fromisoformat(lastw)).days
                except (TypeError, ValueError):
                    pass
                if sig["days_since_win"] is not None and sig["days_since_win"] >= 180 and len(hrs) >= 3:
                    sig["winless180"] = True
                # most recent win conditions vs today
                w0 = sorted(wins, key=lambda r: r.get("date", ""), reverse=True)[0]
                try:
                    okd = (cur_dist_f and w0.get("distance")
                           and abs(float(w0["distance"]) - cur_dist_f) <= 200)
                except (TypeError, ValueError):
                    okd = False
                oks = bool(cur_surf and w0.get("surface") and str(w0["surface"]) == str(cur_surf))
                if okd and (oks or not cur_surf):
                    sig["back_to_win"] = True
            else:
                if len(hrs) >= 3:
                    sig["days_since_win"] = 9999
                    sig["winless180"] = True
            if sig["cur_cfg"] == "D4":
                past_cfg = {canon_def(r.get("deferre")) for r in hrs}
                if "D4" not in past_cfg and len(hrs) >= 3:
                    sig["first_d4"] = True
            # contextual form score (F1)
            tot = wsum = 0.0
            dmin = dmax = None
            for idx, r in enumerate(hrs[:8]):
                try:
                    _dd = float(r.get("distance")) if r.get("distance") is not None else None
                except (TypeError, ValueError):
                    _dd = None
                if _dd is not None:
                    dmin = _dd if dmin is None else min(dmin, _dd)
                    dmax = _dd if dmax is None else max(dmax, _dd)
                w = 1.0 / (1 + 0.15 * idx)
                if cur_dist_f and r.get("distance"):
                    try:
                        if abs(float(r["distance"]) - cur_dist_f) <= 200:
                            w += 0.8
                    except (TypeError, ValueError):
                        pass
                if cur_surf and r.get("surface") and str(r["surface"]) == str(cur_surf):
                    w += 0.6
                tot += w * _pts_place(r.get("rang"))
                wsum += w
            if wsum > 0 and len(hrs) >= 2:
                sig["ctx"] = round(tot / wsum, 3)
            sig["dist_lo"] = dmin
            sig["dist_hi"] = dmax
            out[num] = sig
    return out


def _is_fav_layer(layer_fam, cote=None):
    if layer_fam:
        return str(layer_fam).upper() == "FAV"
    try:
        return cote is not None and float(cote) <= 10
    except (TypeError, ValueError):
        return False


def _valid_runners(participants):
    """[(cote_float, participant)] sorted, non-partants excluded (same rule as engine)."""
    _NP = ("NP", "NON PARTANT", "NON-PARTANT", "NON_PARTANT", "NONPARTANT",
           "FORFAIT", "RETIRE", "RETIRÉ", "SCRATCHED", "OUT", "ABSENT")
    out = []
    for p in participants or []:
        try:
            if str(p.get("rang")) == "NP":
                continue
            bad = False
            for k in ("etat", "statut", "status"):
                v = p.get(k)
                if isinstance(v, str) and v.strip().upper() in _NP:
                    bad = True
                    break
            if bad:
                continue
            for k in ("nonPartant", "non_partant", "forfait", "retire"):
                if p.get(k) is True:
                    bad = True
                    break
            if bad:
                continue
            c = p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
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


def flip_tickets(participants, plot_map=None, min_hidden_ctx=None):
    """Flipped structures: fav#1 × hidden outsiders (ctx-ranked, market rank>=6).

    Returns {"cplB": [(n1,n2)]*3 or [], "trioB": [n,n,n] or []}.
    Honest abstention: missing pieces -> empty (counted in n).
    """
    plot_map = plot_map or {}
    ranked = _valid_runners(participants)
    if len(ranked) < 5:
        return {"cplB": [], "trioB": []}
    market_rank = {p.get("num"): i + 1 for i, (_v, p) in enumerate(ranked)}
    fav1 = ranked[0][1].get("num")
    houts = sorted(
        [n for n, s in plot_map.items()
         if market_rank.get(n, 99) >= 6 and (s.get("ctx") is not None)],
        key=lambda n: -plot_map[n]["ctx"])
    res = {"cplB": [], "trioB": []}
    if fav1 is not None and len(houts) >= 3:
        res["cplB"] = [(fav1, houts[0]), (fav1, houts[1]), (fav1, houts[2])]
    if fav1 is not None and len(houts) >= 2:
        res["trioB"] = [fav1, houts[0], houts[1]]
    return res


def plot_bonus_for_quinte(sig, layer_fam=None, cote=None):
    """Confirm contenders only. Returns (pts<=3, [reasons])."""
    if not _is_fav_layer(layer_fam, cote):
        return 0, []
    sig = sig or {}
    pts, reasons = 0, []

    def add(p, label):
        nonlocal pts
        room = 3 - pts
        if room <= 0:
            return
        pts += min(p, room)
        reasons.append(label)

    if (sig.get("trainer_n") or 0) >= 8 and (sig.get("trainer_rate") or 0) >= 0.25:
        add(2, "entraîneur chaud %d%%" % round(100 * sig["trainer_rate"]))
    if sig.get("back_to_win"):
        add(2, "retour conditions victoire")
    if sig.get("first_d4"):
        add(1, "1er D4")
    if sig.get("winless180"):
        d = sig.get("days_since_win")
        add(1, "sans victoire %dj" % d if isinstance(d, int) and d < 9000 else "sans victoire 180j+")
    return pts, reasons


def expert_ranking(participants, plot_map=None, cur_dist=None):
    """TRUE reading: every horse judged by the same eye, no market anchor.

    score = ctx (0-5) + T2 +2 + T4 +2 + D4 +1 + T3 +1
            - TRAP-fakeform 1.5 - TRAP-first-dist 1.5
    Cote never enters. Favorites and outsiders compete equally.
    Returns [(score, num, [reasons])] best-first.
    """
    _NP = ("NP", "NON PARTANT", "NON-PARTANT", "NON_PARTANT", "NONPARTANT",
           "FORFAIT", "RETIRE", "RETIRÉ", "SCRATCHED", "OUT", "ABSENT")
    plot_map = plot_map or {}
    try:
        cur_f = float(cur_dist) if cur_dist else None
    except (TypeError, ValueError):
        cur_f = None

    def _out(p):
        try:
            if str(p.get("rang")) == "NP":
                return True
            for k in ("etat", "statut", "status"):
                v = p.get(k)
                if isinstance(v, str) and v.strip().upper() in _NP:
                    return True
            for k in ("nonPartant", "non_partant", "forfait", "retire"):
                if p.get(k) is True:
                    return True
        except AttributeError:
            return True
        return False

    field = [p for p in (participants or []) if not _out(p) and p.get("num") is not None]
    have = [(p.get("num"), (plot_map.get(p.get("num")) or {}).get("ctx"))
            for p in field]
    have = [(n, c) for n, c in have if c is not None]
    order = [n for n, _ in sorted(have, key=lambda x: -x[1])]
    scored = []
    for p in field:
        num = p.get("num")
        s = plot_map.get(num, {}) or {}
        score = float(s.get("ctx") or 0.0)
        reasons = []
        if (s.get("trainer_n") or 0) >= 8 and (s.get("trainer_rate") or 0) >= 0.25:
            score += 2
            reasons.append("T2")
        if s.get("back_to_win"):
            score += 2
            reasons.append("T4")
        if s.get("first_d4"):
            score += 1
            reasons.append("D4")
        if s.get("winless180"):
            score += 1
            reasons.append("T3")
        if s.get("ctx") is not None and len(order) >= 5 and order.index(num) >= len(order) / 2:
            score -= 1.5
            reasons.append("TRAP-fake")
        lo, hi = s.get("dist_lo"), s.get("dist_hi")
        try:
            if (lo is not None and hi is not None and cur_f is not None
                    and (cur_f < float(lo) - 200 or cur_f > float(hi) + 200)):
                score -= 1.5
                reasons.append("TRAP-dist")
        except (TypeError, ValueError):
            pass
        scored.append((round(score, 2), num, reasons))
    scored.sort(key=lambda x: (-x[0], x[1]))
    return scored


def trap_of_fav(plot_map, ranked_nums, cur_dist=None):
    """Red flags on the market favorite (measured: 2 flags -> wins ~23% vs 35%).

    Flags (same definitions as measurement):
    1. fakeform: fav ctx in bottom half of field ctx (needs >=5 ctx values).
    2. first-dist: today distance outside [min,max] of recent distances by >200m.
    Returns (count, [labels]).
    """
    plot_map = plot_map or {}
    ranked_nums = list(ranked_nums or [])
    if not ranked_nums:
        return 0, []
    try:
        cur_f = float(cur_dist) if cur_dist else None
    except (TypeError, ValueError):
        cur_f = None
    fav = ranked_nums[0]
    fsig = plot_map.get(fav, {}) or {}
    flags = []
    have_ctx = [n for n in ranked_nums if (plot_map.get(n, {}) or {}).get("ctx") is not None]
    if fsig.get("ctx") is not None and len(have_ctx) >= 5:
        order = sorted(have_ctx, key=lambda n: -plot_map[n]["ctx"])
        if order.index(fav) >= len(order) / 2:
            flags.append("fakeform")
    lo, hi = fsig.get("dist_lo"), fsig.get("dist_hi")
    try:
        if (lo is not None and hi is not None and cur_f is not None
                and (cur_f < float(lo) - 200 or cur_f > float(hi) + 200)):
            flags.append("first-dist")
    except (TypeError, ValueError):
        pass
    return len(flags), flags
