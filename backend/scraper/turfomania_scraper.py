import requests
import re
import time
import random
from datetime import datetime


class TurfomaniaScraper:
    BASE = "https://www.turfomania.fr"
    HDRS = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        )
    }

    MONTHS_FR = {
        "janvier": "01", "fevrier": "02", "mars": "03", "avril": "04",
        "mai": "05", "juin": "06", "juillet": "07", "aout": "08",
        "septembre": "09", "octobre": "10", "novembre": "11", "decembre": "12",
    }

    def __init__(self, delay=(1.2, 2.4), session=None, min_len=50000):
        self.delay = delay
        self.min_len = min_len
        self.session = session or requests.Session()
        self.session.headers.update(self.HDRS)
        self._last = 0.0
        self.request_count = 0
        self._break_every = 25
        self._break_dur = (4.0, 8.0)

    def _wait(self):
        """Human-like random delay between requests."""
        if isinstance(self.delay, (tuple, list)):
            base = random.uniform(self.delay[0], self.delay[1])
        else:
            base = self.delay
        # add 20% jitter
        base *= random.uniform(0.9, 1.2)
        self.request_count += 1
        if self.request_count % self._break_every == 0:
            base += random.uniform(self._break_dur[0], self._break_dur[1])
        elapsed = time.time() - self._last
        if elapsed < base:
            time.sleep(base - elapsed)

    def _get(self, url, retries=3):
        for attempt in range(retries):
            self._wait()
            try:
                r = self.session.get(url, timeout=25)
                self._last = time.time()
                r.encoding = "utf-8"
                if r.status_code == 200 and len(r.text) > self.min_len:
                    return r.text
            except Exception:
                pass
            time.sleep(random.uniform(2.0, 5.0) + attempt * 2)
        return None

    @staticmethod
    def _strip(html):
        if hasattr(html, "group"):
            html = html.group(1)
        text = re.sub(r"<[^>]+>", " ", html or "")
        return re.sub(r"\s+", " ", text).strip()

    def _parse_date(self, label):
        # "Mercredi 12 Aout 2020" -> "2020-08-12"
        m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})", label, re.I)
        if not m:
            return None
        day, month, year = m.group(1), self.MONTHS_FR.get(m.group(2).lower()), m.group(3)
        if not month:
            return None
        return f"{year}-{month}-{int(day):02d}"

    def _parse_time(self, s):
        m = re.search(r"(\d{1,2})h(\d{2})", s)
        return f"{int(m.group(1)):02d}:{m.group(2)}" if m else None

    def fetch_programme(self, date_str):
        # date_str: "YYYY-MM-DD"
        d = datetime.strptime(date_str, "%Y-%m-%d")
        url = f"{self.BASE}/partants-programmes/index.php?choixtype=1&choixdate={d.day:02d}/{d.month:02d}/{d.year}"
        html = self._get(url)
        if html is None:
            return []
        reunions = []
        for row in re.findall(r"<tr[^>]*>(.*?)</tr>", html, re.DOTALL):
            m = re.search(r"idreunion=(\d+)", row)
            if not m:
                continue
            rid = m.group(1)
            jour = self._strip(re.search(r'colJour[^>]*><a[^>]*>(.*?)</a>', row))
            reunion_num = re.search(r'rLong">(.*?)</span>', row)
            rnum_txt = self._strip(reunion_num.group(1)) if reunion_num else ""
            rnum = int(re.search(r"(\d+)", rnum_txt).group(1)) if re.search(r"(\d+)", rnum_txt) else None
            hippo = self._strip(re.search(r'colHippo[^>]*><a[^>]*>(.*?)</a>', row))
            heure = self._strip(re.search(r'colHeure[^>]*>(.*?)</td>', row))
            courses = self._strip(re.search(r'colCourses[^>]*>(.*?)</td>', row))
            n_courses = int(re.search(r"(\d+)", courses).group(1)) if re.search(r"(\d+)", courses) else 0
            quinte = bool(re.search(r"rapportsPictoPMUQuinte", row))
            specs = [s for s in dict.fromkeys(re.findall(r"picto-([a-z]+)", row))]
            reunions.append({
                "idreunion": rid,
                "date": self._parse_date(jour) or date_str,
                "jour_label": jour,
                "reunion_num": rnum,
                "hippodrome": hippo,
                "heure": heure,
                "n_courses": n_courses,
                "quinte": quinte,
                "specs": specs,
            })
        return reunions

    def fetch_reunion(self, idreunion):
        url = f"{self.BASE}/partants-programmes/detail-reunion.php?idreunion={idreunion}&choixtype=1"
        html = self._get(url)
        if html is None:
            return []
        # h1: "ENGHIEN SOISY - R�union 1 - Mercredi 12 Aout 2020"
        h1 = self._strip(re.search(r"<h1[^>]*>(.*?)</h1>", html, re.DOTALL))
        # course ids in order of partants links
        idcourses = []
        slugs = {}
        for m in re.finditer(r'href="(/pronostics/partants-([^"/]*)\.html\?idcourse=(\d+)[^"]*)"', html):
            cid = m.group(3)
            if cid not in idcourses:
                idcourses.append(cid)
            if cid not in slugs:
                slugs[cid] = m.group(2)
        # course blocks with description
        blocks = []
        tb = re.search(r'id="tableauId"(.*?)</table>', html, re.DOTALL)
        if tb:
            for row in re.findall(r"<tr[^>]*class=\"(?:trOne|trTwo)[^\"]*\"[^>]*>(.*?)</tr>", tb.group(1), re.DOTALL):
                txt = re.sub(r"<[^>]+>", " ", row)
                txt = re.sub(r"\s+", " ", txt).strip()
                m2 = re.search(r"Course (\d+)", txt)
                if m2:
                    blocks.append((int(m2.group(1)), txt))
        courses = []
        for i, cid in enumerate(idcourses, start=1):
            desc = ""
            for cnum, txt in blocks:
                if cnum == i:
                    desc = txt
                    break
            # price name: find PRIX ... in desc
            pm = re.search(r"PRIX[^<]{3,80}", desc)
            prix = self._strip(pm.group(0)) if pm else None
            if prix:
                # "PRIX DU PONT DE L'ALMA 1 44.000 Euros - ..." -> name up to number / Euros
                m2 = re.match(r"^(PRIX[^0-9]+)", prix)
                if m2:
                    nm = m2.group(1).strip()
                    # legacy archive style keeps trailing spaces; trim them
                    prix = re.sub(r"\s+", " ", nm).strip()
            # distance: "2.150 mètres" (é may be mojibake) / "2150 mètres" etc.
            dm = re.search(r"([\d][\d\s\.\u00a0]*)\s*m.{0,3}tres", desc)
            distance = None
            if dm:
                dist = re.sub(r"[\s.\u00a0]", "", dm.group(1))
                try:
                    distance = int(dist)
                except ValueError:
                    distance = None
            # discipline from text
            discipline = None
            for d in ["Attel", "Galop", "Steeple", "Haies", "Cross"]:
                if d.lower() in desc.lower():
                    discipline = d
                    break
            # time
            tm = re.search(r"(\d{1,2})h(\d{2})", desc)
            ctime = f"{int(tm.group(1)):02d}:{tm.group(2)}" if tm else None
            courses.append({
                "idcourse": cid,
                "course_num": i,
                "prix": prix,
                "distance": distance,
                "discipline": discipline,
                "time": ctime,
                "slug": slugs.get(cid),
                "desc": desc,
            })
        return {"h1": h1, "idcourses": idcourses, "courses": courses}

    def fetch_partants(self, idcourse, slug=None):
        url = f"{self.BASE}/pronostics/partants-{slug}.html?idcourse={idcourse}"
        html = self._get(url)
        if html is None:
            return None
        return self._parse_partants(html)

    def _parse_partants(self, html):
        tb = re.search(r"<table[^>]*>(.*?)</table>", html, re.DOTALL)
        if not tb:
            return None
        # detect header type: 'Dist.' => attel, 'Poids' => galop
        th = re.search(r"<thead>(.*?)</thead>", tb.group(1), re.DOTALL)
        hdr_txt = self._strip(th.group(1)) if th else ""
        is_attel = "Dist." in hdr_txt or "Dist" in hdr_txt
        participants = []
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tb.group(1), re.DOTALL)
        for row in rows[1:]:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if not cells:
                continue
            # num
            nm = re.search(r"<span class='num'>(\d+)</span>", cells[0])
            num = int(nm.group(1)) if nm else None
            # cheval
            cm = re.search(r'/cheval/[^"]*"[^>]*title="Cheval : ([^:]+) : (\d+)"', cells[1])
            horse = cm.group(1).strip() if cm else None
            horse_id = cm.group(2) if cm else None
            # musique after <br>
            brm = re.search(r"<br\s*/>(.*?)$", cells[1], re.DOTALL)
            musique = self._strip(brm.group(1)) if brm else None
            # weight / distance
            if is_attel:
                # ATTEL: [0]N [1]Cheval [2]Dist [3]Def [4]S/A [5]Driver+T [6]smile [7]Record [8]Gain [9]Cote [10]PMU-Play(opt)
                n = len(cells)
                cote = self._parse_float(cells[n - 2]) if n >= 9 else None
                gain = self._clean_gain(cells[n - 3]) if n >= 9 else None
                record = self._strip(cells[n - 4]) if n >= 9 else None
                jockey, trainer = self._parse_jockey(cells[5]) if n >= 6 else (None, None)
                sa = self._strip(cells[4]) if n >= 5 else None
                deferre = self._strip(cells[3]) if n >= 4 else None
                dist = self._strip(cells[2]) if n >= 3 else None
                try:
                    dist = int(dist)
                except (TypeError, ValueError):
                    dist = None
                oeilleres = None
                poids = None
                decharge = None
                corde = None
                age = self._age_from_sa(sa)
                sexe = self._sexe_from_sa(sa)
            else:
                # GALOP: [0]N [1]Cheval [2]Poids [3]Déch [4]Corde [5]S/A [6]Jockey+T [7]smile [8]Gain [9]Oe [10]Cote [11]PMU-Play(opt)
                # use end-anchored indices for robustness
                n = len(cells)
                cote = self._parse_float(cells[n - 2]) if n >= 10 else None
                oeilleres = self._strip(cells[n - 3]) if n >= 10 else None
                gain = self._clean_gain(cells[n - 4]) if n >= 10 else None
                poids = self._parse_float(cells[2]) if n >= 6 else None
                decharge = None
                if n >= 7:
                    dc = self._strip(cells[3])
                    if dc not in ("-", "", None):
                        decharge = self._parse_float(cells[3])
                corde = None
                if n >= 7:
                    ctxt = self._strip(cells[4])
                    try:
                        corde = int(ctxt)
                    except (TypeError, ValueError):
                        corde = None
                sa = self._strip(cells[5]) if n >= 6 else None
                jockey, trainer = self._parse_jockey(cells[6]) if n >= 7 else (None, None)
                age = self._age_from_sa(sa)
                sexe = self._sexe_from_sa(sa)
                dist = None
                deferre = None
                record = None
            participants.append({
                "num": num,
                "horse": horse,
                "horse_id": horse_id,
                "jockey": jockey,
                "trainer": trainer,
                "age": age,
                "sexe": sexe,
                "gain": gain,
                "poids": poids,
                "decharge": decharge,
                "corde": corde,
                "deferre": deferre,
                "oeilleres": oeilleres,
                "cote_pmu": cote,
                "musique": musique,
                "distance": dist,
                "record": record,
            })
        return participants

    @staticmethod
    def _parse_jockey(cell):
        links = re.findall(r">([A-Z][^<]{1,60})</a>", cell or "")
        # The jockey and trainer names appear in <a> tags
        jockey = trainer = None
        if links:
            jockey = links[0].strip()
        if len(links) > 1:
            trainer = links[1].strip()
        return jockey, trainer

    @staticmethod
    def _clean_gain(cell):
        m = re.search(r"data-text=\"(\d+)\"", cell or "")
        if m:
            return int(m.group(1))
        txt = TurfomaniaScraper._strip(cell)
        txt = txt.replace("\u00a0", "").replace(" ", "").replace("\u20ac", "")
        try:
            return int(txt)
        except ValueError:
            return None

    @staticmethod
    def _parse_float(cell):
        txt = TurfomaniaScraper._strip(cell)
        txt = txt.replace(",", ".").replace("\u00a0", "").replace(" ", "").replace("\u20ac", "")
        try:
            f = float(txt)
            if f == int(f):
                return int(f)
            return f
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _age_from_sa(sa):
        m = re.search(r"([MF])?\s*(\d{1,2})$", sa or "")
        if m:
            try:
                return int(m.group(2))
            except ValueError:
                return None
        return None

    @staticmethod
    def _sexe_from_sa(sa):
        if not sa:
            return None
        if "H" in sa or "M" in sa.upper():
            return "M"
        if "F" in sa.upper():
            return "F"
        return None

    def fetch_rapports(self, idcourse, slug=None):
        url = f"{self.BASE}/pronostics/rapports-{slug}.html?idcourse={idcourse}"
        html = self._get(url)
        if html is None:
            return None
        tb = re.search(r"<table[^>]*>(.*?)</table>", html, re.DOTALL)
        if not tb:
            return None
        rows = re.findall(r"<tr[^>]*>(.*?)</tr>", tb.group(1), re.DOTALL)
        results = []
        for row in rows[1:]:
            cells = re.findall(r"<td[^>]*>(.*?)</td>", row, re.DOTALL)
            if len(cells) < 7:
                continue
            rg = self._strip(cells[0])
            try:
                rg = int(rg)
            except (TypeError, ValueError):
                continue
            num = self._strip(cells[1])
            try:
                num = int(num)
            except (TypeError, ValueError):
                continue
            horse = self._strip(cells[2])
            jockey = self._strip(cells[3])
            trainer = self._strip(cells[4])
            cote = self._parse_float(cells[5])
            results.append({
                "rang": rg,
                "num": num,
                "horse": horse,
                "jockey": jockey,
                "trainer": trainer,
                "cote": cote,
            })
        return results
