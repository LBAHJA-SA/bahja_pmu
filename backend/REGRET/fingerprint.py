"""
COUP SUR - helpers du moteur "Le Solide — le favori fort".

Port de `neglect/fingerprint.py` adapte a une base archive.locale
(database.get_db au lieu de engine.archive.get_db). Ne contient que les
helpers utilises par le scoring solide (bandes poids/valeur, sire, indexes).
"""

import re
from database import get_db

# All bands use HALF-OPEN intervals (lo <= v < hi) so no value can land in
# two bands. Clean integer boundaries; the open-ended top band uses None.
_ODDS_BANDS = ((10.0, 15.0), (15.0, 20.0), (20.0, 25.0),
               (25.0, 30.0), (30.0, None))
_POIDS_BANDS = ((0.0, 54.0), (54.0, 56.0), (56.0, 58.0), (58.0, 60.0), (60.0, None))
_VALEUR_BANDS = ((0.0, 25.0), (25.0, 30.0), (30.0, 35.0), (35.0, 40.0), (40.0, None))

_INDEX_READY = False
_SIRE_CACHE = None


def _ensure_perf_index(conn):
    """rang+cote index so 'winners with high odds' stops scanning 1.5M rows."""
    global _INDEX_READY
    if _INDEX_READY:
        return
    try:
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_participants_rang_cote "
            "ON participants(rang, cote_pmu)"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_races_hippo ON races(hippodrome)"
        )
        conn.commit()
    except Exception:
        pass
    _INDEX_READY = True


def _sire_map():
    """{HORSE_UPPER: (sire, dam)} — loaded once, kept in memory. Avoids a
    per-row NOCASE join that defeats every index."""
    global _SIRE_CACHE
    if _SIRE_CACHE is None:
        m = {}
        try:
            conn = get_db()
            for r in conn.execute("SELECT horse, sire, dam FROM horse_sires"):
                key = str(r["horse"] or "").strip().upper()
                if key:
                    m[key] = (r["sire"], r["dam"])
            conn.close()
        except Exception:
            pass
        _SIRE_CACHE = m
    return _SIRE_CACHE


def _band(value, bands):
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    for lo, hi in bands:
        top = 9999.0 if hi is None else float(hi)
        if lo <= v < top:
            if hi is None or hi >= 9999:
                return "%d+" % int(lo)
            return "%d-%d" % (int(lo), int(hi))
    return None


def _pct(n, total):
    if not total:
        return 0.0
    return round(100.0 * n / total, 1)


def _avg(values):
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return round(sum(vals) / len(vals), 1)


_RUN_SPLIT_RE = re.compile(r"\((\d{2})\)|(\d{1,2})|([A-Z])")


def _parse_runs(musique):
    """Parse a PMU musique into run results, NEWEST FIRST. Each entry is an
    int (finishing place; 0 = unplaced) or None for an incident
    (D=déqualifié, A=arrêté, T=tombé, N/R=non partant). Year markers like
    (25) are skipped; surface/discipline letters (p/h/s/m/c...) are suffixes
    of their number, never standalone runs."""
    s = str(musique or "").upper().strip()
    if not s:
        return []
    runs = []
    for m in _RUN_SPLIT_RE.finditer(s):
        if m.group(1):
            continue                      # (25) year marker -> skip
        if m.group(2):
            runs.append(int(m.group(2)))  # finishing place
        elif m.group(3) in ("D", "A", "T", "N", "R"):
            runs.append(None)             # incident run
    return runs