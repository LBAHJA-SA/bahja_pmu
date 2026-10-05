import requests
import re
import json
from datetime import date, timedelta


class GenyScraper:
    BASE_URL = "https://www.geny.com"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        })
        self._cache = {}
        self._cache_ttl = 120

    def _extract_data(self, html):
        push_pattern = r"self\.__next_f\.push\(\[1,\s*\"(.*?)\"\]\)"
        for m in re.finditer(push_pattern, html, re.DOTALL):
            raw = m.group(1)
            unescaped = raw.encode("raw_unicode_escape").decode("unicode_escape")
            idx = unescaped.find('"mutations":[],"queries"')
            if idx >= 0:
                search_from = max(0, idx - 20)
                brace_idx = unescaped.rfind("{", search_from, idx)
                if brace_idx >= 0:
                    depth = 0
                    in_string = False
                    escape = False
                    for j in range(brace_idx, len(unescaped)):
                        ch = unescaped[j]
                        if escape:
                            escape = False
                            continue
                        if ch == "\\" and in_string:
                            escape = True
                            continue
                        if ch == '"':
                            in_string = not in_string
                            continue
                        if not in_string:
                            if ch == "{":
                                depth += 1
                            elif ch == "}":
                                depth -= 1
                                if depth == 0:
                                    try:
                                        wrapper = json.loads(unescaped[brace_idx:j + 1])
                                        state = wrapper.get("state", wrapper)
                                        for q in state.get("queries", []):
                                            data = q.get("state", {}).get("data")
                                            if data:
                                                return data
                                    except json.JSONDecodeError:
                                        pass
                                    return None
        return None

    def _cache_get(self, key):
        import time
        entry = self._cache.get(key)
        if entry and time.time() - entry["ts"] < self._cache_ttl:
            return entry["data"]
        return None

    def _cache_set(self, key, data):
        import time
        self._cache[key] = {"data": data, "ts": time.time()}

    def fetch_programme(self, target_date=None):
        if target_date is None:
            target_date = date.today()
        cache_key = ("programme", target_date.isoformat())
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        url = f"{self.BASE_URL}/programme/{target_date.isoformat()}"
        resp = self.session.get(url, timeout=15)
        resp.encoding = "utf-8"
        data = self._extract_data(resp.text)
        if data is None:
            result = {"date": target_date.isoformat(), "meetings": []}
        else:
            result = self._transform_programme(data, target_date)
        self._cache_set(cache_key, result)
        return result

    def _transform_programme(self, data, target_date):
        meetings = []
        for item in data:
            r = item.get("reunion", {})
            raw_courses = item.get("courseInfos", [])
            courses = raw_courses if isinstance(raw_courses, list) else []
            meeting = {
                "num": r.get("numeroPmu"),
                "hippodrome": r.get("nomReunion", ""),
                "organizer": r.get("organisateurPari", "PMU"),
                "start_time": r.get("debutOperations", ""),
                "status": r.get("etatReunion", ""),
                "courses": []
            }
            for c in courses:
                meeting["courses"].append({
                    "num": c.get("numeroCourse"),
                    "time": c.get("heureCourse", ""),
                    "prix": c.get("nomPrix", ""),
                    "specialty": c.get("specialite", ""),
                    "discipline": c.get("discipline", ""),
                    "distance": c.get("distance"),
                    "surface": c.get("revetement", ""),
                    "going": c.get("typeEtatTerrain", ""),
                    "runners": c.get("nombrePartants"),
                    "classe": c.get("classe", ""),
                    "quinte": c.get("quintePlus", False),
                    "condition": c.get("conditionDeLaCourse", ""),
                    "corde": c.get("corde", ""),
                    "penetrometer": c.get("penetrometre"),
                    "id": c.get("id")
                })
            meetings.append(meeting)

        meetings.sort(key=lambda m: m["num"])
        return {"date": target_date.isoformat(), "meetings": meetings}

    def _extract_queries(self, html):
        """Extract all queries from RSC payload."""
        push_pattern = r"self\.__next_f\.push\(\[1,\s*\"(.*?)\"\]\)"
        for m in re.finditer(push_pattern, html, re.DOTALL):
            raw = m.group(1)
            unescaped = raw.encode("raw_unicode_escape").decode("unicode_escape")
            idx = unescaped.find('"mutations":[],"queries"')
            if idx >= 0:
                search_from = max(0, idx - 50)
                brace_idx = unescaped.rfind("{", search_from, idx)
                if brace_idx >= 0:
                    depth = 0
                    in_string = False
                    escape = False
                    for j in range(brace_idx, len(unescaped)):
                        ch = unescaped[j]
                        if escape:
                            escape = False
                            continue
                        if ch == "\\" and in_string:
                            escape = True
                            continue
                        if ch == '"':
                            in_string = not in_string
                            continue
                        if not in_string:
                            if ch == "{":
                                depth += 1
                            elif ch == "}":
                                depth -= 1
                                if depth == 0:
                                    try:
                                        wrapper = json.loads(unescaped[brace_idx:j + 1])
                                        state = wrapper.get("state", wrapper)
                                        return state.get("queries", [])
                                    except json.JSONDecodeError:
                                        pass
                                    return []
        return []

    def fetch_race_details(self, race_id):
        cache_key = ("race", race_id)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        url = f"{self.BASE_URL}/course/{race_id}/partants-pronostics"
        resp = self.session.get(url, timeout=15)
        resp.encoding = "utf-8"
        data = self._extract_data(resp.text)
        if data is None:
            self._cache_set(cache_key, None)
            return None
        result = self._transform_race(data)
        # Extract pronostics from Query 2
        all_queries = self._extract_queries(resp.text)
        if len(all_queries) > 2:
            q2 = all_queries[2].get("state", {}).get("data")
            if q2:
                result["pronostics"] = q2
        self._cache_set(cache_key, result)
        return result

    @staticmethod
    def _parse_ref(condition):
        """استخراج REF من نص condition: Réf. +250 -> 25.0, Ref : +17.5 -> 17.5"""
        if not condition:
            return None
        txt = str(condition).replace('�','e')
        m = re.search(r"r[eé]f[^0-9]*\+\s*(\d+(?:[.,]\d+)?)", txt, re.I)
        if not m:
            return None
        try:
            raw = m.group(1).replace(",", ".")
            v = float(raw)
            # حماية: إذا كان >= 50 نفترض أنه بالعشرات (250 -> 25.0)
            # المواصفة أمثلة 17.5 / 18 / 20 -> الخام 175 / 180 / 200
            if v >= 100:
                v = v / 10.0
            if not (5 <= v <= 50):
                return None
            return round(v, 2)
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _parse_refs(condition):
        """يعيد (ref, ref2, ref_text) — ref للـ 3 ans، ref2 للـ 4 ans+"""
        if not condition:
            return (None, None, None)
        txt2 = str(condition).replace('�','e')
        import re as _re
        m = _re.search(r"r[eé]f", txt2, _re.I)
        if not m:
            return (None, None, None)
        sub = txt2[m.start(): m.start()+80]
        nums = _re.findall(r"\+\s*(\d+(?:[.,]\d+)?)", sub)
        vals = []
        for raw in nums:
            try:
                v = float(raw.replace(",","."))
                if v >= 100:
                    v = v / 10.0
                if 5 <= v <= 50:
                    vals.append(round(v,2))
            except:
                pass
        if not vals:
            return (None, None, None)
        if len(vals) == 1:
            return (vals[0], None, str(vals[0]))
        return (vals[0], vals[1], f"{vals[0]},{vals[1]}")

    def _transform_race(self, data):
        course = data.get("course", {})
        reunion = {k: v for k, v in data.items() if k != "course"}
        participants = []
        for p in course.get("participants", []):
            cheval = p.get("cheval", {})
            jockey = p.get("jockey") or {}
            entraineur = p.get("entraineur") or {}
            participants.append({
                "num": p.get("numero"),
                "horse": cheval.get("nom"),
                "horse_id": cheval.get("id"),
                "jockey": f"{jockey.get('prenom', '')} {jockey.get('nom', '')}".strip(),
                "trainer": f"{entraineur.get('prenom', '')} {entraineur.get('nom', '')}".strip(),
                "age": p.get("age"),
                "sexe": p.get("sexe"),
                "gain": p.get("gain"),
                "poids": p.get("poids"),
                "decharge": p.get("decharge"),
                "corde": p.get("positionDepart"),
                "valeur": p.get("valeurHandicap"),
                "deferre": p.get("deferre"),
                "oeilleres": p.get("oeilleres"),
                "bonnet": p.get("bonnet"),
                "attache_langue": p.get("attacheLangue"),
                "premiere_fois_deferre": p.get("premiereFoisDeferre"),
                "premiere_fois_oeilleres": p.get("premiereFoisOeilleres"),
                "premiere_fois_bonnet": p.get("premiereFoisBonnet"),
                "premiere_fois_attache_langue": p.get("premiereFoisAttacheLangue"),
                "cote_pmu": p.get("cotePmu"),
                "cote_geny": p.get("coteGeny"),
                "musique": p.get("musique", {}).get("resume") if p.get("musique") else None,
                "note": p.get("noteFinDeCourse"),
                "red_km": p.get("redKm"),
                "distance": p.get("distance"),
                "rang": p.get("rang"),
                "ecart": p.get("ecartArrivee"),
                "proprietaire": p.get("proprietaire", {}).get("nom") if p.get("proprietaire") else None,
                "casaque": p.get("casaque"),
                "etat": p.get("etatParticipation"),
                "incident": p.get("incident")
            })

        return {
            "reunion": {
                "num": reunion.get("numeroPmu"),
                "hippodrome": reunion.get("nomReunion"),
                "organizer": reunion.get("organisateurPari"),
                "date": reunion.get("dateReunion")
            },
            "course": {
                "id": course.get("id"),
                "num": course.get("numeroCourse"),
                "prix": course.get("nomPrix"),
                "time": course.get("heureCourse"),
                "specialty": course.get("specialite"),
                "discipline": course.get("discipline"),
                "distance": course.get("distance"),
                "surface": course.get("revetement"),
                "going": course.get("typeEtatTerrain"),
                "corde": course.get("corde"),
                "runners": course.get("nombrePartants"),
                "quinte": course.get("quintePlus", False),
                "condition": course.get("conditionDeLaCourse"),
                "classe": course.get("classe"),
                "depart": course.get("depart"),
                "penetrometer": course.get("penetrometre"),
                "types_pari": course.get("typesPari", []),
                "arrivee": course.get("arrivee"),
                "allocations": course.get("allocations"),
                "ref": self._parse_refs(course.get("conditionDeLaCourse"))[0],
                "ref2": self._parse_refs(course.get("conditionDeLaCourse"))[1],
                "ref_text": self._parse_refs(course.get("conditionDeLaCourse"))[2],
            },
            "participants": participants
        }

    def fetch_race_rapports(self, race_id):
        cache_key = ("rapports", race_id)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        url = f"{self.BASE_URL}/course/{race_id}/arrivee-rapports"
        resp = self.session.get(url, timeout=15)
        resp.encoding = "utf-8"
        data = self._extract_data(resp.text)
        if data is None:
            self._cache_set(cache_key, None)
            return None

        course = data.get("course", {})
        reunion = {k: v for k, v in data.items() if k != "course"}

        participants = []
        for p in course.get("participants", []):
            cheval = p.get("cheval", {})
            jockey = p.get("jockey") or {}
            entraineur = p.get("entraineur") or {}
            participants.append({
                "num": p.get("numero"),
                "horse": cheval.get("nom"),
                "horse_id": cheval.get("id"),
                "jockey": f"{jockey.get('prenom', '')} {jockey.get('nom', '')}".strip(),
                "trainer": f"{entraineur.get('prenom', '')} {entraineur.get('nom', '')}".strip(),
                "age": p.get("age"),
                "sexe": p.get("sexe"),
                "deferre": p.get("deferre"),
                "red_km": p.get("redKm"),
                "distance": p.get("distance"),
                "rang": p.get("rang"),
                "ecart": p.get("ecartArrivee"),
                "cote_pmu": p.get("cotePmu"),
                "cote_geny": p.get("coteGeny"),
                "etat": p.get("etatParticipation"),
                "incident": p.get("incident")
            })

        # Extract rapports from the second query (rates data)
        rapports_data = None
        raw = resp.text
        push_pattern = r"self\.__next_f\.push\(\[1,\s*\"(.*?)\"\]\)"
        for m in re.finditer(push_pattern, raw, re.DOTALL):
            unescaped = m.group(1).encode("raw_unicode_escape").decode("unicode_escape")
            idx = unescaped.find('"queries"')
            if idx < 0:
                continue
            search_from = max(0, idx - 50)
            brace_idx = unescaped.rfind("{", search_from, idx)
            if brace_idx < 0:
                continue
            depth = 0
            in_string = False
            escape = False
            for j in range(brace_idx, len(unescaped)):
                ch = unescaped[j]
                if escape:
                    escape = False
                    continue
                if ch == "\\" and in_string:
                    escape = True
                    continue
                if ch == '"':
                    in_string = not in_string
                    continue
                if not in_string:
                    if ch == "{":
                        depth += 1
                    elif ch == "}":
                        depth -= 1
                        if depth == 0:
                            try:
                                wrapper = json.loads(unescaped[brace_idx:j + 1])
                                state = wrapper.get("state", wrapper)
                                queries = state.get("queries", [])
                                # Query 1 has rates/rapports data
                                if len(queries) > 1:
                                    q1 = queries[1].get("state", {}).get("data")
                                    if q1 and isinstance(q1, dict):
                                        rapports_data = q1
                            except (json.JSONDecodeError, IndexError):
                                pass
                            break

        result = {
            "reunion": {
                "num": reunion.get("numeroPmu"),
                "hippodrome": reunion.get("nomReunion"),
                "organizer": reunion.get("organisateurPari"),
                "date": reunion.get("dateReunion")
            },
            "course": {
                "id": course.get("id"),
                "num": course.get("numeroCourse"),
                "prix": course.get("nomPrix"),
                "time": course.get("heureCourse"),
                "specialty": course.get("specialite"),
                "discipline": course.get("discipline"),
                "distance": course.get("distance"),
                "surface": course.get("revetement"),
                "going": course.get("typeEtatTerrain"),
                "corde": course.get("corde"),
                "runners": course.get("nombrePartants"),
                "quinte": course.get("quintePlus", False),
                "condition": course.get("conditionDeLaCourse"),
                "classe": course.get("classe"),
                "depart": course.get("depart"),
                "penetrometer": course.get("penetrometre"),
                "types_pari": course.get("typesPari", []),
                "arrivee": course.get("arrivee"),
                "allocations": course.get("allocations"),
                "etat": course.get("etatCourse")
            },
            "participants": participants,
            "rapports": rapports_data
        }
        self._cache_set(cache_key, result)
        return result

    def fetch_race_cotes(self, race_id):
        cache_key = ("cotes", race_id)
        cached = self._cache_get(cache_key)
        if cached is not None:
            return cached
        url = f"{self.BASE_URL}/course/{race_id}/cotes"
        resp = self.session.get(url, timeout=15)
        resp.encoding = "utf-8"
        data = self._extract_data(resp.text)
        if data is None:
            self._cache_set(cache_key, None)
            return None
        self._cache_set(cache_key, data)
        return data


_shared_scraper = None


def get_scraper():
    global _shared_scraper
    if _shared_scraper is None:
        _shared_scraper = GenyScraper()
    return _shared_scraper
