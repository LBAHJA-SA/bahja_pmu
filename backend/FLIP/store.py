"""FLIP's own log — every reading of a race, kept, so they can be compared.

Why this file exists at all, because a measurement page is not enough:

The /measure endpoint re-runs the rule on old races. That answers "would it
have worked", which is not the question. The question is "what did the engine
say about THIS race, on the day, at the hour I read it" — and if the rule is
edited next week, a re-run silently rewrites last week's answers and the record
of what was actually said is gone. So a reading is written once and never
recomputed; the result is filled in later, and only if the race has finished.

THE SAME RACE SEVERAL TIMES. A race is not overwritten. Each press of the button
is an attempt, numbered, and attempts for one race are shown one under the
other. That is the only way to answer the question the page is actually for:
does reading a race six hours before the off give a different — or better —
ticket than reading it half an hour before. The prices move in between, so
market ranks move, so the ticket can move with them.

  race_key   the race identity: date, meeting, course. Groups the attempts.
  attempt    1, 2, 3… within one race. UNIQUE(race_key, attempt), so a second
             press can never overwrite the first.
  log_key    race_key + attempt. The primary key, and what the API hands out.

Its own SQLite file, not a table in archive.db: this is one page's bookkeeping
and must not become a column nobody remembers in a 133k-race store. It also has
to survive the archive being rebuilt.
"""
import json
import os
import sqlite3
import time
from typing import Any, Dict, List, Optional

DB_PATH = os.environ.get("FLIP_DB") or os.path.join(os.path.dirname(os.path.abspath(__file__)), "flip_log.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS flip_log (
    log_key         TEXT PRIMARY KEY,
    race_key        TEXT NOT NULL,
    attempt         INTEGER NOT NULL,
    race_date       TEXT NOT NULL,
    meeting         INTEGER,
    course          INTEGER,
    hippodrome      TEXT,
    distance        INTEGER,
    disc            TEXT,
    declared_runners INTEGER,
    priced_n        INTEGER,
    field_n         INTEGER,
    engine_version  TEXT,
    start_ms        INTEGER,
    status          TEXT NOT NULL DEFAULT 'pending',
    reason          TEXT,
    ticket_json     TEXT,
    result_json     TEXT,
    any_couple      INTEGER,
    any_both_top3   INTEGER,
    created_at      REAL,
    scored_at       REAL,
    UNIQUE (race_key, attempt)
);
"""

# The indexes are kept apart from the table on purpose. An existing file holds
# the old table without race_key, and an index on a column that does not exist
# yet fails the whole script — so the columns are added first, then indexed.
INDEXES = """
CREATE INDEX IF NOT EXISTS idx_flip_log_race ON flip_log (race_key);
CREATE INDEX IF NOT EXISTS idx_flip_log_status ON flip_log (status);
"""

_JSON = (("ticket_json", "ticket"), ("result_json", "result"))


def _conn() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    c = sqlite3.connect(DB_PATH, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute(SCHEMA.split("CREATE INDEX")[0])     # the table only
    _migrate(c)
    c.executescript(INDEXES)
    return c


# Brought forward by hand rather than by deleting the file: the recorded
# readings are the whole point of the file and must survive an upgrade.
_MOVED = (("race_key", "TEXT"), ("attempt", "INTEGER"))
_MOVED_FROM = ("declared_runners", "priced_n", "field_n", "status", "reason",
               "ticket_json", "result_json", "fav_rank", "any_couple",
               "any_both_top3", "trio_hit", "trio_top3", "field_json", "created_at")


def _migrate(c: sqlite3.Connection) -> None:
    have = {r[1] for r in c.execute("PRAGMA table_info(flip_log)")}
    for name, decl in _MOVED:
        if name not in have:
            c.execute("ALTER TABLE flip_log ADD COLUMN %s %s" % (name, decl))
    if "race_key" in have and "attempt" in have:
        rows = c.execute(
            "SELECT log_key, race_date, meeting, course FROM flip_log "
            "WHERE race_key IS NULL OR attempt IS NULL").fetchall()
        for r in rows:
            rk = race_key_of(r["race_date"], r["meeting"], r["course"])
            c.execute("UPDATE flip_log SET race_key=?, attempt=1 WHERE log_key=?",
                      (rk, r["log_key"]))
    c.commit()


def race_key_of(race_date: Any, meeting: Any, course: Any) -> str:
    return "%s__R%s__C%s" % (str(race_date)[:10], meeting, course)


def lead_minutes(start_ms, created_at):
    """Minutes between the reading and the race going away, exact, never banded.

    The delay is the thing being measured; choosing the bands for it would
    decide the answer before the numbers are in. Negative means the race had
    already gone when the reading was made, which is real and worth seeing.

    Both ends are epoch instants — start_ms in milliseconds, created_at from
    time.time() in seconds — so the subtraction is the same number in any zone.
    That is deliberate: there is no datetime.now() here to drift with the
    machine's clock settings. The GMT the page prints the race clock in is the
    front end's job, not this one's.
    """
    try:
        if start_ms is None or created_at is None:
            return None
        return round((float(start_ms) / 1000.0 - float(created_at)) / 60.0, 1)
    except (TypeError, ValueError):
        return None


def save_attempt(race_key: str, meta: Dict[str, Any], ticket: Dict[str, Any],
                 start_ms: Optional[int] = None,
                 engine_version: str = "1.0.0") -> Dict[str, Any]:
    """Add one reading of one race. Never replaces an earlier one."""
    now = time.time()
    with _conn() as c:
        row = c.execute(
            "SELECT COALESCE(MAX(attempt), 0) AS a FROM flip_log WHERE race_key=?",
            (race_key,)).fetchone()
        attempt = int(row["a"]) + 1
        log_key = "%s#%d" % (race_key, attempt)
        c.execute("""
            INSERT INTO flip_log
              (log_key, race_key, attempt, race_date, meeting, course, hippodrome,
               distance, disc, declared_runners, priced_n, field_n, engine_version,
               start_ms, status, reason, ticket_json, created_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        """, (
            log_key, race_key, attempt, meta.get("date"), meta.get("meeting"),
            meta.get("course"), meta.get("hippodrome"), meta.get("distance"),
            meta.get("disc"), meta.get("declared_runners"), ticket.get("priced_n"),
            ticket.get("field_n"), engine_version, start_ms,
            "pending" if ticket.get("ok") else "abstained",
            ticket.get("reason"),
            json.dumps(ticket, ensure_ascii=False), now,
        ))
    return {"log_key": log_key, "race_key": race_key, "attempt": attempt,
            "status": "pending" if ticket.get("ok") else "abstained",
            "created_at": now,
            "lead_min": lead_minutes(start_ms, now)}


def _row_to_dict(r) -> Dict[str, Any]:
    d = dict(r)
    for src, dst in _JSON:
        v = d.pop(src, None)
        try:
            d[dst] = json.loads(v) if v else None
        except (TypeError, ValueError):
            d[dst] = None
    d["lead_min"] = lead_minutes(d.get("start_ms"), d.get("created_at"))
    return d


def read_all(limit: int = 600) -> List[Dict[str, Any]]:
    with _conn() as c:
        rows = c.execute(
            "SELECT * FROM flip_log ORDER BY race_date DESC, meeting DESC, "
            "course DESC, attempt ASC LIMIT ?", (limit,)).fetchall()
    return [_row_to_dict(r) for r in rows]


def find(log_key: str) -> Optional[Dict[str, Any]]:
    with _conn() as c:
        r = c.execute("SELECT * FROM flip_log WHERE log_key=?", (log_key,)).fetchone()
    return _row_to_dict(r) if r else None


def write_score(log_key: str, sc: Dict[str, Any], result: Dict[str, Any]) -> None:
    """Freeze the result beside the reading. Called once, never re-derived."""
    with _conn() as c:
        c.execute("""
            UPDATE flip_log SET status='scored', scored_at=?, result_json=?,
              any_couple=?, any_both_top3=?
            WHERE log_key=?
        """, (time.time(), json.dumps(result, ensure_ascii=False),
              1 if sc.get("any_couple") else 0,
              1 if sc.get("any_both_top3") else 0, log_key))


def write_arrival(log_key: str, result: Dict[str, Any]) -> None:
    """Attach the finish order to a reading the engine refused.

    Kept apart from write_score on purpose. If the engine gave nothing there is
    nothing to hit or miss, but the race did run and the reader still wants to
    see that it finished and what it came to. The refusal stays in the record.
    """
    with _conn() as c:
        c.execute(
            "UPDATE flip_log SET result_json=?, scored_at=? WHERE log_key=?",
            (json.dumps(result, ensure_ascii=False), time.time(), log_key))


def clear() -> int:
    """Empty the journal. Returns how many rows went.

    The only destructive call in the folder, and the readings cannot be
    regenerated later: if the rule changes, re-running it would answer
    differently than it did on the day. The caller has to say so twice.
    """
    with _conn() as c:
        n = c.execute("SELECT COUNT(*) FROM flip_log").fetchone()[0]
        c.execute("DELETE FROM flip_log")
        c.commit()
    return int(n or 0)


def counts() -> Dict[str, int]:
    with _conn() as c:
        r = c.execute("""
            SELECT COUNT(*) AS total,
                   COUNT(DISTINCT race_key) AS races,
                   SUM(CASE WHEN status='scored'    THEN 1 ELSE 0 END) AS scored,
                   SUM(CASE WHEN status='pending'   THEN 1 ELSE 0 END) AS pending,
                   SUM(CASE WHEN status='abstained' THEN 1 ELSE 0 END) AS abstained
            FROM flip_log""").fetchone()
    return {k: int(r[k] or 0) for k in ("total", "races", "scored", "pending", "abstained")}
