import os

from flask import Blueprint, jsonify, request

from .engine import dna_course_tickets

dna_bp = Blueprint("dna_course", __name__, url_prefix="/api/dna")


@dna_bp.before_request
def _guard():
    from routes.auth import require_session
    if request.method == "OPTIONS" or request.path.endswith("/health"):
        return None
    return require_session()


@dna_bp.route("/extract", methods=["POST"])
def extract():
    body = request.get_json(silent=True) or {}
    participants = body.get("participants") or []
    if not participants:
        return jsonify({"error": "No participants"}), 400
    tickets = dna_course_tickets(
        participants,
        hippodrome=body.get("hippodrome"),
        disc=body.get("disc") or body.get("discipline"),
        distance=body.get("distance"),
        before=body.get("date") or body.get("before"),
        runners=body.get("runners") or len(participants),
        surface=body.get("surface"),
        config=body.get("config") if isinstance(body.get("config"), dict) else None,
    )
    status = 200 if not tickets.get("error") else 503
    return jsonify(tickets), status


@dna_bp.route("/health", methods=["GET"])
def health():
    from . import store
    return jsonify({
        "status": "ok",
        "module": "DNA_COURSE",
        "engine": "RACE_DNA_ENGINE",
        "version": "3.1",
        "ranking": "market-anchored",
        "layers": ["individual", "pair", "trio", "market"],
        "archive": os.path.basename(store.dna_db_path()),
        "compact_archive": store.compact_available(),
    })
