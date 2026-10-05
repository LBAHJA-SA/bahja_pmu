from flask import Blueprint, jsonify, request
from scraper.geny_scraper import GenyScraper
from database import (
    save_geny_race, list_archive_hippodromes, list_archive_races,
    get_archived_race, delete_archive_file, delete_archived_race,
    list_archive_dates, get_horse_names, search_horses, get_horse_races,
    get_horse_specialty,
    get_jockey_names, search_jockeys, get_jockey_races, get_jockey_specialty,
    canonical_jockey_name,
    get_hippodrome_third_places, get_hippodrome_rank_places, get_hippodrome_places
)

archive_bp = Blueprint("archive", __name__)
from scraper.geny_scraper import get_scraper
scraper = get_scraper()

import requests as _req
import time as _time

PMU_BASE = "https://online.turfinfo.api.pmu.fr/rest/client/61"
PMU_HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": "https://www.pmu.fr",
    "Referer": "https://www.pmu.fr/",
}
_pmu_session = _req.Session()
_pmu_session.headers.update(PMU_HEADERS)

def _pmu_get(url, timeout=10):
    for _ in range(3):
        try:
            r = _pmu_session.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception:
            _time.sleep(0.5)
    raise Exception(f"PMU API failed: {url}")

def _format_pmu_date(d):
    ds = d.isoformat().replace("-", "")
    return ds[6:8] + ds[4:6] + ds[:4]


@archive_bp.route("/api/archive", methods=["POST"])
def archive_save():
    data = request.get_json()
    if not data:
        return jsonify({"error": "No data"}), 400
    race_data = data.get("data")
    if not isinstance(race_data, dict):
        return jsonify({"error": "Invalid race format"}), 400
    race_id = data.get("race_id", 0)

    if "reunion" not in race_data and "programme" in race_data:
        race_data = _convert_pmu_to_archive(race_data, race_id)
    elif "reunion" not in race_data and "participants" in race_data:
        pass

    try:
        result = save_geny_race(race_id, race_data)
        return jsonify({"status": "ok", "file": result["filename"], "hippodrome": result["hippodrome"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


def _convert_pmu_to_archive(pmu, race_id):
    parts = pmu.get("participants", pmu.get("partants", []))
    hippo = pmu.get("hippodrome", {})
    hippo_name = ""
    if isinstance(hippo, dict):
        hippo_name = hippo.get("libelleCourt", hippo.get("libelleLong", ""))
    elif isinstance(hippo, str):
        hippo_name = hippo

    participants = []
    for p in parts:
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
        participants.append({
            "num": p.get("numPmu"), "horse": nom, "horse_id": p.get("idCheval"),
            "jockey": driver, "trainer": trainer,
            "age": p.get("age"), "sexe": p.get("sexe"), "gain": gain_val,
            "poids": p.get("handicapPoids"), "corde": p.get("placeCorde"),
            "cote_pmu": cote, "musique": p.get("musique"),
            "proprietaire": p.get("proprietaire", ""),
        })

    spec = pmu.get("specialite")
    if not spec:
        for cl in pmu.get("specialites", []):
            if isinstance(cl, dict) and cl.get("code"):
                spec = cl["code"]
                break

    r_num = pmu.get("numReunion", 0)
    c_num = pmu.get("numOrdre", 0)
    date_str = ""
    dr = pmu.get("dateReunion", "")
    if isinstance(dr, str) and len(dr) >= 10:
        date_str = dr[:10]

    pmu_pen = pmu.get("penetrometre")
    if isinstance(pmu_pen, dict):
        pmu_pen = pmu_pen.get("intitule") or pmu_pen.get("valeurMesure")

    return {
        "reunion": {
            "hippodrome": hippo_name,
            "num": r_num,
            "date": date_str,
        },
        "course": {
            "num": c_num,
            "time": pmu.get("heureDepart"),
            "prix": pmu.get("libelle", ""),
            "specialty": spec,
            "discipline": pmu.get("discipline"),
            "distance": pmu.get("distance"),
            "surface": pmu.get("typePiste"),
            "going": pmu.get("etatTerrain"),
            "corde": pmu.get("corde"),
            "runners": pmu.get("nombreDeclaresPartants"),
            "quinte": pmu.get("quinte", False),
            "classe": pmu.get("categorieParticularite"),
            "depart": pmu.get("depart"),
            "penetrometer": pmu_pen,
            "types_pari": list({p["typePari"].removeprefix("E_") if p["typePari"].startswith("E_") else p["typePari"] for p in pmu.get("paris", []) if "typePari" in p}),
            "allocations": None,
            "arrivee": pmu.get("ordreArrivee"),
        },
        "participants": participants,
    }


@archive_bp.route("/api/archive", methods=["GET"])
def archive_list():
    hippodrome = request.args.get("hippodrome")
    date_filter = request.args.get("date")
    quinte_only = request.args.get("quinte", "").lower() == "true"
    limit = int(request.args.get("limit", 100))
    offset = int(request.args.get("offset", 0))

    if hippodrome or date_filter or quinte_only:
        races = list_archive_races(hippodrome, date_filter, quinte_only, limit, offset)
        return jsonify({"races": races, "total": len(races)})
    else:
        result = list_archive_hippodromes()
        return jsonify(result)


@archive_bp.route("/api/archive/<hippodrome>/<filename>", methods=["DELETE"])
def archive_delete_file(hippodrome, filename):
    delete_archive_file(hippodrome, filename)
    return jsonify({"status": "deleted"})


@archive_bp.route("/api/archive/races/<int:race_id>", methods=["GET", "DELETE"])
def archive_race(race_id):
    if request.method == "DELETE":
        delete_archived_race(race_id)
        return jsonify({"status": "deleted"})
    race = get_archived_race(race_id)
    if race is None:
        return jsonify({"error": "Race not found"}), 404
    return jsonify(race)


@archive_bp.route("/api/archive/save/<int:race_id>", methods=["POST"])
def archive_save_fetch(race_id):
    try:
        race_data = scraper.fetch_race_details(race_id)
        if race_data is None:
            return jsonify({"error": "Race not found"}), 404
        result = save_geny_race(race_id, race_data)
        return jsonify({"status": "saved", "race_id": race_id, "file": result["filename"]})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@archive_bp.route("/api/archive/save-date/<date_str>", methods=["POST"])
def archive_save_date(date_str):
    import datetime
    try:
        target_date = datetime.date.fromisoformat(date_str)
    except ValueError:
        return jsonify({"error": "Invalid date format"}), 400

    d = _format_pmu_date(target_date)

    try:
        pmu = _pmu_get(f"{PMU_BASE}/programme/{d}?meteo=true&specialisation=INTERNET")
    except Exception as e:
        return jsonify({"error": f"PMU API error: {e}"}), 502

    pmu_reunions = pmu.get("programme", {}).get("reunions", [])

    try:
        from routes.morocco import fetch_morocco_programme, MOROCCO_OFFSET
        existing_names = set()
        for r in pmu_reunions:
            h = r.get("hippodrome", {})
            n = h.get("libelleCourt", "") if isinstance(h, dict) else ""
            existing_names.add(str(n).upper())
        ma = fetch_morocco_programme(date_str)
        for mr in ma:
            h = mr.get("hippodrome", {})
            n = str(h.get("libelleCourt", "")).upper() if isinstance(h, dict) else ""
            if n and n in existing_names:
                continue
            pmu_reunions.append(mr)
            existing_names.add(n)
    except Exception:
        pass

    total = 0
    saved = 0
    errors = []

    for r in pmu_reunions:
        r_num = r.get("numOfficiel") or r.get("numero", 0)
        hippo = r.get("hippodrome", {})
        hippo_name = hippo.get("libelleCourt", hippo.get("libelleLong", "UNKNOWN"))
        for c in r.get("courses", []):
            total += 1
            c_num = c.get("numOrdre", 0)
            race_id = f"{date_str}_R{r_num}_C{c_num}"
            try:
                pmu_participants = []
                if r_num < 900:
                    try:
                        part = _pmu_get(f"{PMU_BASE}/programme/{d}/R{r_num}/C{c_num}/participants?specialisation=INTERNET")
                        pmu_participants = part.get("participants", [])
                    except Exception:
                        pass
                if not pmu_participants and c.get("_sorecId"):
                    try:
                        from routes.morocco import fetch_morocco_race
                        mrace = fetch_morocco_race(c["_sorecId"], date_str)
                        pmu_participants = mrace.get("partants", [])
                    except Exception:
                        pass

                participants = []
                for p in pmu_participants:
                    driver = p.get("driver", "")
                    if isinstance(driver, dict):
                        driver = driver.get("nom", "")
                    trainer = p.get("entraineur", "")
                    if isinstance(trainer, dict):
                        trainer = trainer.get("nom", "")
                    race_obj = p.get("race")
                    pnum = p.get("numPmu")
                    if isinstance(race_obj, dict) and not pnum:
                        pnum = race_obj.get("numPmu")
                    nom = p.get("nom", "") or p.get("nomPmu", "")
                    if isinstance(nom, dict):
                        nom = nom.get("libelle", "")
                    cote = None
                    rap = p.get("dernierRapportDirect")
                    if isinstance(rap, dict):
                        cote = rap.get("rapport")
                    elif isinstance(rap, (int, float)):
                        cote = rap

                    gains_obj = p.get("gainsParticipant")
                    gain_val = None
                    if isinstance(gains_obj, dict):
                        gain_val = gains_obj.get("gainsCarriere")

                    participants.append({
                        "num": pnum,
                        "horse": nom,
                        "horse_id": p.get("idCheval"),
                        "jockey": driver,
                        "trainer": trainer,
                        "age": p.get("age"),
                        "sexe": p.get("sexe"),
                        "gain": gain_val,
                        "poids": p.get("handicapPoids"),
                        "corde": p.get("placeCorde"),
                        "cote_pmu": cote,
                        "cote_geny": None,
                        "musique": p.get("musique"),
                        "distance": None,
                        "rang": None,
                        "proprietaire": p.get("proprietaire", ""),
                    })

                spec = c.get("specialite")
                if not spec:
                    for cl in c.get("specialites", []):
                        if cl.get("code"):
                            spec = cl["code"]
                            break

                pmu_pen = c.get("penetrometre")
                if isinstance(pmu_pen, dict):
                    pmu_pen = pmu_pen.get("intitule") or pmu_pen.get("valeurMesure")

                race_data = {
                    "reunion": {
                        "hippodrome": hippo_name,
                        "num": r_num,
                        "date": target_date.isoformat(),
                    },
                    "course": {
                        "num": c_num,
                        "time": c.get("heureDepart"),
                        "prix": c.get("libelle", ""),
                        "specialty": spec,
                        "discipline": c.get("discipline"),
                        "distance": c.get("distance"),
                        "surface": c.get("typePiste"),
                        "going": c.get("etatTerrain"),
                        "corde": c.get("corde"),
                        "runners": c.get("nombreDeclaresPartants"),
                        "quinte": c.get("quinte", False),
                        "classe": c.get("categorieParticularite"),
                        "depart": c.get("depart"),
                        "penetrometer": pmu_pen,
                        "types_pari": list({p["typePari"].removeprefix("E_") if p["typePari"].startswith("E_") else p["typePari"] for p in c.get("paris", []) if "typePari" in p}),
                        "allocations": None,
                        # The finish order, when PMU has one. This was hard-coded
                        # to None, so a re-save of a date that had already run
                        # threw the result away while PMU was sending it — which
                        # is why 39 of the stored press days had no result to
                        # score against and every measurement of the engine was
                        # made on 72 races instead of 111. The other save path,
                        # above, already read pmu.get("ordreArrivee").
                        "arrivee": c.get("ordreArrivee"),
                    },
                    "participants": participants,
                }

                save_geny_race(race_id, race_data)
                saved += 1
            except Exception as e:
                errors.append({"id": race_id, "error": str(e)})

    return jsonify({
        "total": total,
        "saved": saved,
        "errors": errors,
        "date": date_str
    })


@archive_bp.route("/api/archive/pattern-3e", methods=["GET"])
def archive_pattern_3e():
    hippodrome = request.args.get("hippodrome", "").strip()
    if not hippodrome:
        return jsonify({"error": "Missing ?hippodrome="}), 400
    discipline = request.args.get("discipline", "").strip() or None
    return jsonify(build_pattern_response(hippodrome, discipline, 3))


@archive_bp.route("/api/archive/pattern-1er", methods=["GET"])
def archive_pattern_1er():
    hippodrome = request.args.get("hippodrome", "").strip()
    if not hippodrome:
        return jsonify({"error": "Missing ?hippodrome="}), 400
    discipline = request.args.get("discipline", "").strip() or None
    return jsonify(build_pattern_response(hippodrome, discipline, 1))


@archive_bp.route("/api/archive/pattern/<int:rank>", methods=["GET"])
def archive_pattern_rank(rank):
    if rank < 1 or rank > 5:
        return jsonify({"error": "rank must be between 1 and 5"}), 400
    hippodrome = request.args.get("hippodrome", "").strip()
    if not hippodrome:
        return jsonify({"error": "Missing ?hippodrome="}), 400
    discipline = request.args.get("discipline", "").strip() or None
    return jsonify(build_pattern_response(hippodrome, discipline, rank))


def _family_percent_from_cotes(cotes):
    dist = {}
    for c in cotes:
        fam = "GF" if c <= 2.5 else "FC" if c <= 5.0 else "OC" if c <= 10.0 else "OUT" if c <= 20.0 else "TOC"
        d = dist.setdefault(fam, {"count": 0, "percent": 0.0})
        d["count"] += 1
    total = sum(d["count"] for d in dist.values())
    for fam, d in dist.items():
        d["percent"] = round(d["count"] / total * 100, 1) if total else 0.0
    return dist


def build_pattern_history(hippodrome, discipline, rank):
    rows = get_hippodrome_places(hippodrome, discipline)
    by_rank = {1: [], 2: [], 3: []}
    for r in rows:
        by_rank.setdefault(r["rang"], []).append(r)

    position_distributions = {}
    for pos in (1, 2, 3, 4, 5):
        position_distributions[pos] = _family_percent_from_cotes(
            [r["cote_pmu"] for r in by_rank.get(pos, [])]
        )

    target = by_rank.get(rank, [])
    total = len(target)
    surprise = sum(1 for r in target if r["cote_pmu"] > 10) / total * 100 if total else 0
    fav_win = sum(1 for r in target if r["cote_pmu"] <= 2.5) / total * 100 if total else 0

    if fav_win >= 30:
        profile_type = "favorites_dominant"
    elif surprise >= 50:
        profile_type = "upset_prone"
    elif fav_win >= 20:
        profile_type = "balanced"
    else:
        profile_type = "open_market"

    return {
        "hippodrome": hippodrome,
        "discipline": discipline,
        "pattern_rank": rank,
        "total_places": total,
        "position_distributions": position_distributions,
        "surprise_rate": round(surprise, 1),
        "favorite_win_rate": round(fav_win, 1),
        "profile_type": profile_type,
    }


def build_pattern_filters(hippodrome, discipline, rank, participants):
    ordered = []
    for p in participants or []:
        if not isinstance(p, dict):
            continue
        num = p.get("numPmu") or p.get("numero") or p.get("num")
        odds = p.get("odds") or p.get("cote_pmu")
        if num is None or odds is None:
            continue
        try:
            odds = float(odds)
        except (TypeError, ValueError):
            continue
        ordered.append({
            "numPmu": num,
            "nom": p.get("nom") or p.get("horse") or "",
            "odds": odds,
            "rank": p.get("rank") or 0,
        })
    ordered.sort(key=lambda h: (h["odds"], str(h["numPmu"])))
    for i, h in enumerate(ordered):
        h["rank"] = i + 1
    market = {"ordered": ordered, "count": len(ordered)}

    history = build_pattern_history(hippodrome, discipline, rank)
    results = [{"numPmu": h["numPmu"], "score": 0, "reason": ""} for h in ordered]

    return {
        "rank": rank,
        "history": history,
        "market": {
            "count": market.get("count", 0),
            "pressure": {},
            "balance": {},
            "families": {},
            "top": [
                {"numPmu": h["numPmu"], "odds": h["odds"], "family": "", "rank": h["rank"]}
                for h in market.get("ordered", [])[:8]
            ],
        },
        "results": results,
        "total": len(results),
    }


@archive_bp.route("/api/archive/pattern-filters", methods=["POST"])
def archive_pattern_filters():
    body = request.get_json(silent=True) or {}
    hippodrome = (body.get("hippodrome") or "").strip()
    rank = int(body.get("rank") or 1)
    participants = body.get("participants") or []
    if not hippodrome or not participants:
        return jsonify({"error": "Missing hippodrome or participants"}), 400
    discipline = (body.get("discipline") or "").strip() or None
    return jsonify(build_pattern_filters(hippodrome, discipline, rank, participants))


def build_pattern_response(hippodrome, discipline, rank):
    import statistics
    from collections import Counter

    rows = get_hippodrome_rank_places(hippodrome, rank, discipline)
    if not rows:
        return {
            "hippodrome": hippodrome,
            "discipline": discipline,
            "found": False, "stats": None, "patterns": [],
            "distribution": [],
        }

    cotes = [r["cote_pmu"] for r in rows if r["cote_pmu"] is not None]

    BUCKETS = [
        ("<= 2", lambda c: c <= 2),
        ("2 - 4", lambda c: 2 < c <= 4),
        ("4 - 10", lambda c: 4 < c <= 10),
        ("10.1 - 16", lambda c: 10 < c <= 16),
        ("16.1 - 25", lambda c: 16 < c <= 25),
        ("25.1 - 45", lambda c: 25 < c <= 45),
        ("> 45.1", lambda c: c > 45),
    ]
    buckets = [{"label": label, "items": [r for r in rows if fn(r["cote_pmu"])]} for label, fn in BUCKETS]
    distribution = [{
        "bucket": b["label"], "count": len(b["items"]),
        "pct": round(len(b["items"]) / len(cotes) * 100, 1) if cotes else 0,
        "min": round(min(r["cote_pmu"] for r in b["items"]), 1) if b["items"] else None,
        "max": round(max(r["cote_pmu"] for r in b["items"]), 1) if b["items"] else None,
    } for b in buckets]

    all_rows = get_hippodrome_places(hippodrome, discipline)
    by_pos = {}
    for r in all_rows:
        by_pos.setdefault(r["rang"], []).append(r)
    cross_position_pcts = {}
    for pos in sorted(by_pos):
        cots = [r["cote_pmu"] for r in by_pos[pos]]
        if not cots:
            continue
        cross_position_pcts[str(pos)] = {
            label: round(sum(1 for c in cots if fn(c)) / len(cots) * 100, 1)
            for label, fn in BUCKETS
        }

    target_pcts = cross_position_pcts.get(str(rank), {})

    def bucket_lift(label):
        vals = [cross_position_pcts[p].get(label, 0) for p in cross_position_pcts]
        avg = sum(vals) / len(vals) if vals else 1
        p = target_pcts.get(label, 0)
        return p / avg if avg > 0 else 0

    distinctive = []
    for b in buckets:
        pct = len(b["items"]) / len(cotes) * 100 if cotes else 0
        lift = bucket_lift(b["label"])
        if len(b["items"]) >= 2:
            distinctive.append((b, pct, lift))
    distinctive.sort(key=lambda x: -(x[1] * x[2]))

    patterns = []
    for i, (b, pct, lift) in enumerate(distinctive[:3]):
        patterns.append({
            "rank": i + 1, "bucket": b["label"], "count": len(b["items"]),
            "pct": round(pct, 1),
            "lift": round(lift, 2),
            "min": round(min(r["cote_pmu"] for r in b["items"]), 1) if b["items"] else None,
            "max": round(max(r["cote_pmu"] for r in b["items"]), 1) if b["items"] else None,
        })

    stats = {
        "total": len(rows),
        "min_cote": round(min(cotes), 1),
        "max_cote": round(max(cotes), 1),
        "avg_cote": round(sum(cotes) / len(cotes), 1),
        "median_cote": round(statistics.median(cotes), 1),
    }

    mode_cotes = Counter(round(c, 1) for c in cotes).most_common(5)
    stats["top_cotes"] = [{"cote": c, "count": n} for c, n in mode_cotes]

    return {
        "hippodrome": hippodrome,
        "discipline": discipline,
        "rank": rank,
        "found": True,
        "stats": stats,
        "patterns": patterns,
        "distribution": distribution,
        "cross_position_pcts": cross_position_pcts,
    }


@archive_bp.route("/api/archive/dates", methods=["GET"])
def archive_dates():
    import datetime
    dates = list_archive_dates()
    today = datetime.date.today().isoformat()
    return jsonify({
        "dates": dates,
        "today": today,
        "yesterday": (datetime.date.today() - datetime.timedelta(days=1)).isoformat(),
        "tomorrow": (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
    })


@archive_bp.route("/api/archive/check/<int:race_id>", methods=["GET"])
def archive_check(race_id):
    r = get_archived_race(race_id)
    return jsonify({"archived": r is not None})


@archive_bp.route("/api/horses/names")
def horse_names():
    q = request.args.get("q", "").strip()
    names = get_horse_names(q)
    return jsonify(names[:50])


@archive_bp.route("/api/horses/<path:name>/races")
def horse_races(name):
    races = get_horse_races(name)
    if not races:
        return jsonify({"found": False, "horse": name, "races": []})
    specialty = get_horse_specialty(name)
    return jsonify({"found": True, "horse": name, "races": races, "total": len(races), "specialty": specialty})


@archive_bp.route("/api/jockeys/names")
def jockey_names():
    q = request.args.get("q", "").strip()
    names = get_jockey_names(q)
    return jsonify(names[:50])


@archive_bp.route("/api/jockeys/search")
def jockey_search():
    q = request.args.get("q", "").strip().upper()
    if not q:
        return jsonify({"error": "Missing ?q="}), 400

    from collections import defaultdict

    rows = search_jockeys(q, limit=10000)
    if not rows:
        return jsonify({"query": q, "found": False, "jockeys": [], "total_appearances": 0})

    by_name = defaultdict(list)
    for r in rows:
        by_name[r.get("canon") or r["jockey"].upper()].append(r)

    def compute_specialty(apps):
        disc_stats = {}
        dist_buckets = {"<1800m": [], "1800-2100m": [], "2100-2500m": [], "2500-2800m": [], ">2800m": []}
        surface_stats = {}
        hippo_stats = {}

        for a in apps:
            disc = a.get("discipline") or "INCONNU"
            if disc not in disc_stats:
                disc_stats[disc] = {"runs": 0, "wins": 0, "top3": 0}
            disc_stats[disc]["runs"] += 1
            if a.get("rang") and a["rang"] == 1:
                disc_stats[disc]["wins"] += 1
            if a.get("rang") and 1 <= a["rang"] <= 3:
                disc_stats[disc]["top3"] += 1

            dist = a.get("distance") or 0
            if dist > 0:
                if dist < 1800:
                    bucket = "<1800m"
                elif dist <= 2100:
                    bucket = "1800-2100m"
                elif dist <= 2500:
                    bucket = "2100-2500m"
                elif dist <= 2800:
                    bucket = "2500-2800m"
                else:
                    bucket = ">2800m"
                dist_buckets[bucket].append(a)

            surf = (a.get("surface") or "").strip()
            if surf:
                if surf not in surface_stats:
                    surface_stats[surf] = {"runs": 0, "wins": 0}
                surface_stats[surf]["runs"] += 1
                if a.get("rang") and a["rang"] == 1:
                    surface_stats[surf]["wins"] += 1

            hippo = (a.get("hippodrome") or "INCONNU")
            if hippo not in hippo_stats:
                hippo_stats[hippo] = {"runs": 0, "wins": 0, "top3": 0}
            hippo_stats[hippo]["runs"] += 1
            if a.get("rang") and a["rang"] == 1:
                hippo_stats[hippo]["wins"] += 1
            if a.get("rang") and 1 <= a["rang"] <= 3:
                hippo_stats[hippo]["top3"] += 1

        discipline = {}
        for d, s in disc_stats.items():
            discipline[d] = {
                "runs": s["runs"], "wins": s["wins"], "top3": s["top3"],
                "win_rate": round(s["wins"] / s["runs"] * 100, 1) if s["runs"] else 0,
            }

        distance = {}
        for b, items in dist_buckets.items():
            if items:
                wins = sum(1 for r in items if r.get("rang") and r["rang"] == 1)
                top3 = sum(1 for r in items if r.get("rang") and 1 <= r["rang"] <= 3)
                distance[b] = {
                    "runs": len(items), "wins": wins, "top3": top3,
                    "win_rate": round(wins / len(items) * 100, 1) if items else 0,
                }

        surface = {}
        for s, st in surface_stats.items():
            surface[s] = {
                "runs": st["runs"], "wins": st["wins"],
                "win_rate": round(st["wins"] / st["runs"] * 100, 1) if st["runs"] else 0,
            }

        hippodromes = {}
        for h, st in hippo_stats.items():
            hippodromes[h] = {
                "runs": st["runs"], "wins": st["wins"], "top3": st["top3"],
                "win_rate": round(st["wins"] / st["runs"] * 100, 1) if st["runs"] else 0,
            }

        return {
            "total": len(apps),
            "discipline": discipline,
            "distance": distance,
            "surface": surface,
            "hippodrome": hippodromes,
        }

    jockeys = []
    for name, apps in by_name.items():
        total = len(apps)
        wins = 0
        top3 = 0
        top5 = 0
        best_rang = 999
        best_app = None
        last_app = apps[0]

        for a in apps:
            rang = a.get("rang")
            if rang == 1: wins += 1
            if rang and 1 <= rang <= 3: top3 += 1
            if rang and 1 <= rang <= 5: top5 += 1
            if rang and rang > 0 and rang < best_rang:
                best_rang = rang
                best_app = a

        avg_odds_list = [a.get("cote_pmu") for a in apps if a.get("cote_pmu")]
        avg_odds = round(sum(avg_odds_list) / len(avg_odds_list), 1) if avg_odds_list else None

        specialty = compute_specialty(apps)

        jockeys.append({
            "nom": apps[0].get("canon") or apps[0]["jockey"],
            "total_appearances": total, "wins": wins, "top3": top3,
            "top5": top5,
            "win_rate": round(wins / total * 100, 1) if total else 0,
            "top3_rate": round(top3 / total * 100, 1) if total else 0,
            "avg_odds": avg_odds,
            "last_appearance": last_app["date"] if last_app else None,
            "last_hippodrome": last_app.get("hippodrome"),
            "last_position": last_app.get("rang"),
            "best_position": best_app["rang"] if best_app else None,
            "best_race": best_app.get("prix") if best_app else None,
            "musique": apps[0].get("musique"),
            "specialty": specialty,
        })

    jockeys.sort(key=lambda x: -x["total_appearances"])
    return jsonify({"query": q, "found": len(jockeys) > 0, "jockeys": jockeys, "total_appearances": len(rows)})


@archive_bp.route("/api/jockeys/<path:name>/races")
def jockey_races(name):
    races = get_jockey_races(name)
    if not races:
        return jsonify({"found": False, "jockey": name, "races": []})
    specialty = get_jockey_specialty(name)
    display = canonical_jockey_name(name)
    return jsonify({"found": True, "jockey": display, "races": races, "total": len(races), "specialty": specialty})


@archive_bp.route("/api/analysis/<int:race_id>", methods=["GET"])
def get_race_analysis(race_id):
    from analysis import analyze_race
    from routes.programme import format_archived_race
    from database import get_archived_race

    import time
    t0 = time.time()
    data = scraper.fetch_race_details(race_id)
    t1 = time.time()
    participants = (data or {}).get("participants") or (data or {}).get("course", {}).get("participants") or []
    if data is not None and len(participants) > 0:
        result = analyze_race(data)
        t2 = time.time()
        print(f"[analysis] fetch={t1-t0:.3f}s analyze={t2-t1:.3f}s total={t2-t0:.3f}s race_id={race_id} cached={len(scraper._cache)}", file=__import__('sys').stderr, flush=True)
        return jsonify(result)
    db_race = get_archived_race(race_id)
    if db_race is not None:
        formatted = format_archived_race(db_race)
        result = analyze_race(formatted)
        return jsonify(result)
    return jsonify({"error": "Race not found"}), 404


@archive_bp.route("/api/horses/search")
def horse_search():
    q = request.args.get("q", "").strip().upper()
    if not q:
        return jsonify({"error": "Missing ?q="}), 400

    from collections import defaultdict

    rows = search_horses(q, limit=200)
    if not rows:
        return jsonify({"query": q, "found": False, "horses": [], "total_appearances": 0})

    by_name = defaultdict(list)
    for r in rows:
        by_name[r["horse"].upper()].append(r)

    def compute_specialty(apps):
        disc_stats = {}
        dist_buckets = {"<1800m": [], "1800-2100m": [], "2100-2500m": [], "2500-2800m": [], ">2800m": []}
        surface_stats = {}
        corde_stats = {"G": [], "D": []}
        running_styles = {"front": 0, "mid": 0, "back": 0}

        for a in apps:
            disc = a.get("discipline") or "INCONNU"
            if disc not in disc_stats:
                disc_stats[disc] = {"runs": 0, "wins": 0, "top3": 0}
            disc_stats[disc]["runs"] += 1
            if a.get("rang") and a["rang"] == 1:
                disc_stats[disc]["wins"] += 1
            if a.get("rang") and 1 <= a["rang"] <= 3:
                disc_stats[disc]["top3"] += 1

            dist = a.get("distance") or 0
            if dist > 0:
                if dist < 1800:
                    bucket = "<1800m"
                elif dist <= 2100:
                    bucket = "1800-2100m"
                elif dist <= 2500:
                    bucket = "2100-2500m"
                elif dist <= 2800:
                    bucket = "2500-2800m"
                else:
                    bucket = ">2800m"
                dist_buckets[bucket].append(a)

            surf = (a.get("surface") or "").strip()
            if surf:
                if surf not in surface_stats:
                    surface_stats[surf] = {"runs": 0, "wins": 0}
                surface_stats[surf]["runs"] += 1
                if a.get("rang") and a["rang"] == 1:
                    surface_stats[surf]["wins"] += 1

            corde = a.get("corde")
            if corde in ("G", "D"):
                corde_stats[corde].append(a)

            cote = a.get("cote_pmu") or 0
            runners = a.get("runners") or 0
            rang = a.get("rang")
            if cote and runners and rang:
                if cote <= 3.0 and rang <= 3:
                    running_styles["front"] += 1
                elif rang <= runners * 0.3:
                    running_styles["front"] += 1
                elif rang > runners * 0.6:
                    running_styles["back"] += 1
                else:
                    running_styles["mid"] += 1

        discipline = {}
        for d, s in disc_stats.items():
            discipline[d] = {
                "runs": s["runs"], "wins": s["wins"], "top3": s["top3"],
                "win_rate": round(s["wins"] / s["runs"] * 100, 1) if s["runs"] else 0,
            }

        distance = {}
        for b, items in dist_buckets.items():
            if items:
                wins = sum(1 for r in items if r.get("rang") and r["rang"] == 1)
                top3 = sum(1 for r in items if r.get("rang") and 1 <= r["rang"] <= 3)
                distance[b] = {
                    "runs": len(items), "wins": wins, "top3": top3,
                    "win_rate": round(wins / len(items) * 100, 1) if items else 0,
                }

        surface = {}
        for s, st in surface_stats.items():
            surface[s] = {
                "runs": st["runs"], "wins": st["wins"],
                "win_rate": round(st["wins"] / st["runs"] * 100, 1) if st["runs"] else 0,
            }

        corde = {}
        for c, items in corde_stats.items():
            if items:
                wins = sum(1 for r in items if r.get("rang") and r["rang"] == 1)
                corde[c] = {
                    "runs": len(items), "wins": wins,
                    "win_rate": round(wins / len(items) * 100, 1) if items else 0,
                }

        style_total = running_styles["front"] + running_styles["mid"] + running_styles["back"]
        style = {}
        if style_total:
            style = {
                "leader": {"count": running_styles["front"], "pct": round(running_styles["front"] / style_total * 100, 1)},
                "midfield": {"count": running_styles["mid"], "pct": round(running_styles["mid"] / style_total * 100, 1)},
                "closer": {"count": running_styles["back"], "pct": round(running_styles["back"] / style_total * 100, 1)},
            }

        return {
            "total": len(apps),
            "discipline": discipline,
            "distance": distance,
            "surface": surface,
            "corde": corde,
            "style": style,
        }

    horses = []
    for name, apps in by_name.items():
        total = len(apps)
        wins = 0
        top3 = 0
        top5 = 0
        best_rang = 999
        best_app = None
        last_app = apps[0]

        for a in apps:
            rang = a.get("rang")
            if rang == 1: wins += 1
            if rang and 1 <= rang <= 3: top3 += 1
            if rang and 1 <= rang <= 5: top5 += 1
            if rang and rang > 0 and rang < best_rang:
                best_rang = rang
                best_app = a

        avg_odds_list = [a.get("cote_pmu") for a in apps if a.get("cote_pmu")]
        avg_odds = round(sum(avg_odds_list) / len(avg_odds_list), 1) if avg_odds_list else None

        specialty = compute_specialty(apps)

        horses.append({
            "nom": apps[0]["horse"],
            "total_appearances": total, "wins": wins, "top3": top3,
            "top5": top5,
            "win_rate": round(wins / total * 100, 1) if total else 0,
            "top3_rate": round(top3 / total * 100, 1) if total else 0,
            "avg_odds": avg_odds,
            "last_appearance": last_app["date"] if last_app else None,
            "last_hippodrome": last_app.get("hippodrome"),
            "last_position": last_app.get("rang"),
            "best_position": best_app["rang"] if best_app else None,
            "best_race": best_app.get("prix") if best_app else None,
            "age": apps[0].get("age"), "sexe": apps[0].get("sexe"),
            "musique": apps[0].get("musique"),
            "specialty": specialty,
        })

    horses.sort(key=lambda x: -x["total_appearances"])
    return jsonify({"query": q, "found": len(horses) > 0, "horses": horses, "total_appearances": len(rows)})
