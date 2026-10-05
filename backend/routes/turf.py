from flask import Blueprint, request, jsonify
import os, json

turf_bp = Blueprint('turf', __name__)
STORE = os.path.join(os.path.dirname(__file__), '..', 'turf_pronostics.json')

# Professional persistent storage: Postgres on Railway, JSON locally
_db = None

def get_db():
    global _db
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    if _db is not None:
        return _db
    try:
        import psycopg2
        _db = psycopg2.connect(url)
        _db.autocommit = True
        with _db.cursor() as cur:
            cur.execute("CREATE TABLE IF NOT EXISTS pronostics (race_id TEXT PRIMARY KEY, data JSONB, updated_at TIMESTAMPTZ DEFAULT NOW())")
        return _db
    except Exception:
        _db = None
        return None

def load_store():
    if not os.path.exists(STORE):
        return {}
    try:
        with open(STORE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_store(data):
    try:
        with open(STORE, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except:
        pass

@turf_bp.route('/api/turf', methods=['GET'])
def list_pronos():
    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                cur.execute("SELECT race_id, data FROM pronostics ORDER BY updated_at DESC")
                return jsonify({row[0]: row[1] for row in cur.fetchall()})
        except Exception:
            pass
    return jsonify(load_store())

@turf_bp.route('/api/turf/<race_id>', methods=['GET'])
def get_prono(race_id):
    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                cur.execute("SELECT data, updated_at FROM pronostics WHERE race_id=%s", (race_id,))
                row = cur.fetchone()
                if row:
                    data = dict(row[0]) if isinstance(row[0], dict) else {}
                    data["_updated_at"] = row[1].isoformat() if row[1] else None
                    return jsonify(data)
                return jsonify({})
        except Exception:
            pass
    store = load_store()
    return jsonify(store.get(race_id, {}))

@turf_bp.route('/api/turf/<race_id>', methods=['POST'])
def set_prono(race_id):
    secret = os.environ.get("ADMIN_SECRET")
    if secret and request.headers.get("X-Admin-Key") != secret:
        return jsonify({"error": "Non autorisé"}), 403
    body = request.get_json(silent=True) or {}
    db = get_db()
    if db:
        try:
            with db.cursor() as cur:
                cur.execute(
                    "INSERT INTO pronostics (race_id, data, updated_at) VALUES (%s, %s, NOW()) "
                    "ON CONFLICT (race_id) DO UPDATE SET data=EXCLUDED.data, updated_at=NOW()",
                    (race_id, json.dumps(body, ensure_ascii=False)))
            return jsonify({"ok": True, "race_id": race_id, "stored": "postgres"})
        except Exception:
            pass
    store = load_store()
    store[race_id] = body
    save_store(store)
    return jsonify({"ok": True, "race_id": race_id, "stored": "json"})
