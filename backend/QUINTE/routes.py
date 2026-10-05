from flask import Blueprint, jsonify, request
from .service import (
    get_quinte_top5_stats,
    match_alfaraj_current,
    outsider_ticket,
    trio_infiltre,
    trio_coherent,
    current_market_dna,
    brave_ticket,
    get_brave_archetypes,
    _similar_signatures,
    _fam_vector,
)
from .v3_service import v3_trio

# The Synthèse page's own engine. It lives here, in the page's own folder, and
# it is the only thing that decides which horse fills which box. The cell
# weights in the front end are a fallback for the days this returns nothing.
try:
    from .synthese_engine import strength as engine_strength
except Exception as _e:  # the archive may be mid-rebuild; the page still runs
    engine_strength = None
    _ENGINE_ERR = str(_e)

alfaraj_bp = Blueprint("alfaraj", __name__, url_prefix="/api/alfaraj")

# A separate blueprint, same folder, same page. /api/synthese/motor is the
# engine of the Synthèse page and belongs to no other page.
synthese_motor_bp = Blueprint("synthese_motor", __name__,
                              url_prefix="/api/synthese")


@synthese_motor_bp.route("/motor", methods=["GET"])
def motor():
    """The strength of every runner of that day's Quinté, from the archive."""
    date = request.args.get("date") or ""
    if len(date) != 10:
        return jsonify({"error": "date required (YYYY-MM-DD)"}), 400
    if engine_strength is None:
        return jsonify({"error": "engine indisponible", "detail": _ENGINE_ERR}), 503
    try:
        st = engine_strength(date)
    except Exception as e:
        return jsonify({"error": str(e)}), 500
    return jsonify({"date": date, "n": len(st), "strength": st})

@alfaraj_bp.before_request
def _guard():
    from routes.auth import require_session
    if request.method == 'OPTIONS' or request.path.endswith('/health'):
        return None
    return require_session()

@alfaraj_bp.route("/health", methods=["GET"])
def health():
    return jsonify({"status":"ok","module":"ALFARAJ","version":"2.1.0","scope":"Quinté Top5, family DNA with support gate"})

@alfaraj_bp.route("/stats", methods=["GET"])
def stats():
    limit=request.args.get("limit", type=int) or 4054
    hippodrome=request.args.get("hippodrome")
    disc=request.args.get("disc") or request.args.get("discipline")
    data=get_quinte_top5_stats(limit=limit, hippodrome=hippodrome, disc=disc)
    return jsonify(data)

@alfaraj_bp.route("/extract", methods=["POST"])
def extract():
    body=request.get_json(silent=True) or {}
    participants=body.get("participants") or []
    hippodrome=body.get("hippodrome")
    if isinstance(hippodrome, dict):
        hippodrome=hippodrome.get("libelleLong") or hippodrome.get("libelleCourt") or ""
    disc=body.get("disc") or body.get("discipline") or body.get("disciplineFamily")
    if isinstance(disc, dict):
        disc=disc.get("disc_canonical") or disc.get("family") or ""
    try:
        distance=int(body.get("distance") or 0) or None
    except (TypeError, ValueError):
        distance=None
    try:
        runners=int(body.get("runners") or len(participants)) or None
    except (TypeError, ValueError):
        runners=None
    if not participants:
        return jsonify({"error":"No participants"}),400
    def _support(h):
        try:
            return sum(1 for c in (h.get("family_counter") or {}).values() if int(c or 0) >= 5)
        except Exception:
            return 0
    hist=get_quinte_top5_stats(limit=4054, before=body.get("date"), hippodrome=hippodrome, disc=disc, distance=distance, runners=runners)
    hist_scope="shape"
    if _support(hist) < 1:
        hist=get_quinte_top5_stats(limit=4054, before=body.get("date"), hippodrome=hippodrome, disc=disc)
        hist_scope="hippodrome"
    if _support(hist) < 1:
        hist=get_quinte_top5_stats(limit=4054, before=body.get("date"), disc=disc)
        hist_scope="discipline"
    # diagnostic: combien de cotes valides ?
    n_valid=0
    for p in participants:
        c=p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")
        try:
            if c is not None and str(c).strip()!="" and float(c)>0:
                n_valid+=1
        except:
            pass
    matched, level=match_alfaraj_current(participants, hist, disc=disc, before=body.get("date"), distance=distance)
    outsider, outsider_level=outsider_ticket(participants, hist, disc=disc, before=body.get("date"), distance=distance)
    cur=current_market_dna(participants)
    similar, _lv=_similar_signatures(_fam_vector(cur.get("layers", [])), hist.get("family_counter", {}), top=5)
    coverage=round(n_valid/len(participants), 3) if participants else 0
    partial=coverage < 0.8
    if partial:
        for m in matched:
            m["weak"]=True
    msg=None
    hist_total=(hist or {}).get("total_quinte_races", 0)
    hist_scope=(hist or {}).get("scope", "?")
    if n_valid<5:
        if len(participants)<5:
            msg=(f"Champ réduit ({len(participants)} partants) — Quinté et Trio Top5 impossibles "
                 f"(minimum 5) ; Couple ci-dessous")
        else:
            msg=f"Pas de cotes PMU ({n_valid}/{len(participants)}) — course future, relancez après publication des cotes"
    elif not matched:
        msg=f"Base insuffisante — aucun pronostic (cotes {n_valid}/{len(participants)}, hist {hist_scope}: {hist_total} courses)"
    elif partial:
        msg=f"Analyse partielle ({n_valid}/{len(participants)} cotes) — pronostics faibles"
    elif level is not None and level < 2:
        msg=f"Similarité relâchée (niveau {level}) — pronostics fragiles"
    if not outsider and n_valid >= 5:
        msg=(msg + " · " if msg else "") + "Pas d'outsider éligible pour ce champ"
    brave=brave_ticket(participants, disc=disc)
    try:
        _arch_meta=get_brave_archetypes(disc=disc)
        brave_features=_arch_meta.get("selected_features", {})
    except Exception:
        brave_features={}
    trio, _trio_level=trio_infiltre(participants, hist, disc=disc, before=body.get("date"), distance=distance)
    try:
        trio_coh, _coh_level = trio_coherent(participants, hist, disc=disc)
    except Exception:
        trio_coh = []
    try:
        trio_v3, _v3meta = v3_trio(participants, before=body.get("date"), disc=disc,
                                  distance=distance, runners=len(participants))
    except Exception:
        trio_v3, _v3meta = [], {}
    field = []
    try:
        from database import get_db as _gdb
        from signals.plot_signals import compute_field_plot, trap_of_fav
        _pc = _gdb()
        try:
            pmap = compute_field_plot(_pc, participants, before=body.get("date"), cur_dist=distance)
        finally:
            _pc.close()
        _ranked = sorted(
            [p for p in participants
             if (p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")) is not None],
            key=lambda p: (float(p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote")),
                           p.get("num")))
        _rank = {p.get("num"): i + 1 for i, p in enumerate(_ranked)}
        _trap_n, _trap_l = trap_of_fav(pmap, [p.get("num") for p in _ranked], distance)
        _fav1 = _ranked[0].get("num") if _ranked else None
        for p in participants:
            num = p.get("num")
            s = pmap.get(num, {}) or {}
            try:
                cote = float(p.get("cote_pmu") if p.get("cote_pmu") is not None else p.get("cote"))
            except (TypeError, ValueError):
                cote = None
            flags = []
            if (s.get("trainer_n") or 0) >= 8 and (s.get("trainer_rate") or 0) >= 0.25:
                flags.append("T2 entrain-chaud")
            if s.get("back_to_win"):
                flags.append("T4 retour-conditions")
            if s.get("first_d4"):
                flags.append("1er D4")
            if s.get("winless180"):
                flags.append("T3 sans-victoire")
            if _trap_n >= 2 and num is not None and num == _fav1:
                flags += ["TRAP " + x for x in _trap_l]
            field.append({"num": num, "horse": p.get("horse"), "cote": cote,
                          "market_rank": _rank.get(num), "ctx": s.get("ctx"),
                          "runs_n": s.get("runs_n"), "flags": flags})
    except Exception:
        field = []
    return jsonify({"hist": hist, "matches": matched, "trio": trio, "trio_coh": trio_coh, "trio_v3": trio_v3, "count": len(matched), "brave": brave, "brave_features": brave_features, "outsider": outsider, "outsider_level": outsider_level, "match_level": level, "n_valid_cotes": n_valid, "n_participants": len(participants), "coverage": coverage, "partial": partial, "message": msg, "current_dna": cur, "similar": similar, "field": field})

@alfaraj_bp.route("/analyze", methods=["POST"])
def analyze():
    return extract()

@alfaraj_bp.route("/race/<date>/<int:reunion>/<int:course>", methods=["GET"])
def race_analyze(date, reunion, course):
    from database import get_db
    conn=get_db()
    row=conn.execute("SELECT * FROM races WHERE date=? AND reunion_num=? AND course_num=? AND quinte=1 LIMIT 1", (date, reunion, course)).fetchone()
    if not row:
        conn.close()
        return jsonify({"error":"Quinté race not found"}),404
    hippodrome=row["hippodrome"]
    parts=conn.execute("SELECT * FROM participants WHERE race_id=? ORDER BY num", (row["race_id"],)).fetchall()
    conn.close()
    participants=[dict(p) for p in parts]
    # derive disc from stored race if available
    disc=(row["disc_canonical"] or row["discipline"] or row["specialty"] or "")
    hist=get_quinte_top5_stats(limit=4000, hippodrome=hippodrome, disc=disc)
    matched, level=match_alfaraj_current(participants, hist, disc=disc, before=date, distance=row["distance"])
    outsider, outsider_level=outsider_ticket(participants, hist, disc=disc, before=date, distance=row["distance"])
    # trio is the brave infiltré ticket (2 favoris + 1 outsider forme)
    trio, _trio_level=trio_infiltre(participants, hist, disc=disc, before=date, distance=row["distance"])
    return jsonify({"race": dict(row), "hist": hist, "matches": matched, "trio": trio, "match_level": level, "outsider": outsider, "outsider_level": outsider_level})