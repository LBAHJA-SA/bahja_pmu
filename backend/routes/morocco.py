import requests as req
import re
import os
import json
from flask import Blueprint, jsonify, request

CASACOURSES = "https://pro.casacourses.com"
ESOREC_API = "https://e-sorec.ma/api/meetings"
MOROCCO_OFFSET = 100

_session = req.Session()
_session.headers.update({
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
})

# Offline cache directory
CACHE_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "cache")
os.makedirs(CACHE_DIR, exist_ok=True)

def _load_cache(date_str):
    cache_file = os.path.join(CACHE_DIR, f"morocco_v2_{date_str}.json")
    if os.path.exists(cache_file):
        try:
            with open(cache_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except:
            pass
    return None

def _save_cache(date_str, data):
    cache_file = os.path.join(CACHE_DIR, f"morocco_v2_{date_str}.json")
    try:
        with open(cache_file, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False)
    except:
        pass

morocco_bp = Blueprint("morocco", __name__)


def _get(url, timeout=10, tries=3):
    import time as _t
    last_err = None
    for attempt in range(max(1, tries)):
        try:
            r = _session.get(url, timeout=timeout)
            r.raise_for_status()
            return r.json()
        except Exception as e:
            last_err = e
            _t.sleep(2 * (attempt + 1))
    raise last_err


def _parse_int(s):
    return int(re.search(r"\d+", str(s)).group()) if re.search(r"\d+", str(s)) else 0


_STATUS_MAP = {
    "OFFICIAL": "TERMINEE",
    "FINISHED": "TERMINEE",
    "RUNNING": "EN_COURS",
    "STARTING": "DEPART",
    "OPEN": "OUVERTE",
    "CLOSED": "FERMEE",
    "DISABLED": "ANNULEE",
    "STALE": "TERMINEE",
    "SCHEDULED": "PROGRAMMEE",
}

_FAMILY_MAP = {
    "N": "PLAT",
    "PA": "PLAT",
    "PLAT": "PLAT",
    "GALOP": "GALOP",
    "ATTELE": "ATTELE",
    "MONTE": "MONTE",
    "MONTE": "MONTE",
    "TROT": "TROT",
    "OBSTACLE": "OBSTACLE",
    "HAIES": "HAIES",
    "STEEPLECHASE": "STEEPLECHASE",
}

# Country mapping: CasaCourses sometimes mislabels countries
_COUNTRY_MAP = {
    "ES": "AR",  # San Isidro (Argentina) mislabeled as Spain
    "MA": "MA",
    "FR": "FR",
    "GB": "GB",
    "US": "US",
}

# Track-specific overrides for country detection
_TRACK_COUNTRY_OVERRIDES = {
    "san isidro": "AR",  # Argentina
}

_BET_TYPE_MAP = {
    "sorec_simple:gagnant": {"typePari": "SIMPLE_GAGNANT"},
    "sorec_simple:place": {"typePari": "SIMPLE_PLACE"},
    "sorec_jumele:gagnant": {"typePari": "COUPLE_GAGNANT"},
    "sorec_jumele:place": {"typePari": "COUPLE_PLACE"},
    "sorec_jumele:ordre": {"typePari": "JUMELE_ORDRE"},
    "sorec_trio:gagnant": {"typePari": "E_TRIO"},
    "sorec_trio:place": {"typePari": "E_TRIO"},
    "sorec_trio:ordre": {"typePari": "E_TRIO_ORDRE"},
    "sorec_quarte": {"typePari": "E_QUARTE_PLUS"},
    "sorec_quinte": {"typePari": "E_QUINTE_PLUS"},
    "sorec_tierce": {"typePari": "TIERCE"},
}

_PREMIUM_MAP = {
    "Simple Gagnant": "SIMPLE_GAGNANT",
    "Simple Place": "SIMPLE_PLACE",
    "Jumele Gagnant": "COUPLE_GAGNANT",
    "Jumele Place": "COUPLE_PLACE",
    "Jumele Ordre": "JUMELE_ORDRE",
    "Trio": "E_TRIO",
    "Trio Place": "E_TRIO",
    "Trio Ordre": "E_TRIO_ORDRE",
    "Quarte": "E_QUARTE_PLUS",
    "Quarte+": "E_QUARTE_PLUS",
    "Quinte": "E_QUINTE_PLUS",
    "Quinte+": "E_QUINTE_PLUS",
    "Tierce": "TIERCE",
}


def _build_paris(race):
    """Convert casacourses available_bet_types to PMU-style paris array.

    Same convention as programme.py: E_ prefix stripped, deduplicated.
    Also fallback to meeting premium (Quinte+) if race-level bets missing.
    """
    seen = set()
    paris = []
    # 1) direct bet types
    for bt in list(race.get("available_bet_types") or []) + [
            (b.get("code") if isinstance(b, dict) else str(b)) for b in (race.get("bet_types") or [])]:
        mapped = _BET_TYPE_MAP.get(bt) or (_PREMIUM_MAP.get(bt) and {"typePari": _PREMIUM_MAP[bt]})
        # also handle case like 'sorec_quinte_plus' etc
        if not mapped and isinstance(bt, str) and 'quinte' in bt.lower():
            mapped = {"typePari": "E_QUINTE_PLUS"}
        if not mapped and isinstance(bt, str) and 'quarte' in bt.lower():
            mapped = {"typePari": "E_QUARTE_PLUS"}
        if not mapped and isinstance(bt, str) and 'tierce' in bt.lower():
            mapped = {"typePari": "TIERCE"}
        if not mapped:
            continue
        code = str(mapped["typePari"])
        if code.startswith("E_"):
            code = code[2:]
        if code in seen:
            continue
        seen.add(code)
        paris.append({"typePari": code})
    # 2) fallback: if race has no QUINTE but parent meeting premium says Quinte+, keep check at meeting level (handled in fetch_morocco_programme)
    return paris


def _convert_type(t):
    t = (t or "").upper().strip()
    for k, v in _FAMILY_MAP.items():
        if k in t:
            return v
    return t if t else None


def _ts_to_ms(ts):
    """Convert unix seconds to epoch milliseconds (PMU format)."""
    try:
        return int(ts) * 1000
    except (TypeError, ValueError):
        return None


def _detect_country(m):
    """Detect country from CasaCourses meeting data with corrections."""
    track = (m.get("track") or "").lower()
    
    # Check track-specific overrides first
    if track in _TRACK_COUNTRY_OVERRIDES:
        return _TRACK_COUNTRY_OVERRIDES[track]
    
    # Fall back to provided country code with mapping
    cc = m.get("country", "MA")
    return _COUNTRY_MAP.get(cc, cc)


# Track name normalization
_TRACK_NAME_MAP = {
    "san isidro": "San Isidro",
    "settat": "Settat",
    "anfa": "Anfa",
}

# OpenWeather-style icon -> French label (SOREC weather_icon: 02d...)
_WEATHER_LABELS = {
    "01": "Dégagé", "02": "Peu nuageux", "03": "Nuageux", "04": "Très nuageux",
    "09": "Averses", "10": "Pluie", "11": "Orage", "13": "Neige", "50": "Brouillard",
}


def sorec_meteo(icon=None, temp=None):
    """Normalize a SOREC weather_icon/weather_temp pair to meteo object."""
    if temp is None:
        return None
    try:
        code = str(icon or "")[:2]
    except Exception:
        code = ""
    return {"temp": temp, "code": code or None,
            "label": _WEATHER_LABELS.get(code), "vent": None}


def _fetch_esorec_raw(date):
    """Fetch e-sorec.ma meetings for Sorec venue - source officielle du 3e Quinté.
    Fast-fail (4s, no retry): e-sorec is a complement, programme must never
    hang when it is unreachable."""
    try:
        data = _get(f"{ESOREC_API}?date={date}", timeout=4, tries=1)
        if data.get("status")=="SUCCESS" and data.get("content"):
            return data["content"].get("events") or []
        # fallback: try without wrapper
        if isinstance(data, dict) and data.get("events"):
            return data.get("events")
    except Exception as e:
        print(f"[ESOREC] {e}")
    return []

def _convert_esorec_events(events, start_idx):
    converted=[]
    for idx, ev in enumerate(events):
        track = ev.get("track") or ev.get("label") or "Inconnu"
        country = "MA" if "SOREC" in str(ev.get("track","")).upper() or ev.get("track","").lower() in ["khemisset","marrakech","casablanca","rabat","meknes","el jadida"] else ev.get("country") or "MA"
        # e-sorec premium is at event level and race bets level
        reunion_num = MOROCCO_OFFSET + start_idx + idx
        hippo = {"code": track.upper().replace(" ","_")[:15], "libelleCourt": track, "libelleLong": track}
        courses=[]
        for rc in ev.get("races") or []:
            code_str = rc.get("code","C1")
            num_ordre = _parse_int(code_str)
            # build paris from bets array where premium true or code Quinte+
            paris=[]
            for b in rc.get("bets") or []:
                code = b.get("code") or b.get("title") or ""
                is_premium = b.get("premium")
                if "quinte" in code.lower() or (is_premium and "quinte" in code.lower()):
                    paris.append({"typePari":"QUINTE_PLUS"})
                elif "quarte" in code.lower():
                    paris.append({"typePari":"QUARTE_PLUS"})
                elif "tierce" in code.lower():
                    paris.append({"typePari":"TIERCE"})
            # if event premium contains Quinte+ and no race has it, will be handled later
            courses.append({
                "numOrdre": num_ordre,
                "libelle": rc.get("name") or "",
                "distance": rc.get("distance") or 0,
                "discipline": _convert_type(rc.get("type") or ""),
                "specialite": rc.get("type") or "",
                "heureDepart": _ts_to_ms(rc.get("timestamp",0) //1000 if str(rc.get("timestamp","")).__len__()>10 else rc.get("timestamp",0)),
                "nombreDeclaresPartants": rc.get("starters") or 0,
                "statut": _STATUS_MAP.get(rc.get("status",""), rc.get("status","")),
                "hippodrome": hippo,
                "paris": paris,
                "cagnottes": [],
                "_sorecId": rc.get("id"),
            })
        # fallback premium at event level
        _premium = ev.get("premium") or []
        has_q = any(any("QUINTE" in str(p.get("typePari","")) for p in (c.get("paris") or [])) for c in courses)
        if _premium and any("quinte" in str(x).lower() for x in _premium) and not has_q and courses:
            # find race where bets contain Quinte+ premium
            best=None
            for c_raw,c_conv in zip(ev.get("races") or [], courses):
                for b in c_raw.get("bets") or []:
                    if "quinte" in str(b.get("code","")).lower() and b.get("premium"):
                        best=c_conv; break
                if best: break
            if best is None:
                best = courses[0]
            if best is not None and not any(p.get("typePari")=="QUINTE_PLUS" for p in best.get("paris") or []):
                best["paris"].append({"typePari":"QUINTE_PLUS"})
        converted.append({
            "numero": reunion_num,
            "hippodrome": hippo,
            "cagnottes": [],
            "courses": courses,
            "provider": "esorec",
            "country": "MA" if "khemisset" in track.lower() or "marrakech" in track.lower() else country,
            "meteo": None,
            "_sorecReunion": _parse_int(ev.get("code","")),
            "_premium": _premium,
        })
    return converted

def fetch_morocco_programme(date):
    """Fetch SOREC (casacourses + e-sorec) programme, convert all meetings to PMU format."""
    # Cache avec invalidation si premium Quinte+ mais aucun pari QUINTE trouvé (cache stale)
    cached = _load_cache(date)
    if cached:
        has_premium_quinte = False
        has_pari_quinte = False
        try:
            # check raw premium would need live fetch, so just check if cached has at least one QUINTE_PLUS
            for _m in cached:
                for _c in (_m.get("courses") or []):
                    for _p in (_c.get("paris") or []):
                        if "QUINTE" in str(_p.get("typePari","")).upper():
                            has_pari_quinte = True
                            break
        except Exception:
            pass
        # si pas de QUINTE dans cache, on force refresh (évite stale cache qui cache R4 C6 Sagitta Q+)
        if has_pari_quinte:
            return cached
        # sinon on tente refresh live; si échec on retourne cached
    
    try:
        raw = _get(f"{CASACOURSES}/api/programme?date={date}")
    except Exception as e:
        print(f"[OFFLINE] CasaCourses API unavailable for {date}: {e}")
        return []
    
    meetings = raw.get("meetings") or []

    converted = []
    for idx, m in enumerate(meetings):
        track = m.get("track", "Inconnu")
        track_lower = track.lower()
        track = _TRACK_NAME_MAP.get(track_lower, track.title() if track_lower == track else track)
        country = _detect_country(m)
        reunion_num = MOROCCO_OFFSET + idx
        hippo = {
            "code": track.upper().replace(" ", "_")[:15],
            "libelleCourt": track,
            "libelleLong": track,
        }
        courses = []
        for rc in m.get("races") or []:
            race_id = rc.get("id")
            code_str = rc.get("code", "C1")
            num_ordre = _parse_int(code_str)
            course = {
                "numOrdre": num_ordre,
                "libelle": rc.get("name", ""),
                "distance": rc.get("distance", 0),
                "discipline": _convert_type(rc.get("type", "")),
                "specialite": rc.get("type", ""),
                "heureDepart": _ts_to_ms(rc.get("ts", 0)),
                "nombreDeclaresPartants": rc.get("starters", 0),
                "statut": _STATUS_MAP.get(rc.get("status", ""), rc.get("status", "")),
                "hippodrome": hippo,
                "paris": _build_paris(rc),
                "cagnottes": [],
                "_sorecId": race_id,
            }
            courses.append(course)

        # fallback premium: si premium contient Quinte+ mais aucune course n'a QUINTE_PLUS, injecte sur la course avec sorec_quinte ou la plus grosse cagnotte
        _premium = m.get("premium") or []
        has_quinte_in_courses = any(any("QUINTE" in str(p.get("typePari","")) for p in (c.get("paris") or [])) for c in courses)
        if _premium and any("quinte" in str(x).lower() for x in _premium) and not has_quinte_in_courses:
            # cherche course avec sorec_quinte dans raw si disponible, sinon première course avec le plus de partants
            best = None
            for c_raw, c_conv in zip(m.get("races") or [], courses):
                bets_raw = c_raw.get("available_bet_types") or []
                if any("quinte" in str(b).lower() for b in bets_raw):
                    best = c_conv
                    break
            if best is None and courses:
                # fallback: course avec max starters
                best = max(courses, key=lambda x: x.get("nombreDeclaresPartants") or 0)
            if best is not None:
                if not any(p.get("typePari")=="QUINTE_PLUS" for p in (best.get("paris") or [])):
                    best["paris"].append({"typePari": "QUINTE_PLUS"})
        converted.append({
            "numero": reunion_num,
            "hippodrome": hippo,
            "cagnottes": [],
            "courses": courses,
            "provider": m.get("provider", "sorec"),
            "country": country,
            "meteo": sorec_meteo(m.get("weather_icon"), m.get("weather_temp")),
            "_sorecReunion": _parse_int(m.get("reunion_code", "")),
            "_premium": _premium,
        })

    # Complément e-sorec.ma (source officielle du 3e Quinté SOREC) - merge sans doublon
    try:
        esorec_events = _fetch_esorec_raw(date)
        if esorec_events:
            # ne garder que les events avec Quinte+ pour éviter doublons inutiles
            esorec_quinte_events = [e for e in esorec_events if any("quinte" in str(b.get("code","")).lower() or ("premium" in str(b).lower() and "quinte" in str(b.get("code","")).lower()) for r in (e.get("races") or []) for b in (r.get("bets") or [])) or any("quinte" in str(x).lower() for x in (e.get("premium") or []))]
            # si aucun avec Quinte+, on prend tous (au cas où premium mal détecté)
            if not esorec_quinte_events:
                esorec_quinte_events = esorec_events
            esorec_converted = _convert_esorec_events(esorec_quinte_events, len(converted))
            # merge: éviter doublon même hippodrome + même heure
            for em in esorec_converted:
                is_dup=False
                for cm in converted:
                    if cm["hippodrome"]["libelleCourt"].lower()==em["hippodrome"]["libelleCourt"].lower():
                        # même hippodrome -> vérifier si même course Quinte déjà présente
                        cm_quinte = any("QUINTE" in str(p.get("typePari","")) for c in cm["courses"] for p in c["paris"])
                        em_quinte = any("QUINTE" in str(p.get("typePari","")) for c in em["courses"] for p in c["paris"])
                        if cm_quinte and em_quinte:
                            is_dup=True
                            break
                if not is_dup:
                    converted.append(em)
    except Exception as e:
        print(f"[ESOREC merge] {e}")

    # Save to cache
    if converted:
        _save_cache(date, converted)
    
    return converted


def fetch_morocco_race(race_id, date_str):
    """Fetch single race from casacourses, convert to PMU-like format with partants."""
    data = _get(f"{CASACOURSES}/api/race/{race_id}?date={date_str}")

    paris = []
    for div in data.get("dividends") or []:
        bt = div.get("bet_type", "")
        pari_type = bt.replace(" ", "_") if bt else bt
        paris.append({"typePari": pari_type})

    ordre_arrivee = []
    for r in data.get("results") or []:
        pos = r.get("position", 0)
        num = r.get("number", "")
        ordre_arrivee.append([int(num)] if num else [])

    partants = []
    for rn in data.get("runners") or []:
        odd_raw = rn.get("odd") or rn.get("odd_opening")
        if odd_raw is None and rn.get("odd_numeric") is not None:
            odd_raw = rn.get("odd_numeric")
        try:
            odd_val = float(str(odd_raw).replace(",", ".")) if odd_raw else None
        except (TypeError, ValueError):
            odd_val = None
        finish = rn.get("finish_order")
        partant = {
            "numPmu": int(rn.get("number", 0)),
            "nom": rn.get("horse_name", ""),
            "age": rn.get("horse_age"),
            "sexe": rn.get("horse_gender", ""),
            "driver": rn.get("jockey_name", ""),
            "entraineur": rn.get("horse_trainer", ""),
            "musique": rn.get("performance", ""),
            "ordreArrivee": finish if finish else None,
            "statut": "PARTANT" if rn.get("status") else "NON-PARTANT",
            "poids": rn.get("weight"),
            "dernierRapportDirect": {"rapport": odd_val} if odd_val else None,
            "dernierRapportReference": {"rapport": odd_val} if odd_val else None,
            "proprietaire": rn.get("horse_owner", ""),
            "nomSire": rn.get("horse_sire", ""),
            "nomMere": rn.get("horse_dam", ""),
        }
        partants.append(partant)

    result = {
        "numOrdre": _parse_int(data.get("code", "")),
        "libelle": data.get("name", ""),
        "distance": data.get("distance", 0),
        "discipline": _convert_type(data.get("type", "")),
        "specialite": data.get("type", ""),
        "heureDepart": _ts_to_ms(data.get("timestamp", 0)),
        "nombreDeclaresPartants": data.get("runner_count", 0),
        "statut": _STATUS_MAP.get(data.get("status", ""), data.get("status", "")),
        "hippodrome": {
            "code": data.get("track_name", "").upper().replace(" ", "_")[:15],
            "libelleCourt": data.get("track_name", ""),
            "libelleLong": data.get("track_name", ""),
        },
        "paris": paris,
        "cagnottes": [],
        "ordreArrivee": ordre_arrivee if ordre_arrivee else [],
        "partants": partants,
        "_sorecId": race_id,
        "_provider": "sorec",
    }
    return result
