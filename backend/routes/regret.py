from flask import Blueprint, jsonify, request

regret_bp = Blueprint("regret", __name__)

@regret_bp.before_request
def _guard():
    from routes.auth import require_session
    if request.method == 'OPTIONS':
        return None
    return require_session()


@regret_bp.route("/api/regret/analyze", methods=["POST"])
def regret_analyze():
    body = request.get_json(silent=True) or {}
    participants = body.get("participants") or []
    if not participants:
        return jsonify({"error": "No participants"}), 400
    hippodrome = body.get("hippodrome") or ""
    distance = body.get("distance") or 0
    race_date = body.get("date")
    discipline = body.get("discipline", "") or None
    runners = body.get("runners") or len(participants)
    min_odds = body.get("min_odds", 12.0)

    from REGRET.regret import analyze_regret  # moteur indépendant backend/REGRET/
    # Flags (A/B testing only, production defaults = legacy):
    #   use_v3_regret  -> Regret = P4 of the coherent COUPLE V3 Top3
    #   p2p3_allocation -> legacy engine but final pick respects P2/P3
    use_v3 = bool(body.get("use_v3_regret", False))
    p2p3 = bool(body.get("p2p3_allocation", False))
    coherent_top3 = None
    coherent_info = None
    if use_v3:
        # Top3 cohérent V3 (même scénario DNA) -> le Regret en dérive (P4 du scénario).
        try:
            from COUPLE.service import match_small_couple, get_small_top3_stats
            _hist = get_small_top3_stats(limit=3000, before=race_date)
            _m = match_small_couple(participants, _hist)
            _by_key = {r.get("key"): r for r in (_m or [])}
            if "P1-P2" in _by_key and "P2-P3" in _by_key:
                _p1 = _by_key["P1-P2"]["horses"][0]["num"]
                _p2 = _by_key["P1-P2"]["horses"][1]["num"]
                _p3 = _by_key["P2-P3"]["horses"][1]["num"]
                if len({_p1, _p2, _p3}) == 3:
                    coherent_top3 = [_p1, _p2, _p3]
                    _d0 = (_by_key["P1-P2"].get("details") or {})
                    coherent_info = {"pattern": _d0.get("pattern"),
                                     "support": _d0.get("pattern_support"),
                                     "level": _d0.get("level")}
        except Exception:
            coherent_top3 = None
    result = analyze_regret(
        participants,
        hippodrome=hippodrome,
        distance=distance,
        discipline=discipline,
        race_date=race_date,
        min_odds=min_odds,
        coherent_top3=coherent_top3,
        coherent_info=coherent_info,
        p2p3_allocation=p2p3,
    )
    if result is None:
        return jsonify({"error": "No participants"}), 400
    result["filters"] = {"runners": runners}
    result["card"] = "regret"
    return jsonify(result)