from flask import Blueprint, request, jsonify
from database import get_db
import sqlite3
import json as _json
import os
import datetime
from datetime import date as _date, timedelta

synthese_bp = Blueprint('synthese', __name__)

def _parse_top5(arrivee):
    if arrivee is None:
        return []
    s = str(arrivee).strip()
    if not s:
        return []
    try:
        obj = _json.loads(s)
        if isinstance(obj, list):
            out = []
            for e in obj:
                if isinstance(e, list) and e:
                    out.append(int(e[0]))
                elif isinstance(e, (int, float)):
                    out.append(int(e))
            return out[:5]
    except Exception:
        pass
    return [int(t) for t in s.replace(';', ',').split(',') if t.strip().lstrip('-').isdigit()][:5]


@synthese_bp.route('/api/synthese/history', methods=['GET'])
def history():
    """Historique des QuintÃ©s avec arrivÃ©es officielles (Top5 dans l'ordre).
    N'inclut que les courses rÃ©solues (au moins P1-P3 connus)."""
    try:
        limit = int(request.args.get('limit', 20))
    except (TypeError, ValueError):
        limit = 20
    limit = max(1, min(limit, 60))
    conn = get_db()
    rows = conn.execute(
        "SELECT race_id, date, hippodrome, prix FROM races "
        "WHERE quinte=1 ORDER BY date DESC LIMIT ?", (limit,)).fetchall()
    out = []
    for r in rows:
        parts = conn.execute(
            "SELECT num FROM participants WHERE race_id=? AND rang BETWEEN 1 AND 5 ORDER BY rang",
            (r["race_id"],)).fetchall()
        top5 = [p["num"] for p in parts]
        if len(top5) < 3:
            continue
        syn8 = None
        try:
            pr = conn.execute("SELECT synthese FROM presse_synthese WHERE date=?", (r["date"],)).fetchone()
            if pr and pr["synthese"]:
                obj = _json.loads(pr["synthese"]) if isinstance(pr["synthese"], str) else pr["synthese"]
                nums = [int(n) for n in (obj or []) if n is not None]
                if len(nums) >= 8:
                    syn8 = nums[:8]
        except Exception:
            syn8 = None
        out.append({"date": r["date"], "hippodrome": r["hippodrome"], "prix": r["prix"],
                    "arrivee": top5, "synthese8": syn8})
    conn.close()
    return jsonify({"races": out})


@synthese_bp.route('/api/synthese/ecarts', methods=['GET'])
def ecarts():
    """Places hit/miss in recent window (default 14 days).
    Returns per place P1..P18: hit (bool), last_hit date, days_since.
    No averages, no predictions â€” just recent presence/absence."""
    try:
        days = int(request.args.get('days', 14))
    except (TypeError, ValueError):
        days = 14
    days = max(1, min(days, 90))
    from QUINTE.synthese_service import _secret_display_order
    conn = get_db()
    today = _date.today().isoformat()
    cutoff = (_date.today() - timedelta(days=days)).isoformat()
    races = conn.execute(
        "SELECT race_id, date, hippodrome FROM races "
        "WHERE quinte=1 AND arrivee IS NOT NULL AND date >= ? "
        "ORDER BY date DESC",
        (cutoff,)).fetchall()
    places = {p: {"hit": False, "last_hit": None} for p in range(1, 19)}
    n_races = 0
    for row in conn.execute(
        "SELECT race_id, date, hippodrome, arrivee FROM races "
        "WHERE quinte=1 AND arrivee IS NOT NULL AND date >= ? ORDER BY date DESC",
        (cutoff,)).fetchall():
        race = dict(row)
        top5 = _parse_top5(race.get('arrivee'))
        if len(top5) < 5:
            continue
        base = None
        try:
            pr = conn.execute("SELECT synthese FROM presse_synthese WHERE date=?",
                              (race['date'],)).fetchone()
            if pr and pr['synthese']:
                obj = _json.loads(pr['synthese']) if isinstance(pr['synthese'], str) else pr['synthese']
                nums = [int(n) for n in (obj or []) if n is not None]
                if len(nums) >= 14:
                    base = nums[:18]
        except Exception:
            base = None
        if base is None:
            parts = [dict(x) for x in conn.execute(
                "SELECT num, cote_pmu FROM participants WHERE race_id=?",
                (race['race_id'],)).fetchall()]
            parts.sort(key=lambda p: ((p.get('cote_pmu') is None),
                                      p.get('cote_pmu') if p.get('cote_pmu') is not None else 999,
                                      p.get('num') or 999))
            base = [p['num'] for p in parts[:18]]
        order = _secret_display_order(base) if base else []
        place_of = {n: i + 1 for i, n in enumerate(order)}
        n_races += 1
        for n in top5:
            p = place_of.get(n)
            if p is None or p > 18:
                continue
            places[p]['hit'] = True
            if race['date'] > (places[p]['last_hit'] or ''):
                places[p]['last_hit'] = race['date']
        n_races += 1
    conn.close()
    out = []
    for p in range(1, 19):
        h = places[p]['hit']
        last = places[p]['last_hit']
        days_since = None
        if places[p]['last_hit']:
            try:
                gap = (_date.fromisoformat(_date.today().isoformat()) - _date.fromisoformat(places[p]['last_hit'])).days
            except Exception:
                gap = None
            days_since = gap
        else:
            days_since = None
        out.append({"place": p, "hit": bool(h), "last_hit": last, "days_since": days_since})
    out.sort(key=lambda x: (0 if x['hit'] else 1, x['place']))
    return jsonify({"today": today, "days": days, "races": n_races, "places": out})

def _presse_row(conn, date):
    try:
        r = conn.execute("SELECT date, hippodrome, prix, synthese FROM presse_synthese WHERE date=?", (date,)).fetchone()
        if not r:
            return None
        nums = _json.loads(r["synthese"]) if r["synthese"] else []
        return {"date": r["date"], "found": True, "source": "presse-turfinfo",
                "race": {"hippodrome": r["hippodrome"], "prix": r["prix"]}, "synthese": nums}
    except Exception:
        return None

def _store_presse(conn, data):
    try:
        if not data.get("date") or not data.get("synthese"):
            return
        conn.execute("""INSERT INTO presse_synthese (date, hippodrome, prix, synthese, resultat, fetched_at)
            VALUES (?,?,?,?,?,CURRENT_TIMESTAMP)
            ON CONFLICT(date) DO UPDATE SET hippodrome=excluded.hippodrome, prix=excluded.prix,
            synthese=excluded.synthese, resultat=excluded.resultat, fetched_at=CURRENT_TIMESTAMP""",
            (data["date"], data.get("hippodrome"), data.get("prix"),
             _json.dumps(data["synthese"]),
             "-".join(map(str, data["resultat"])) if data.get("resultat") else None))
        conn.commit()
    except Exception:
        pass

def _market_line(date):
    """The money's view of the same race: every runner, its cote and its rank.

    This is what the method needs. The press must fill its first three places,
    so it puts a horse nobody is on there. Measured on the real syntheses we
    hold: a press entry whose horse the money had in its top five finishes
    67% of the time, an entry it does not back finishes 25%.
    """
    conn = get_db()
    try:
        race = conn.execute(
            "SELECT race_id FROM races WHERE date=? AND quinte=1 "
            "ORDER BY runners DESC LIMIT 1", (date,)).fetchone()
        if not race:
            return None
        parts = conn.execute(
            """SELECT num, cote_pmu, rang FROM participants
               WHERE race_id=? AND rang IS NOT NULL AND rang<90
                 AND cote_pmu IS NOT NULL
               ORDER BY cote_pmu ASC, num ASC""",
            (race["race_id"],)).fetchall()
        if len(parts) < 8:
            return None
        out = {}
        for i, p in enumerate(parts):
            out[int(p["num"])] = {
                "cote": p["cote_pmu"],
                "rank": i + 1,
                "rang": p["rang"],
            }
        return {"n": len(out), "line": out}
    except Exception:
        return None
    finally:
        conn.close()


def _flag(line, nums):
    """Mark every synthesis number complete or hollow, in the press order."""
    if not line or not nums:
        return {}
    out = {}
    for pos, n in enumerate(nums or [], 1):
        if n is None:
            continue
        m = line["line"].get(int(n))
        out[str(n)] = {
            "pos": pos,
            "cote": (m or {}).get("cote"),
            "rank": (m or {}).get("rank"),
            "backed": bool(m and m["rank"] <= 5),
        }
    return out


def _with_market(payload):
    date = payload.get("date")
    try:
        line = _market_line(date)
    except Exception:
        line = None
    payload["market"] = line
    payload["quality"] = _flag(line, payload.get("synthese"))
    return jsonify(payload)


@synthese_bp.route('/api/synthese', methods=['GET'])
def get_synthese():
    return _synthese_core()


@synthese_bp.route('/api/synthese/core', methods=['GET'])
def _unused():
    return _synthese_core()


def _synthese_core():
    date = request.args.get('date')
    if not date:
        return jsonify({"error": "date required (YYYY-MM-DD)"}), 400
    conn = get_db()
    # 1) Daily presse fetch (pronostics-turf.info) â€” stored, served first
    hit = _presse_row(conn, date)
    if hit and len(hit.get("synthese", [])) >= 14:
        conn.close()
        return _with_market(hit)
    # 1b) Live presse fetch (homepage covers today/tomorrow) â€” store + serve
    try:
        from scraper.turfinfo_scraper import fetch_daily
        live = fetch_daily()
        if live.get("date") == date and len(live.get("synthese", [])) >= 14:
            _store_presse(conn, live)
            conn.close()
            return _with_market({"date": date, "found": True, "source": "presse-turfinfo-live",
                                 "race": {"hippodrome": live.get("hippodrome"), "prix": live.get("prix")},
                                 "synthese": live["synthese"]})
    except Exception:
        pass
    # Find quintÃ© races for that date
    rows = conn.execute("SELECT race_id, hippodrome, prix FROM races WHERE date=? AND quinte=1 ORDER BY race_id LIMIT 5", (date,)).fetchall()
    if not rows:
        # Fallback: try live Geny for future dates
        try:
            from datetime import datetime as _dt
            from scraper.geny_scraper import get_scraper
            scraper = get_scraper()
            prog = scraper.fetch_programme(_dt.strptime(date, "%Y-%m-%d").date())
            for m in prog.get("meetings", []):
                for c in m.get("courses", []):
                    if c.get("quinte"):
                        # Try to fetch partants for this course
                        data = scraper.fetch_race_details(c.get("id"))
                        if data and data.get("participants"):
                            nums = [p.get("num") for p in sorted(data["participants"], key=lambda x: (x.get("cotePmu") is None, x.get("cotePmu") or 999))][:18]
                            while len(nums) < 14:
                                nums.append(None)
                            conn.close()
                            return _with_market({"date": date, "found": True, "race": {"hippodrome": m.get("hippodrome"), "prix": c.get("prix"), "race_id": c.get("id")}, "synthese": nums, "source": "geny-live"})
        except Exception:
            pass
        conn.close()
        # Fallback to default 14 when no QuintÃ© (e.g. future date)
        default_nums = [14, 9, 13, 12, 6, 10, 2, 4, 11, 7, 8, 3, 5, 1]
        return _with_market({"date": date, "found": False, "message": "Aucun Quinte trouve pour cette date - Synthese par defaut affichee", "synthese": default_nums, "race": {"hippodrome": "-", "prix": "-"}})
    # Take first quintÃ© (PMU usually has 1 QuintÃ© per day)
    race = dict(rows[0])
    parts = conn.execute("SELECT num, cote_pmu, horse FROM participants WHERE race_id=? ORDER BY cote_pmu ASC, num ASC", (race["race_id"],)).fetchall()
    conn.close()
    if not parts:
        return jsonify({"date": date, "found": False, "message": "Participants non trouvÃ©s"}), 404
    # Build up to 18 numbers in press order (by cote)
    nums = [p["num"] for p in parts][:18]
    # Pad if less than 14
    while len(nums) < 14:
        nums.append(None)
    # Build meta
    race["synthese"] = nums
    race["count"] = len([n for n in nums if n is not None])
    return _with_market({"date": date, "found": True, "race": race, "synthese": nums, "source": "market-fallback"})


# --------------------------------------------------------------------------
# What the archive knows about each runner, for the race of the day.
#
# The market price says where a horse is expected. It does not say whether the
# horse has run this distance before, how long it has been away, or whether its
# record is strong and only its recent form is poor. Those are the two cases that
# decide whether a group is worth trusting: a G5 horse whose form looks bad
# because of a long layoff, and a G1 horse whose form looks good but has never
# run at this distance.
#
# Everything is computed from races that finished BEFORE the race asked about, so
# nothing here can see the result it is being used to predict. A horse with no
# history returns nulls rather than zeros, because zero runs and zero wins are
# different facts and only one of them is a record.
#
# Distance is banded at 200 m, which is the width the archives use elsewhere.
# Going is not used: it is recorded for 1.3% of races, so a rule leaning on it
# would be a rule that silently does nothing.
DNA_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "dna_archive.db")
# a SQLite file: URI wants forward slashes; the raw Windows path has backslashes
# and every open of it fails, which is what made this endpoint return nothing
_DNA_URI = DNA_PATH.replace(chr(92), "/")


def _history_for(hid, before_date):
    """Every past run of one horse: (date, distance, place)."""
    try:
        c = sqlite3.connect("file:%s?mode=ro" % _DNA_URI, uri=True, timeout=20)
        c.row_factory = sqlite3.Row
        out = []
        for r in c.execute(
                "SELECT d.date, d.dist, rr.rang FROM runners rr "
                "JOIN race_dna d ON d.rid = rr.rid "
                "WHERE rr.hid = ? AND rr.rang IS NOT NULL AND d.date < ? "
                "AND d.date IS NOT NULL",
                (hid, before_date)):
            out.append((r["date"], r["dist"], r["rang"]))
        c.close()
    except Exception:
        return None
    return out or None


def _horse_signals(hid, race_date, distance):
    h = _history_for(hid, race_date)
    if not h:
        return {"runs": None, "last_run": None, "days_since": None,
                "dist_runs": None, "dist_wins": None, "dist_top3": None,
                "wins": None, "top3": None, "last5_top3": None}
    h.sort(key=lambda x: x[0])
    band = int(distance) // 200 * 200 if distance else None
    same = [x for x in h if band and x[1] and int(x[1]) // 200 * 200 == band]
    last5 = h[-5:]
    last_date = h[-1][0]
    try:
        d0 = datetime.date.fromisoformat(last_date)
        d1 = datetime.date.fromisoformat(race_date)
        days = (d1 - d0).days
    except Exception:
        days = None
    return {
        "runs": len(h),
        "last_run": last_date,
        "days_since": days,
        "dist_runs": len(same),
        "dist_wins": sum(1 for x in same if x[2] == 1),
        "dist_top3": sum(1 for x in same if x[2] and x[2] <= 3),
        "wins": sum(1 for x in h if x[2] == 1),
        "top3": sum(1 for x in h if x[2] and x[2] <= 3),
        "last5_top3": sum(1 for x in last5 if x[2] and x[2] <= 3),
    }


@synthese_bp.route("/api/synthese/signals", methods=["GET"])
def synthese_signals():
    """Per-runner archive signals for the Quinté of a date, for the engine."""
    d = request.args.get("date")
    if not d:
        return jsonify({"error": "date required (YYYY-MM-DD)"}), 400
    conn = get_db()
    race = conn.execute(
        "SELECT race_id, distance, reunion_num, course_num FROM races "
        "WHERE date=? AND quinte=1 ORDER BY race_id LIMIT 1", (d,)).fetchone()
    if not race:
        return jsonify({"error": "no Quinté on that date"}), 404
    rows = conn.execute(
        "SELECT num, horse FROM participants WHERE race_id=? AND horse IS NOT NULL "
        "AND horse <> ''", (race["race_id"],)).fetchall()
    conn.close()

    # archive.db carries a composite horse_id of the shape
    # "ANSSIO-VARSITY-SCISSOR KICK ANSSIO" while dna_archive keys on a numeric
    # hid, so the two cannot be joined on id and the name is the only key they
    # share. Matched on name, case-folded, the lookup returned a hid for every
    # one of the sixteen runners of the 29 September race; matched on id it
    # returned none, which is why the first run of this endpoint came back empty.
    hids = {}
    try:
        dc = sqlite3.connect("file:%s?mode=ro" % _DNA_URI, uri=True, timeout=20)
        dc.row_factory = sqlite3.Row
        for r in dc.execute("SELECT hid, name FROM horses"):
            hids[(r["name"] or "").strip().upper()] = r["hid"]
        dc.close()
    except Exception as e:
        return jsonify({"error": "horse index unavailable: %s" % e}), 500

    out = {}
    unmatched = []
    for r in rows:
        hid = hids.get((r["horse"] or "").strip().upper())
        if hid is None:
            unmatched.append(r["horse"])
            continue
        s = _horse_signals(hid, d, race["distance"])
        if s.get("runs"):
            out[str(r["num"])] = s
    return jsonify({"date": d, "race_id": race["race_id"],
                    "distance": race["distance"],
                    "known": len(out), "of": len(rows),
                    "unmatched": unmatched[:8],
                    "signals": out})
