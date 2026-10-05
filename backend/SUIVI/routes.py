"""Suivi — betting journal: log analyses, resolve arrivals, stats.

Tests the user's hypothesis (early meeting races hit, late ones miss) via:
- course_num buckets (C1-C4 vs C5+)
- analyzed-before-start delay buckets (cotes freshness proxy)
- per-hippodrome breakdowns
"""
from flask import Blueprint, jsonify, request
from database import get_db

track_bp = Blueprint("track", __name__, url_prefix="/api/track")

TICKETS = ("trio", "trio_coh", "trio_v3", "quinte", "outsider", "forme", "couple",
            "bench2", "bench3", "reserve", "syn8", "flip_cpl", "flip_trio",
            "expert_trio", "expert_8")

_PG_TRACK_DDL = (
    "CREATE TABLE IF NOT EXISTS tracked_races (id SERIAL PRIMARY KEY, date TEXT NOT NULL, "
    "reunion_num INTEGER NOT NULL, course_num INTEGER NOT NULL, hippodrome TEXT, discipline TEXT, "
    "distance INTEGER, runners INTEGER, race_time BIGINT, analyzed_at TIMESTAMPTZ DEFAULT NOW(), "
    "UNIQUE(date, reunion_num, course_num))",
    "CREATE TABLE IF NOT EXISTS tracked_picks (id SERIAL PRIMARY KEY, tracked_id INTEGER NOT NULL "
    "REFERENCES tracked_races(id) ON DELETE CASCADE, ticket TEXT NOT NULL, target_pos INTEGER, "
    "num INTEGER, horse TEXT, driver TEXT, cote DOUBLE PRECISION, score DOUBLE PRECISION)",
    "ALTER TABLE tracked_picks ADD COLUMN IF NOT EXISTS driver TEXT",
    "CREATE TABLE IF NOT EXISTS tracked_results (tracked_id INTEGER PRIMARY KEY "
    "REFERENCES tracked_races(id) ON DELETE CASCADE, p1 INTEGER, p2 INTEGER, p3 INTEGER, "
    "p4 INTEGER, p5 INTEGER, source TEXT, resolved_at TIMESTAMPTZ DEFAULT NOW())",
    "ALTER TABLE tracked_picks ADD COLUMN IF NOT EXISTS driver TEXT",
    "CREATE TABLE IF NOT EXISTS race_rapports (date TEXT NOT NULL, reunion_num INTEGER NOT NULL, "
    "course_num INTEGER NOT NULL, hippodrome TEXT, payload TEXT, "
    "fetched_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (date, reunion_num, course_num))",
)
_track_ddl_done = False


class _TrackConn:
    """Thin wrapper: Postgres (durable, Railway) or SQLite (local/USB).

    Same .execute/.commit/.close surface; translates ? placeholders.
    pg rows come back as dicts (RealDictCursor) like sqlite Rows.
    """

    def __init__(self, conn, is_pg):
        self._conn = conn
        self.is_pg = is_pg
        self._cur = None
        if is_pg:
            from psycopg2.extras import RealDictCursor
            self._cur = conn.cursor(cursor_factory=RealDictCursor)

    def execute(self, sql, params=()):
        if self.is_pg:
            self._cur.execute(sql.replace("?", "%s"), params)
            return self._cur
        return self._conn.execute(sql, params)

    def commit(self):
        if not self.is_pg:
            self._conn.commit()

    def close(self):
        try:
            if self.is_pg:
                self._cur.close()
            else:
                self._conn.close()
        except Exception:
            pass


def _connect():
    try:
        from routes.auth import pg
        c = pg()
    except Exception:
        c = None
    if c is not None:
        global _track_ddl_done
        if not _track_ddl_done:
            cur = c.cursor()
            try:
                for stmt in _PG_TRACK_DDL:
                    cur.execute(stmt)
            finally:
                cur.close()
            _track_ddl_done = True
        return _TrackConn(c, True)
    return _TrackConn(get_db(), False)


@track_bp.route("/log", methods=["POST"])
def log_analysis():
    body = request.get_json(silent=True) or {}
    meta = body.get("race") or {}
    date = meta.get("date")
    rnum, cnum = meta.get("rnum"), meta.get("cnum")
    if not date or rnum is None or cnum is None:
        return jsonify({"error": "date/rnum/cnum requis"}), 400
    # analyzed_at optionnel (restauration d'historique): sinon NOW() côté base.
    # Valide strictement pour ne pas corrompre le bucket "fraîcheur des cotes".
    analyzed_at = meta.get("analyzed_at")
    try:
        import datetime as _dt
        _dt.datetime.fromisoformat(str(analyzed_at))
        use_analyzed = isinstance(analyzed_at, str) and len(analyzed_at) >= 10
    except (TypeError, ValueError):
        use_analyzed = False
    cols = "(date, reunion_num, course_num, hippodrome, discipline, distance, runners, race_time)"
    vals = [date, rnum, cnum, meta.get("hippodrome"), meta.get("discipline"),
            meta.get("distance"), meta.get("runners"), meta.get("time")]
    if use_analyzed:
        cols = cols.replace("race_time)", "race_time, analyzed_at)")
        vals.append(analyzed_at)
    ph = ",".join(["?"] * len(vals))
    db = _connect()
    if db.is_pg:
        db.execute(
            "INSERT INTO tracked_races %s VALUES (%s) "
            "ON CONFLICT (date, reunion_num, course_num) DO NOTHING" % (cols, ph), vals)
    else:
        db.execute(
            "INSERT OR IGNORE INTO tracked_races %s VALUES (%s)" % (cols, ph), vals)
    row = db.execute(
        "SELECT id FROM tracked_races WHERE date=? AND reunion_num=? AND course_num=?",
        (date, rnum, cnum)).fetchone()
    tid = row["id"]
    db.execute("DELETE FROM tracked_picks WHERE tracked_id=?", (tid,))
    n = 0
    for ticket, picks in (body.get("tickets") or {}).items():
        if ticket not in TICKETS:
            continue
        for p in picks or []:
            if not isinstance(p, dict) or p.get("num") is None:
                continue
            try:
                cote = float(p.get("cote")) if p.get("cote") is not None else None
            except (TypeError, ValueError):
                cote = None
            try:
                score = float(p.get("score", p.get("ecart", 0)))
            except (TypeError, ValueError):
                score = 0
            db.execute(
                "INSERT INTO tracked_picks (tracked_id, ticket, target_pos, num, horse, driver, cote, score) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (tid, ticket, p.get("target_pos"), p.get("num"),
                 p.get("horse"), p.get("driver"), cote, score))
            n += 1
    db.commit()
    db.close()
    return jsonify({"status": "ok", "tracked_id": tid, "picks": n})


def _norm_track(s):
    import unicodedata
    s = unicodedata.normalize("NFD", str(s or "").upper())
    return "".join(c for c in s if not unicodedata.combining(c)).strip()


def _resolve_sorec(t):
    """Morocco virtual meetings (R>=100): CasaCourses results."""
    try:
        from routes.morocco import fetch_morocco_programme, fetch_morocco_race, MOROCCO_OFFSET
    except Exception:
        return None, None
    try:
        want = _norm_track(t.get("hippodrome"))
        meetings = fetch_morocco_programme(t["date"]) or []
        target = None
        for m in meetings:
            hip = m.get("hippodrome", {}) or {}
            name = hip.get("libelleCourt", "") if isinstance(hip, dict) else str(hip)
            if _norm_track(name) == want and m.get("numero") == t["reunion_num"]:
                target = m
                break
        if target is None:
            for m in meetings:
                hip = m.get("hippodrome", {}) or {}
                name = hip.get("libelleCourt", "") if isinstance(hip, dict) else str(hip)
                if _norm_track(name) == want:
                    target = m
                    break
        if target is None:
            return None, None
        courses = target.get("courses", []) or []
        sid = None
        for rc in courses:
            try:
                if rc.get("numOrdre") is not None and int(rc.get("numOrdre")) == int(t["course_num"]):
                    sid = rc.get("_sorecId")
                    break
            except (TypeError, ValueError):
                continue
        if not sid:
            # fallback: positional (C1 = first listed) when numbers are missing
            try:
                idx = int(t["course_num"]) - 1
                if 0 <= idx < len(courses):
                    sid = courses[idx].get("_sorecId")
            except (TypeError, ValueError, IndexError):
                pass
        if not sid:
            return None, None
        import time as _t
        det = None
        for attempt in range(4):
            try:
                det = fetch_morocco_race(sid, t["date"])
                break
            except Exception:
                _t.sleep(5 * (attempt + 1))
        if not det:
            return None, None
        order = []
        for r in sorted(det.get("results") or [], key=lambda x: int(x.get("position", 99))):
            try:
                order.append(int(r.get("number")))
            except (TypeError, ValueError):
                continue
        if len(order) >= 3:
            while len(order) < 5:
                order.append(None)
            return order[:5], "sorec"
    except Exception:
        pass
    return None, None


def _resolve_one(conn, t):
    """Arrival from archive Geny rows, else SOREC (R>=100), else PMU ordreArrivee."""
    tid = t["id"]
    rows = conn.execute(
        "SELECT p.num, p.rang FROM participants p JOIN races r ON r.race_id=p.race_id "
        "WHERE r.date=? AND r.reunion_num=? AND r.course_num=? AND p.rang IS NOT NULL "
        "AND p.rang BETWEEN 1 AND 5 ORDER BY p.rang",
        (t["date"], t["reunion_num"], t["course_num"])).fetchall()
    bypos = {}
    for r in rows:
        try:
            bypos.setdefault(int(r["rang"]), r["num"])
        except (TypeError, ValueError):
            continue
    if all(k in bypos for k in (1, 2, 3, 4, 5)):
        top5 = [bypos[k] for k in (1, 2, 3, 4, 5)]
        return top5, "archive"
    try:
        rnum = int(t["reunion_num"] or 0)
    except (TypeError, ValueError):
        rnum = 0
    if rnum >= 100:
        top5, src = _resolve_sorec(t)
        if top5:
            return top5, src
        return None, None
    # PMU live/fallback (real reunion numbers only)
    try:
        from routes.programme import _get, BASE_URL, _format_date
        d = _format_date(t["date"])
        course = _get("%s/programme/%s/R%d/C%d" % (BASE_URL, d, t["reunion_num"], t["course_num"]))
        oa = course.get("ordreArrivee") or []
        nums = []
        for entry in oa:
            if isinstance(entry, (list, tuple)) and entry:
                nums.append(int(entry[0]))
            elif isinstance(entry, int):
                nums.append(entry)
        if len(nums) >= 3:
            while len(nums) < 5:
                nums.append(None)
            return nums[:5], "pmu"
    except Exception:
        pass
    return None, None


@track_bp.route("/resolve", methods=["POST"])
def resolve():
    body = request.get_json(silent=True) or {}
    only_id = body.get("tracked_id")
    force = bool(body.get("force"))
    db = _connect()
    adb = get_db()
    if only_id:
        rows = db.execute("SELECT * FROM tracked_races WHERE id=?", (only_id,)).fetchall()
    elif force:
        # Mise à jour après enquête/déclassement: ne revérifie que le récent (3 jours),
        # l'officiel pouvant changer le soir même (ex: 1-13-9 → 1-12-10).
        if db.is_pg:
            rows = db.execute(
                "SELECT tr.* FROM tracked_races tr JOIN tracked_results r ON r.tracked_id=tr.id "
                "WHERE tr.date >= to_char(NOW() - INTERVAL '3 days', 'YYYY-MM-DD')").fetchall()
        else:
            rows = db.execute(
                "SELECT tr.* FROM tracked_races tr JOIN tracked_results r ON r.tracked_id=tr.id "
                "WHERE tr.date >= date('now','-3 days')").fetchall()
    else:
        rows = db.execute(
            "SELECT tr.* FROM tracked_races tr LEFT JOIN tracked_results r ON r.tracked_id=tr.id "
            "WHERE r.tracked_id IS NULL").fetchall()
    done, pending, updated = 0, 0, 0
    _pay_count = 0
    for t in rows:
        t = dict(t)
        top5, src = _resolve_one(adb, t)
        if top5:
            cur = db.execute(
                "SELECT p1,p2,p3,p4,p5 FROM tracked_results WHERE tracked_id=?", (t["id"],)).fetchone()
            old = [cur["p1"], cur["p2"], cur["p3"], cur["p4"], cur["p5"]] if cur else None
            if db.is_pg:
                db.execute(
                    "INSERT INTO tracked_results "
                    "(tracked_id, p1, p2, p3, p4, p5, source) VALUES (?,?,?,?,?,?,?) "
                    "ON CONFLICT (tracked_id) DO UPDATE SET p1=EXCLUDED.p1, p2=EXCLUDED.p2, "
                    "p3=EXCLUDED.p3, p4=EXCLUDED.p4, p5=EXCLUDED.p5, source=EXCLUDED.source",
                    (t["id"], top5[0], top5[1], top5[2], top5[3], top5[4], src))
            else:
                db.execute(
                    "INSERT OR REPLACE INTO tracked_results "
                    "(tracked_id, p1, p2, p3, p4, p5, source) VALUES (?,?,?,?,?,?,?)",
                    (t["id"], top5[0], top5[1], top5[2], top5[3], top5[4], src))
            if old is None:
                done += 1
            elif list(old) != list(top5):
                updated += 1
            else:
                done += 1
            # rapports € pour le ROI (best effort, sans bloquer)
            try:
                from race_rapports import fetch_rapports_for, store as _store_rap, get_stored as _get_rap
                if (only_id is not None or _pay_count < 3) and not _get_rap(
                        db, t["date"], t["reunion_num"], t["course_num"]):
                    keys = fetch_rapports_for(t["date"], t.get("hippodrome"),
                                              t["reunion_num"], t["course_num"])
                    if keys:
                        _store_rap(db, t["date"], t["reunion_num"], t["course_num"],
                                   t.get("hippodrome"), keys)
                        _pay_count += 1
            except Exception:
                pass
        else:
            pending += 1
    db.commit()
    db.close()
    try:
        adb.close()
    except Exception:
        pass
    return jsonify({"resolved": done, "updated": updated, "pending": pending})


@track_bp.route("/resolve-manual", methods=["POST"])
def resolve_manual():
    body = request.get_json(silent=True) or {}
    tid = body.get("tracked_id")
    top5 = body.get("top5") or []
    if not tid or len(top5) < 3:
        return jsonify({"error": "tracked_id + au moins 3 arrivants requis"}), 400
    nums = []
    for v in list(top5)[:5]:
        if v is None or v == "":
            nums.append(None)
            continue
        try:
            nums.append(int(v))
        except (TypeError, ValueError):
            return jsonify({"error": "numéros invalides"}), 400
    while len(nums) < 5:
        nums.append(None)
    db = _connect()
    row = db.execute("SELECT id FROM tracked_races WHERE id=?", (tid,)).fetchone()
    if not row:
        db.close()
        return jsonify({"error": "course inconnue"}), 404
    if db.is_pg:
        db.execute(
            "INSERT INTO tracked_results "
            "(tracked_id, p1, p2, p3, p4, p5, source) VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT (tracked_id) DO UPDATE SET p1=EXCLUDED.p1, p2=EXCLUDED.p2, "
            "p3=EXCLUDED.p3, p4=EXCLUDED.p4, p5=EXCLUDED.p5, source=EXCLUDED.source",
            (tid, nums[0], nums[1], nums[2], nums[3], nums[4], "manual"))
    else:
        db.execute(
            "INSERT OR REPLACE INTO tracked_results "
            "(tracked_id, p1, p2, p3, p4, p5, source) VALUES (?,?,?,?,?,?,?)",
            (tid, nums[0], nums[1], nums[2], nums[3], nums[4], "manual"))
    db.commit()
    try:
        from race_rapports import fetch_rapports_for, store as _store_rap, get_stored as _get_rap
        rr = db.execute("SELECT date, reunion_num, course_num, hippodrome FROM tracked_races WHERE id=?",
                        (tid,)).fetchone()
        if rr:
            rr = dict(rr)
            if not _get_rap(db, rr["date"], rr["reunion_num"], rr["course_num"]):
                keys = fetch_rapports_for(rr["date"], rr.get("hippodrome"), rr["reunion_num"], rr["course_num"])
                if keys:
                    _store_rap(db, rr["date"], rr["reunion_num"], rr["course_num"], rr.get("hippodrome"), keys)
    except Exception:
        pass
    db.close()
    return jsonify({"status": "ok", "top5": nums})


@track_bp.route("/rapports/backfill", methods=["POST"])
def rapports_backfill():
    """Remplit les rapports € manquants (in calcule le ROI). Best effort."""
    body = request.get_json(silent=True) or {}
    try:
        days = int(body.get("days", 30))
    except (TypeError, ValueError):
        days = 30
    try:
        limit = int(body.get("limit", 15))
    except (TypeError, ValueError):
        limit = 15
    from datetime import date as _d, timedelta
    cutoff = (_d.today() - timedelta(days=max(1, min(days, 120)))).isoformat()
    db = _connect()
    rows = db.execute(
        "SELECT tr.date, tr.reunion_num, tr.course_num, tr.hippodrome FROM tracked_races tr "
        "JOIN tracked_results r ON r.tracked_id=tr.id "
        "LEFT JOIN race_rapports p ON p.date=tr.date AND p.reunion_num=tr.reunion_num "
        "AND p.course_num=tr.course_num "
        "WHERE tr.date >= ? AND p.date IS NULL ORDER BY tr.date DESC LIMIT ?",
        (cutoff, max(1, min(limit, 40)))).fetchall()
    from race_rapports import fetch_rapports_for, store as _store_rap
    fetched = 0
    for t in rows:
        t = dict(t)
        try:
            keys = fetch_rapports_for(t["date"], t.get("hippodrome"), t["reunion_num"], t["course_num"])
            if keys and _store_rap(db, t["date"], t["reunion_num"], t["course_num"], t.get("hippodrome"), keys):
                fetched += 1
        except Exception:
            continue
    db.close()
    return jsonify({"checked": len(rows), "fetched": fetched})


@track_bp.route("/delete", methods=["POST"])
def delete_tracked():
    from flask import request as freq
    body = freq.get_json(silent=True) or {}
    tid = body.get("tracked_id")
    if not tid:
        return jsonify({"error": "tracked_id required"}), 400
    db = _connect()
    db.execute("DELETE FROM tracked_picks WHERE tracked_id=?", (tid,))
    db.execute("DELETE FROM tracked_results WHERE tracked_id=?", (tid,))
    db.execute("DELETE FROM tracked_races WHERE id=?", (tid,))
    db.commit()
    db.close()
    return jsonify({"ok": True, "deleted": tid})

@track_bp.route("/delete-all", methods=["POST"])
def delete_all_tracked():
    db = _connect()
    db.execute("DELETE FROM tracked_picks")
    db.execute("DELETE FROM tracked_results")
    db.execute("DELETE FROM tracked_races")
    db.commit()
    db.close()
    return jsonify({"ok": True, "deleted": "all"})

@track_bp.route("/list", methods=["GET"])
def list_tracked():
    db = _connect()
    races = db.execute(
        "SELECT tr.*, r.p1, r.p2, r.p3, r.p4, r.p5, r.source "
        "FROM tracked_races tr LEFT JOIN tracked_results r ON r.tracked_id=tr.id "
        "ORDER BY tr.date DESC, tr.reunion_num, tr.course_num").fetchall()
    out = []
    for t in races:
        t = dict(t)
        picks = db.execute(
            "SELECT ticket, target_pos, num, horse, driver, cote, score FROM tracked_picks "
            "WHERE tracked_id=? ORDER BY ticket, target_pos", (t["id"],)).fetchall()
        t["picks"] = [dict(p) for p in picks]
        out.append(t)
    db.close()
    return jsonify({"races": out})


def _delay_bucket(analyzed_at, race_time):
    try:
        import datetime
        a = datetime.datetime.fromisoformat(str(analyzed_at))
        t = race_time / 1000 if (race_time or 0) > 1e12 else (race_time or 0)
        if not t:
            return "?"
        mins = (datetime.datetime.fromtimestamp(t) - a).total_seconds() / 60
        if mins < 0:
            return "après départ"
        if mins <= 30:
            return "≤30min"
        if mins <= 120:
            return "30-120min"
        return ">120min"
    except Exception:
        return "?"


@track_bp.route("/stats", methods=["GET"])
def stats():
    db = _connect()
    races = db.execute(
        "SELECT tr.*, r.p1, r.p2, r.p3, r.p4, r.p5 FROM tracked_races tr "
        "JOIN tracked_results r ON r.tracked_id=tr.id "
        "ORDER BY tr.date, tr.reunion_num, tr.course_num").fetchall()
    agg = {"n": 0, "by_ticket": {}, "by_hippo": {}, "by_slot": {"C1-C4": {}, "C5+": {}},
           "by_delay": {}, "by_temp": {}, "portfolio": {}, "roi": {}, "roi_norapports": 0}

    def bucket(d, key, hit, tot=1):
        b = d.setdefault(key, {"n": 0, "hits": 0})
        b["n"] += tot
        b["hits"] += hit

    def _norm_hip(s):
        import unicodedata
        s = unicodedata.normalize("NFD", str(s or "").upper())
        return "".join(c for c in s if not unicodedata.combining(c)).strip()

    meet_fav = {}
    port_counter = {}
    misses = []

    def bucket(d, key, hit, tot=1):
        b = d.setdefault(key, {"n": 0, "hits": 0})
        b["n"] += tot
        b["hits"] += hit

    for t in races:
        t = dict(t)
        actual3 = {t["p1"], t["p2"], t["p3"]} - {None}
        if not actual3:
            continue
        picks = db.execute(
            "SELECT ticket, target_pos, num, driver, cote FROM tracked_picks WHERE tracked_id=?", (t["id"],)).fetchall()
        by_ticket = {}
        for p in picks:
            by_ticket.setdefault(p["ticket"], []).append((p["target_pos"], p["num"]))
        # Benchmark auto: 2/3 favoris (cotes les plus basses) — remplit
        # aussi l'historique des courses suivies avant ce patch.
        cote_of = {}
        for p in picks:
            try:
                c = float(p["cote"]) if p["cote"] is not None else None
            except (TypeError, ValueError):
                c = None
            if c and c > 0 and p["num"] is not None:
                if p["num"] not in cote_of or c < cote_of[p["num"]]:
                    cote_of[p["num"]] = c
        fav = sorted(cote_of, key=lambda n: (cote_of[n], n))
        if "bench2" not in by_ticket and len(fav) >= 2:
            by_ticket["bench2"] = [(1, fav[0]), (2, fav[1])]
        if "bench3" not in by_ticket and len(fav) >= 3:
            by_ticket["bench3"] = [(1, fav[0]), (2, fav[1]), (3, fav[2])]
        mrank = {n: i + 1 for i, n in enumerate(fav)}
        agg["n"] += 1
        slot = "C1-C4" if (t["course_num"] or 99) <= 4 else "C5+"
        delay = _delay_bucket(t.get("analyzed_at"), t.get("race_time"))
        hip = t.get("hippodrome") or "?"
        race_hits = {}
        for ticket, lst in by_ticket.items():
            if ticket in ("reserve", "syn8", "flip_cpl", "flip_trio", "expert_trio", "expert_8"):
                # reserve: composant du Kanti-8 ; syn8/flip/expert: scorés à part (win+coverage)
                continue
            if ticket == "couple":
                # unpositioned pair/triple: overlap of all picked horses
                nums = {n for _, n in lst if n is not None}
                hit = len(nums & actual3)
                p1hit = 0
            else:
                posmap = dict(lst)
                trio = {posmap.get(1), posmap.get(2), posmap.get(3)} - {None}
                hit = len(trio & actual3) if trio else 0
                p1hit = 1 if posmap.get(1) in actual3 and posmap.get(1) == t["p1"] else 0
            bucket(agg["by_ticket"], ticket, hit)
            agg["by_ticket"][ticket].setdefault("p1", {"n": 0, "hits": 0})
            b = agg["by_ticket"][ticket]["p1"]
            b["n"] += 1
            b["hits"] += p1hit
            bucket(agg["by_hippo"].setdefault(hip, {}), ticket, hit)
            bucket(agg["by_slot"][slot], ticket, hit)
            bucket(agg["by_delay"].setdefault(delay, {}), ticket, hit)
            race_hits[ticket] = hit
        # Gains exacts (vrais paris): Couplé gagnant = nos 2 == P1+P2,
        # Trio = nos 3 == P1+P2+P3 (désordre).
        if "couple" in by_ticket and t["p1"] is not None and t["p2"] is not None:
            nums = {n for _, n in by_ticket["couple"] if n is not None}
            w = 1 if len(nums) == 2 and nums == {t["p1"], t["p2"]} else 0
            bucket(agg["by_ticket"], "couple_win", w)
            bucket(agg["by_hippo"].setdefault(hip, {}), "couple_win", w)
            bucket(agg["by_slot"][slot], "couple_win", w)
            bucket(agg["by_delay"].setdefault(delay, {}), "couple_win", w)
        if "trio" in by_ticket and t["p1"] is not None and t["p2"] is not None and t["p3"] is not None:
            tset = {n for _, n in by_ticket["trio"] if n is not None}
            w = 1 if len(tset) == 3 and tset == {t["p1"], t["p2"], t["p3"]} else 0
            bucket(agg["by_ticket"], "trio_win", w)
            bucket(agg["by_hippo"].setdefault(hip, {}), "trio_win", w)
            bucket(agg["by_slot"][slot], "trio_win", w)
            bucket(agg["by_delay"].setdefault(delay, {}), "trio_win", w)
        if "trio_coh" in by_ticket and t["p1"] is not None and t["p2"] is not None and t["p3"] is not None:
            tset = {n for _, n in by_ticket["trio_coh"] if n is not None}
            w = 1 if len(tset) == 3 and tset == {t["p1"], t["p2"], t["p3"]} else 0
            bucket(agg["by_ticket"], "trio_coh_win", w)
            bucket(agg["by_hippo"].setdefault(hip, {}), "trio_coh_win", w)
            bucket(agg["by_slot"][slot], "trio_coh_win", w)
            bucket(agg["by_delay"].setdefault(delay, {}), "trio_coh_win", w)
        if "trio_v3" in by_ticket and t["p1"] is not None and t["p2"] is not None and t["p3"] is not None:
            tset = {n for _, n in by_ticket["trio_v3"] if n is not None}
            w = 1 if len(tset) == 3 and tset == {t["p1"], t["p2"], t["p3"]} else 0
            bucket(agg["by_ticket"], "trio_v3_win", w)
            bucket(agg["by_hippo"].setdefault(hip, {}), "trio_v3_win", w)
            bucket(agg["by_slot"][slot], "trio_v3_win", w)
            bucket(agg["by_delay"].setdefault(delay, {}), "trio_v3_win", w)
        # Kanti-8: Top5 dans nos 8 (5 classés + 3 réserves).
        actual5 = [x for x in (t["p1"], t["p2"], t["p3"], t["p4"], t["p5"]) if x is not None]
        if "quinte" in by_ticket and "reserve" in by_ticket and len(actual5) == 5:
            q = [n for pos, n in sorted(by_ticket["quinte"], key=lambda x: (x[0] is None, x[0] or 99))
                 if pos in (1, 2, 3, 4, 5) and n is not None][:5]
            r = [n for _, n in by_ticket["reserve"] if n is not None][:3]
            eight = list(dict.fromkeys(q + r))[:8]
            if len(eight) >= 8:
                hit = len(set(eight) & set(actual5))
                bucket(agg["by_ticket"], "kanti8", hit)
                bucket(agg["by_hippo"].setdefault(hip, {}), "kanti8", hit)
                bucket(agg["by_slot"][slot], "kanti8", hit)
                bucket(agg["by_delay"].setdefault(delay, {}), "kanti8", hit)
                w = 1 if hit == 5 else 0
                bucket(agg["by_ticket"], "kanti8_win", w)
                bucket(agg["by_hippo"].setdefault(hip, {}), "kanti8_win", w)
                bucket(agg["by_slot"][slot], "kanti8_win", w)
                bucket(agg["by_delay"].setdefault(delay, {}), "kanti8_win", w)
        # Syn8: Quinté-8 de la presse (même métrique que Kanti-8 — duel direct).
        if "syn8" in by_ticket and len(actual5) == 5:
            eight = [n for _, n in by_ticket["syn8"] if n is not None][:8]
            if len(eight) >= 8:
                hit = len(set(eight) & set(actual5))
                bucket(agg["by_ticket"], "syn8", hit)
                bucket(agg["by_hippo"].setdefault(hip, {}), "syn8", hit)
                bucket(agg["by_slot"][slot], "syn8", hit)
                bucket(agg["by_delay"].setdefault(delay, {}), "syn8", hit)
                w = 1 if hit == 5 else 0
                bucket(agg["by_ticket"], "syn8_win", w)
                bucket(agg["by_hippo"].setdefault(hip, {}), "syn8_win", w)
                bucket(agg["by_slot"][slot], "syn8_win", w)
                bucket(agg["by_delay"].setdefault(delay, {}), "syn8_win", w)
        # Expert (lecture vraie, sans ancre marché): trio ordonné + 8.
        if "expert_trio" in by_ticket and t["p1"] is not None and t["p2"] is not None and t["p3"] is not None:
            posmap = {}
            for pos, n in by_ticket["expert_trio"]:
                if pos in (1, 2, 3) and n is not None and pos not in posmap:
                    posmap[pos] = n
            if len(posmap) == 3:
                tset = set(posmap.values())
                cov = len(tset & actual3)
                w = 1 if tset == {t["p1"], t["p2"], t["p3"]} else 0
                bucket(agg["by_ticket"], "expert_trio", cov)
                bucket(agg["by_hippo"].setdefault(hip, {}), "expert_trio", cov)
                bucket(agg["by_slot"][slot], "expert_trio", cov)
                bucket(agg["by_delay"].setdefault(delay, {}), "expert_trio", cov)
                bucket(agg["by_ticket"], "expert_trio_win", w)
                bucket(agg["by_hippo"].setdefault(hip, {}), "expert_trio_win", w)
                bucket(agg["by_slot"][slot], "expert_trio_win", w)
                bucket(agg["by_delay"].setdefault(delay, {}), "expert_trio_win", w)
        if "expert_8" in by_ticket and len(actual5) == 5:
            eight = [n for _, n in by_ticket["expert_8"] if n is not None][:8]
            if len(eight) == 8:
                hit = len(set(eight) & set(actual5))
                bucket(agg["by_ticket"], "expert_8", hit)
                bucket(agg["by_hippo"].setdefault(hip, {}), "expert_8", hit)
                bucket(agg["by_slot"][slot], "expert_8", hit)
                bucket(agg["by_delay"].setdefault(delay, {}), "expert_8", hit)
                w = 1 if hit == 5 else 0
                bucket(agg["by_ticket"], "expert_8_win", w)
                bucket(agg["by_hippo"].setdefault(hip, {}), "expert_8_win", w)
                bucket(agg["by_slot"][slot], "expert_8_win", w)
                bucket(agg["by_delay"].setdefault(delay, {}), "expert_8_win", w)
        # Flip: fav#1 x outsiders cachés — duel direct contre les structures classiques.
        if "flip_cpl" in by_ticket and t["p1"] is not None and t["p2"] is not None:
            pairs = []
            for _, n in by_ticket["flip_cpl"]:
                if n is None:
                    continue
                if pairs and len(pairs[-1]) == 1:
                    pairs[-1].append(n)
                else:
                    pairs.append([n])
            pairs = [p for p in pairs if len(p) == 2]
            cov = max([len(set(pr) & actual3) for pr in pairs] + [0]) if pairs else 0
            w = 1 if any(set(pr) == {t["p1"], t["p2"]} for pr in pairs) else 0
            bucket(agg["by_ticket"], "flip_cpl", cov)
            bucket(agg["by_hippo"].setdefault(hip, {}), "flip_cpl", cov)
            bucket(agg["by_slot"][slot], "flip_cpl", cov)
            bucket(agg["by_delay"].setdefault(delay, {}), "flip_cpl", cov)
            bucket(agg["by_ticket"], "flip_cpl_win", w)
            bucket(agg["by_hippo"].setdefault(hip, {}), "flip_cpl_win", w)
            bucket(agg["by_slot"][slot], "flip_cpl_win", w)
            bucket(agg["by_delay"].setdefault(delay, {}), "flip_cpl_win", w)
        if "flip_trio" in by_ticket and t["p1"] is not None and t["p2"] is not None and t["p3"] is not None:
            tset = {n for _, n in by_ticket["flip_trio"] if n is not None}
            cov = len(tset & actual3)
            w = 1 if len(tset) == 3 and tset == {t["p1"], t["p2"], t["p3"]} else 0
            bucket(agg["by_ticket"], "flip_trio", cov)
            bucket(agg["by_hippo"].setdefault(hip, {}), "flip_trio", cov)
            bucket(agg["by_slot"][slot], "flip_trio", cov)
            bucket(agg["by_delay"].setdefault(delay, {}), "flip_trio", cov)
            bucket(agg["by_ticket"], "flip_trio_win", w)
            bucket(agg["by_hippo"].setdefault(hip, {}), "flip_trio_win", w)
            bucket(agg["by_slot"][slot], "flip_trio_win", w)
            bucket(agg["by_delay"].setdefault(delay, {}), "flip_trio_win", w)
        # --- Miss analysis: trio 0/3 -> chaos or selection error? ---
        if "trio" in by_ticket and race_hits.get("trio") == 0 and len(actual3) >= 3:
            trio_set = {n for _, n in by_ticket["trio"] if n is not None}
            our8 = {n for _, n in (by_ticket.get("quinte", []) + by_ticket.get("reserve", []))
                    if n is not None}
            winfo = []
            for pos, w in ((1, t["p1"]), (2, t["p2"]), (3, t["p3"])):
                if w is None:
                    continue
                winfo.append({"pos": pos, "num": w, "cote": cote_of.get(w),
                              "rank": mrank.get(w)})
            r3 = [w for w in winfo if (w["rank"] or 99) <= 3 and w["num"] not in trio_set]
            in8 = [w for w in winfo if w["num"] in our8 and w["num"] not in trio_set]
            known = [w for w in winfo if w["rank"] is not None]
            allout = (len(winfo) == 3 and len(known) >= 2
                      and all(w["rank"] >= 4 for w in known))
            if allout:
                verdict = "chaos"
            elif r3:
                verdict = "selection"
            elif in8:
                verdict = "construction"
            else:
                verdict = "mixte"
            misses.append({"date": t["date"], "rnum": t["reunion_num"], "cnum": t["course_num"],
                           "hippodrome": t.get("hippodrome"), "verdict": verdict, "winners": winfo})
        # --- ROI (€, rapports PMU-internet stockés) ---
        pay = None
        try:
            from race_rapports import get_stored as _get_pay
            pay = _get_pay(db, t["date"], t["reunion_num"], t["course_num"])
        except Exception:
            pay = None
        if pay:
            ecouple = pay.get("ecouple_gagnant_rows") or []
            trio_d = pay.get("trio_rows") or []
            trio_o = pay.get("trio_ordre_rows") or []
            quinte = pay.get("quinte_rows") or []

            def _gagnant(rows, want):
                for r in rows:
                    try:
                        if "gagnant" in str(r.get("type", "")).lower() and set(r.get("combi", [])) == set(want):
                            return float(r["rapport"])
                    except (TypeError, ValueError):
                        continue
                return 0.0

            def _first(rows, *needles):
                for r in rows:
                    tl = str(r.get("type", "")).lower().replace(" ", "")
                    if all(x in tl for x in needles):
                        try:
                            return float(r["rapport"])
                        except (TypeError, ValueError):
                            continue
                return 0.0

            def _roi_tick(key, cost, credit):
                b = agg["roi"].setdefault(key, {"n": 0, "staked": 0.0, "returned": 0.0, "max1": 0.0})
                b["n"] += 1
                b["staked"] += cost
                b["returned"] += credit
                if credit > b["max1"]:
                    b["max1"] = credit

            trio_by_pos = {}
            for pos, n in by_ticket.get("trio", []):
                if pos in (1, 2, 3) and n is not None and pos not in trio_by_pos:
                    trio_by_pos[pos] = n
            bench3_by_pos = {}
            for pos, n in by_ticket.get("bench3", []):
                if pos in (1, 2, 3) and n is not None and pos not in bench3_by_pos:
                    bench3_by_pos[pos] = n
            triocoh_by_pos = {}
            for pos, n in by_ticket.get("trio_coh", []):
                if pos in (1, 2, 3) and n is not None and pos not in triocoh_by_pos:
                    triocoh_by_pos[pos] = n
            triov3_by_pos = {}
            for pos, n in by_ticket.get("trio_v3", []):
                if pos in (1, 2, 3) and n is not None and pos not in triov3_by_pos:
                    triov3_by_pos[pos] = n
            # couple (1 paire loggée) + bench2
            for key, lst in (("couple", by_ticket.get("couple", [])),
                             ("bench2", by_ticket.get("bench2", []))):
                nums = [n for _, n in lst if n is not None][:2]
                if len(nums) == 2 and t["p1"] is not None and t["p2"] is not None and ecouple:
                    _roi_tick(key, 1.0,
                              _gagnant(ecouple, {t["p1"], t["p2"]}) if set(nums) == {t["p1"], t["p2"]} else 0.0)
            # trio + bench3 + trio_coh + trio_v3 (désordre + ordre exact)
            for key, posmap in (("trio", trio_by_pos), ("bench3", bench3_by_pos),
                                ("trio_coh", triocoh_by_pos), ("trio_v3", triov3_by_pos)):
                if len(posmap) == 3 and t["p1"] is not None and t["p2"] is not None and t["p3"] is not None and trio_d:
                    tset = set(posmap.values())
                    cred = _gagnant(trio_d, {t["p1"], t["p2"], t["p3"]}) if tset == {t["p1"], t["p2"], t["p3"]} else 0.0
                    _roi_tick(key, 1.0, cred)
                    ordered = [posmap.get(1), posmap.get(2), posmap.get(3)]
                    if trio_o and ordered == [t["p1"], t["p2"], t["p3"]]:
                        _roi_tick(key + "-ordre", 1.0, _gagnant(trio_o, {t["p1"], t["p2"], t["p3"]}))
                    elif trio_o:
                        _roi_tick(key + "-ordre", 1.0, 0.0)
            # flip_cpl (3 paires, 3€) + flip_trio (1€)
            if "flip_cpl" in by_ticket and t["p1"] is not None and t["p2"] is not None and ecouple:
                fprs = []
                for _, n in by_ticket["flip_cpl"]:
                    if n is None:
                        continue
                    if fprs and len(fprs[-1]) == 1:
                        fprs[-1].append(n)
                    else:
                        fprs.append([n])
                fprs = [p for p in fprs if len(p) == 2]
                if fprs:
                    won = any(set(pr) == {t["p1"], t["p2"]} for pr in fprs)
                    _roi_tick("flip_cpl", 3.0, _gagnant(ecouple, {t["p1"], t["p2"]}) if won else 0.0)
            if "flip_trio" in by_ticket and t["p1"] is not None and t["p2"] is not None and t["p3"] is not None and trio_d:
                fset = {n for _, n in by_ticket["flip_trio"] if n is not None}
                if len(fset) == 3:
                    _roi_tick("flip_trio", 1.0,
                              _gagnant(trio_d, {t["p1"], t["p2"], t["p3"]}) if fset == {t["p1"], t["p2"], t["p3"]} else 0.0)
            # expert_trio (ordonné 1-2-3): désordre + ordre exact
            if "expert_trio" in by_ticket and t["p1"] is not None and t["p2"] is not None and t["p3"] is not None and trio_d:
                emap = {}
                for pos, n in by_ticket["expert_trio"]:
                    if pos in (1, 2, 3) and n is not None and pos not in emap:
                        emap[pos] = n
                if len(emap) == 3:
                    eset = set(emap.values())
                    cred = _gagnant(trio_d, {t["p1"], t["p2"], t["p3"]}) if eset == {t["p1"], t["p2"], t["p3"]} else 0.0
                    _roi_tick("expert_trio", 1.0, cred)
                    ordered = [emap.get(1), emap.get(2), emap.get(3)]
                    if trio_o and ordered == [t["p1"], t["p2"], t["p3"]]:
                        _roi_tick("expert_trio-ordre", 1.0, _gagnant(trio_o, {t["p1"], t["p2"], t["p3"]}))
                    elif trio_o:
                        _roi_tick("expert_trio-ordre", 1.0, 0.0)
            # kanti8 + syn8 (champ réduit 8, 56€): désordre + bonus 4/5
            if quinte and len(actual5) == 5:
                des = _first(quinte, "desordre")
                bon4 = _first(quinte, "4sur5", "bonus") or _first(quinte, "bonus", "4")
                if not bon4:
                    for r_ in quinte:
                        if "bonus" in str(r_.get("type", "")).lower() and "3" not in str(r_.get("type", "")):
                            try:
                                bon4 = float(r_["rapport"])
                                break
                            except (TypeError, ValueError):
                                continue
                for key, nums8 in (("kanti8", None), ("syn8", None), ("expert_8", None)):
                    if key == "kanti8":
                        if not ("quinte" in by_ticket and "reserve" in by_ticket):
                            continue
                        q = [n for pos, n in sorted(by_ticket["quinte"], key=lambda x: (x[0] is None, x[0] or 99))
                             if pos in (1, 2, 3, 4, 5) and n is not None][:5]
                        rr = [n for _, n in by_ticket["reserve"] if n is not None][:3]
                        nums8 = list(dict.fromkeys(q + rr))[:8]
                    elif key == "expert_8":
                        nums8 = [n for _, n in by_ticket.get("expert_8", []) if n is not None][:8]
                    else:
                        nums8 = [n for _, n in by_ticket.get("syn8", []) if n is not None][:8]
                    if len(nums8) == 8:
                        inset = len(set(nums8) & set(actual5))
                        cred = des if inset == 5 else (bon4 if inset == 4 else 0.0)
                        _roi_tick(key, 56.0, cred)
        else:
            agg["roi_norapports"] = agg.get("roi_norapports", 0) + 1
        mlabel = "%s · %s R%s" % (t["date"], t.get("hippodrome") or "?", t["reunion_num"])
        mkey = (t["date"], _norm_hip(t.get("hippodrome")), t["reunion_num"])
        drivers_p1 = set()
        for p in picks:
            if p["target_pos"] == 1 and p["ticket"] in ("trio", "quinte", "bench2", "bench3"):
                d = (p["driver"] or "").strip().upper()
                if d:
                    drivers_p1.add(d)
        for d in drivers_p1:
            port_counter.setdefault(mlabel, {}).setdefault(d, 0)
            port_counter[mlabel][d] += 1
        # --- Température du meeting: favoris parmi les gagnants précédents ---
        try:
            cnum = int(t["course_num"] or 0)
        except (TypeError, ValueError):
            cnum = 0
        hist = meet_fav.setdefault(mkey, [])
        earlier = [f for (c, f) in hist if c < cnum and f is not None]
        if len(earlier) < 2:
            temp = "early (C1-C2)"
        else:
            fr = sum(earlier) / len(earlier)
            temp = "hot (fav)" if fr >= 0.6 else ("cold (outs)" if fr <= 1 / 3 else "neutral")
        for ticket in ("trio", "couple", "bench2", "bench3"):
            if ticket in race_hits:
                bucket(agg["by_temp"].setdefault(temp, {}), ticket, race_hits[ticket])
        cote_of = {}
        for p in picks:
            try:
                c = float(p["cote"]) if p["cote"] is not None else None
            except (TypeError, ValueError):
                c = None
            if c and c > 0 and p["num"] is not None:
                if p["num"] not in cote_of or c < cote_of[p["num"]]:
                    cote_of[p["num"]] = c
        if cote_of and t["p1"] is not None:
            fav1 = min(cote_of, key=lambda n: (cote_of[n], n))
            hist.append((cnum, 1 if fav1 == t["p1"] else 0))
        else:
            hist.append((cnum, None))
    db.close()

    def fmt(d):
        o = {}
        for k, v in d.items():
            if isinstance(v, dict) and "n" in v:
                o[k] = {"n": v["n"], "hits": v["hits"],
                        "avg": round(v["hits"] / v["n"], 2) if v["n"] else 0}
                if isinstance(v.get("p1"), dict) and "n" in v["p1"]:
                    p1 = v["p1"]
                    o[k]["p1"] = {"n": p1["n"], "hits": p1["hits"],
                                  "avg": round(p1["hits"] / p1["n"], 3) if p1["n"] else 0}
            else:
                o[k] = fmt(v)
        return o

    out = {"n": agg["n"], "by_ticket": {}, "by_hippo": {}, "by_slot": {}, "by_delay": {},
           "by_temp": {}, "portfolio": [], "roi": {}, "roi_norapports": agg.get("roi_norapports", 0)}
    for k in ("by_ticket", "by_hippo", "by_slot", "by_delay", "by_temp"):
        out[k] = fmt(agg[k])
    for tk, v in (agg.get("roi") or {}).items():
        out["roi"][tk] = {"n": v["n"], "staked": round(v["staked"], 1), "returned": round(v["returned"], 1),
                          "roi": round(100 * v["returned"] / v["staked"], 1) if v["staked"] else 0,
                          "maxshare": round(100 * v.get("max1", 0) / v["returned"], 1) if v["returned"] else 0}
    # flatten nested group → ticket levels for table display
    for k in ("by_hippo", "by_slot", "by_delay", "by_temp"):
        flat = {}
        for group, tickets in (out[k] or {}).items():
            if not isinstance(tickets, dict):
                continue
            for ticket, v in tickets.items():
                if isinstance(v, dict) and "avg" in v:
                    flat["%s · %s" % (group, ticket)] = v
        out[k] = flat
    # flatten p1 sub-buckets
    for ticket, v in out["by_ticket"].items():
        if isinstance(v, dict) and "p1" in v and isinstance(v["p1"], dict):
            v["p1_avg"] = v["p1"]["hits"] / v["p1"]["n"] if v["p1"]["n"] else 0
    # portefeuille drivers par meeting (concentration P1)
    for mlabel, dc in sorted(port_counter.items()):
        ds = sorted(dc.items(), key=lambda x: -x[1])
        if ds:
            out["portfolio"].append({"meeting": mlabel, "drivers": [[d, c] for d, c in ds[:6]],
                                    "max": ds[0][1]})
    return jsonify(out)
