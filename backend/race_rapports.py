"""Race payouts (rapports PMU-internet via Turfomania) for ROI accounting.

Stored per (date, reunion, course) so re-logged races reuse them.
Best-effort everywhere: missing mapping or page -> {} (race excluded from ROI).
"""
import re
import json as _json
import unicodedata

_RAPPORTS_DDL_SQLITE = """CREATE TABLE IF NOT EXISTS race_rapports (
    date TEXT NOT NULL,
    reunion_num INTEGER NOT NULL,
    course_num INTEGER NOT NULL,
    hippodrome TEXT,
    payload TEXT,
    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (date, reunion_num, course_num)
)"""

_RAPPORTS_DDL_PG = (
    "CREATE TABLE IF NOT EXISTS race_rapports (date TEXT NOT NULL, reunion_num INTEGER NOT NULL, "
    "course_num INTEGER NOT NULL, hippodrome TEXT, payload TEXT, "
    "fetched_at TIMESTAMPTZ DEFAULT NOW(), PRIMARY KEY (date, reunion_num, course_num))",
)


def norm(s):
    s = unicodedata.normalize("NFD", str(s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return " ".join(s.split())


def _txt(s):
    s = re.sub(r"<[^>]+>", " ", s or "")
    return " ".join(s.replace("&nbsp;", " ").replace("€", " ").split())


def _num_fr(s):
    s = _txt(s).replace(" ", "").replace(" ", "").replace(",", ".")
    m = re.search(r"\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def parse_payouts(html):
    out = {}
    for b in re.split(r'<div class="blocR', html or "")[1:]:
        m = re.search(r"entetePictoText[^>]*>(.*?)</span>", b, re.DOTALL)
        label = _txt(m.group(1)) if m else "UNKNOWN"
        rows = []
        for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", b, re.DOTALL):
            if "titreCombi" in tr:
                continue
            tds = re.findall(r"<td[^>]*>(.*?)</td>", tr, re.DOTALL)
            if len(tds) < 3:
                continue
            combi = [int(x) for x in re.findall(r"\d+", _txt(tds[0]))]
            typ = _txt(tds[1])
            rap = _num_fr(tds[2])
            if combi and rap:
                rows.append({"combi": combi, "type": typ, "rapport": rap})
        if rows:
            out.setdefault(label, []).extend(rows)
    return out


def _norm_label(s):
    return "".join(ch for ch in str(s or "").lower() if ch.isalnum())


def extract_keys(pay):
    """Payouts keyed for ROI: E-internet preferred, base fallback."""
    if not pay:
        return {}
    by_norm = {}
    for label, rows in pay.items():
        by_norm.setdefault(_norm_label(label), []).extend(rows)
    out = {}

    def pick(*names):
        for nm in names:
            if nm in by_norm and by_norm[nm]:
                return by_norm[nm]
        return []

    def gagnant(rows, want_set=None):
        for r in rows:
            if "gagnant" in r["type"].lower() and (want_set is None or set(r["combi"]) == set(want_set)):
                return r["rapport"]
        return 0.0

    ec = pick("ecouple", "couple", "jumel")
    out["ecouple_gagnant_rows"] = ec
    tr = pick("trio")
    out["trio_rows"] = tr
    tro = pick("trioordre")
    out["trio_ordre_rows"] = tro
    qu = pick("equinteplus", "quinte")
    out["quinte_rows"] = qu
    return out


def _table_rows(pay_rows, want_set=None, want_order=None):
    if not pay_rows:
        return 0.0
    for r in pay_rows:
        if want_order is not None and list(r["combi"]) == list(want_order) and "gagnant" in r["type"].lower():
            return r["rapport"]
        if want_set is not None and set(r["combi"]) == set(want_set):
            return r["rapport"]
    return 0.0


class _Mapper:
    def __init__(self):
        self._sc = None
        self.prog = {}
        self.reu = {}

    def _scraper(self):
        if self._sc is None:
            from scraper.turfomania_scraper import TurfomaniaScraper
            self._sc = TurfomaniaScraper()
        return self._sc

    def idcourse(self, date_iso, hippo, rnum, cnum):
        try:
            sc = self._scraper()
            if date_iso not in self.prog:
                p = sc.fetch_programme(date_iso) or []
                self.prog[date_iso] = p if isinstance(p, list) else p.get("meetings", [])
            want = norm(hippo).replace("PARIS ", "")
            best = None
            for x in self.prog[date_iso]:
                h = norm(x.get("hippodrome") or x.get("name"))
                if want and (want in h or h in want):
                    best = x
                    break
            if not best:
                return None, None
            rid = best.get("idreunion")
            if rid not in self.reu:
                self.reu[rid] = sc.fetch_reunion(rid) or {}
            for c in self.reu[rid].get("courses", []):
                if str(c.get("course_num")) == str(cnum):
                    return c.get("idcourse"), c.get("slug")
        except Exception:
            pass
        return None, None


_MAPPER = _Mapper()


def fetch_rapports_for(date_iso, hippo, rnum, cnum, timeout_note=None):
    """Return extracted payout keys or {} (never raises)."""
    try:
        cid, slug = _MAPPER.idcourse(date_iso, hippo, rnum, cnum)
        if not cid or not slug:
            return {}
        sc = _MAPPER._scraper()
        html = sc._get(f"{sc.BASE}/pronostics/rapports-{slug}.html?idcourse={cid}")
        if not html or len(html) < 50000:
            return {}
        return extract_keys(parse_payouts(html))
    except Exception:
        return {}


def ensure_tables_sqlite(conn):
    conn.execute(_RAPPORTS_DDL_SQLITE)


def pg_ddl():
    return _RAPPORTS_DDL_PG


def get_stored(db, date_iso, rnum, cnum):
    """db: _TrackConn-like (execute with ? placeholders). Returns dict or None."""
    try:
        row = db.execute(
            "SELECT payload FROM race_rapports WHERE date=? AND reunion_num=? AND course_num=?",
            (date_iso, rnum, cnum)).fetchone()
        if not row:
            return None
        payload = row["payload"] if isinstance(row, dict) else row[0]
        return _json.loads(payload) if isinstance(payload, str) else payload
    except Exception:
        return None


def store(db, date_iso, rnum, cnum, hippo, keys):
    try:
        payload = _json.dumps(keys, ensure_ascii=False)
        if getattr(db, "is_pg", False):
            db.execute(
                "INSERT INTO race_rapports (date, reunion_num, course_num, hippodrome, payload) "
                "VALUES (?,?,?,?,?) ON CONFLICT (date, reunion_num, course_num) DO UPDATE SET "
                "payload=EXCLUDED.payload, hippodrome=EXCLUDED.hippodrome, fetched_at=NOW()",
                (date_iso, rnum, cnum, hippo, payload))
        else:
            db.execute(
                "INSERT OR REPLACE INTO race_rapports (date, reunion_num, course_num, hippodrome, payload) "
                "VALUES (?,?,?,?,?)",
                (date_iso, rnum, cnum, hippo, payload))
        db.commit()
        return True
    except Exception:
        return False
