"""FLIP routes — the COUPLE engine's three couples, recorded and scored.

The page asks for a race, gets the three couples the COUPLE engine already
produces, and keeps them. Nothing is shown without its result beside it. The
same race can be read as many times as wanted: every press adds an attempt, and
the attempts for one race appear one under the other so the hour of the reading
can be compared with the hour of the result.
"""
from typing import Any, Dict, List

from flask import Blueprint, jsonify, request

from .engine import (MIN_FIELD, MAX_FIELD, check_field, normalise, score,
                     tally, market_baseline, priced_runners)
from . import store

flip_bp = Blueprint("flip", __name__, url_prefix="/api/flip")

ENGINE_VERSION = "2.0.0"
MAX_RACES = 70


def _guard_session():
    from routes.auth import require_session
    if request.method == "OPTIONS" or request.path.endswith("/health"):
        return None
    return require_session()


flip_bp.before_request(_guard_session)


@flip_bp.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status": "ok", "module": "FLIP", "version": ENGINE_VERSION,
        "scope": "les 3 couples du moteur COUPLE, enregistrés et notés, "
                 "%d à %d partants" % (MIN_FIELD, MAX_FIELD),
    })


def _is_finished(statut):
    """PMU says a race is over in several ways, so match the family."""
    s = str(statut or "").upper()
    return any(w in s for w in ("ARRIVEE", "ARRETO", "TERMINE", "FINI",
                                "CLOTUR", "RESULTAT"))


def _top5_from_ordre_arrivee(oa):
    """PMU `ordreArrivee` -> [{num, rank}].

    The field is a list of GROUPS, one per finishing place, so a dead heat is a
    group with more than one runner: [[4, 5], [2], [3]] means 4 and 5 share 1st,
    2 is 3rd, 3 is 4th. The rank of a group is one more than the number of
    runners in every group before it — not its index. Getting that wrong would
    quietly award a couple that never was.
    """
    out, rank = [], 1
    for entry in oa or []:
        nums = entry if isinstance(entry, (list, tuple)) else [entry]
        nums = [n for n in nums if n is not None]
        if not nums:
            continue
        for n in nums:
            try:
                out.append({"num": int(n), "rank": rank})
            except (TypeError, ValueError):
                pass
        rank += len(nums)
    return out


def _resolve_result(race_date, meeting, course):
    """The finish order of a race, from the archive or from PMU live.

    The archive is tried first because it is local and complete. It lags by a
    day, though, so a race read this afternoon has its result published by PMU
    hours before the archive has it. Waiting for the archive would leave the row
    pending on a result that has been public for hours.

    Only the top five are resolved, and that is not a shortcut: every claim on
    this page is about the first three places. A runner outside the top five
    gets no entry, which is all the scoring needs.

    A race that finished with two runners is still a real result — two finishers
    in a steeplechase is not a glitch. One finisher is a red flag, not a
    result, so that case is still refused.
    """
    day = str(race_date)[:10]
    try:
        m, c = int(meeting), int(course)
    except (TypeError, ValueError):
        return None

    try:
        from database import get_db
        conn = get_db()
        try:
            row = conn.execute(
                "SELECT race_id, hippodrome FROM races "
                "WHERE date=? AND reunion_num=? AND course_num=? LIMIT 1",
                (day, m, c)).fetchone()
            if row:
                rows = conn.execute(
                    "SELECT num, rang FROM participants WHERE race_id=? AND rang IS NOT NULL "
                    "AND rang<90 ORDER BY rang LIMIT 5", (row["race_id"],)).fetchall()
                if len(rows) >= 2:
                    top = []
                    for r in rows:
                        try:
                            top.append({"num": int(r["num"]), "rank": int(r["rang"])})
                        except (TypeError, ValueError):
                            pass
                    n = conn.execute(
                        "SELECT COUNT(*) FROM participants WHERE race_id=? AND rang IS NOT NULL "
                        "AND rang<90", (row["race_id"],)).fetchone()[0]
                    return {"source": "archive", "race_id": row["race_id"],
                            "hippodrome": row["hippodrome"], "finishers": n, "top5": top}
        finally:
            conn.close()
    except Exception:
        pass

    try:
        from routes.programme import _get, BASE_URL, _format_date
        d = _format_date(day)
        cse = _get("%s/programme/%s/R%d/C%d" % (BASE_URL, d, m, c), timeout=15)
        top = _top5_from_ordre_arrivee(cse.get("ordreArrivee"))
        if len(top) >= 2 and _is_finished(cse.get("statut")):
            hip = cse.get("hippodrome") or {}
            name = hip.get("libelleCourt", "") if isinstance(hip, dict) else str(hip or "")
            return {"source": "pmu", "race_id": "%s_R%d_C%d" % (day, m, c),
                    "hippodrome": name, "finishers": len(top), "top5": top}
    except Exception:
        pass
    return None


def _couple_matches(participants):
    """The three couples the COUPLE engine gives, called exactly as TROT and
    GALOP call it. Those two pages are the ones that work, so their call is the
    one to copy: the same history lookup, the same coherent-on-big-fields path,
    the same V3 patterns on small ones. No extra argument, because every extra
    argument narrows the history and makes this page answer differently from
    the two that produce results.

    The view is invoked inside a test request context rather than reimplemented
    here, so there is exactly one place where the couples are decided. The app
    is imported lazily because app.py imports this module.
    """
    from app import app as flask_app
    from COUPLE.routes import extract as view
    with flask_app.test_request_context(json={"participants": participants}):
        resp = view()
    data = resp.get_json()
    if not isinstance(data, dict):
        return [], {}
    return data.get("matches") or [], data.get("hist") or {}


@flip_bp.route("/pick", methods=["POST"])
def pick():
    """Record one reading of one race. Each call adds an attempt."""
    body = request.get_json(silent=True) or {}
    participants = body.get("participants") or []
    if not participants:
        return jsonify({"error": "No participants"}), 400
    race_date = str(body.get("date") or "")[:10]
    if len(race_date) != 10:
        return jsonify({"error": "date YYYY-MM-DD obligatoire"}), 400
    meeting, course = body.get("meeting"), body.get("course")

    ranked = priced_runners(participants)
    out_of_range = check_field(participants)
    if out_of_range:
        ticket = {"ok": False, "reason": "field_out_of_range", "reason_fr": out_of_range,
                  "pairs": [], "board": ranked, "priced_n": len(ranked),
                  "field_n": len(participants), "favourite": ranked[0] if ranked else None}
    else:
        try:
            matches, hist = _couple_matches(participants)
        except Exception as e:
            return jsonify({"error": "moteur COUPLE indisponible: %s" % str(e)[:160]}), 500
        ticket = normalise(matches, ranked, len(participants))
        ticket["coherent"] = bool((hist or {}).get("coherent"))

    try:
        start_ms = int(body.get("start_ms")) if body.get("start_ms") else None
    except (TypeError, ValueError):
        start_ms = None

    key = store.race_key_of(race_date, meeting, course)
    saved = store.save_attempt(
        key,
        meta={"date": race_date, "meeting": meeting, "course": course,
              "hippodrome": body.get("hippodrome"),
              "distance": body.get("distance"), "disc": body.get("disc"),
              "declared_runners": body.get("runners")},
        ticket=ticket, start_ms=start_ms, engine_version=ENGINE_VERSION)
    return jsonify({"saved": saved, "ticket": ticket})


@flip_bp.route("/log", methods=["GET"])
def log():
    """Every reading, grouped by race, with the result filled in where there is
    one. Scoring happens here, lazily: a reading still pending is retried on
    every call, so a race that finished an hour ago is scored the next time the
    page is opened. No background job, nothing to forget to run."""
    filled = resolved = 0
    for e in store.read_all(limit=1000):
        r = e.get("result")
        # A scored reading needs its per-pair verdicts as well as its arrival.
        # An earlier version stored only the arrival, which left the page with
        # nothing to mark each couplé on — a winning pair showed as a miss.
        if e.get("status") == "scored" and r and r.get("rows"):
            continue
        if e.get("status") == "abstained" and r:
            continue
        res = _resolve_result(e["race_date"], e["meeting"], e["course"])
        if not res:
            continue
        payload = {"race_id": res["race_id"], "hippodrome": res.get("hippodrome") or "",
                   "finishers": res["finishers"], "source": res["source"],
                   "podium": [[t["num"], t["rank"]] for t in res["top5"]]}
        if e.get("status") == "abstained":
            store.write_arrival(e["log_key"], payload)
            resolved += 1
            continue
        rank_by_num = {t["num"]: t["rank"] for t in res["top5"]}
        sc = score(e.get("ticket") or {}, rank_by_num)
        base = market_baseline(e["ticket"].get("board") or [], rank_by_num)
        # The per-pair verdicts go in with the result. Storing only the summary
        # left the page with nothing to mark each couplé on, so a winning pair
        # was shown as a miss.
        payload["rows"] = sc.get("rows") or []
        payload["baseline"] = base
        store.write_score(e["log_key"], sc, payload)
        filled += 1

    entries = store.read_all()
    scored = [e for e in entries if e.get("status") == "scored"]
    measured = [{"any_couple": bool(e.get("any_couple")),
                 "any_both_top3": bool(e.get("any_both_top3")),
                 "rows": ((e.get("result") or {}).get("rows"))}
                for e in scored]

    # group the attempts of one race together, newest race first
    groups: Dict[str, Dict[str, Any]] = {}
    order: List[str] = []
    for e in entries:
        rk = e["race_key"]
        if rk not in groups:
            groups[rk] = {"race_key": rk, "race_date": e["race_date"],
                          "meeting": e["meeting"], "course": e["course"],
                          "hippodrome": e["hippodrome"], "distance": e["distance"],
                          "disc": e["disc"], "attempts": []}
            order.append(rk)
        groups[rk]["attempts"].append(e)

    return jsonify({
        "groups": [groups[k] for k in order],
        "entries": entries,
        "counts": store.counts(),
        "newly_scored": filled,
        "newly_resolved": resolved,
        "tally": tally(measured) if measured else {"races": 0},
        "caveats": [
            "Une lecture est écrite une fois et jamais recalculée : si le moteur "
            "change, les réponses anciennes restent celles du jour.",
            "Résultat : archive en priorité, sinon PMU en direct.",
            "Seul le top 5 est résolu. Un cheval au-delà ne peut ni gagner un "
            "couple (top 2) ni une paire top 3 — c'est tout ce que la page affirme.",
            "La même course peut être lue plusieurs fois : chaque lecture est une "
            "tentative numérotée, empilée sous les autres de la même course. "
            "C'est ainsi qu'on voit si l'heure change le billet.",
            "Aucun seuil n'est fixé : c'est vous qui décidez quand le nombre suffit.",
        ],
    })


@flip_bp.route("/log/clear", methods=["POST"])
def clear_log():
    """Empty the journal. Needs the word, and says what went."""
    body = request.get_json(silent=True) or {}
    if body.get("confirm") != "EFFACER":
        return jsonify({"error": "confirmation requise", "expected": "EFFACER",
                        "counts": store.counts()}), 400
    removed = store.clear()
    return jsonify({"cleared": removed, "counts": store.counts()})


@flip_bp.route("/dates", methods=["GET"])
def dates():
    """The most recent days that can be scored, so the page opens on real data."""
    limit = request.args.get("limit", type=int) or 21
    from database import get_db
    conn = get_db()
    try:
        rows = conn.execute("""
            SELECT r.date AS d, COUNT(*) AS races
            FROM races r
            WHERE EXISTS (SELECT 1 FROM participants p
                          WHERE p.race_id = r.race_id AND p.rang IS NOT NULL AND p.rang < 90)
            GROUP BY r.date ORDER BY r.date DESC LIMIT ?""", (limit,)).fetchall()
        return jsonify({"dates": [{"date": r["d"], "races": r["races"]} for r in rows]})
    finally:
        conn.close()


@flip_bp.route("/measure", methods=["GET"])
def measure():
    """Reconstruct a whole day: run the rule now and score it, for comparison
    with what the journal recorded at the time. Not a substitute for the log —
    a re-run answers for today, not for the day the race was read."""
    day = (request.args.get("date") or "").strip()[:10]
    if len(day) != 10:
        return jsonify({"error": "date YYYY-MM-DD obligatoire"}), 400

    from database import get_db
    conn = get_db()
    try:
        races = conn.execute(
            "SELECT race_id, reunion_num, course_num, hippodrome, distance, "
            "disc_canonical FROM races WHERE date=? ORDER BY race_id", (day,)).fetchall()
        rows, abstained = [], []
        for r in races[:MAX_RACES]:
            parts = [dict(p) for p in conn.execute(
                "SELECT num, horse, cote_pmu, age, poids, sexe, gain, red_km, "
                "deferre, rang FROM participants WHERE race_id=? ORDER BY num",
                (r["race_id"],)).fetchall()]
            if not parts:
                continue
            base_meta = {"date": day, "meeting": r["reunion_num"], "course": r["course_num"],
                         "hippodrome": r["hippodrome"], "distance": r["distance"],
                         "disc": r["disc_canonical"]}
            oor = check_field(parts)
            if oor:
                abstained.append(dict(base_meta, reason_fr=oor))
                continue
            try:
                matches, hist = _couple_matches(parts)
            except Exception:
                continue
            ticket = normalise(matches, priced_runners(parts), len(parts))
            if not ticket["ok"]:
                abstained.append(dict(base_meta, reason_fr=ticket["reason_fr"]))
                continue
            rank_by_num = {p["num"]: p["rang"] for p in parts if p["rang"] and p["rang"] < 90}
            sc = score(ticket, rank_by_num)
            rows.append(dict(base_meta, ticket=ticket, score=sc,
                             coherent=bool((hist or {}).get("coherent")),
                             baseline=market_baseline(ticket["board"], rank_by_num)))
        return jsonify({"date": day, "races_found": len(races),
                        "races_scored": len(rows), "races_abstained": len(abstained),
                        "capped": len(races) > MAX_RACES, "max_races": MAX_RACES,
                        "rows": rows, "abstained": abstained,
                        "tally": tally([{"any_couple": r["score"]["any_couple"],
                                         "any_both_top3": r["score"]["any_both_top3"],
                                         "rows": r["score"]["rows"]} for r in rows]),
                        "caveats": [
                            " reconstitution : la règle est relancée aujourd'hui sur "
                            "des courses déjà terminées. Le journal enregistre ce "
                            "qui a été dit le jour même ; les deux peuvent différer.",
                        ]})
    finally:
        conn.close()
