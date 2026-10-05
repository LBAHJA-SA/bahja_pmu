from flask import Flask, send_from_directory, jsonify, request
from flask_cors import CORS
import os, threading

app = Flask(__name__, static_folder="../dist")
CORS(app)

from database import init_db
init_db()

import auto_maintenance

from routes.programme import pmu_bp as programme_bp
app.register_blueprint(programme_bp)

from routes.archive import archive_bp
app.register_blueprint(archive_bp)

from QUINTE.routes import alfaraj_bp, synthese_motor_bp
app.register_blueprint(alfaraj_bp)
app.register_blueprint(synthese_motor_bp)

from COUPLE.routes import couple_bp
app.register_blueprint(couple_bp)


from SUIVI.routes import track_bp as suivi_bp
app.register_blueprint(suivi_bp)

from routes.turf import turf_bp
app.register_blueprint(turf_bp)

from QUINTE.synthese_routes import synthese_bp
app.register_blueprint(synthese_bp)

from QUINTE.dna_routes import synthese_dna_bp
app.register_blueprint(synthese_dna_bp)

from DNA_COURSE.routes import dna_bp
app.register_blueprint(dna_bp)

from routes.turffrance import turffrance_bp
app.register_blueprint(turffrance_bp)

# TROT and GALOP call /api/regret/analyze; the engine lives in backend/REGRET/
from routes.regret import regret_bp
app.register_blueprint(regret_bp)

# FLIP is measured against real results, on its own page
from FLIP.routes import flip_bp
app.register_blueprint(flip_bp)

from routes.auth import auth_bp, ensure_owner
app.register_blueprint(auth_bp)
try:
    ensure_owner()
except Exception:
    pass

def _prewarm():
    pass
    # plat_dna prewarm removed (page deleted)
    try:
        from QUINTE.service import get_quinte_top5_stats, get_brave_archetypes
        get_quinte_top5_stats(limit=1000)
        get_brave_archetypes()
        for _d in ("TROT", "GALOP"):
            try:
                get_quinte_top5_stats(limit=1000, disc=_d)
            except Exception:
                pass
            try:
                get_brave_archetypes(disc=_d)
            except Exception:
                pass
    except Exception:
        pass
    try:
        from COUPLE.service import get_small_top3_stats
        get_small_top3_stats(limit=3000)
    except Exception:
        pass
    # le_sniper prewarm lazy via cache on first request to avoid startup lock

threading.Thread(target=_prewarm, daemon=True).start()


@app.route("/api/health/db")
def health_db():
    import database
    info = {"db_path": database.DB_PATH}
    try:
        import sqlite3
        conn = sqlite3.connect(database.DB_PATH)
        info["races"] = conn.execute("SELECT COUNT(*) FROM races").fetchone()[0]
        try:
            info["quinte"] = conn.execute("SELECT COUNT(*) FROM races WHERE quinte=1").fetchone()[0]
        except Exception:
            info["quinte"] = None
        conn.close()
    except Exception as e:
        info["error"] = str(e)[:200]
    try:
        from routes.auth import pg, lite
        db = pg()
        if db is not None:
            with db.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM users")
                info["users_db"] = "postgres"
                info["users"] = cur.fetchone()[0]
        else:
            conn = lite()
            try:
                info["users_db"] = "sqlite"
                info["users"] = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
            finally:
                conn.close()
    except Exception as e:
        info["users_error"] = str(e)[:200]
    return jsonify(info)


@app.route("/api/auto/status")
def auto_status():
    return jsonify(auto_maintenance.status())


@app.route("/api/auto/turfomania", methods=["POST"])
def auto_turfomania_toggle():
    enabled = request.get_json(silent=True) or {}
    flag = enabled.get("enabled", True)
    auto_maintenance.set_turfomania_watchdog(flag)
    return jsonify(auto_maintenance.status())


@app.route("/api/auto/run", methods=["POST"])
def auto_run():
    archived, purged, errors = auto_maintenance.run_once()
    return jsonify({"archived": archived, "purged": purged, "errors": errors})


auto_maintenance.set_turfomania_watchdog(True)
auto_maintenance.start()


import time as _time

_AUDIT_PATH = os.path.join(os.path.dirname(__file__), "logs", "api_audit.log")


@app.before_request
def _audit_start():
    request._t0 = _time.time()


@app.after_request
def _audit_log(response):
    try:
        if request.path.startswith("/api/") and request.method == "POST":
            ms = int((_time.time() - getattr(request, "_t0", _time.time())) * 1000)
            n = ""
            try:
                body = request.get_json(silent=True) or {}
                ps = body.get("participants") or []
                n = len(ps)
            except Exception:
                pass
            with open(_AUDIT_PATH, "a", encoding="utf-8") as f:
                f.write("%s %s %s n=%s %dms\n" % (
                    _time.strftime("%Y-%m-%d %H:%M:%S"), request.path,
                    response.status_code, n, ms))
    except Exception:
        pass
    return response


@app.route("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


@app.route("/<path:path>")
def static_files(path):
    if path.startswith("api/"):
        from flask import jsonify
        return jsonify({"error": "Not found"}), 404
    file_path = os.path.join(app.static_folder, path)
    if os.path.exists(file_path):
        return send_from_directory(app.static_folder, path)
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    # threaded: the UI fires parallel API calls; single-threaded server
    # queues them and looks dead under load
    # Railway/Heroku provide PORT env var
    port = int(os.environ.get("PORT", 3000))
    app.run(host="0.0.0.0", port=port, debug=False, threaded=True)

