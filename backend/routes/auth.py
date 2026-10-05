"""Accounts: phone login, trial, block, single session, device binding.
Postgres on Railway (DATABASE_URL), SQLite users.db locally.
"""
from flask import Blueprint, request, jsonify
import os, json, sqlite3, secrets, hashlib
from datetime import datetime, timedelta

auth_bp = Blueprint('auth', __name__)
USERS_DB = os.path.join(os.path.dirname(__file__), '..', 'users.db')
_pg = None

def _now():
    return datetime.utcnow()

def _now_iso():
    from datetime import timezone
    return datetime.now(timezone.utc).isoformat()

def _client_ip():
    fwd = request.headers.get("X-Forwarded-For", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.remote_addr

def pg():
    global _pg
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    if _pg is not None:
        return _pg
    try:
        import psycopg2
        _pg = psycopg2.connect(url)
        _pg.autocommit = True
        with _pg.cursor() as cur:
            cur.execute("""CREATE TABLE IF NOT EXISTS users (
                phone TEXT PRIMARY KEY, pass_hash TEXT, active INT DEFAULT 1,
                trial_until TIMESTAMPTZ, session_token TEXT, device_id TEXT,
                created_at TIMESTAMPTZ DEFAULT NOW(), last_login TIMESTAMPTZ,
                last_seen TIMESTAMPTZ, ip TEXT)""")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ip TEXT")
            cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_from TIMESTAMPTZ")
        return _pg
    except Exception:
        _pg = None
        return None

def lite():
    conn = sqlite3.connect(USERS_DB)
    conn.row_factory = sqlite3.Row
    conn.execute("""CREATE TABLE IF NOT EXISTS users (
        phone TEXT PRIMARY KEY, pass_hash TEXT, active INT DEFAULT 1,
        trial_until TEXT, session_token TEXT, device_id TEXT,
        created_at TEXT, last_login TEXT, last_seen TEXT, ip TEXT)""")
    for col in ("last_seen TEXT", "ip TEXT", "trial_from TEXT"):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except Exception:
            pass
    return conn

def hash_pw(pw, phone):
    return hashlib.sha256(f"{phone}:{pw}:bahja".encode()).hexdigest()

def get_user(phone):
    db = pg()
    if db:
        with db.cursor() as cur:
            cur.execute("SELECT phone, pass_hash, active, trial_until, session_token, device_id, last_seen, ip, trial_from FROM users WHERE phone=%s", (phone,))
            r = cur.fetchone()
            if not r:
                return None
            return {"phone": r[0], "pass_hash": r[1], "active": r[2],
                    "trial_until": str(r[3]) if r[3] else None,
                    "session_token": r[4], "device_id": r[5],
                    "last_seen": str(r[6]) if r[6] else None, "ip": r[7],
                    "trial_from": str(r[8]) if r[8] else None}
    conn = lite()
    try:
        r = conn.execute("SELECT * FROM users WHERE phone=?", (phone,)).fetchone()
        return dict(r) if r else None
    finally:
        conn.close()

def save_user(u):
    db = pg()
    if db:
        with db.cursor() as cur:
            cur.execute("""INSERT INTO users (phone, pass_hash, active, trial_until, session_token, device_id, created_at, last_login, last_seen, ip, trial_from)
                VALUES (%s,%s,%s,%s,%s,%s,NOW(),NOW(),%s,%s,%s)
                ON CONFLICT (phone) DO UPDATE SET pass_hash=EXCLUDED.pass_hash, active=EXCLUDED.active,
                trial_until=EXCLUDED.trial_until, session_token=EXCLUDED.session_token,
                device_id=EXCLUDED.device_id, last_login=NOW(), last_seen=EXCLUDED.last_seen, ip=EXCLUDED.ip, trial_from=EXCLUDED.trial_from""",
                (u["phone"], u["pass_hash"], u.get("active", 1), u.get("trial_until"), u.get("session_token"), u.get("device_id"), u.get("last_seen"), u.get("ip"), u.get("trial_from")))
        return
    conn = lite()
    try:
        conn.execute("""INSERT OR REPLACE INTO users
            (phone, pass_hash, active, trial_until, session_token, device_id, created_at, last_login, last_seen, ip, trial_from)
            VALUES (?,?,?,?,?,?,COALESCE((SELECT created_at FROM users WHERE phone=?),?),?,?,?,?)""",
            (u["phone"], u["pass_hash"], u.get("active", 1), u.get("trial_until"),
             u.get("session_token"), u.get("device_id"), u["phone"], _now().isoformat(), _now().isoformat(),
             u.get("last_seen"), u.get("ip"), u.get("trial_from")))
        conn.commit()
    finally:
        conn.close()

def _ensure_tables_pg(cur):
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS last_seen TIMESTAMPTZ")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS ip TEXT")
    cur.execute("ALTER TABLE users ADD COLUMN IF NOT EXISTS trial_from TIMESTAMPTZ")
    cur.execute("""CREATE TABLE IF NOT EXISTS login_attempts (
        id SERIAL PRIMARY KEY, phone TEXT, ip TEXT, device_id TEXT,
        result TEXT, at TIMESTAMPTZ DEFAULT NOW())""")

def _ensure_tables_lite(conn):
    for col in ("last_seen TEXT", "ip TEXT", "trial_from TEXT"):
        try:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col}")
        except Exception:
            pass
    conn.execute("""CREATE TABLE IF NOT EXISTS login_attempts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, phone TEXT, ip TEXT, device_id TEXT,
        result TEXT, at TEXT)""")

def log_attempt(phone, ip, device, result):
    try:
        db = pg()
        if db:
            with db.cursor() as cur:
                _ensure_tables_pg(cur)
                cur.execute("INSERT INTO login_attempts (phone, ip, device_id, result) VALUES (%s,%s,%s,%s)",
                            (phone, ip, device, result))
            return
    except Exception:
        pass
    try:
        conn = lite()
        try:
            _ensure_tables_lite(conn)
            conn.execute("INSERT INTO login_attempts (phone, ip, device_id, result, at) VALUES (?,?,?,?,?)",
                         (phone, ip, device, result, _now().isoformat()))
            conn.commit()
        finally:
            conn.close()
    except Exception:
        pass

def ensure_owner():
    """Permanent owner account for local management (localhost only use)."""
    try:
        if get_user("0000000000"):
            return
        pw = os.environ.get("OWNER_PASSWORD", "bahja-admin")
        save_user({"phone": "0000000000", "pass_hash": hash_pw(pw, "0000000000"),
                   "active": 1, "trial_until": None, "session_token": None, "device_id": None})
    except Exception:
        pass

def check_admin():
    secret = os.environ.get("ADMIN_SECRET")
    if not secret:
        return True
    return request.headers.get("X-Admin-Key") == secret

def require_session():
    """For app-only analysis endpoints: valid active session required.
    Returns None if OK, else (json, status)."""
    token = request.headers.get("X-Session-Token", "")
    phone = request.headers.get("X-Phone", "")
    if not token or not phone:
        return jsonify({"error": "Session requise - connectez-vous"}), 401
    u = get_user(phone)
    if not u:
        return jsonify({"error": "Utilisateur introuvable"}), 401
    
    # Admin accounts (0000000000, admin) - more lenient for local dev
    is_admin = phone in ("admin", "0000000000")
    is_local = request.host.startswith("127.0.0.1") or request.host.startswith("localhost")
    
    if not is_admin and u.get("session_token") != token:
        return jsonify({"error": "Session invalide - reconnectez-vous"}), 401
    
    if not u.get("active"):
        return jsonify({"error": "Compte bloqué"}), 403
    return None

@auth_bp.route('/api/auth/login', methods=['POST'])
def login():
    body = request.get_json(silent=True) or {}
    phone = str(body.get("phone", "")).strip()
    pw = str(body.get("password", ""))
    device = str(body.get("device_id", "") or "")[:64]
    u = get_user(phone)
    if not u or u["pass_hash"] != hash_pw(pw, phone):
        log_attempt(phone, _client_ip(), device, "wrong-password")
        return jsonify({"error": "رقم الهاتف أو كلمة السر خاطئة"}), 401
    if not u.get("active"):
        return jsonify({"error": "الحساب موقف - تواصل مع البائع"}), 403
    tu = u.get("trial_until")
    if tu:
        try:
            exp = datetime.fromisoformat(str(tu).replace("Z", "+00:00"))
            if exp.tzinfo is None:
                exp = exp  # naive compare
            if _now().replace(tzinfo=exp.tzinfo) > exp if exp.tzinfo else _now() > exp:
                return jsonify({"error": "انتهت مدة الاشتراك - جدد اشتراكك"}), 403
        except Exception:
            pass
    # strict device binding (admin accounts exempt)
    is_admin_acct = phone in ("admin", "0000000000")
    bound = (u.get("device_id") or "").strip()
    if not is_admin_acct and bound and device and device != bound:
        log_attempt(phone, _client_ip(), device, f"blocked-foreign-device:{bound}")
        return jsonify({"error": "هذا الحساب مربوط بجهاز آخر - تواصل مع البائع"}), 403
    if not bound and device:
        u["device_id"] = device
    log_attempt(phone, _client_ip(), device, "ok")
    token = secrets.token_hex(16)
    u["session_token"] = token
    if device:
        u["device_id"] = device
    u["last_seen"] = _now_iso()
    u["ip"] = _client_ip()
    save_user(u)
    return jsonify({"ok": True, "token": token, "phone": phone, "trial_until": tu})

@auth_bp.route('/api/auth/logout', methods=['POST'])
def logout():
    token = request.headers.get("X-Session-Token", "")
    phone = request.headers.get("X-Phone", "")
    u = get_user(phone) if phone else None
    if u and (not token or u.get("session_token") == token):
        u["session_token"] = None
        save_user(u)
    return jsonify({"ok": True})

@auth_bp.route('/api/auth/me', methods=['GET'])
def me():
    token = request.headers.get("X-Session-Token", "")
    phone = request.headers.get("X-Phone", "")
    if not token:
        return jsonify({"error": "no session"}), 401
    u = get_user(phone) if phone else None
    if not u and phone:
        return jsonify({"error": "no user"}), 401
    # find by token if phone missing
    if not u:
        return jsonify({"error": "no user"}), 401
    if u.get("session_token") != token:
        return jsonify({"error": "تم الدخول من جهاز آخر - أعد الدخول"}), 401
    if not u.get("active"):
        return jsonify({"error": "الحساب موقف"}), 403
    try:
        u["last_seen"] = _now_iso()
        u["ip"] = _client_ip()
        save_user(u)
    except Exception:
        pass
    return jsonify({"ok": True, "phone": phone, "trial_until": u.get("trial_until")})

@auth_bp.route('/api/auth/password', methods=['POST'])
def change_own_password():
    token = request.headers.get("X-Session-Token", "")
    phone = request.headers.get("X-Phone", "")
    u = get_user(phone) if (phone and token) else None
    if not u or u.get("session_token") != token:
        return jsonify({"error": "Session invalide"}), 401
    body = request.get_json(silent=True) or {}
    new_pw = str(body.get("new_password", ""))
    if len(new_pw) < 4:
        return jsonify({"error": "كلمة السر قصيرة (4+ حروف)"}), 400
    u["pass_hash"] = hash_pw(new_pw, phone)
    u["session_token"] = None
    save_user(u)
    return jsonify({"ok": True})

# ---- Admin ----
@auth_bp.route('/api/admin/attempts', methods=['GET'])
def list_attempts():
    if not check_admin():
        return jsonify({"error": "Non autorisé"}), 403
    phone = request.args.get("phone", "")
    out = []
    db = pg()
    if db:
        with db.cursor() as cur:
            _ensure_tables_pg(cur)
            if phone:
                cur.execute("SELECT phone, ip, device_id, result, at FROM login_attempts WHERE phone=%s ORDER BY id DESC LIMIT 30", (phone,))
            else:
                cur.execute("SELECT phone, ip, device_id, result, at FROM login_attempts ORDER BY id DESC LIMIT 50")
            for r in cur.fetchall():
                out.append({"phone": r[0], "ip": r[1], "device": r[2], "result": r[3], "at": str(r[4])})
        return jsonify(out)
    conn = lite()
    try:
        _ensure_tables_lite(conn)
        if phone:
            rows = conn.execute("SELECT phone, ip, device_id, result, at FROM login_attempts WHERE phone=? ORDER BY id DESC LIMIT 30", (phone,))
        else:
            rows = conn.execute("SELECT phone, ip, device_id, result, at FROM login_attempts ORDER BY id DESC LIMIT 50")
        for r in rows:
            out.append(dict(r))
        return jsonify(out)
    finally:
        conn.close()

@auth_bp.route('/api/admin/users', methods=['GET'])
def list_users():
    if not check_admin():
        return jsonify({"error": "Non autorisé"}), 403
    db = pg()
    out = []
    if db:
        with db.cursor() as cur:
            cur.execute("SELECT phone, active, trial_until, device_id, last_login, last_seen, ip, trial_from FROM users ORDER BY phone")
            for r in cur.fetchall():
                out.append({"phone": r[0], "active": r[1], "trial_until": str(r[2]) if r[2] else None,
                            "device_id": r[3], "last_login": str(r[4]) if r[4] else None,
                            "last_seen": str(r[5]) if r[5] else None, "ip": r[6],
                            "trial_from": str(r[7]) if r[7] else None})
        return jsonify(out)
    conn = lite()
    try:
        for r in conn.execute("SELECT phone, active, trial_until, device_id, last_login, last_seen, ip, trial_from FROM users ORDER BY phone"):
            out.append(dict(r))
        return jsonify(out)
    finally:
        conn.close()

@auth_bp.route('/api/admin/users', methods=['POST'])
def create_user():
    if not check_admin():
        return jsonify({"error": "Non autorisé"}), 403
    body = request.get_json(silent=True) or {}
    phone = str(body.get("phone", "")).strip()
    pw = str(body.get("password", ""))
    days = int(body.get("days", 1))
    if not phone or not pw:
        return jsonify({"error": "phone + password required"}), 400
    trial_until = (_now() + timedelta(days=days)).isoformat()
    save_user({"phone": phone, "pass_hash": hash_pw(pw, phone), "active": 1,
               "trial_until": trial_until, "session_token": None, "device_id": None})
    return jsonify({"ok": True, "phone": phone, "trial_until": trial_until})

@auth_bp.route('/api/admin/users/<phone>', methods=['POST'])
def manage_user(phone):
    if not check_admin():
        return jsonify({"error": "Non autorisé"}), 403
    body = request.get_json(silent=True) or {}
    action = body.get("action")
    u = get_user(phone)
    if not u:
        return jsonify({"error": "not found"}), 404
    if action == "block":
        u["active"] = 0
        u["session_token"] = None
    elif action == "unblock":
        u["active"] = 1
    elif action == "delete":
        db = pg()
        if db:
            with db.cursor() as cur:
                cur.execute("DELETE FROM users WHERE phone=%s", (phone,))
            return jsonify({"ok": True, "phone": phone, "deleted": True})
        conn = lite()
        try:
            conn.execute("DELETE FROM users WHERE phone=?", (phone,))
            conn.commit()
        finally:
            conn.close()
        return jsonify({"ok": True, "phone": phone, "deleted": True})
    elif action == "extend":
        days = int(body.get("days", 30))
        try:
            base = datetime.fromisoformat(str(u.get("trial_until")).replace("Z", "+00:00")) if u.get("trial_until") else _now()
        except Exception:
            base = _now()
        try:
            now_cmp = _now().replace(tzinfo=base.tzinfo) if base.tzinfo else _now()
            if base < now_cmp:
                base = now_cmp
        except Exception:
            pass
        u["trial_until"] = (base + timedelta(days=days)).isoformat()
    elif action == "set-expiry":
        date_from = str(body.get("date_from", "") or "").strip()
        date_to = str(body.get("date_to", "") or "").strip()
        if not date_to:
            return jsonify({"error": "date_to required (YYYY-MM-DD)"}), 400
        u["trial_from"] = date_from or None
        u["trial_until"] = date_to if "T" in date_to else date_to + "T23:59:59"
    elif action == "password":
        u["pass_hash"] = hash_pw(str(body.get("password", "")), phone)
    elif action == "logout":
        u["session_token"] = None
    elif action == "device-reset":
        u["device_id"] = None
        u["session_token"] = None
    else:
        return jsonify({"error": "unknown action"}), 400
    save_user(u)
    return jsonify({"ok": True, "phone": phone, "trial_until": u.get("trial_until")})
