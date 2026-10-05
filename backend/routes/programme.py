from datetime import date, timedelta
import re
import os
import json
import requests as req
from flask import Blueprint, jsonify

pmu_bp = Blueprint("pmu", __name__)

BASE_URL = "https://online.turfinfo.api.pmu.fr/rest/client/61"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": "https://www.pmu.fr",
    "Referer": "https://www.pmu.fr/",
}

_session = req.Session()
_session.headers.update(HEADERS)

# Offline cache directory
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def _load_cache(date_str):
    cache_file = os.path.join(CACHE_DIR, f"programme_{date_str}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return None

def _save_cache(date_str, data):
    cache_file = os.path.join(CACHE_DIR, f"programme_{date_str}.json")
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except:
        pass

def _load_race_cache(date_str, meeting, race):
    # v2: includes statut/non-partant mapping; v1 files are stale by design
    cache_file = os.path.join(CACHE_DIR, f"race_v2_{date_str}_R{meeting}_C{race}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return None

def _save_race_cache(date_str, meeting, race, data):
    cache_file = os.path.join(CACHE_DIR, f"race_v2_{date_str}_R{meeting}_C{race}.json")
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except:
        pass

def _parse_ref(condition):
    if not condition:
        return None
    txt = str(condition).replace('�','e')
    import re as _re
    m = _re.search(r"r[eé]f[^0-9]*\+?\s*(\d+(?:[.,]\d+)?)", txt, _re.I)
    if not m:
        return None
    try:
        raw = m.group(1).replace(",",".")
        v = float(raw)
        if v >= 100:
            v = v / 10.0
        if not (5 <= v <= 50):
            return None
        return round(v, 2)
    except:
        return None

def _enrich_ref(course, date_str, meeting, race):
    if not course or course.get("ref") is not None:
        return course
    cond = course.get("condition")
    ref = _parse_ref(cond)
    if ref is not None:
        course["ref"] = ref
        return course
    # fallback: try Geny for same date/hippodrome
    try:
        from scraper.geny_scraper import get_scraper
        scraper = get_scraper()
        prog = scraper.fetch_programme(__import__('datetime').date.fromisoformat(date_str)) if date_str else None
        if prog:
            for m in prog.get("meetings", []):
                # match meeting num
                if m.get("num") != meeting:
                    continue
                for c in m.get("courses", []):
                    if c.get("num") == race:
                        rc = _parse_ref(c.get("condition"))
                        if rc is not None:
                            course["ref"] = rc
                            if not course.get("condition") and c.get("condition"):
                                course["condition"] = c.get("condition")
                            return course
    except:
        pass
    # fallback: check DB
    try:
        from database import get_db
        conn = get_db()
        row = conn.execute("SELECT ref, condition FROM races WHERE date=? AND reunion_num=? AND course_num=? LIMIT 1", (date_str, meeting, race)).fetchone()
        conn.close()
        if row and row["ref"] is not None:
            course["ref"] = row["ref"]
        elif row and row["condition"]:
            rc = _parse_ref(row["condition"])
            if rc is not None:
                course["ref"] = rc
    except:
        pass
    return course

def _enrich_valeur(parts, date_str, meeting, race):
    """
    Attach `valeur` (Geny handicap) to live participants when the race exists
    in the local archive. Only plat races carry a valeur in the archive, so
    this stays empty for trot. Matches participants by horse name (normalized)
    or by num, on the same reunion + course.
    """
    if not parts or not date_str:
        return parts
    try:
        from database import get_db
        conn = get_db()
        archived = conn.execute(
            "SELECT race_id FROM races WHERE date=? AND reunion_num=? AND course_num=? LIMIT 1",
            (date_str, meeting, race),
        ).fetchone()
        if not archived:
            conn.close()
            return parts
        rows = conn.execute(
            "SELECT num, horse, valeur, deferre FROM participants WHERE race_id=? AND (valeur IS NOT NULL AND valeur != '' OR deferre IS NOT NULL AND deferre != '')",
            (archived["race_id"],),
        ).fetchall()
        conn.close()
        if not rows:
            return parts

        def _norm(name):
            return re.sub(r"[^a-z0-9]", "", (name or "").lower())

        by_name = {}
        by_num = {}
        for r in rows:
            key = _norm(r["horse"])
            if r["valeur"] is not None and r["valeur"] != "" and key not in by_name:
                by_name[key] = r["valeur"]
            if r["valeur"] is not None and r["valeur"] != "" and r["num"] not in by_num:
                by_num[r["num"]] = r["valeur"]
        deferre_by_num = {r["num"]: r["deferre"] for r in rows if r["deferre"]}
        deferre_by_name = {_norm(r["horse"]): r["deferre"] for r in rows if r["deferre"]}
        for p in parts:
            v = by_num.get(p.get("num"))
            if v is None:
                v = by_name.get(_norm(p.get("horse")))
            if v is not None:
                p["valeur"] = v
            d = deferre_by_num.get(p.get("num"))
            if not d:
                d = deferre_by_name.get(_norm(p.get("horse")))
            if d and not p.get("deferre"):
                p["deferre"] = d
        return parts
    except Exception:
        return parts


def _fmt_deferre(deferre):
    """Python mirror of frontend formatDeferre: PROTEGE_ANTERIEURS_DEFERRRE_POSTERIEURS -> D2"""
    if not deferre:
        return None
    raw = str(deferre).upper()
    tokens = [re.sub(r"DEFERRR+", "DEFERRE", t) for t in raw.split("_")]
    is_state = lambda w: bool(w) and ("DEFERRE" in w or "REFERRE" in w or "PROTEGE" in w)

    ant = ""
    for i, t in enumerate(tokens):
        if t == "ANTERIEURS" and i > 0 and is_state(tokens[i - 1]):
            ant = tokens[i - 1]
    post = ""
    for i, t in enumerate(tokens):
        if t == "POSTERIEURS" and i > 0 and is_state(tokens[i - 1]):
            post = tokens[i - 1]
    if not post and "POSTERIEURS" in tokens:
        post = ant

    def side(v):
        v = v or ""
        if "DEFERRE" in v:
            return "D"
        if "REFERRE" in v:
            return "R"
        if "PROTEGE" in v:
            return "P"
        return ""

    a, p = side(ant), side(post)

    if a == "D" and p == "D":
        return "D4"
    if a == "R" and p == "R":
        return "R4"
    if a == "P" and p == "P":
        return "P4"
    if a == "D" and p == "P":
        return "D2A"
    if a == "P" and p == "D":
        return "D2"
    if a == "D":
        return "D2A"
    if p == "D":
        return "D2"
    if a == "R":
        return "R2"
    if p == "R":
        return "R2"
    if a == "P":
        return "P2"
    if p == "P":
        return "P2"
    if "FF" in raw:
        return "FF"
    if "FD" in raw:
        return "FD"
    if "DF" in raw:
        return "DF"
    return raw.replace("_", " ")


def _enrich_deferre_stats(parts, max_races=30):
    """
    For each participant, look up every archived race (past + this one) of that
    horse, group by normalised deferrage code and compute a verdict:
        {"D2": {n, top5, disq, avgRang}, ...}
    Attached as `deferre_stats` so the UI can show e.g. "D2: 5/6 top5 · 1 disq".
    Only horse names found in the archive produce stats.
    """
    if not parts:
        return parts
    try:
        from database import get_db
        conn = get_db()
        names = list({p.get("horse") for p in parts if p.get("horse")})
        if not names:
            conn.close()
            return parts
        placeholders = ",".join("?" * len(names))
        rows = conn.execute(
            f"SELECT p.horse, p.deferre, p.rang, r.date FROM participants p JOIN races r ON p.race_id=r.race_id "
            f"WHERE p.horse IN ({placeholders}) ORDER BY r.date DESC",
            names,
        ).fetchall()
        conn.close()

        stats_by_horse = {}
        kept = {}
        for row in rows:
            horse, deferre, rang, _date = row["horse"], row["deferre"], row["rang"], row["date"]
            if kept.get(horse, 0) >= max_races:
                continue
            kept[horse] = kept.get(horse, 0) + 1
            code = _fmt_deferre(deferre)
            if not code:
                continue
            bucket = stats_by_horse.setdefault(horse, {}).setdefault(code, {"n": 0, "top5": 0, "disq": 0, "rangs": []})
            bucket["n"] += 1
            if rang is not None and rang < 99:
                bucket["rangs"].append(rang)
                if rang <= 5:
                    bucket["top5"] += 1
            elif rang is None or rang >= 99:
                bucket["disq"] += 1
        for horse, by_code in stats_by_horse.items():
            for code, s in by_code.items():
                rangs = s.pop("rangs", [])
                s["avgRang"] = round(sum(rangs) / len(rangs), 1) if rangs else None
            stats_by_horse[horse] = {code: {k: v for k, v in s.items()} for code, s in by_code.items()}

        for p in parts:
            mine = stats_by_horse.get(p.get("horse"))
            if mine and not p.get("deferre_stats"):
                p["deferre_stats"] = mine
        return parts
    except Exception:
        return parts


# Morocco integration
from .morocco import fetch_morocco_programme, fetch_morocco_race, MOROCCO_OFFSET
_morocco_cache = {}  # key: f"{date}:{virtual_meeting}:{race_num}" -> sorec_id

# Equidia integration
from .equidia import fetch_equidia_programme, fetch_equidia_race, EQUIDIA_OFFSET


def _format_date(date_str):
    d = date_str.replace("-", "")
    return d[6:8] + d[4:6] + d[:4]


def _get(url, timeout=10):
    last_err = None
    for _ in range(3):
        try:
            r = _session.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
    raise last_err


@pmu_bp.route("/api/programme/<date>")
def programme(date):
    data = None
    try:
        data = _get(f"{BASE_URL}/programme/{_format_date(date)}?meteo=true&specialisation=INTERNET")
        if data and data.get("programme", {}).get("reunions"):
            _save_cache(date, data)
    except Exception as e:
        print(f"[OFFLINE] PMU API unavailable for {date}: {e}")
        data = _load_cache(date)
        if data:
            print(f"[OFFLINE] Using cached data for {date}")
        else:
            data = {"programme": {"reunions": []}, "error": str(e), "offline": True}

    pmu_reunions = data.get("programme", {}).get("reunions", [])

    def _meeting_start(r):
        courses = r.get("courses") or []
        if not courses:
            return None
        return courses[0].get("heureDepart")

    def _tokens(name):
        toks = {t for t in re.split(r"[^A-Z0-9]+", str(name).upper()) if len(t) >= 4}
        return toks

    def _duplicate(er):
        er_start = _meeting_start(er)
        er_toks = _tokens((er.get("hippodrome") or {}).get("libelleCourt", ""))
        if not er_toks:
            return False
        for r in pmu_reunions:
            r_start = _meeting_start(r)
            if (er_start and r_start
                    and isinstance(er_start, (int, float))
                    and isinstance(r_start, (int, float))
                    and abs(er_start - r_start) < 5 * 60 * 1000):
                h = r.get("hippodrome", {})
                r_name = h.get("libelleCourt", "") if isinstance(h, dict) else ""
                if er_toks & _tokens(r_name):
                    return True
        return False

    try:
        ma_reunions = fetch_morocco_programme(date)
        _morocco_cache[date] = {}
        for mr in ma_reunions:
            vn = mr["numero"]
            for rc in mr.get("courses", []):
                rn = rc["numOrdre"]
                sid = rc.get("_sorecId")
                if sid:
                    _morocco_cache[date][f"{vn}:{rn}"] = sid
            if not _duplicate(mr):
                pmu_reunions.append(mr)
            else:
                # Duplicate mais peut contenir un Quinté Sorec manquant côté PMU (ex: R4 C6 Sagitta Q+)
                # On fusionne le QUINTE_PLUS Sorec dans la réunion PMU correspondante
                try:
                    # trouve réunion PMU correspondante
                    mr_start = _meeting_start(mr)
                    mr_toks = _tokens((mr.get("hippodrome") or {}).get("libelleCourt", ""))
                    for pr in pmu_reunions:
                        pr_start = _meeting_start(pr)
                        if (mr_start and pr_start and isinstance(mr_start, (int, float)) and isinstance(pr_start, (int, float)) and abs(mr_start - pr_start) < 5*60*1000):
                            h = pr.get("hippodrome", {})
                            r_name = h.get("libelleCourt", "") if isinstance(h, dict) else ""
                            if mr_toks & _tokens(r_name):
                                # fusionne les paris QUINTE
                                for s_course in mr.get("courses", []):
                                    s_num = s_course.get("numOrdre")
                                    s_paris = s_course.get("paris") or []
                                    has_quinte = any("QUINTE" in str(p.get("typePari","")) for p in s_paris)
                                    if not has_quinte:
                                        continue
                                    # trouve course PMU correspondante
                                    for p_course in pr.get("courses", []):
                                        if p_course.get("numOrdre") == s_num:
                                            # injecte QUINTE_PLUS si absent
                                            if not any("QUINTE" in str(pp.get("typePari","")) for pp in (p_course.get("paris") or [])):
                                                p_course.setdefault("paris", []).append({"typePari": "QUINTE_PLUS"})
                                                # aussi flag quinte
                                                p_course["quinte"] = True
                                            break
                                break
                except Exception as _e:
                    print(f"[MOROCCO merge] {_e}")
    except Exception as e:
        print(f"[MOROCCO] Error: {e}")

    try:
        eq_reunions = fetch_equidia_programme(date)
        for er in eq_reunions:
            if _duplicate(er):
                continue
            pmu_reunions.append(er)
    except Exception as e:
        print(f"[EQUIDIA] Error: {e}")

    meetings = []
    for r in pmu_reunions:
        hippo = r.get("hippodrome", {})
        r_num = r.get("numOfficiel") or r.get("numero", 0)
        courses = []
        for c in r.get("courses", []):
            spec = c.get("specialite")
            if not spec:
                for cl in c.get("specialites", []):
                    if cl.get("code"):
                        spec = cl["code"]
                        break
            if not spec and c.get("conditionAge"):
                spec = "PLAT"
            hippo_obj = {"code": hippo.get("code", ""), "libelleCourt": hippo.get("libelleCourt", ""), "libelleLong": hippo.get("libelleLong", "")}
            c_num = c.get("numOrdre", 0)
            pari_types = list({p["typePari"].removeprefix("E_") if p["typePari"].startswith("E_") else p["typePari"] for p in c.get("paris", []) if "typePari" in p})
            courses.append({
                "id": f"{date}_R{r_num}_C{c_num}",
                "num": c_num,
                "numOrdre": c_num,
                "time": c.get("heureDepart"),
                "specialty": spec,
                "quinte": bool(c.get("quinte")) or ("QUINTE_PLUS" in pari_types),
                "libelle": c.get("libelle", ""),
                "distance": c.get("distance"),
                "discipline": c.get("discipline"),
                "statut": c.get("statut"),
                "imminent": bool(c.get("isDepartImminent") or c.get("departImminent")),
                "definitif": bool(c.get("rapportsDefinitifsDisponibles")),
                "replay": bool(c.get("replayDisponible")),
                "conditionAge": c.get("conditionAge"),
                "runners": c.get("nombreDeclaresPartants"),
                "hippodrome": hippo_obj,
                "types_pari": pari_types,
            })
        _met = r.get("meteo") or {}
        meetings.append({
            "num": r_num,
            "hippodrome": hippo.get("libelleCourt", hippo.get("libelleLong", "")),
            "hippodrome_full": hippo.get("libelleLong", ""),
            "meteo": {
                "temp": _met.get("temperature", _met.get("temp")),
                "code": _met.get("nebulositeCode", _met.get("code")),
                "label": _met.get("nebulositeLibelleCourt", _met.get("label")),
                "vent": _met.get("forceVent", _met.get("vent")),
            } if _met else None,
            "organizer": r.get("typePari", "PMU"),
            "country": r.get("_country") or r.get("country"),
            "start_time": courses[0]["time"] if courses else None,
            "courses": courses,
            "disciplines": list(set(c["specialty"] for c in courses if c["specialty"])),
        })

    return jsonify({"meetings": meetings})


@pmu_bp.route("/api/race/<race_id>")
def race_by_id(race_id):
    import re
    m = re.match(r"^(\d{4}-\d{2}-\d{2})_R(\d+)_C(\d+)$", race_id)
    if not m:
        return jsonify({"error": "Invalid race ID format"}), 400
    r_date, r_num, c_num = m.group(1), int(m.group(2)), int(m.group(3))
    return race(r_date, r_num, c_num)


@pmu_bp.route("/api/race/<race_id>/rapports")
def rapports_by_id(race_id):
    return jsonify(None)


@pmu_bp.route("/api/race/<race_id>/cotes")
def cotes_by_id(race_id):
    return jsonify(None)


@pmu_bp.route("/api/race/<date>/<int:meeting>/<int:race>")
def race(date, meeting, race):
    if meeting >= EQUIDIA_OFFSET:
        try:
            num_reunion = meeting - EQUIDIA_OFFSET
            result = fetch_equidia_race(num_reunion, race, date)

            hippo = result.get("hippodrome", {})
            hippo_name = hippo.get("libelleCourt", "") if isinstance(hippo, dict) else str(hippo)

            transformed_parts = []
            for p in result.get("partants", []):
                transformed_parts.append({
                    "num": p.get("numPmu"), "horse": p.get("nom", ""),
                    "horse_id": None,
                    "jockey": p.get("driver", ""), "trainer": p.get("entraineur", ""),
                    "age": p.get("age"), "sexe": p.get("sexe"),
                    "poids": p.get("poids"),
                    "cote_pmu": None, "musique": p.get("musique"),
                    "proprietaire": p.get("proprietaire", ""),
                    "deferre": p.get("deferre"), "distance": p.get("distance"),
                })

            return jsonify({
                "reunion": {
                    "hippodrome": hippo_name,
                    "num": meeting,
                    "date": date,
                },
                "course": {
                    "num": race,
                    "time": result.get("heureDepart"),
                    "statut": result.get("statut"),
                    "imminent": bool(result.get("isDepartImminent") or result.get("departImminent")),
                    "definitif": bool(result.get("rapportsDefinitifsDisponibles")),
                    "replay": bool(result.get("replayDisponible")),
                    "prix": result.get("libelle", ""),
                    "specialty": result.get("specialite"),
                    "discipline": result.get("discipline"),
                    "distance": result.get("distance"),
                    "surface": None,
                    "going": None,
                    "corde": result.get("corde"),
                    "runners": result.get("nombreDeclaresPartants"),
                    "quinte": False,
                    "classe": result.get("categorieParticularite"),
                    "arrivee": None,
                },
                "participants": transformed_parts,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 502
    elif meeting >= MOROCCO_OFFSET:
        ma = None
        try:
            cache = _morocco_cache.get(date, {})
            sid = cache.get(f"{meeting}:{race}")
            if not sid:
                try:
                    ma = fetch_morocco_programme(date)
                    _morocco_cache[date] = {}
                    for mr in ma:
                        vn = mr["numero"]
                        for rc in mr.get("courses", []):
                            rn = rc["numOrdre"]
                            sorec_id = rc.get("_sorecId")
                            if sorec_id:
                                _morocco_cache[date][f"{vn}:{rn}"] = sorec_id
                    cache = _morocco_cache.get(date, {})
                    sid = cache.get(f"{meeting}:{race}")
                except Exception:
                    pass
            if not sid:
                # Try archive fallback for SOREC races
                try:
                    from database import get_db
                    conn = get_db()
                    # Get hippodrome name from programme
                    hippo_name = None
                    for mr in (ma or []):
                        if mr.get("numero") == meeting:
                            hippo_obj = mr.get("hippodrome", {})
                            hippo_name = hippo_obj.get("libelleCourt", "") if isinstance(hippo_obj, dict) else str(hippo_obj)
                            break
                    
                    if hippo_name:
                        hippo_db = hippo_name.upper().replace(" ", "_").replace("'", "")
                        archived = conn.execute(
                            "SELECT * FROM races WHERE date=? AND course_num=? AND hippodrome LIKE ? LIMIT 1",
                            (date, race, f"%{hippo_db}%")
                        ).fetchone()
                    else:
                        archived = conn.execute(
                            "SELECT * FROM races WHERE date=? AND course_num=? LIMIT 1",
                            (date, race)
                        ).fetchone()
                    
                    if archived:
                        archived = dict(archived)
                        participants = conn.execute(
                            "SELECT * FROM participants WHERE race_id=? ORDER BY num",
                            (archived["race_id"],)
                        ).fetchall()
                        archived["participants"] = [dict(p) for p in participants]
                        conn.close()
                        
                        parts = archived.get("participants", [])
                        transformed_parts = []
                        for p in parts:
                            transformed_parts.append({
                                "num": p.get("num"), "horse": p.get("horse", ""),
                                "horse_id": None, "jockey": p.get("jockey", ""),
                                "trainer": p.get("trainer", ""),
                                "age": p.get("age"), "sexe": p.get("sexe"),
                                "poids": p.get("poids"),
                                "cote_pmu": p.get("cote_pmu"), "musique": p.get("musique", ""),
                                "proprietaire": p.get("proprietaire", ""),
                            })
                        return jsonify({
                            "reunion": {
                                "hippodrome": hippo_name or archived.get("hippodrome", ""),
                                "num": meeting,
                                "date": date,
                            },
                            "course": {
                                "num": race,
                                "time": None,
                                "prix": archived.get("prix", ""),
                                "specialty": archived.get("discipline"),
                                "discipline": archived.get("discipline"),
                                "distance": archived.get("distance"),
                                "surface": archived.get("surface"),
                                "going": archived.get("going"),
                                "corde": archived.get("corde"),
                                "runners": archived.get("runners"),
                                "quinte": False,
                                "classe": None,
                                "penetrometer": None,
                                "arrivee": None,
                            },
                            "participants": transformed_parts,
                        })
                    conn.close()
                except Exception:
                    pass
                return jsonify({"error": "Morocco race not found in cache"}), 404
            result = fetch_morocco_race(sid, date)

            hippo = result.get("hippodrome", {})
            hippo_name = hippo.get("libelleCourt", "") if isinstance(hippo, dict) else str(hippo)

            pmu_parts = result.get("partants", [])
            transformed_parts = []
            for p in pmu_parts:
                driver = p.get("driver", "")
                if isinstance(driver, dict):
                    driver = driver.get("nom", "")
                trainer = p.get("entraineur", "")
                if isinstance(trainer, dict):
                    trainer = trainer.get("nom", "")
                nom = p.get("nom", "") or p.get("nomPmu", "")
                if isinstance(nom, dict):
                    nom = nom.get("libelle", "")
                cote = None
                rap = p.get("dernierRapportDirect")
                if isinstance(rap, dict):
                    cote = rap.get("rapport")
                transformed_parts.append({
                    "num": p.get("numPmu"), "horse": nom, "horse_id": p.get("idCheval"),
                    "jockey": driver, "trainer": trainer,
                    "age": p.get("age"), "sexe": p.get("sexe"),
                    "poids": p.get("poids"),
                    "cote_pmu": cote, "musique": p.get("musique"),
                    "deferre": p.get("deferre", ""), "proprietaire": p.get("proprietaire", ""),
                })

            _enrich_valeur(transformed_parts, date, meeting, race)
            _enrich_deferre_stats(transformed_parts)
            return jsonify({
                "reunion": {
                    "hippodrome": hippo_name,
                    "num": meeting,
                    "date": date,
                },
                "course": {
                    "num": race,
                    "time": result.get("heureDepart"),
                    "statut": result.get("statut"),
                    "imminent": bool(result.get("isDepartImminent") or result.get("departImminent")),
                    "definitif": bool(result.get("rapportsDefinitifsDisponibles")),
                    "replay": bool(result.get("replayDisponible")),
                    "prix": result.get("libelle", ""),
                    "specialty": result.get("specialite"),
                    "discipline": result.get("discipline"),
                    "distance": result.get("distance"),
                    "surface": result.get("typePiste"),
                    "going": result.get("etatTerrain"),
                    "corde": result.get("corde"),
                    "runners": result.get("nombreDeclaresPartants"),
                    "quinte": False,
                    "classe": result.get("categorieParticularite"),
                    "arrivee": result.get("ordreArrivee"),
                },
                "participants": transformed_parts,
            })
        except Exception as e:
            return jsonify({"error": str(e)}), 502
    else:
        # Try PMU first, fallback to cache, then archive
        d = _format_date(date)
        cached = _load_race_cache(date, meeting, race)
        try:
            course = _get(f"{BASE_URL}/programme/{d}/R{meeting}/C{race}")
            participants_resp = _get(
                f"{BASE_URL}/programme/{d}/R{meeting}/C{race}/participants?specialisation=INTERNET"
            )
            pmu_parts = participants_resp.get("participants", [])
            if not pmu_parts:
                raise Exception("No PMU participants available")

            hippo = course.get("hippodrome", {})
            hippo_name = hippo.get("libelleCourt", "") if isinstance(hippo, dict) else str(hippo)

            transformed_parts = []
            for p in pmu_parts:
                driver = p.get("driver", "")
                if isinstance(driver, dict):
                    driver = driver.get("nom", "")
                trainer = p.get("entraineur", "")
                if isinstance(trainer, dict):
                    trainer = trainer.get("nom", "")
                nom = p.get("nom", "") or p.get("nomPmu", "")
                if isinstance(nom, dict):
                    nom = nom.get("libelle", "")
                cote = None
                rap = p.get("dernierRapportDirect")
                if isinstance(rap, dict):
                    cote = rap.get("rapport")
                gains = p.get("gainsParticipant")
                gain_val = None
                if isinstance(gains, dict):
                    gain_val = gains.get("gainsCarriere")
                transformed_parts.append({
                    "num": p.get("numPmu"), "horse": nom, "horse_id": p.get("idCheval"),
                    "jockey": driver, "trainer": trainer,
                    "age": p.get("age"), "sexe": p.get("sexe"), "gain": gain_val,
                    "valeur": p.get("handicapValeur"), "poids": p.get("handicapPoids"), "corde": p.get("placeCorde"),
                    "cote_pmu": cote, "musique": p.get("musique"),
                    "deferre": p.get("deferre", ""),
                    "oeilleres": p.get("oeilleres"), "proprietaire": p.get("proprietaire", ""),
                    "nombreCourses": p.get("nombreCourses"), "nombreVictoires": p.get("nombreVictoires"),
                    "nombrePlaces": p.get("nombrePlaces"), "nombrePlacesSecond": p.get("nombrePlacesSecond"),
                    "nombrePlacesTroisieme": p.get("nombrePlacesTroisieme"),
                    "statut": p.get("statut"), "codeStatut": p.get("codeStatut"),
                    "nonPartant": p.get("nonPartant"), "etat": p.get("etat"),
                })

            spec = course.get("specialite")
            pmu_pen = course.get("penetrometre")
            if isinstance(pmu_pen, dict):
                pmu_pen = pmu_pen.get("intitule") or pmu_pen.get("valeurMesure")

            corde = course.get("corde", "")
            if isinstance(corde, str):
                if "GAUCHE" in corde.upper():
                    corde = "G"
                elif "DROITE" in corde.upper():
                    corde = "D"

            pari_types = list({p["typePari"].removeprefix("E_") if p["typePari"].startswith("E_") else p["typePari"] for p in course.get("paris", []) if "typePari" in p})
            _enrich_valeur(transformed_parts, date, meeting, race)
            _enrich_deferre_stats(transformed_parts)
            # enrich course ref for PLAT DNA
            _course_tmp = {
                'condition': course.get('condition'),
                'ref': course.get('ref')
            }
            _course_tmp = _enrich_ref(_course_tmp, date, meeting, race)
            # will be merged into result below
            result = {
                "reunion": {
                    "hippodrome": hippo_name,
                    "num": meeting,
                    "date": date,
                },
                "course": {
                    "num": race,
                    "time": course.get("heureDepart"),
                    "statut": course.get("statut"),
                    "imminent": bool(course.get("isDepartImminent") or course.get("departImminent")),
                    "definitif": bool(course.get("rapportsDefinitifsDisponibles")),
                    "replay": bool(course.get("replayDisponible")),
                    "prix": course.get("libelle", ""),
                    "specialty": spec,
                    "discipline": course.get("discipline"),
                    "distance": course.get("distance"),
                    "surface": course.get("typePiste"),
                    "going": course.get("etatTerrain"),
                    "corde": corde,
                    "runners": course.get("nombreDeclaresPartants"),
                    "quinte": course.get("quinte", False),
                    "classe": course.get("categorieParticularite"),
                    "penetrometer": pmu_pen,
                    "arrivee": course.get("ordreArrivee"),
                    "types_pari": pari_types,
                },
                "participants": transformed_parts,
            }
            # attach ref to course
            try:
                result['course']['ref'] = _course_tmp.get('ref')
                if not result['course'].get('condition') and _course_tmp.get('condition'):
                    result['course']['condition'] = _course_tmp.get('condition')
            except: pass
            _save_race_cache(date, meeting, race, result)
            return jsonify(result)
        except Exception as e:
            print(f"[OFFLINE] PMU API unavailable for race {date}/R{meeting}/C{race}: {e}")
            # Try cache first
            if cached:
                print(f"[OFFLINE] Using cached data for race {date}/R{meeting}/C{race}")
                return jsonify(cached)
            # Fallback to archive for past races
            try:
                from database import get_db
                conn = get_db()
                
                # Get hippodrome name from programme for SOREC meetings
                hippo_name = None
                if meeting >= MOROCCO_OFFSET:
                    try:
                        from .morocco import fetch_morocco_programme
                        ma_reunions = fetch_morocco_programme(date)
                        for mr in ma_reunions:
                            if mr.get("numero") == meeting:
                                hippo_obj = mr.get("hippodrome", {})
                                hippo_name = hippo_obj.get("libelleCourt", "") if isinstance(hippo_obj, dict) else str(hippo_obj)
                                break
                    except Exception:
                        pass
                
                # Search by date and course_num, optionally filtering by hippodrome
                if hippo_name:
                    # Normalize hippodrome name for DB search
                    hippo_db = hippo_name.upper().replace(" ", "_").replace("'", "")
                    archived = conn.execute(
                        "SELECT * FROM races WHERE date=? AND course_num=? AND hippodrome LIKE ? LIMIT 1",
                        (date, race, f"%{hippo_db}%")
                    ).fetchone()
                else:
                    archived = conn.execute(
                        "SELECT * FROM races WHERE date=? AND course_num=? LIMIT 1",
                        (date, race)
                    ).fetchone()
                    
                if archived:
                    archived = dict(archived)
                    participants = conn.execute(
                        "SELECT * FROM participants WHERE race_id=? ORDER BY num",
                        (archived["race_id"],)
                    ).fetchall()
                    archived["participants"] = [dict(p) for p in participants]
                    conn.close()
                    parts = archived.get("participants", [])
                    transformed_parts = []
                    for p in parts:
                        transformed_parts.append({
                            "num": p.get("num"), "horse": p.get("horse", ""),
                            "horse_id": None, "jockey": p.get("jockey", ""),
                            "trainer": p.get("trainer", ""),
                            "age": p.get("age"), "sexe": p.get("sexe"),
                            "poids": p.get("poids"),
                            "cote_pmu": p.get("cote_pmu"), "musique": p.get("musique", ""),
                            "deferre": p.get("deferre", ""), "valeur": p.get("valeur"),
                            "proprietaire": p.get("proprietaire", ""),
                        })
                    _enrich_deferre_stats(transformed_parts)
                    return jsonify({
                        "reunion": {
                            "hippodrome": archived.get("hippodrome", ""),
                            "num": meeting,
                            "date": date,
                        },
                        "course": {
                            "num": race,
                            "time": None,
                            "prix": archived.get("prix", ""),
                            "specialty": archived.get("discipline"),
                            "discipline": archived.get("discipline"),
                            "distance": archived.get("distance"),
                            "surface": archived.get("surface"),
                            "going": archived.get("going"),
                            "corde": archived.get("corde"),
                            "runners": archived.get("runners"),
                            "quinte": False,
                            "classe": None,
                            "penetrometer": None,
                            "arrivee": None,
                        },
                        "participants": transformed_parts,
                    })
                conn.close()
            except Exception:
                pass
            return jsonify({"error": str(e)}), 502


@pmu_bp.route("/api/programme/dates", methods=["GET"])
def get_available_dates():
    today = date.today()
    return jsonify({
        "today": today.isoformat(),
        "yesterday": (today - timedelta(days=1)).isoformat(),
        "tomorrow": (today + timedelta(days=1)).isoformat()
    })
