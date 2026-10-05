import sqlite3
import json
import os
import re
import unicodedata
from datetime import date

def _resolve_db_path(base_dir, env_val=None):
    """Choose the SQLite file to use.

    - Explicit ARCHIVE_DB env wins (Railway dashboard can override).
    - Else archive.db when it exists and is non-trivial (>1MB guards
      against the empty file SQLite auto-creates on first connect).
    - Else archive_slim.db when deployed (Railway/Docker ignore the
      776MB archive.db but ship the 82MB slim with ~4300 quintes).
    - Else fall back to archive.db (will be created empty).
    """
    if env_val:
        return os.path.join(base_dir, env_val)
    full = os.path.join(base_dir, "archive.db")
    try:
        if os.path.isfile(full) and os.path.getsize(full) > 1_000_000:
            return full
    except OSError:
        pass
    slim = os.path.join(base_dir, "archive_slim.db")
    try:
        if os.path.isfile(slim) and os.path.getsize(slim) > 1_000_000:
            return slim
    except OSError:
        pass
    return full


DB_PATH = _resolve_db_path(os.path.dirname(__file__), os.environ.get("ARCHIVE_DB"))
ARCHIVE_DIR = os.path.join(os.path.dirname(__file__), "archives")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _norm_token(s):
    s = unicodedata.normalize("NFD", str(s or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^A-Z]+", " ", s).strip()


_MONTE_TOKENS = {"MONTE", "TROT MONTE", "MONTE TROT"}
_ATTELE_TOKENS = {"ATTELE", "TROT ATTELE", "ATTEL", "ATTELE TROT"}
_PLAT_TOKENS = {"PLAT", "GALOP", "FLAT"}
_HAIE_TOKENS = {"HAIE", "HAIES"}
_STEEPLE_TOKENS = {"STEEPLE", "STEEPLECHASE", "STEEPLE CHASE", "STEEPLE CHASES"}
_CROSS_TOKENS = {"CROSS", "CROSS COUNTRY", "CROSSCOUNTRY"}


def canonical_discipline(discipline=None, specialty=None):
    """Single canonical discipline across PMU/Geny/SOREC/Equidia spellings.

    Specialty wins (more specific), then discipline. Returns one of
    ATTELE, MONTE, PLAT, HAIE, STEEPLE, CROSS, or UNKNOWN.
    """
    for raw in (specialty, discipline):
        t = _norm_token(raw)
        if not t or t in ("?", "UNKNOWN", "INCONNU", "N"):
            continue
        if t in _MONTE_TOKENS or "MONTE" in t.split():
            return "MONTE"
        if t in _ATTELE_TOKENS or "ATTELE" in t.split() or "ATTEL" in t.split():
            return "ATTELE"
        if t in _HAIE_TOKENS or "HAIE" in t.split() or "HAIES" in t.split():
            return "HAIE"
        if t in _STEEPLE_TOKENS or "STEEPLE" in t.split():
            return "STEEPLE"
        if t in _CROSS_TOKENS or "CROSS" in t.split():
            return "CROSS"
        if t in _PLAT_TOKENS or "PLAT" in t.split() or "GALOP" in t.split():
            # bare TROT without attelé/monté qualifier defaults to harness
            if t == "TROT":
                return "ATTELE"
            return "PLAT"
        if t == "TROT":
            return "ATTELE"
        if t == "OBSTACLE":
            continue  # too generic alone; let the other field decide
    return "UNKNOWN"


def discipline_family(canonical=None, discipline=None, specialty=None):
    """TROT (attelé+monté) vs GALOP (plat+haie+steeple+cross) vs UNKNOWN."""
    c = canonical or canonical_discipline(discipline, specialty)
    if c in ("ATTELE", "MONTE"):
        return "TROT"
    if c in ("PLAT", "HAIE", "STEEPLE", "CROSS"):
        return "GALOP"
    return "UNKNOWN"


_HIPPO_STOP = {"HIP", "HIPPODROME", "HIPPODROMES", "DE", "DU", "DES", "LA", "LE",
               "LES", "L", "D", "EN", "PAYS", "BAS", "SUR", "ET", "AU", "AUX", "EN"}


def canonical_hippodrome(name):
    """Single canonical folder/merge name for a hippodrome spelling.

    Unifies: accents (É->E), mojibake (� removed), bracket suffixes
    (_[NORVEGE], _(CHILI)), PARIS_ prefix, '-' vs '_' separators.
    Examples: 'LE_CROISÉ-LAROCHE'/'LE_CROIS�-LAROCHE' -> 'LE_CROISE_LAROCHE',
    'PARIS_VINCENNES' -> 'VINCENNES', 'MOMARKEN_[NORVÈGE]' -> 'MOMARKEN'.
    Distinct tracks stay distinct (MARSEILLE_BORELY vs MARSEILLE_VIVAUX).
    """
    if not name or not isinstance(name, str):
        return "UNKNOWN"
    s = unicodedata.normalize("NFD", name)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^\x00-\x7F]", "", s).upper().strip().replace(" ", "_").replace("'", "")
    s = re.sub(r"_[\[\(].*?[\]\)]\s*$", "", s)  # _[..] / _(..) suffix
    s = re.sub(r"^PARIS_", "", s)
    s = s.replace("-", "_")
    s = re.sub(r"_+", "_", s).strip("_")
    return s or "UNKNOWN"


def hippodrome_tokens(name):
    """Significant tokens of any spelling: 'HIPPODROME DE PARIS-VINCENNES'
    -> ['PARIS', 'VINCENNES']; 'VINCENNES' -> ['VINCENNES']."""
    if not name or not isinstance(name, str):
        return []
    toks = []
    for t in re.split(r"[^A-Z0-9]+", _norm_token(name).replace(" ", " ")):
        t = t.strip()
        if len(t) >= 3 and t not in _HIPPO_STOP and t not in toks:
            toks.append(t)
    return toks[:3]


def hippodrome_in_clause(conn, col, name):
    """(sql, params) matching stored hippodrome spellings for ANY input form.

    Resolves to exact stored values first (index-friendly IN), so short
    ('VINCENNES') and long ('HIPPODROME DE PARIS-VINCENNES') inputs hit the
    same rows. Empty/unknown input -> no filter (global scope, never empty).
    """
    toks = hippodrome_tokens(name)
    if not toks:
        return "1=1", []
    cond = " OR ".join([f"{col} LIKE ?"] * len(toks))
    try:
        rows = conn.execute(
            f"SELECT DISTINCT {col} FROM races WHERE {cond}",
            [f"%{t}%" for t in toks],
        ).fetchall()
    except Exception:
        return "1=1", []
    vals = [r[0] for r in rows if r[0]]
    if not vals:
        return "1=1", []
    ph = ",".join("?" * len(vals))
    return f"{col} IN ({ph})", vals


def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS races (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id INTEGER NOT NULL UNIQUE,
            hippodrome TEXT NOT NULL,
            filename TEXT NOT NULL,
            date TEXT,
            time TEXT,
            reunion_num INTEGER,
            course_num INTEGER,
            prix TEXT,
            specialty TEXT,
            discipline TEXT,
            distance INTEGER,
            surface TEXT,
            going TEXT,
            corde TEXT,
            runners INTEGER,
            quinte INTEGER DEFAULT 0,
            classe TEXT,
            condition TEXT,
            depart TEXT,
            penetrometer REAL,
            types_pari TEXT,
            allocations TEXT,
            arrivee TEXT,
            ref REAL,
            ref2 REAL,
            ref_text TEXT,
            saved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(hippodrome, filename)
        );

        CREATE TABLE IF NOT EXISTS participants (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            race_id INTEGER NOT NULL,
            num INTEGER,
            horse TEXT,
            horse_id INTEGER,
            jockey TEXT,
            trainer TEXT,
            age INTEGER,
            sexe TEXT,
            gain REAL,
            poids REAL,
            decharge REAL,
            corde INTEGER,
            valeur INTEGER,
            deferre TEXT,
            oeilleres TEXT,
            bonnet INTEGER,
            attache_langue INTEGER,
            cote_pmu REAL,
            cote_geny REAL,
            musique TEXT,
            note TEXT,
            red_km TEXT,
            distance INTEGER,
            rang INTEGER,
            ecart TEXT,
            proprietaire TEXT,
            casaque TEXT,
            etat TEXT,
            incident TEXT,
            FOREIGN KEY (race_id) REFERENCES races(race_id)
        );

        CREATE INDEX IF NOT EXISTS idx_races_date ON races(date);
        CREATE INDEX IF NOT EXISTS idx_races_hippodrome ON races(hippodrome);
        CREATE INDEX IF NOT EXISTS idx_races_quinte ON races(quinte);
        CREATE INDEX IF NOT EXISTS idx_participants_horse ON participants(horse);
        CREATE INDEX IF NOT EXISTS idx_participants_horse_nocase ON participants(horse COLLATE NOCASE);
        CREATE INDEX IF NOT EXISTS idx_participants_race ON participants(race_id);
        CREATE INDEX IF NOT EXISTS idx_participants_jockey ON participants(jockey);
        CREATE INDEX IF NOT EXISTS idx_participants_trainer ON participants(trainer);
        CREATE INDEX IF NOT EXISTS idx_races_ref ON races(ref);
        -- Suivi: user-tracked analyses + outcomes (betting journal)
        CREATE TABLE IF NOT EXISTS tracked_races (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT NOT NULL,
            reunion_num INTEGER NOT NULL,
            course_num INTEGER NOT NULL,
            hippodrome TEXT,
            discipline TEXT,
            distance INTEGER,
            runners INTEGER,
            race_time INTEGER,
            analyzed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(date, reunion_num, course_num)
        );
        CREATE TABLE IF NOT EXISTS tracked_picks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            tracked_id INTEGER NOT NULL,
            ticket TEXT NOT NULL,
            target_pos INTEGER,
            num INTEGER,
            horse TEXT,
            driver TEXT,
            cote REAL,
            score REAL,
            FOREIGN KEY(tracked_id) REFERENCES tracked_races(id)
        );
        CREATE TABLE IF NOT EXISTS tracked_results (
            tracked_id INTEGER PRIMARY KEY,
            p1 INTEGER, p2 INTEGER, p3 INTEGER, p4 INTEGER, p5 INTEGER,
            source TEXT,
            resolved_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS race_rapports (
            date TEXT NOT NULL,
            reunion_num INTEGER NOT NULL,
            course_num INTEGER NOT NULL,
            hippodrome TEXT,
            payload TEXT,
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            PRIMARY KEY (date, reunion_num, course_num)
        );
        CREATE TABLE IF NOT EXISTS horse_sires (
            horse TEXT PRIMARY KEY,
            sire TEXT,
            dam TEXT
        );
        CREATE TABLE IF NOT EXISTS presse_synthese (
            date TEXT PRIMARY KEY,
            hippodrome TEXT,
            prix TEXT,
            synthese TEXT,
            resultat TEXT,
            source TEXT DEFAULT 'pronostics-turf.info',
            fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    _migrate(conn)
    conn.commit()
    conn.close()
    os.makedirs(ARCHIVE_DIR, exist_ok=True)


def _migrate(conn):
    """Idempotent Phase-1 migrations for pre-existing databases."""
    cols = [r["col"] for r in conn.execute("SELECT name AS col FROM pragma_table_info('races')")]
    if "disc_canonical" not in cols:
        conn.execute("ALTER TABLE races ADD COLUMN disc_canonical TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_races_disc_canon ON races(disc_canonical)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_part_race_rang_cote "
                 "ON participants(race_id, rang, cote_pmu, poids, valeur)")
    tp = [r["col"] for r in conn.execute("SELECT name AS col FROM pragma_table_info('tracked_picks')")]
    if tp and "driver" not in tp:
        conn.execute("ALTER TABLE tracked_picks ADD COLUMN driver TEXT")


def extract_date_from_filename(filename):
    parts = filename.replace(".json", "").split("_")
    for p in parts:
        if "-" in p and len(p) == 10 and p[:4].isdigit():
            return p
    return None


def _scalar(v):
    """Flatten PMU/Geny list/dict fields (e.g. distance handed as a list)
    into a single bindable SQLite value."""
    if isinstance(v, dict):
        return json.dumps(v, ensure_ascii=False)
    if isinstance(v, list):
        if not v:
            return None
        return _scalar(v[0])
    return v


def find_race_ids(date, reunion_num, course_num, exclude=None):
    """All race_ids stored for the same physical race (any id scheme)."""
    conn = get_db()
    rows = conn.execute(
        "SELECT race_id FROM races WHERE date=? AND reunion_num=? AND course_num=?",
        (date, reunion_num, course_num),
    ).fetchall()
    conn.close()
    return [r["race_id"] for r in rows if r["race_id"] != exclude]


def _race_has_results(race_id):
    conn = get_db()
    n = conn.execute(
        "SELECT COUNT(*) AS n FROM participants WHERE race_id=? AND rang IS NOT NULL",
        (race_id,),
    ).fetchone()["n"]
    conn.close()
    return n > 0


def save_geny_race(race_id, race_data, rapports_data=None):
    reunion = race_data.get("reunion", {})
    course = race_data.get("course", {})
    participants = race_data.get("participants", [])

    hippodrome = str(reunion.get("hippodrome", "UNKNOWN")).upper().strip().replace(" ", "_").replace("'", "")
    hippodrome = canonical_hippodrome(reunion.get("hippodrome", "UNKNOWN"))
    rnum = reunion.get("num", 0)
    cnum = course.get("num", 0)
    d = reunion.get("date", "UNKNOWN")
    filename = f"race_R{rnum}_C{cnum}_{d}.json"

    folder = os.path.join(ARCHIVE_DIR, hippodrome)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, filename), "w", encoding="utf-8") as f:
        json.dump(race_data, f, ensure_ascii=False, indent=2)

    # Unify duplicate ids: same (date, R, C) must not fork new rows.
    incoming_has_results = bool(course.get("arrivee")) or any(
        (p or {}).get("rang") is not None for p in participants
    )
    if d != "UNKNOWN":
        for eid in find_race_ids(d, rnum, cnum, exclude=race_id):
            if incoming_has_results and not _race_has_results(eid):
                delete_archived_race(eid)  # absorb pre-race shadow
            elif not incoming_has_results and _race_has_results(eid):
                return {"filename": filename, "hippodrome": hippodrome,
                        "folder": folder, "skipped_shadow_of": eid}

    conn = get_db()
    try:
        conn.execute("DELETE FROM participants WHERE race_id=?", (race_id,))
        conn.execute("DELETE FROM races WHERE race_id=?", (race_id,))

        disc_canon = canonical_discipline(course.get("discipline"), course.get("specialty"))
        conn.execute("""
            INSERT INTO races (
                race_id, hippodrome, filename, date, time,
                reunion_num, course_num, prix, specialty, discipline,
                distance, surface, going, corde, runners, quinte,
                classe, condition, depart, penetrometer,
                types_pari, allocations, arrivee, ref, ref2, ref_text,
                disc_canonical
            ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            race_id,
            hippodrome,
            filename,
            d,
            _scalar(course.get("time")),
            rnum,
            cnum,
            _scalar(course.get("prix")),
            _scalar(course.get("specialty")),
            _scalar(course.get("discipline")),
            _scalar(course.get("distance")),
            _scalar(course.get("surface")),
            _scalar(course.get("going")),
            _scalar(course.get("corde")),
            _scalar(course.get("runners")),
            1 if course.get("quinte") else 0,
            _scalar(course.get("classe")),
            _scalar(course.get("condition")),
            _scalar(course.get("depart")),
            _scalar(course.get("penetrometer")),
            json.dumps(course.get("types_pari", []), ensure_ascii=False),
            json.dumps(course.get("allocations"), ensure_ascii=False) if course.get("allocations") else None,
            json.dumps(course.get("arrivee"), ensure_ascii=False) if isinstance(course.get("arrivee"), (list, dict)) else course.get("arrivee"),
            _scalar(course.get("ref")),
            _scalar(course.get("ref2")),
            _scalar(course.get("ref_text")),
            disc_canon,
        ))

        for p in participants:
            conn.execute("""
                INSERT INTO participants (
                    race_id, num, horse, horse_id, jockey, trainer,
                    age, sexe, gain, poids, decharge, corde, valeur,
                    deferre, oeilleres, bonnet, attache_langue,
                    cote_pmu, cote_geny, musique, note, red_km,
                    distance, rang, ecart, proprietaire, casaque, etat, incident
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                race_id,
                _scalar(p.get("num")), _scalar(p.get("horse")), _scalar(p.get("horse_id")),
                _scalar(p.get("jockey")), _scalar(p.get("trainer")),
                _scalar(p.get("age")), _scalar(p.get("sexe")), _scalar(p.get("gain")),
                _scalar(p.get("poids")), _scalar(p.get("decharge")), _scalar(p.get("corde")), _scalar(p.get("valeur")),
                _scalar(p.get("deferre")), _scalar(p.get("oeilleres")),
                1 if p.get("bonnet") else 0,
                1 if p.get("attache_langue") else 0,
                _scalar(p.get("cote_pmu")), _scalar(p.get("cote_geny")),
                _scalar(p.get("musique")), _scalar(p.get("note")), _scalar(p.get("red_km")),
                _scalar(p.get("distance")), _scalar(p.get("rang")), _scalar(p.get("ecart")),
                _scalar(p.get("proprietaire")), _scalar(p.get("casaque")),
                _scalar(p.get("etat")), _scalar(p.get("incident"))
            ))

        conn.commit()
        _clear_jockey_cache()
        return {"filename": filename, "hippodrome": hippodrome, "folder": folder}
    except Exception as e:
        conn.rollback()
        raise e
    finally:
        conn.close()


def list_archive_hippodromes():
    conn = get_db()
    rows = conn.execute("""
        SELECT hippodrome, COUNT(*) as total_races
        FROM races
        GROUP BY hippodrome
        ORDER BY total_races DESC
    """).fetchall()
    conn.close()
    return [{"hippodrome": r["hippodrome"], "total_races": r["total_races"]} for r in rows]


def list_archive_races(hippodrome=None, date_filter=None, quinte_only=False, limit=50, offset=0):
    conn = get_db()
    query = "SELECT * FROM races WHERE 1=1"
    params = []
    if hippodrome:
        hclause, hparams = hippodrome_in_clause(conn, "hippodrome", hippodrome)
        if hclause != "1=1":
            query += f" AND ({hclause})"
            params.extend(hparams)
    if date_filter:
        query += " AND date=?"
        params.append(date_filter)
    if quinte_only:
        query += " AND quinte=1"
    query += " ORDER BY date DESC, time DESC LIMIT ? OFFSET ?"
    params.extend([limit, offset])
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def list_archive_dates():
    conn = get_db()
    rows = conn.execute("SELECT DISTINCT date FROM races ORDER BY date DESC").fetchall()
    conn.close()
    return [r["date"] for r in rows]


def delete_archive_file(hippodrome, filename):
    filepath = os.path.join(ARCHIVE_DIR, hippodrome, filename)
    if os.path.exists(filepath):
        os.remove(filepath)
    conn = get_db()
    conn.execute("DELETE FROM participants WHERE race_id IN (SELECT race_id FROM races WHERE hippodrome=? AND filename=?)", (hippodrome, filename))
    conn.execute("DELETE FROM races WHERE hippodrome=? AND filename=?", (hippodrome, filename))
    conn.commit()
    conn.close()
    _clear_jockey_cache()


def delete_archived_race(race_id):
    conn = get_db()
    row = conn.execute("SELECT hippodrome, filename FROM races WHERE race_id=?", (race_id,)).fetchone()
    if row:
        filepath = os.path.join(ARCHIVE_DIR, row["hippodrome"], row["filename"])
        if os.path.exists(filepath):
            os.remove(filepath)
    conn.execute("DELETE FROM participants WHERE race_id=?", (race_id,))
    conn.execute("DELETE FROM races WHERE race_id=?", (race_id,))
    conn.commit()
    conn.close()
    _clear_jockey_cache()


def purge_oldest_day():
    """Delete ONLY the single oldest date present in the archive (files + DB rows).
    Returns the number of races deleted (0 if archive is empty)."""
    conn = get_db()
    row = conn.execute("SELECT MIN(date) FROM races").fetchone()
    oldest = row[0] if row else None
    if not oldest:
        conn.close()
        return 0
    rows = conn.execute("SELECT hippodrome, filename FROM races WHERE date=?", (oldest,)).fetchall()
    for r in rows:
        filepath = os.path.join(ARCHIVE_DIR, r["hippodrome"], r["filename"])
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass
    count = len(rows)
    conn.execute("DELETE FROM participants WHERE race_id IN (SELECT race_id FROM races WHERE date=?)", (oldest,))
    conn.execute("DELETE FROM races WHERE date=?", (oldest,))
    conn.commit()
    conn.close()
    return count


def purge_archive_before(date_str):
    """Delete all archived races strictly older than date_str (files + DB rows).
    Returns the number of races deleted."""
    conn = get_db()
    rows = conn.execute("SELECT hippodrome, filename FROM races WHERE date < ?", (date_str,)).fetchall()
    for r in rows:
        filepath = os.path.join(ARCHIVE_DIR, r["hippodrome"], r["filename"])
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except OSError:
                pass
    count = len(rows)
    conn.execute("DELETE FROM participants WHERE race_id IN (SELECT race_id FROM races WHERE date < ?)", (date_str,))
    conn.execute("DELETE FROM races WHERE date < ?", (date_str,))
    conn.commit()
    conn.close()
    return count


_DISCIPLINE_SYNONYMS = {
    "GALOP": ("GALOP", "PLAT"),
    "PLAT": ("GALOP", "PLAT"),
    "HAIE": ("HAIE", "HAIES"),
    "HAIES": ("HAIE", "HAIES"),
    "STEEPLECHASE": ("STEEPLECHASE", "STEEPLE CHASE"),
    "STEEPLE CHASE": ("STEEPLECHASE", "STEEPLE CHASE"),
    "ATTELE": ("ATTELE", "TROT", "ATTELÉ"),
    "TROT": ("ATTELE", "TROT", "ATTELÉ"),
    "MONTE": ("MONTE",),
    "CROSS": ("CROSS",),
}


def _discipline_variants(discipline):
    if not discipline:
        return ()
    key = str(discipline).strip().upper()
    return _DISCIPLINE_SYNONYMS.get(key, (key,))


def get_hippodrome_rank_places(hippodrome, rank, discipline=None, limit=50000):
    conn = get_db()
    hclause, hparams = hippodrome_in_clause(conn, "r.hippodrome", hippodrome)
    params = list(hparams)
    query = """
        SELECT r.race_id, r.date, r.hippodrome, r.prix, r.distance, r.discipline,
               p.num, p.horse, p.cote_pmu, p.rang
        FROM participants p
        JOIN races r ON r.race_id = p.race_id
        WHERE (""" + hclause + """) AND p.rang = ? AND p.cote_pmu IS NOT NULL AND p.cote_pmu > 0
    """
    params.append(rank)
    variants = _discipline_variants(discipline)
    if variants:
        query += " AND (" + " OR ".join(["r.discipline LIKE ?"] * len(variants)) + ")"
        for v in variants:
            params.append(f"%{v}%")
    query += " ORDER BY r.date DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_hippodrome_places(hippodrome, discipline=None, limit=50000):
    conn = get_db()
    hclause, hparams = hippodrome_in_clause(conn, "r.hippodrome", hippodrome)
    params = list(hparams)
    query = """
        SELECT r.race_id, r.date, r.hippodrome, r.prix, r.distance, r.discipline,
               p.num, p.horse, p.cote_pmu, p.rang
        FROM participants p
        JOIN races r ON r.race_id = p.race_id
        WHERE (""" + hclause + """) AND p.rang IS NOT NULL AND p.rang > 0 AND p.rang <= 5
              AND p.cote_pmu IS NOT NULL AND p.cote_pmu > 0
    """
    variants = _discipline_variants(discipline)
    if variants:
        query += " AND (" + " OR ".join(["r.discipline LIKE ?"] * len(variants)) + ")"
        for v in variants:
            params.append(f"%{v}%")
    query += " ORDER BY r.date DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_hippodrome_third_places(hippodrome, discipline=None, limit=50000):
    return get_hippodrome_rank_places(hippodrome, 3, discipline, limit)


def get_archived_race(race_id):
    conn = get_db()
    race = conn.execute("SELECT * FROM races WHERE race_id=?", (race_id,)).fetchone()
    if not race:
        conn.close()
        return None
    participants = conn.execute(
        "SELECT * FROM participants WHERE race_id=? ORDER BY num",
        (race_id,)
    ).fetchall()
    result = dict(race)
    result["participants"] = [dict(p) for p in participants]
    conn.close()
    return result


def search_horses(q, limit=50):
    conn = get_db()
    search = f"%{q}%"
    rows = conn.execute("""
        SELECT p.horse, p.age, p.sexe, p.jockey, p.musique,
               p.rang, p.cote_pmu, p.gain, p.proprietaire,
               r.date, r.hippodrome, r.distance, r.discipline, r.prix,
               r.surface, r.going, r.corde,
               r.reunion_num, r.course_num, r.runners
        FROM participants p
        JOIN races r ON r.race_id = p.race_id
        WHERE p.horse LIKE ?
        ORDER BY r.date DESC
        LIMIT ?
    """, (search, limit)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_horse_names(q=""):
    conn = get_db()
    if q:
        rows = conn.execute("""
            SELECT DISTINCT horse FROM participants
            WHERE horse LIKE ? AND horse != ''
            ORDER BY horse LIMIT 60
        """, (f"{q}%",)).fetchall()
    else:
        rows = conn.execute("""
            SELECT DISTINCT horse FROM participants
            WHERE horse != '' ORDER BY horse LIMIT 50
        """).fetchall()
    conn.close()
    return [r["horse"] for r in rows]


def get_horse_races(horse_name):
    conn = get_db()
    rows = conn.execute("""
        SELECT p.*,
               r.date, r.hippodrome, r.time, r.prix, r.specialty,
               r.discipline, r.distance, r.surface, r.going, r.corde,
               r.runners, r.quinte, r.classe, r.depart,
               r.reunion_num, r.course_num, r.filename
        FROM participants p
        JOIN races r ON r.race_id = p.race_id
        WHERE p.horse = ? AND p.horse != ''
        ORDER BY r.date DESC, r.time DESC
    """, (horse_name.upper(),)).fetchall()
    if not rows:
        rows = conn.execute("""
            SELECT p.*,
                   r.date, r.hippodrome, r.time, r.prix, r.specialty,
                   r.discipline, r.distance, r.surface, r.going, r.corde,
                   r.runners, r.quinte, r.classe, r.depart,
                   r.reunion_num, r.course_num, r.filename
            FROM participants p
            JOIN races r ON r.race_id = p.race_id
            WHERE p.horse LIKE ? AND p.horse != ''
            ORDER BY r.date DESC, r.time DESC
        """, (f"%{horse_name}%",)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


_JOCKEY_TITLES = {"MLLE", "MM", "MME", "DR", "MR", "MISS", "SR", "SIR"}

_JOCKEY_NAMES_CACHE = None


def _clear_jockey_cache():
    global _JOCKEY_NAMES_CACHE
    _JOCKEY_NAMES_CACHE = None


def _all_jockey_names():
    global _JOCKEY_NAMES_CACHE
    if _JOCKEY_NAMES_CACHE is None:
        conn = get_db()
        rows = conn.execute(
            "SELECT DISTINCT jockey FROM participants WHERE jockey != ''"
        ).fetchall()
        conn.close()
        _JOCKEY_NAMES_CACHE = [
            (r["jockey"], _name_tokens(r["jockey"]), _jockey_keys(r["jockey"]))
            for r in rows
        ]
    return _JOCKEY_NAMES_CACHE


def _norm_name(s):
    s = unicodedata.normalize("NFD", str(s or "").upper())
    return "".join(c for c in s if not unicodedata.combining(c))


def _name_tokens(name):
    return [t for t in re.split(r"[^A-Z]+", _norm_name(name)) if t and t not in _JOCKEY_TITLES]


def _jockey_keys(name):
    tokens = _name_tokens(name)
    if not tokens:
        return frozenset()
    if len(tokens[-1]) > 1:
        given = tokens[:-1]
        return frozenset({tokens[-1] + ":" + "".join(sorted(set(t[0] for t in given)))})
    return frozenset()


def _display_choice(names):
    def score(n):
        return (len(n.replace(" ", "")), sum(c.islower() for c in n))
    return max(names, key=score)


def _tok_match(qt, t):
    if len(qt) == 1:
        return t.startswith(qt)
    if len(t) == 1:
        return qt.startswith(t)
    return t.startswith(qt) or qt.startswith(t)


def resolve_jockey_names(q=""):
    """Regroupe les variantes d'orthographe d'un même jockey en groupes {display, names}."""
    q = (q or "").strip()
    qtokens = _name_tokens(q)
    if not qtokens:
        return []

    all_names = _all_jockey_names()
    all_initials = all(len(qt) == 1 for qt in qtokens)

    matched = []
    for name, toks, keys in all_names:
        if len(toks) < len(qtokens):
            continue
        if all_initials:
            if all(_tok_match(qtokens[i], toks[i]) for i in range(len(qtokens))):
                matched.append((name, keys))
        else:
            if len(toks[-1]) > 1 and _tok_match(qtokens[-1], toks[-1]):
                if all(_tok_match(qtokens[i], toks[i]) for i in range(len(qtokens) - 1)):
                    matched.append((name, keys))

    if not matched:
        return []

    key_set = set()
    for _n, keys in matched:
        key_set |= keys
    if key_set:
        matched_map = {n: k for n, k in matched}
        for name, toks, keys in all_names:
            if name not in matched_map and (keys & key_set):
                matched_map[name] = keys
        matched = list(matched_map.items())

    names = [n for n, _k in matched]
    parent = list(range(len(names)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    key_owner = {}
    key_sets = {}
    for i, n in enumerate(names):
        ks = _jockey_keys(n)
        key_sets[i] = ks
        for k in ks:
            if k in key_owner:
                union(i, key_owner[k])
            else:
                key_owner[k] = i

    groups = {}
    for i, n in enumerate(names):
        root = find(i)
        g = groups.setdefault(root, {"names": set(), "keys": set()})
        g["names"].add(n)
        g["keys"] |= key_sets[i]

    result = []
    first_q = qtokens[0]
    for g in groups.values():
        names_list = sorted(g["names"])
        display = _display_choice(names_list)
        d_tokens = _name_tokens(display)
        result.append({
            "display": display,
            "names": names_list,
            "keys": list(g["keys"]),
            "lead": bool(d_tokens) and d_tokens[0].startswith(first_q),
        })
    result.sort(key=lambda x: (not x["lead"], -len(x["names"])))
    return result


def canonical_jockey_name(name):
    groups = resolve_jockey_names(name)
    if not groups:
        return name
    return groups[0]["display"]


def _jockey_group_names(name):
    groups = resolve_jockey_names(name)
    if not groups:
        return [name]
    return groups[0]["names"]


def search_jockeys(q, limit=10000):
    groups = resolve_jockey_names(q)
    if not groups:
        return []
    all_names = sorted({n for g in groups for n in g["names"]})
    canon = {n: g["display"] for g in groups for n in g["names"]}
    placeholders = ",".join("?" * len(all_names))
    conn = get_db()
    rows = conn.execute(f"""
        SELECT p.jockey, p.horse, p.age, p.sexe, p.musique,
               p.rang, p.cote_pmu, p.gain,
               r.date, r.hippodrome, r.distance, r.discipline, r.prix,
               r.surface, r.going, r.corde,
               r.reunion_num, r.course_num, r.runners
        FROM participants p
        JOIN races r ON r.race_id = p.race_id
        WHERE p.jockey IN ({placeholders})
        ORDER BY r.date DESC
        LIMIT ?
    """, all_names + [limit]).fetchall()
    conn.close()
    result = []
    for r in rows:
        d = dict(r)
        d["canon"] = canon.get(r["jockey"], r["jockey"])
        result.append(d)
    return result


def get_jockey_names(q=""):
    groups = resolve_jockey_names(q)
    return [g["display"] for g in groups][:50]


def get_jockey_races(jockey_name):
    names = _jockey_group_names(jockey_name)
    placeholders = ",".join("?" * len(names))
    conn = get_db()
    rows = conn.execute(f"""
        SELECT p.*,
               r.date, r.hippodrome, r.time, r.prix, r.specialty,
               r.discipline, r.distance, r.surface, r.going, r.corde,
               r.runners, r.quinte, r.classe, r.depart,
               r.reunion_num, r.course_num, r.filename
        FROM participants p
        JOIN races r ON r.race_id = p.race_id
        WHERE p.jockey IN ({placeholders}) AND p.jockey != ''
        ORDER BY r.date DESC, r.time DESC
    """, names).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_jockey_specialty(jockey_name):
    names = _jockey_group_names(jockey_name)
    placeholders = ",".join("?" * len(names))
    conn = get_db()
    rows = conn.execute(f"""
        SELECT p.rang, p.cote_pmu, p.distance as p_distance,
               r.discipline, r.distance as r_distance, r.surface, r.going,
               r.corde, r.hippodrome, r.runners
        FROM participants p
        JOIN races r ON r.race_id = p.race_id
        WHERE p.jockey IN ({placeholders}) AND p.jockey != ''
    """, names).fetchall()
    conn.close()

    if not rows:
        return None

    total = len(rows)

    disc_stats = {}
    dist_buckets = {"<1800m": [], "1800-2100m": [], "2100-2500m": [], "2500-2800m": [], ">2800m": []}
    surface_stats = {}
    hippo_stats = {}

    for r in rows:
        disc = r["discipline"] or "INCONNU"
        if disc not in disc_stats:
            disc_stats[disc] = {"runs": 0, "wins": 0, "top3": 0}
        disc_stats[disc]["runs"] += 1
        if r["rang"] and r["rang"] == 1:
            disc_stats[disc]["wins"] += 1
        if r["rang"] and 1 <= r["rang"] <= 3:
            disc_stats[disc]["top3"] += 1

        dist = r["r_distance"] or r["p_distance"] or 0
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
            dist_buckets[bucket].append(r)

        surf = r["surface"] or "INCONNU"
        if surf and surf.strip():
            if surf not in surface_stats:
                surface_stats[surf] = {"runs": 0, "wins": 0}
            surface_stats[surf]["runs"] += 1
            if r["rang"] and r["rang"] == 1:
                surface_stats[surf]["wins"] += 1

        hippo = r["hippodrome"] or "INCONNU"
        if hippo not in hippo_stats:
            hippo_stats[hippo] = {"runs": 0, "wins": 0, "top3": 0}
        hippo_stats[hippo]["runs"] += 1
        if r["rang"] and r["rang"] == 1:
            hippo_stats[hippo]["wins"] += 1
        if r["rang"] and 1 <= r["rang"] <= 3:
            hippo_stats[hippo]["top3"] += 1

    discipline = {}
    for d, s in disc_stats.items():
        discipline[d] = {
            "runs": s["runs"],
            "wins": s["wins"],
            "top3": s["top3"],
            "win_rate": round(s["wins"] / s["runs"] * 100, 1) if s["runs"] else 0,
        }

    distance = {}
    for b, items in dist_buckets.items():
        if items:
            wins = sum(1 for r in items if r["rang"] and r["rang"] == 1)
            top3 = sum(1 for r in items if r["rang"] and 1 <= r["rang"] <= 3)
            distance[b] = {
                "runs": len(items),
                "wins": wins,
                "top3": top3,
                "win_rate": round(wins / len(items) * 100, 1) if items else 0,
            }

    surface = {}
    for s, st in surface_stats.items():
        if s.strip():
            surface[s] = {
                "runs": st["runs"],
                "wins": st["wins"],
                "win_rate": round(st["wins"] / st["runs"] * 100, 1) if st["runs"] else 0,
            }

    hippodromes = {}
    for h, st in hippo_stats.items():
        hippodromes[h] = {
            "runs": st["runs"],
            "wins": st["wins"],
            "top3": st["top3"],
            "win_rate": round(st["wins"] / st["runs"] * 100, 1) if st["runs"] else 0,
        }

    return {
        "total": total,
        "discipline": discipline,
        "distance": distance,
        "surface": surface,
        "hippodrome": hippodromes,
    }


def get_horse_specialty(horse_name):
    conn = get_db()
    name = horse_name.upper()
    rows = conn.execute("""
        SELECT p.rang, p.cote_pmu, p.distance as p_distance,
               r.discipline, r.distance as r_distance, r.surface, r.going,
               r.corde, r.hippodrome, r.runners
        FROM participants p
        JOIN races r ON r.race_id = p.race_id
        WHERE p.horse = ? AND p.horse != ''
    """, (name,)).fetchall()
    if not rows:
        rows = conn.execute("""
            SELECT p.rang, p.cote_pmu, p.distance as p_distance,
                   r.discipline, r.distance as r_distance, r.surface, r.going,
                   r.corde, r.hippodrome, r.runners
            FROM participants p
            JOIN races r ON r.race_id = p.race_id
            WHERE p.horse LIKE ? AND p.horse != ''
        """, (f"%{horse_name}%",)).fetchall()
    conn.close()

    if not rows:
        return None

    total = len(rows)

    disc_stats = {}
    dist_buckets = {"<1800m": [], "1800-2100m": [], "2100-2500m": [], "2500-2800m": [], ">2800m": []}
    surface_stats = {}
    corde_stats = {"G": [], "D": []}
    running_styles = {"front": 0, "mid": 0, "back": 0}

    for r in rows:
        disc = r["discipline"] or "INCONNU"
        if disc not in disc_stats:
            disc_stats[disc] = {"runs": 0, "wins": 0, "top3": 0}
        disc_stats[disc]["runs"] += 1
        if r["rang"] and r["rang"] == 1:
            disc_stats[disc]["wins"] += 1
        if r["rang"] and 1 <= r["rang"] <= 3:
            disc_stats[disc]["top3"] += 1

        dist = r["r_distance"] or r["p_distance"] or 0
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
            dist_buckets[bucket].append(r)

        surf = r["surface"] or "INCONNU"
        if surf and surf.strip():
            if surf not in surface_stats:
                surface_stats[surf] = {"runs": 0, "wins": 0}
            surface_stats[surf]["runs"] += 1
            if r["rang"] and r["rang"] == 1:
                surface_stats[surf]["wins"] += 1

        corde = r["corde"]
        if corde in ("G", "D"):
            corde_stats[corde].append(r)

        cote = r["cote_pmu"] or 0
        runners = r["runners"] or 0
        rang = r["rang"]
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
            "runs": s["runs"],
            "wins": s["wins"],
            "top3": s["top3"],
            "win_rate": round(s["wins"] / s["runs"] * 100, 1) if s["runs"] else 0,
        }

    distance = {}
    for b, items in dist_buckets.items():
        if items:
            wins = sum(1 for r in items if r["rang"] and r["rang"] == 1)
            top3 = sum(1 for r in items if r["rang"] and 1 <= r["rang"] <= 3)
            distance[b] = {
                "runs": len(items),
                "wins": wins,
                "top3": top3,
                "win_rate": round(wins / len(items) * 100, 1) if items else 0,
            }

    surface = {}
    for s, st in surface_stats.items():
        if s.strip():
            surface[s] = {
                "runs": st["runs"],
                "wins": st["wins"],
                "win_rate": round(st["wins"] / st["runs"] * 100, 1) if st["runs"] else 0,
            }

    corde = {}
    for c, items in corde_stats.items():
        if items:
            wins = sum(1 for r in items if r["rang"] and r["rang"] == 1)
            corde[c] = {
                "runs": len(items),
                "wins": wins,
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
        "total": total,
        "discipline": discipline,
        "distance": distance,
        "surface": surface,
        "corde": corde,
        "style": style,
    }
