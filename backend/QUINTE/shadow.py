"""
Shadow Mode — diagnostic only. Never touches the ticket.
Baseline ticket = synthese_match (original, market tiebreak). Shadow signals
are computed alongside and compared to the real arrivee, read-only.
"""
import re
from collections import defaultdict

_FORM_PTS = {1: 10.0, 2: 7.0, 3: 5.0, 4: 3.0, 5: 2.0, 6: 1.0, 7: 1.0, 8: 1.0, 9: 1.0}
_FORM_K = 6


def _form_score_shadow(musique, k=_FORM_K):
    """Shadow form score — identical to the candidate that was reverted.
    Not used in any selection; scored here only for correlation vs arrivee."""
    if not musique:
        return 0.0
    s = str(musique).strip()
    if not s:
        return 0.0
    runs = []
    for m in re.finditer(r"(\d+)?([A-Za-z]+)?", s):
        digits, letters = m.group(1), (m.group(2) or "")
        if not digits and not letters:
            continue
        if digits:
            rest = digits
            while rest:
                if len(rest) > 2 or (len(rest) == 2 and int(rest) > 20):
                    runs.append(int(rest[0]))
                    rest = rest[1:]
                else:
                    runs.append(int(rest))
                    rest = ""
        else:
            if "d" in letters.lower():
                runs.append(99)
    scored = []
    for place in runs[:k]:
        scored.append(_FORM_PTS.get(place, 0.0))
    return sum(scored) / len(scored) if scored else 0.0


def shadow_for_race(participants, baseline_ticket, top5, zones_by_place=None):
    """Compare baseline picks vs form-only picks inside each zone.
    Returns a dict with per-zone diagnostics, no selection change."""
    if zones_by_place is None:
        return {}
    # zones_by_place: {num: zone} from display order (same as baseline)
    # Build per-zone horse lists with form
    zone_horses = defaultdict(list)
    for p in participants:
        n = p.get("num")
        z = zones_by_place.get(n)
        if z is None:
            continue
        zone_horses[z].append((p, _form_score_shadow(p.get("musique"))))

    diag = {}
    tset = set(top5 or [])
    bset = set(baseline_ticket or [])
    for z in ("A", "B", "C", "D"):
        horses = zone_horses.get(z, [])
        if not horses:
            continue
        # form-ranked within zone
        form_sorted = sorted(horses, key=lambda x: (-x[1], x[0].get("num") or 999))
        form_pick = [p.get("num") for p, _ in form_sorted]
        # baseline picks that belong to this zone
        base_in_zone = [n for n in baseline_ticket if zones_by_place.get(n) == z]
        diag[z] = {
            "zone_size": len(horses),
            "baseline_in_zone": base_in_zone,
            "form_sorted_top3": [
                {"num": p.get("num"), "form": round(s, 2), "in_top5": p.get("num") in tset}
                for p, s in form_sorted[:3]
            ],
            "form_hit_in_top5": sum(1 for p, _ in horses if p.get("num") in tset and p.get("num") == form_sorted[0][0].get("num")) if horses else 0,
            "baseline_hits": sum(1 for n in base_in_zone if n in tset),
            "zone_top5_count": sum(1 for p, _ in horses if p.get("num") in tset),
        }
    return diag
