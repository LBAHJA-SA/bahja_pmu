"""pmu_archive.py — daily archiving via PMU API (Geny is rate-limited: 'Trop de requêtes').

Run hours after the last race (Task Scheduler ~06:30) so definitive arrivals
(ordreArrivee) and final cotes are published. Saves via save_geny_race, whose
shadow logic absorbs pre-race skeletons once results land.
"""
import sys
import os
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import requests
from database import save_geny_race, get_db

PMU_BASE = "https://online.turfinfo.api.pmu.fr/rest/client/61"
HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Origin": "https://www.pmu.fr",
    "Referer": "https://www.pmu.fr/",
}
_session = requests.Session()
_session.headers.update(HEADERS)
_SLEEP = 0.7


def _pmu_get(url, timeout=20):
    last = None
    for attempt in range(3):
        try:
            r = _session.get(url, timeout=timeout)
            r.raise_for_status()
            time.sleep(_SLEEP)
            return r.json()
        except Exception as e:
            last = e
            time.sleep(1.5 * (attempt + 1))
    raise Exception(f"PMU API failed: {url} ({last})")


def _dstr(d):
    s = d.isoformat().replace("-", "")
    return s[6:8] + s[4:6] + s[:4]


def _as_text(v):
    if v is None:
        return None
    if isinstance(v, dict):
        return v.get("nom") or v.get("libelle") or v.get("libelleCourt") or None
    return str(v)


def _norm_corde_side(s):
    if not s:
        return s
    u = str(s).upper()
    if "GAUCHE" in u:
        return "G"
    if "DROITE" in u:
        return "D"
    return s


def _arrival_list(course):
    out = []
    for entry in course.get("ordreArrivee") or []:
        try:
            if isinstance(entry, (list, tuple)) and entry:
                out.append(int(entry[0]))
            elif isinstance(entry, int):
                out.append(entry)
            elif isinstance(entry, str) and entry.strip().isdigit():
                out.append(int(entry.strip()))
        except (TypeError, ValueError):
            continue
    return out


def _is_definitive(course):
    if course.get("isArriveeDefinitive") or course.get("rapportsDefinitifsDisponibles"):
        return True
    st = str(course.get("statut") or "")
    return st.startswith("ARRIVEE_DEFINITIVE")


def _build_race_data(date_iso, r_num, hippo_name, c_entry, detail, parts):
    """Map PMU payloads to the save_geny_race format (same keys as archive_save_date)."""
    src = detail or c_entry or {}
    spec = src.get("specialite")
    if not spec:
        for cl in (src.get("specialites") or []):
            if isinstance(cl, dict) and cl.get("code"):
                spec = cl["code"]
                break
    pari_types = []
    for p in (src.get("paris") or []):
        t = p.get("typePari") if isinstance(p, dict) else None
        if not t:
            continue
        pari_types.append(t[2:] if t.startswith("E_") else t)
    pari_types = sorted(set(pari_types))
    pen = src.get("penetrometre")
    if isinstance(pen, dict):
        pen = pen.get("intitule") or pen.get("valeurMesure")
    going = src.get("etatTerrain") or c_entry.get("etatTerrain") if isinstance(c_entry, dict) else src.get("etatTerrain")

    arrival = _arrival_list(src)
    rank_of = {num: i + 1 for i, num in enumerate(arrival)}

    participants = []
    for p in parts or []:
        if not isinstance(p, dict):
            continue
        driver = p.get("driver", "")
        if isinstance(driver, dict):
            driver = driver.get("nom", "")
        trainer = p.get("entraineur", "")
        if isinstance(trainer, dict):
            trainer = trainer.get("nom", "")
        nom = p.get("nom", "") or p.get("nomPmu", "")
        if isinstance(nom, dict):
            nom = nom.get("libelle", "")
        num = p.get("numPmu")
        race_obj = p.get("race")
        if isinstance(race_obj, dict) and not num:
            num = race_obj.get("numPmu")
        cote = None
        rap = p.get("dernierRapportDirect")
        if isinstance(rap, dict):
            cote = rap.get("rapport")
        elif isinstance(rap, (int, float)):
            cote = rap
        gains = p.get("gainsParticipant")
        gain_val = gains.get("gainsCarriere") if isinstance(gains, dict) else None
        statut = p.get("statut")
        is_np = bool(p.get("nonPartant")) or (isinstance(statut, str) and statut != "PARTANT")
        rang = rank_of.get(num) if (not is_np and num is not None) else None
        participants.append({
            "num": num,
            "horse": nom,
            "horse_id": p.get("idCheval"),
            "jockey": driver,
            "trainer": trainer,
            "age": p.get("age"),
            "sexe": p.get("sexe"),
            "gain": gain_val,
            "valeur": p.get("handicapValeur"),
            "poids": p.get("handicapPoids"),
            "corde": p.get("placeCorde"),
            "cote_pmu": cote,
            "cote_geny": None,
            "musique": p.get("musique"),
            "deferre": p.get("deferre", ""),
            "oeilleres": p.get("oeilleres"),
            "proprietaire": _as_text(p.get("proprietaire")) or "",
            "nombreCourses": p.get("nombreCourses"),
            "nombreVictoires": p.get("nombreVictoires"),
            "statut": statut,
            "nonPartant": p.get("nonPartant"),
            "etat": None if (statut in (None, "PARTANT")) else statut,
            "rang": rang,
        })

    return {
        "reunion": {"hippodrome": hippo_name, "num": r_num, "date": date_iso},
        "course": {
            "num": (c_entry or {}).get("numOrdre", 0) if isinstance(c_entry, dict) else 0,
            "time": src.get("heureDepart"),
            "prix": src.get("libelle", ""),
            "specialty": spec,
            "discipline": src.get("discipline"),
            "distance": src.get("distance"),
            "surface": src.get("typePiste"),
            "going": going,
            "corde": _norm_corde_side(src.get("corde")),
            "runners": src.get("nombreDeclaresPartants"),
            "quinte": bool(src.get("quinte")) or ("QUINTE_PLUS" in pari_types),
            "classe": src.get("categorieParticularite"),
            "depart": src.get("depart"),
            "penetrometer": pen,
            "types_pari": pari_types,
            "allocations": None,
            "arrivee": arrival or None,
        },
        "participants": participants,
    }


def archive_date_pmu(target):
    """Archive one full day via PMU. Returns (saved, with_results, skipped_no_arrival)."""
    iso = target.isoformat()
    d = _dstr(target)
    prog = _pmu_get(f"{PMU_BASE}/programme/{d}?meteo=true&specialisation=INTERNET")
    reunions = prog.get("programme", {}).get("reunions", [])
    saved = with_results = skipped = 0
    for r in reunions:
        r_num = r.get("numOfficiel") or r.get("numero", 0) or 0
        try:
            r_num = int(r_num)
        except (TypeError, ValueError):
            continue
        if r_num >= 900:
            continue  # SOREC namespace — handled by the Morocco scraper
        hippo = r.get("hippodrome", {}) or {}
        hippo_name = hippo.get("libelleCourt", hippo.get("libelleLong", "UNKNOWN")) if isinstance(hippo, dict) else str(hippo)
        for c in r.get("courses", []) or []:
            c_num = c.get("numOrdre", 0) or 0
            race_id = f"{iso}_R{r_num}_C{c_num}"
            try:
                try:
                    detail = _pmu_get(f"{PMU_BASE}/programme/{d}/R{r_num}/C{c_num}")
                except Exception:
                    detail = None
                parts = []
                try:
                    pj = _pmu_get(f"{PMU_BASE}/programme/{d}/R{r_num}/C{c_num}/participants?specialisation=INTERNET")
                    parts = pj.get("participants", []) or []
                except Exception:
                    pass
                data = _build_race_data(iso, r_num, hippo_name, c, detail, parts)
                has_res = bool(data["course"]["arrivee"]) and len(data["course"]["arrivee"]) >= 3
                save_geny_race(race_id, data)
                saved += 1
                if has_res:
                    with_results += 1
                else:
                    skipped += 1
                if has_res:
                    print(f"  saved {race_id} {hippo_name} arr={data['course']['arrivee'][:5]}")
            except Exception as e:
                print(f"  error {race_id}: {e}")
    return saved, with_results, skipped


def update_missing_results_pmu(days_back=7):
    """Re-fetch races lacking any ranked participant (recent days)."""
    from datetime import date as _date
    cutoff = (_date.today() - timedelta(days=days_back)).isoformat()
    today = _date.today().isoformat()
    conn = get_db()
    rows = conn.execute(
        "SELECT race_id, date FROM races WHERE date >= ? AND date < ?", (cutoff, today)).fetchall()
    ids = [(r["race_id"], r["date"]) for r in rows]
    conn.close()
    conn = get_db()
    todo = []
    for rid, rdate in ids:
        try:
            n = conn.execute(
                "SELECT COUNT(*) c FROM participants WHERE race_id=? AND rang IS NOT NULL",
                (rid,)).fetchone()["c"]
        except Exception:
            n = 0
        if not n:
            todo.append((rid, rdate))
    conn.close()
    print(f"[Update] {len(todo)} races without results (last {days_back}d)")
    fixed = 0
    for rid, rdate in todo:
        try:
            parts = str(rid).split("_")
            r_num = int([x[1:] for x in parts if x.startswith("R")][0])
            c_num = int([x[1:] for x in parts if x.startswith("C")][0])
        except (IndexError, ValueError):
            continue  # Geny numeric ids — handled by the legacy pass
        try:
            d = _dstr(__import__("datetime").date.fromisoformat(rdate))
            detail = _pmu_get(f"{PMU_BASE}/programme/{d}/R{r_num}/C{c_num}")
            arr = _arrival_list(detail or {})
            if len(arr) < 3:
                continue
            pj = _pmu_get(f"{PMU_BASE}/programme/{d}/R{r_num}/C{c_num}/participants?specialisation=INTERNET")
            hippo = (detail.get("hippodrome", {}) or {}).get("libelleCourt", "UNKNOWN")
            data = _build_race_data(rdate, r_num, hippo, None, detail, pj.get("participants", []))
            save_geny_race(rid, data)
            fixed += 1
            print(f"  updated {rid}")
        except Exception as e:
            print(f"  error {rid}: {e}")
    return fixed


def reverify_recent(days_back=3):
    """Enquête/déclassement guard: last N days' stored Top5 vs fresh official arrival."""
    from datetime import date as _date
    cutoff = (_date.today() - timedelta(days=days_back)).isoformat()
    conn = get_db()
    rows = conn.execute("SELECT race_id, date FROM races WHERE date >= ?", (cutoff,)).fetchall()
    conn.close()
    fixed = 0
    for r in rows:
        rid, rdate = r["race_id"], r["date"]
        try:
            parts = str(rid).split("_")
            r_num = int([x[1:] for x in parts if x.startswith("R")][0])
            c_num = int([x[1:] for x in parts if x.startswith("C")][0])
            d = _dstr(__import__("datetime").date.fromisoformat(rdate))
            detail = _pmu_get(f"{PMU_BASE}/programme/{d}/R{r_num}/C{c_num}")
            arr = _arrival_list(detail or {})
            if len(arr) < 5:
                continue
            conn2 = get_db()
            stored = conn2.execute(
                "SELECT num FROM participants WHERE race_id=? AND rang BETWEEN 1 AND 5 ORDER BY rang",
                (rid,)).fetchall()
            conn2.close()
            if [x["num"] for x in stored][:5] != arr[:5]:
                pj = _pmu_get(f"{PMU_BASE}/programme/{d}/R{r_num}/C{c_num}/participants?specialisation=INTERNET")
                hippo = (detail.get("hippodrome", {}) or {}).get("libelleCourt", "UNKNOWN")
                data = _build_race_data(rdate, r_num, hippo, None, detail, pj.get("participants", []))
                save_geny_race(rid, data)
                fixed += 1
                print(f"  corrected {rid}: {[x['num'] for x in stored][:5]} -> {arr[:5]}")
        except Exception as e:
            print(f"  error {rid}: {e}")
    return fixed


if __name__ == "__main__":
    import datetime as _dt
    target = date.today() - timedelta(days=1)
    if len(sys.argv) > 1:
        try:
            target = _dt.datetime.strptime(sys.argv[1], "%Y-%m-%d").date()
        except ValueError:
            pass
    print(f"[PMU Archive] {target.isoformat()} ...")
    s, wr, sk = archive_date_pmu(target)
    print(f"Done: saved={s} with_results={wr} no_arrival_yet={sk}")
    try:
        print(f"Missing-results pass: fixed={update_missing_results_pmu(7)}")
    except Exception as e:
        print(f"[Update] error: {e}")
    try:
        print(f"Enquête re-verify: corrected={reverify_recent(3)}")
    except Exception as e:
        print(f"[Reverify] error: {e}")
