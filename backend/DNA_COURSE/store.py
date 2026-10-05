"""Fast, purpose-built store for the RACE DNA ENGINE.

The engine does not read the generic application archive. It reads
``dna_archive.db``, a compact file that is discipline-complete
(86k races / 178k horses / 972k runner rows since 2019) instead of the
Quinté-only slice that shipped before, which held 0-2 rows for most runners
and made every form statistic meaningless.

Everything the engine needs is answered by SQL against indexed columns:
per-horse form, pair co-run synergy, trio co-run synergy, and precomputed
market-DNA structure patterns in ``race_dna``.
"""
from __future__ import annotations

import os
import re
import sqlite3
import threading
import time
import unicodedata
from collections import Counter

_LOCK = threading.Lock()
_CONN = None
_CONN_PATH = None
_CACHE = {}
_CACHE_TTL = 900

BAND_LABELS = ("F", "S", "O", "O2", "T")
# label -> ordinal used by the compact store
LABEL_ORD = {"F": 0, "S": 1, "O": 2, "O2": 3, "T": 4}
ORD_LABEL = {v: k for k, v in LABEL_ORD.items()}


def dna_db_path() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env = os.environ.get("DNA_ARCHIVE_DB")
    if env:
        cand = os.path.join(base, env)
        if os.path.isfile(cand):
            return cand
        return env
    for name in ("dna_archive.db", "archive_slim_20260911.db", "archive_slim.db"):
        cand = os.path.join(base, name)
        try:
            if os.path.isfile(cand) and os.path.getsize(cand) > 1_000_000:
                return cand
        except OSError:
            continue
    return os.path.join(base, "dna_archive.db")


def compact_available() -> bool:
    path = dna_db_path()
    try:
        conn = sqlite3.connect(path)
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='race_dna'"
        ).fetchone()
        conn.close()
        return row is not None
    except sqlite3.Error:
        return False


def connect() -> sqlite3.Connection:
    global _CONN, _CONN_PATH
    path = dna_db_path()
    with _LOCK:
        if _CONN is None or _CONN_PATH != path:
            if _CONN is not None:
                try:
                    _CONN.close()
                except sqlite3.Error:
                    pass
            _CONN = sqlite3.connect(path, check_same_thread=False)
            _CONN.row_factory = sqlite3.Row
            _CONN.execute("PRAGMA journal_mode=WAL")
            _CONN.execute("PRAGMA cache_size=-40000")
            _CONN.execute("PRAGMA temp_store=MEMORY")
            _CONN_PATH = path
        return _CONN


def clear_cache() -> None:
    with _LOCK:
        _CACHE.clear()


# --------------------------------------------------------------------- utils
def norm_horse(name: str) -> str:
    s = unicodedata.normalize("NFD", str(name or "").upper())
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"\s*\([^)]*\)\s*", " ", s)
    return " ".join(s.split())


def _ph(n: int) -> str:
    return ",".join("?" * n)


def _cache_get(key):
    hit = _CACHE.get(key)
    if hit and time.time() - hit[0] < _CACHE_TTL:
        return hit[1]
    return None


def _cache_put(key, value):
    _CACHE[key] = (time.time(), value)
    return value


def resolve_horses(names):
    """Map normalised horse name -> hid for the ones the archive knows."""
    clean = []
    for n in names:
        nn = norm_horse(n)
        if nn and nn not in clean:
            clean.append(nn)
    if not clean:
        return {}
    conn = connect()
    out = {}
    for i in range(0, len(clean), 400):
        chunk = clean[i:i + 400]
        rows = conn.execute(
            f"SELECT hid, name FROM horses WHERE name IN ({_ph(len(chunk))})", chunk
        ).fetchall()
        for r in rows:
            out[r["name"]] = r["hid"]
    return out


# ------------------------------------------------------------------- market
def disc_set(disc) -> tuple:
    d = str(disc or "").upper()
    if d in ("TROT", "ATTELE", "ATTELÉ", "MONTE"):
        return ("ATTELE", "MONTE")
    if d in ("GALOP", "PLAT", "HAIE", "HAIES", "STEEPLE", "STEEPLECHASE", "CROSS"):
        return ("PLAT", "HAIE", "STEEPLE", "CROSS")
    return (d,) if d else ()


STORE_DEFAULT_MAX = (5.0, 10.0, 20.0, 30.0)


def bands_match_store(bands) -> bool:
    """True when the active thresholds equal the ones baked into dna_archive.db."""
    if len(bands) != 5:
        return False
    if tuple(b["label"] for b in bands) != BAND_LABELS:
        return False
    for b, mx in zip(bands, STORE_DEFAULT_MAX):
        if abs(float(b["max"]) - mx) > 1e-9:
            return False
    return True


def band_from_cote(cote, bands):
    try:
        v = float(cote)
    except (TypeError, ValueError):
        return "UNK"
    if v <= 0:
        return "UNK"
    for b in bands:
        if v <= float(b["max"]):
            return b["label"]
    return bands[-1]["label"]


def market_dna(conn, before, discs, distance, runners, bands):
    """Structure of the historical market for this race context."""
    fast = bands_match_store(bands)
    key = ("mkt", before, discs, distance, runners, fast,
           tuple((b["label"], b["max"]) for b in bands))
    hit = _cache_get(key)
    if hit is not None:
        return hit

    args = [*discs, before]
    where = f"disc IN ({_ph(len(discs))}) AND date < ?"
    if runners:
        where += " AND ABS(runners - ?) <= 2"
        args.append(int(runners))
    if distance:
        where += " AND (ABS(dist - ?) <= 200 OR dist IS NULL)"
        args.append(int(distance))

    top5 = Counter()
    top3 = Counter()
    couple = Counter()
    trio = Counter()
    field_prof = Counter()
    pos_band = {i: Counter() for i in range(1, 6)}
    n_races = 0

    if fast:
        rows = conn.execute(
            f"SELECT p1,p2,p3,p4,p5,f_count,s_count,o_count,o2_count,t_count "
            f"FROM race_dna WHERE {where}",
            args,
        )
        for r in rows:
            n_races += 1
            p = [ORD_LABEL.get(r[f"p{i}"]) or "UNK" for i in range(1, 6)]
            top5["+".join(p)] += 1
            top3["+".join(p[:3])] += 1
            couple["+".join(p[:2])] += 1
            trio["+".join(p[:3])] += 1
            for i, b in enumerate(p, 1):
                pos_band[i][b] += 1
            field_prof["+".join([
                f"F:{r['f_count'] or 0}", f"S:{r['s_count'] or 0}",
                f"O:{r['o_count'] or 0}", f"O2:{r['o2_count'] or 0}",
                f"T:{r['t_count'] or 0}",
            ])] += 1
    else:
        # Custom thresholds: recompute bands from the stored cotes.
        rows = conn.execute(
            f"""SELECT rn.rid, rn.cote, rn.rang,
                       ROW_NUMBER() OVER (PARTITION BY rn.rid ORDER BY rn.rang) pos
                FROM runners rn JOIN races rc ON rc.rid = rn.rid
                WHERE {where.replace('disc', 'rc.disc').replace('date', 'rc.date')
                        .replace('runners', 'rc.runners').replace('dist', 'rc.dist')}
                  AND rn.cote IS NOT NULL AND rn.rang < 90""",
            args,
        )
        per = {}
        for r in rows:
            per.setdefault(r["rid"], []).append(
                (r["pos"], band_from_cote(r["cote"], bands))
            )
        for rid, entries in per.items():
            if len(entries) < 3:
                continue
            n_races += 1
            entries.sort()
            p = [b for _, b in entries[:5]]
            while len(p) < 5:
                p.append("UNK")
            top5["+".join(p)] += 1
            top3["+".join(p[:3])] += 1
            couple["+".join(p[:2])] += 1
            trio["+".join(p[:3])] += 1
            for i, b in enumerate(p, 1):
                pos_band[i][b] += 1
            cnt = Counter(b for _, b in entries)
            field_prof["+".join([
                f"{lbl}:{cnt.get(lbl, 0)}" for lbl, _ in bands
            ])] += 1

    tilt = Counter()
    for key3, c in top3.items():
        for b in key3.split("+"):
            tilt[b] += c
    total = sum(tilt.values()) or 1

    return _cache_put(key, {
        "races": n_races,
        "top5": top5,
        "top3": top3,
        "couple": couple,
        "trio": trio,
        "field_prof": field_prof,
        "pos_band": pos_band,
        "tilt": [{"band": k, "share": round(v / total, 4)} for k, v in tilt.most_common()],
    })


# ---------------------------------------------------------------------- form
def horse_profiles(conn, hids, before, distance, surface, bands, limit=40):
    """Per-horse form with Bayesian shrinkage, computed in SQL."""
    hids = [h for h in hids if h]
    if not hids:
        return {}
    out = {}
    for i in range(0, len(hids), 300):
        chunk = hids[i:i + 300]
        rows = conn.execute(
            f"""SELECT rn.hid, rn.rang, rn.cote, rn.age, rn.poids, rn.d4, rn.dai,
                       rn.tid, rc.date, rc.dist, rc.surf, rc.disc
                FROM runners rn JOIN races rc ON rc.rid = rn.rid
                WHERE rn.hid IN ({_ph(len(chunk))})
                  AND rc.date < ? AND rn.rang IS NOT NULL AND rn.rang < 90
                ORDER BY rn.hid, rc.date DESC""",
            [*chunk, before],
        ).fetchall()
        for r in rows:
            out.setdefault(r["hid"], []).append(dict(r))
    return profiles_from_runs(out, distance, surface, bands, conn=conn, limit=limit)


def profiles_from_runs(runs_by_hid, distance, surface, bands, conn=None, limit=40):
    """Shrink every rate towards the prior; a 1-run horse cannot reach 35 pts."""
    k = 2.5
    profiles = {}
    hot_tids = _hot_trainers(conn) if conn is not None else set()
    for hid, all_runs in runs_by_hid.items():
        runs = all_runs[:limit]
        n = len(runs)
        ranks = [r["rang"] for r in runs]
        wins = sum(1 for x in ranks if x == 1)
        top3 = sum(1 for x in ranks if x <= 3)
        top5 = sum(1 for x in ranks if x <= 5)
        dai = 0
        for r in runs:
            if r.get("dai") or r.get("d4") == 2:
                dai += 1
        dist_fit = surface_fit = 0.0
        for r in runs:
            if distance and r.get("dist") and abs(r["dist"] - distance) <= 200:
                dist_fit += 1
            if surface and r.get("surf") and str(r["surf"]).upper() == str(surface).upper():
                surface_fit += 1
        p_top3 = (top3 + 0.30 * k) / (n + k)
        p_top5 = (top5 + 0.45 * k) / (n + k)
        p_win = (wins + 0.15 * k) / (n + k)
        p_avg = (sum(ranks) + 8.0 * k) / (n + k)
        trainer_hot = any(r.get("tid") in hot_tids for r in runs[:8]) if hot_tids else False
        back_cond = any(
            r["rang"] == 1
            and (not distance or not r.get("dist") or abs(r["dist"] - distance) <= 200)
            for r in runs[:8]
        )
        first_d4 = _first_d4(runs)
        # "winless" must mean winless RECENTLY. Checking the last 8 runs meant a
        # horse with a win 30 starts ago still counted as winless, which made
        # the flag fire for almost the whole field and carry no information.
        recent = runs[:5]
        recent_days = 0
        for r in recent:
            if r["rang"] == 1:
                break
            recent_days += 1
        winless = n >= 5 and not any(r["rang"] == 1 for r in recent)
        dist_rate = dist_fit / n if n else 0.0
        surf_rate = surface_fit / n if n else 0.0
        # distance_fit fires for most of the field (a 200m window is generous on
        # a 2850m track), so it is reported but excluded from signal_count: it
        # is context, not evidence.
        distance_ok = dist_rate >= 0.5
        profiles[hid] = {
            "hid": hid,
            "runs_n": n,
            "wins": wins,
            "top3": top3,
            "top5": top5,
            "win_rate": wins / n if n else 0.0,
            "p_top3": p_top3,
            "p_top5": p_top5,
            "p_win": p_win,
            "p_avg": p_avg,
            "raw_top3_rate": top3 / n if n else 0.0,
            "raw_top5_rate": top5 / n if n else 0.0,
            "distance_fit": dist_rate,
            "surface_fit": surf_rate,
            "dai_rate": dai / n if n else 0.0,
            "recent_winless_streak": recent_days,
            "signals": {
                "trainer_hot": trainer_hot,
                "back_to_conditions": back_cond,
                "first_d4": first_d4,
                "winless_recent": winless,
                "distance_fit": distance_ok,
            },
            "context_flags": {
                "distance_fit": dist_rate >= 0.34,
                "surface_fit": surf_rate >= 0.34,
            },
        }
    return profiles


def _hot_trainers(conn):
    rows = conn.execute(
        """SELECT tid FROM runners WHERE rang < 90 AND tid IS NOT NULL
           GROUP BY tid HAVING COUNT(*) >= 12
              AND SUM(CASE WHEN rang=1 THEN 1 ELSE 0 END) * 1.0 / COUNT(*) >= 0.22"""
    ).fetchall()
    return {r["tid"] for r in rows}


def _first_d4(runs):
    """Deferre anterieur-posterieur on the most recent run.

    The archive carries almost no d4 flags, so this stays a weak signal and is
    never allowed to stand alone in a selection rule.
    """
    return bool(runs and runs[0].get("d4"))


# -------------------------------------------------------------- pair / trio
def pair_synergy(conn, hids, before):
    """Real co-run statistics for every pair inside the current field."""
    hids = [h for h in hids if h]
    if len(hids) < 2:
        return {}
    key = ("pair", before, tuple(sorted(hids)))
    hit = _cache_get(key)
    if hit is not None:
        return hit
    rows = conn.execute(
        f"""SELECT a.hid h1, b.hid h2, COUNT(*) n,
                   SUM(CASE WHEN a.rang<=3 AND b.rang<=3 THEN 1 ELSE 0 END) t3,
                   SUM(CASE WHEN a.rang<=5 AND b.rang<=5 THEN 1 ELSE 0 END) t5,
                   SUM(CASE WHEN a.rang<=2 AND b.rang<=2 THEN 1 ELSE 0 END) f2
            FROM runners a
            JOIN runners b ON b.rid = a.rid AND b.hid > a.hid
            JOIN races rc ON rc.rid = a.rid
            WHERE a.hid IN ({_ph(len(hids))})
              AND b.hid IN ({_ph(len(hids))})
              AND rc.date < ? AND a.rang < 90 AND b.rang < 90
            GROUP BY a.hid, b.hid""",
        [*hids, *hids, before],
    ).fetchall()
    return _cache_put(key, {
        (r["h1"], r["h2"]): {
            "n": r["n"], "top3": r["t3"] or 0, "top5": r["t5"] or 0,
            "first2": r["f2"] or 0,
        }
        for r in rows
    })


def trio_synergy(conn, hids, before):
    hids = [h for h in hids if h]
    if len(hids) < 3:
        return {}
    key = ("trio", before, tuple(sorted(hids)))
    hit = _cache_get(key)
    if hit is not None:
        return hit
    rows = conn.execute(
        f"""SELECT a.hid h1, b.hid h2, c.hid h3, COUNT(*) n,
                   SUM(CASE WHEN a.rang<=3 AND b.rang<=3 AND c.rang<=3 THEN 1 ELSE 0 END) t3,
                   SUM(CASE WHEN a.rang<=5 AND b.rang<=5 AND c.rang<=5 THEN 1 ELSE 0 END) t5
            FROM runners a
            JOIN runners b ON b.rid = a.rid AND b.hid > a.hid
            JOIN runners c ON c.rid = b.rid AND c.hid > b.hid
            JOIN races rc ON rc.rid = a.rid
            WHERE a.hid IN ({_ph(len(hids))})
              AND b.hid IN ({_ph(len(hids))})
              AND c.hid IN ({_ph(len(hids))})
              AND rc.date < ? AND a.rang < 90 AND b.rang < 90 AND c.rang < 90
            GROUP BY a.hid, b.hid, c.hid""",
        [*hids, *hids, *hids, before],
    ).fetchall()
    return _cache_put(key, {
        (r["h1"], r["h2"], r["h3"]): {
            "n": r["n"], "top3": r["t3"] or 0, "top5": r["t5"] or 0,
        }
        for r in rows
    })


def trainer_stats(conn, before):
    return {}
