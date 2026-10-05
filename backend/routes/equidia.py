import re
import os
import time as _time
import json
from datetime import datetime
import requests as req

EQUIDIA_OFFSET = 300
PROGRAMME_URL = "https://www.equidia.fr/courses-hippique"
COURSE_URL = "https://www.equidia.fr/courses/{date}/R{num}/C{cnum}"

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_session = req.Session()
_session.headers.update({
    "User-Agent": _UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.8",
})

_state_cache = {}
_CACHE_TTL = 300

# Offline cache directory
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def _load_cache(date_str):
    cache_file = os.path.join(CACHE_DIR, f"equidia_{date_str}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return None

def _save_cache(date_str, data):
    cache_file = os.path.join(CACHE_DIR, f"equidia_{date_str}.json")
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except:
        pass


def _fetch_state(url):
    now = _time.time()
    hit = _state_cache.get(url)
    if hit and now - hit[0] < _CACHE_TTL:
        return hit[1]
    r = _session.get(url, timeout=15)
    r.raise_for_status()
    m = re.search(
        r'<script id="serverApp-state" type="application/json">(.*?)</script>',
        r.text, re.S,
    )
    state = json.loads(m.group(1)) if m else {}
    _state_cache[url] = (now, state)
    return state


def _iso_to_ms(iso):
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso)
        return int(dt.timestamp() * 1000)
    except Exception:
        return None


def _map_specialty(discipline):
    if not discipline:
        return None
    key = str(discipline).strip().lower()
    if "attel" in key:
        return "ATTELE"
    if "mont" in key:
        return "MONTE"
    if "plat" in key or "galop" in key:
        return "PLAT"
    if "haie" in key:
        return "HAIES"
    if "steeple" in key or "steep" in key:
        return "STEEPLE"
    if "cross" in key:
        return "CROSS"
    return str(discipline).strip().upper()


def _map_corde(lib):
    if not lib:
        return None
    if "GAUCHE" in lib.upper():
        return "G"
    if "DROITE" in lib.upper():
        return "D"
    return None


def fetch_equidia_programme(date):
    """Fetch equidia daily reunions and convert to PMU-like format."""
    # Try cache first
    cached = _load_cache(date)
    if cached:
        return cached
    
    try:
        url = f"{PROGRAMME_URL}?date={date}"
        state = _fetch_state(url)
    except Exception as e:
        print(f"[OFFLINE] Equidia API unavailable for {date}: {e}")
        return []
    
    reunions = state.get(f"dailyreunions/{date}") or []

    converted = []
    for r in reunions:
        if r.get("is_canceled"):
            continue
        num_reunion = r.get("num_reunion") or 0
        if not num_reunion:
            continue
        reunion_num = EQUIDIA_OFFSET + num_reunion

        hippo_obj = r.get("hippodrome") or {}
        hippo_name = r.get("lib_reunion") or hippo_obj.get("name") or "Inconnu"
        hippo = {
            "code": hippo_name.upper().replace(" ", "_")[:15],
            "libelleCourt": hippo_name,
            "libelleLong": hippo_name,
        }

        courses = []
        for c in r.get("courses_by_day") or []:
            cnum = c.get("num_course_pmu") or 0
            discipline = c.get("discipline", "")
            spec = _map_specialty(discipline)
            course = {
                "numOrdre": cnum,
                "libelle": c.get("libcourt_prix_course", ""),
                "distance": c.get("distance", 0),
                "discipline": spec,
                "specialite": spec,
                "heureDepart": _iso_to_ms(c.get("real_heure_course")) or c.get("heure_depart_course"),
                "nombreDeclaresPartants": c.get("nbdeclare_course", 0),
                "quinte": bool(c.get("is_quinte_plus") or c.get("is_quinte_new")),
                "hippodrome": hippo,
                "conditionAge": c.get("categ_course"),
                "_guid": c.get("guid"),
            }
            courses.append(course)

        is_pmh = bool(r.get("is_pmh"))
        converted.append({
            "numero": reunion_num,
            "hippodrome": hippo,
            "typePari": "PMH" if is_pmh else "INTERNET",
            "courses": courses,
            "_provider": "equidia",
            "_country": r.get("pays_site_reunion"),
            "_num_reunion": num_reunion,
            "_is_pmh": is_pmh,
        })

    # Save to cache
    if converted:
        _save_cache(date, converted)
    
    return converted


def fetch_equidia_race(num_reunion, course_num, date):
    """Fetch a single race (partants) from equidia, PMU-like format."""
    url = COURSE_URL.format(date=date, num=num_reunion, cnum=course_num)
    state = _fetch_state(url)
    key = f"v2/courses/{date}/R{num_reunion}/C{course_num}"
    c = state.get(key)
    if not c:
        raise Exception(f"Equidia race not found: {url}")

    reunion = c.get("reunion", {})
    hippo_obj = reunion.get("hippodrome", {}) or {}
    hippo_name = hippo_obj.get("name") or reunion.get("lib_reunion", "Inconnu")

    spec = _map_specialty(c.get("discipline", ""))

    partants = []
    for p in c.get("partants") or []:
        cheval = p.get("cheval", {}) or {}
        monte = p.get("monte", {}) or {}
        entraineur = p.get("entraineur", {}) or {}
        partants.append({
            "numPmu": p.get("num_partant"),
            "nom": cheval.get("nom_cheval", ""),
            "age": p.get("age_cheval") or cheval.get("age_cheval"),
            "sexe": p.get("sexe_cheval") or cheval.get("sexe_cheval"),
            "driver": monte.get("nom_monte", ""),
            "entraineur": entraineur.get("nom_entraineur", ""),
            "musique": p.get("musique") or cheval.get("musique", ""),
            "statut": "PARTANT" if p.get("statut_part") else "NON-PARTANT",
            "deferre": p.get("deferrer_partant", ""),
            "distance": p.get("dist_partant"),
            "dernierRapportDirect": None,
            "proprietaire": "",
        })

    return {
        "numOrdre": course_num,
        "libelle": c.get("libcourt_prix_course") or c.get("liblong_prix_course", ""),
        "distance": c.get("distance", 0),
        "discipline": spec,
        "specialite": spec,
        "heureDepart": _iso_to_ms(c.get("real_heure_course")),
        "nombreDeclaresPartants": c.get("nbdeclare_course", 0),
        "statut": c.get("type_statut_course_id"),
        "typePiste": None,
        "etatTerrain": None,
        "corde": _map_corde(c.get("lib_corde_course", "")),
        "categorieParticularite": c.get("type_course"),
        "hippodrome": {
            "code": hippo_name.upper().replace(" ", "_")[:15],
            "libelleCourt": hippo_name,
            "libelleLong": hippo_name,
        },
        "partants": partants,
        "ordreArrivee": [],
        "_provider": "equidia",
    }
