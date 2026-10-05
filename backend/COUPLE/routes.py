from flask import Blueprint, jsonify, request
from .service import get_small_top3_stats, match_small_couple, explain_candidates, _market_family

couple_bp = Blueprint("couple_dna", __name__, url_prefix="/api/couple")

@couple_bp.before_request
def _guard():
    from routes.auth import require_session
    if request.method == 'OPTIONS' or request.path.endswith('/health'):
        return None
    return require_session()

@couple_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"ok","module":"COUPLE DNA","version":"1.0.0","scope":"Petites courses <12, Top3 Couple/Jumelé"})

@couple_bp.route("/stats", methods=["GET"])
def stats():
    limit=request.args.get("limit", type=int) or 3000
    data=get_small_top3_stats(limit=limit)
    return jsonify(data)

@couple_bp.route("/extract", methods=["POST"])
def extract():
    body=request.get_json(silent=True) or {}
    participants=body.get("participants") or []
    if not participants:
        return jsonify({"error":"No participants"}),400
    runners = body.get("runners") or len(participants)
    try:
        runners = int(runners)
    except (TypeError, ValueError):
        runners = len(participants)

    _memo = {}

    def _pmap():
        if "m" not in _memo:
            try:
                from database import get_db as _gdb
                from signals.plot_signals import compute_field_plot
                try:
                    _dist = int(body.get("distance") or 0) or None
                except (TypeError, ValueError):
                    _dist = None
                _pc = _gdb()
                try:
                    _memo["m"] = compute_field_plot(_pc, participants, before=body.get("date"),
                                                    cur_dist=_dist)
                finally:
                    _pc.close()
            except Exception:
                _memo["m"] = {}
        return _memo["m"]

    def _expert_payload():
        """Expert: true reading, no market anchor. Trio top3 + 8."""
        from signals.plot_signals import expert_ranking
        try:
            ranked = expert_ranking(participants, _pmap(),
                                    cur_dist=(int(body.get("distance") or 0) or None))
        except Exception:
            ranked = []
        bynum = {p.get("num"): p.get("horse") for p in participants}
        trio = [{"num": n, "horse": bynum.get(n), "target_pos": i + 1,
                 "score": s, "reasons": rs} for i, (s, n, rs) in enumerate(ranked[:3])]
        huit = [{"num": n, "horse": bynum.get(n), "target_pos": None,
                 "score": s, "reasons": rs} for (s, n, rs) in ranked[:8]]
        return {"trio": trio, "huit": huit}

    def _flip_payload():
        """Flipped tickets: fav#1 x hidden outsiders (same stakes as classic)."""
        from signals.plot_signals import flip_tickets as _ft
        pmap = _pmap()
        ft = _ft(participants, pmap)
        bynum = {}
        rankm = {}
        try:
            _priced = sorted(
                [p for p in participants
                 if p.get("cote_pmu") is not None or p.get("cote") is not None],
                key=lambda p: (float(p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")), p.get("num")))
            for _i, _p in enumerate(_priced):
                rankm[_p.get("num")] = _i + 1
        except (TypeError, ValueError):
            pass
        for p in participants:
            bynum[p.get("num")] = p.get("horse")
        return {
            "couple": [{"key": f"F-O{i+1}", "type": "Flip",
                        "horses": [{"num": a, "horse": bynum.get(a), "market_rank": rankm.get(a, 99)},
                                   {"num": b, "horse": bynum.get(b), "market_rank": rankm.get(b, 99)}],
                        "details": {"pattern": "fav-x-hidden"}}
                       for i, (a, b) in enumerate(ft["cplB"])],
            "trio": [{"num": n, "horse": bynum.get(n), "target_pos": None,
                      "market_rank": rankm.get(n, 99)} for n in ft["trioB"]],
        }
    # Coherence rule: the V3 pattern engine is trained on runners<12.
    # For fields >=10, Couple is derived from the SAME ALFARAJ trio
    # (structural P1..P3) so Couple/Trio/Quinté tell one story.
    if runners >= 10:
        try:
            from QUINTE.service import get_quinte_top5_stats, trio_infiltre
            hippodrome = body.get("hippodrome")
            if isinstance(hippodrome, dict):
                hippodrome = hippodrome.get("libelleLong") or hippodrome.get("libelleCourt") or ""
            disc = body.get("disc") or body.get("discipline") or body.get("disciplineFamily")
            if isinstance(disc, dict):
                disc = disc.get("disc_canonical") or disc.get("family") or ""
            try:
                distance = int(body.get("distance") or 0) or None
            except (TypeError, ValueError):
                distance = None
            before = body.get("date")
            def _support(h):
                try:
                    return sum(1 for c in (h.get("family_counter") or {}).values() if int(c or 0) >= 5)
                except Exception:
                    return 0
            hist = get_quinte_top5_stats(limit=4054, before=before, hippodrome=hippodrome, disc=disc, distance=distance, runners=runners)
            if _support(hist) < 1:
                hist = get_quinte_top5_stats(limit=4054, before=before, hippodrome=hippodrome, disc=disc)
            if _support(hist) < 1:
                hist = get_quinte_top5_stats(limit=4054, before=before, disc=disc)
            trio, _lvl = trio_infiltre(participants, hist, disc=disc, before=before, distance=distance)
            trio = [t for t in (trio or []) if t.get("target_pos") in (1, 2, 3) and not t.get("reserve")]
            trio.sort(key=lambda t: t.get("target_pos", 99))
            if len(trio) >= 3:
                # market ranks for display (defensive: skip bad cotes)
                def _cote(p):
                    try:
                        v = float(p.get("cote_pmu"))
                        return v if v > 0 else None
                    except (TypeError, ValueError):
                        return None
                priced = sorted(
                    [p for p in participants if _cote(p) is not None],
                    key=lambda p: (_cote(p), p.get("num")))
                rank_map = {p.get("num"): i + 1 for i, p in enumerate(priced)}
                t1, t2, t3 = trio[0], trio[1], trio[2]
                pairs = [(t1, t2), (t1, t3), (t2, t3)]
                keys = ["P1-P2", "P1-P3", "P2-P3"]
                matched = []
                for key, (pa, pb) in zip(keys, pairs):
                    fa = _market_family(pa.get("cote") if pa.get("cote") is not None else pa.get("cote_pmu"))
                    fb = _market_family(pb.get("cote") if pb.get("cote") is not None else pb.get("cote_pmu"))
                    matched.append({
                        "type": "Couple", "key": key, "sub_key": f"{fa}-{fb}",
                        "horses": [
                            {"num": pa.get("num"), "horse": pa.get("horse"),
                             "market_rank": rank_map.get(pa.get("num"), 99), "fam": fa},
                            {"num": pb.get("num"), "horse": pb.get("horse"),
                             "market_rank": rank_map.get(pb.get("num"), 99), "fam": fb},
                        ],
                        "score": None, "count": None,
                        "details": {"pattern": "alfaraj-trio", "level": "trio",
                                    "pattern_support": None},
                    })
                resp = {"hist": {"coherent": True, "source": "alfaraj-trio"}, "matches": matched}
                try:
                    resp["flip"] = _flip_payload()
                except Exception:
                    pass
                try:
                    resp["expert"] = _expert_payload()
                except Exception:
                    pass
                if body.get("explain"):
                    resp["alternatives"] = []
                return jsonify(resp)
        except Exception as e:
            return jsonify({"error": f"coherent couple failed: {str(e)[:200]}"}), 500
    hist=get_small_top3_stats(limit=3000, before=body.get("date"))
    matched=match_small_couple(participants, hist)
    resp={"hist": hist, "matches": matched}
    try:
        resp["flip"] = _flip_payload()
    except Exception:
        pass
    try:
        resp["expert"] = _expert_payload()
    except Exception:
        pass
    if body.get("explain"):
        try:
            resp["alternatives"] = explain_candidates(participants, hist, top_n=int(body.get("explain_top_n", 3)))
        except Exception as e:
            resp["alternatives_error"] = str(e)[:200]
    return jsonify(resp)

@couple_bp.route("/analyze", methods=["POST"])
def analyze():
    return extract()
