from flask import Blueprint, request, jsonify

turffrance_bp = Blueprint('turffrance', __name__)


@turffrance_bp.route('/api/turffrance/tops', methods=['GET'])
def tops():
    date = (request.args.get('date') or '').strip()
    reunion = (request.args.get('reunion') or '').strip().upper()
    course = (request.args.get('course') or '').strip().upper()
    pays = (request.args.get('pays') or 'FRANCE').strip().upper()
    if not date or not reunion or not course:
        return jsonify({"error": "date + reunion (R1) + course (C1) required"}), 400
    try:
        from scraper.turffrance_scraper import fetch_tops
        tops = fetch_tops(date, reunion, course, pays)
        return jsonify({"date": date, "reunion": reunion, "course": course,
                        "found": True, "source": "turf-france", "tops": tops})
    except Exception as e:
        return jsonify({"error": str(e)[:200]}), 502
