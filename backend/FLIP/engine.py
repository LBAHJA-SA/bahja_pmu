"""FLIP — the same tickets the COUPLE engine already gives, plus a record.

WHAT CHANGED, and why, in one paragraph because the earlier version was wrong:

This page used to run its own rule — the market favourite against three horses
ranked sixth or worse whose archive reading was strong. That rule was measured
on 193 real races at every cutoff from 2 to 8 and lost to the market at every
one of them, from 10 points worse to 24 points worse. The cutoff also made the
rule arithmetically impossible on any field under eight runners, while the page
it was built for is about small fields. So it is gone.

What the page does now is take the three couples the COUPLE engine already
produces — the ALFARAJ trio on fields of ten or more, the V3 Top3 patterns
under ten, exactly what TROT and GALOP read — and record them, one at a time,
beside the real finish order. The point of the page is no longer to invent a
bet. It is to answer two questions about a bet that already exists: does it
win, and does the hour at which it was read change the answer.

THE SAME RACE, READ SEVERAL TIMES. A prediction is no longer overwritten. Each
press of the button is an attempt, and attempts for one race are shown one
under the other, because that is the only way to see whether reading a race
six hours before the off gives a different — or better — ticket than reading it
half an hour before. The delay of every attempt is kept exactly, in minutes,
and nothing is grouped or banded: the reader decides which hours matter.

What "won" means, and it is the same for every attempt: a couplé needs both
horses in the top 2, in any order.
"""
from typing import Any, Dict, List, Optional

# The page covers fields of four runners to twenty. Under four there is no room
# for a couplé worth making; over twenty the market's core is so long that the
# ticket stops saying anything.
MIN_FIELD = 4
MAX_FIELD = 20

NOT_RUNNING = (
    "NP", "NON PARTANT", "NON-PARTANT", "NON_PARTANT", "NONPARTANT",
    "FORFAIT", "RETIRE", "RETIRE%", "SCRATCHED", "OUT", "ABSENT",
)


def cote_of(p: Dict[str, Any]) -> Optional[float]:
    c = p.get("cote_pmu")
    if c is None or str(c).strip() == "":
        c = p.get("cote")
    if c is None or str(c).strip() == "":
        return None
    try:
        v = float(c)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def priced_runners(participants: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Every runner that has a usable price, ascending, non-participants dropped.

    Sorted by (cote, num) so a tie on price keeps a stable order — the same race
    must always produce the same ticket, or nothing here is repeatable.
    """
    out = []
    for p in participants or []:
        if not isinstance(p, dict) or str(p.get("num")) == "NP":
            continue
        skip = False
        for k in ("etat", "statut", "status"):
            v = p.get(k)
            if isinstance(v, str) and v.strip().upper() in NOT_RUNNING:
                skip = True
                break
        if not skip:
            for k in ("nonPartant", "non_partant", "forfait", "retire"):
                if p.get(k) is True:
                    skip = True
                    break
        if skip:
            continue
        v = cote_of(p)
        if v is None:
            continue
        out.append({"num": p.get("num"), "horse": p.get("horse"), "cote": v})
    out.sort(key=lambda h: (h["cote"], h["num"] if h["num"] is not None else 0))
    for i, h in enumerate(out):
        h["market_rank"] = i + 1
    return out


def market_baseline(ranked: List[Dict[str, Any]],
                    rang_by_num: Dict[Any, int]) -> Dict[str, Any]:
    """What the market's own second, third and fourth choice would have won.

    The number the rule has to beat. A method that finds fewer winning couples
    than simply taking 1st x 2nd favourite is not finding anything.
    """
    by_rank = {h["market_rank"]: h for h in ranked}
    fav = by_rank.get(1)
    if not fav:
        return {"available": False}
    fav_r = rang_by_num.get(fav["num"])
    out = {"available": True, "fav_num": fav["num"], "fav_horse": fav.get("horse"),
           "fav_rank": fav_r, "rows": []}
    for i in (2, 3, 4):
        o = by_rank.get(i)
        if not o:
            continue
        o_r = rang_by_num.get(o["num"])
        out["rows"].append({
            "key": "M-%d" % (i - 1), "out_num": o["num"], "out_horse": o.get("horse"),
            "out_market_rank": i, "fav_rank": fav_r, "out_rank": o_r,
            "couple_hit": bool(fav_r and o_r and fav_r <= 2 and o_r <= 2),
            "both_top3": bool(fav_r and o_r and fav_r <= 3 and o_r <= 3),
        })
    out["any_couple"] = any(r["couple_hit"] for r in out["rows"])
    out["any_both_top3"] = any(r["both_top3"] for r in out["rows"])
    return out


def normalise(matches: List[Dict[str, Any]],
              ranked: List[Dict[str, Any]],
              field_n: int) -> Dict[str, Any]:
    """Turn the COUPLE engine's three pairs into this page's ticket.

    The pairs are taken exactly as the COUPLE engine returned them. Nothing is
    re-ranked, re-picked or added: if the engine gave three couples, there are
    three couples here, and the only thing this function does is attach the
    market rank to each horse so the page can show what the market thought.
    """
    board = priced_runners([])
    rank_of = {h["num"]: h for h in ranked}
    by_num = {}
    for h in ranked:
        by_num[h["num"]] = h

    pairs = []
    for m in (matches or [])[:3]:
        horses = []
        for h in (m.get("horses") or []):
            n = h.get("num")
            r = by_num.get(n) or {}
            horses.append({
                "num": n, "horse": h.get("horse") or r.get("horse"),
                "market_rank": r.get("market_rank"),
                "cote": r.get("cote"), "fam": h.get("fam"),
            })
        if len(horses) < 2:
            continue
        pairs.append({
            "key": m.get("key") or "P%d" % (len(pairs) + 1),
            "sub_key": m.get("sub_key"),
            "support": m.get("count"),
            "pattern": (m.get("details") or {}).get("pattern"),
            "horses": horses,
        })

    board = ranked
    return {
        "ok": bool(pairs),
        "reason": None if pairs else "no_pairs",
        "reason_fr": None if pairs else "le moteur COUPLE n'a donné aucune paire sur ce champ",
        "pairs": pairs,
        "board": board,
        "favourite": board[0] if board else None,
        "field_n": field_n,
        "priced_n": len(ranked),
        "field_range": [MIN_FIELD, MAX_FIELD],
    }


def check_field(participants: List[Dict[str, Any]]) -> Optional[str]:
    """The French reason this field is out of range, or None if it is fine."""
    n = len(priced_runners(participants))
    if n < MIN_FIELD:
        return ("champ trop petit : %d partants cotés, il en faut %d"
                % (n, MIN_FIELD))
    if n > MAX_FIELD:
        return ("champ trop grand : %d partants cotés, la page va jusqu'à %d"
                % (n, MAX_FIELD))
    return None


def score(ticket: Dict[str, Any], rang_by_num: Dict[Any, int]) -> Dict[str, Any]:
    """Compare a ticket with the real finish order. Pure arithmetic, no I/O."""
    rows = []
    for p in ticket.get("pairs") or []:
        hs = p["horses"]
        a_r = rang_by_num.get(hs[0].get("num"))
        b_r = rang_by_num.get(hs[1].get("num"))
        rows.append({
            "key": p["key"],
            "a_num": hs[0].get("num"), "a_horse": hs[0].get("horse"),
            "b_num": hs[1].get("num"), "b_horse": hs[1].get("horse"),
            "a_rank": a_r, "b_rank": b_r,
            "couple_hit": bool(a_r and b_r and a_r <= 2 and b_r <= 2),
            "both_top3": bool(a_r and b_r and a_r <= 3 and b_r <= 3),
        })
    return {
        "rows": rows,
        "any_couple": any(r["couple_hit"] for r in rows),
        "any_both_top3": any(r["both_top3"] for r in rows),
        "n_pairs": len(rows),
    }


def tally(scored: List[Dict[str, Any]]) -> Dict[str, Any]:
    """One honest number per claim, each with its own denominator."""
    n = len(scored)
    if not n:
        return {"races": 0}

    def pct(k, d=None):
        d = d or n
        return round(100.0 * k / d, 1) if d else 0.0

    cpl = sum(1 for m in scored if m.get("any_couple"))
    t3 = sum(1 for m in scored if m.get("any_both_top3"))
    per_key = {}
    for m in scored:
        for r in m.get("rows") or []:
            k = r["key"]
            b = per_key.setdefault(k, {"n": 0, "couple": 0, "top3": 0})
            b["n"] += 1
            b["couple"] += 1 if r["couple_hit"] else 0
            b["top3"] += 1 if r["both_top3"] else 0
    for b in per_key.values():
        b["couple_pct"] = round(100.0 * b["couple"] / b["n"], 1) if b["n"] else 0.0
        b["top3_pct"] = round(100.0 * b["top3"] / b["n"], 1) if b["n"] else 0.0
    return {
        "races": n,
        "any_couple": {"k": cpl, "pct": pct(cpl)},
        "any_both_top3": {"k": t3, "pct": pct(t3)},
        "per_key": per_key,
    }
