from flask import Blueprint, request, jsonify
from QUINTE.synthese_service import synthese_fingerprint, synthese_match

synthese_dna_bp = Blueprint('synthese_dna', __name__)

@synthese_dna_bp.route('/api/synthese/fingerprint', methods=['POST'])
def fingerprint():
    data = request.get_json(silent=True) or {}
    participants = data.get('participants', [])
    res = synthese_fingerprint(
        participants,
        hippodrome=data.get('hippodrome'),
        distance=data.get('distance'),
        runners=data.get('runners')
    )
    pool = res.get("pool", [])
    return jsonify({
        "structures": len(pool),
        "level": len(pool),
        "top": [{"signature": s["signature"], "count": s["count"]} for s in pool[:3]],
        "hist_n": res["hist"].get("total_top5_races", 0)
    })

@synthese_dna_bp.route('/api/synthese/match', methods=['POST'])
def match():
    data = request.get_json(silent=True) or {}
    participants = data.get('participants', [])
    results, support = synthese_match(
        participants,
        hippodrome=data.get('hippodrome'),
        distance=data.get('distance'),
        runners=data.get('runners'),
        presse=data.get('presse', data.get('presse14')),
        disc=data.get('disc') or data.get('discipline')
    )
    return jsonify({"matches": results, "support": support,
                    "level": support.get("structures", 0)
                    if isinstance(support, dict) else support})


@synthese_dna_bp.route('/api/synthese/match-by-date', methods=['POST'])
def match_by_date():
    """TRUE RACE DNA direct depuis l'archive (pas de Geny live).
    Retourne les 8 chevaux (4-1-1-2) choisis par la بصمة pour le Quinté de cette date."""
    from database import get_db
    data = request.get_json(silent=True) or {}
    date = (data.get('date') or '').strip()
    if not date:
        return jsonify({"error": "date required (YYYY-MM-DD)"}), 400
    conn = get_db()
    row = conn.execute(
        "SELECT * FROM races "
        "WHERE date=? AND quinte=1 ORDER BY race_id LIMIT 1", (date,)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error": "no-archive", "message": "Aucun Quinté archivé pour cette date"}), 404
    race = dict(row)
    parts = [dict(x) for x in conn.execute(
        "SELECT * FROM participants WHERE race_id=?", (race["race_id"],)).fetchall()]
    # Presse TRUE first: presse_synthese table (same source as /api/synthese).
    # Market sort is fallback only, so zones stay presse zones (4-1-1-2).
    presse = None
    try:
        import json as _json
        pr = conn.execute("SELECT synthese FROM presse_synthese WHERE date=?", (date,)).fetchone()
        if pr and pr["synthese"]:
            nums = _json.loads(pr["synthese"]) if isinstance(pr["synthese"], str) else pr["synthese"]
            nums = [int(n) for n in (nums or []) if n is not None]
            if len(nums) >= 14:
                presse = nums[:18]
    except Exception:
        presse = None
    conn.close()
    if not parts:
        return jsonify({"error": "no-participants", "message": "Participants non trouvés"}), 404
    if presse is None:
        presse = [dict(x)["num"] for x in sorted(
            parts, key=lambda p: ((p.get("cote_pmu") is None),
                                  p.get("cote_pmu") if p.get("cote_pmu") is not None else 999,
                                  p.get("num") or 999))][:16]
    results, support = synthese_match(
        parts,
        hippodrome=race.get("hippodrome"),
        distance=race.get("distance"),
        runners=len(parts),
        presse=presse,
        disc=race.get("disc_canonical") or race.get("discipline"),
    )
    if not results:
        return jsonify({"error": "no-dna", "message": "Aucune signature DNA similaire", "race": race}), 404
    return jsonify({"matches": results, "support": support,
                    "level": support.get("structures", 0)
                    if isinstance(support, dict) else support,
                    "race": race})
