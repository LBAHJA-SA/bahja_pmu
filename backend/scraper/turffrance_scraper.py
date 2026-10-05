"""Scraper for https://www.turf-france.com/php/reu.php (Top10 + La Synthese).
Used by bahja-turf Quinté R1 pages. Tested against 2026-09-16 R1C1.
"""
import re
import unicodedata
import requests

BASE = "https://www.turf-france.com/php/reu.php"
HDRS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0.0.0 Safari/537.36"}

LABELS = [
    ("chevaux", "chevaux", 10),
    ("drivers", "drivers", 10),
    ("entraineurs", "entraineurs", 10),
    ("topCotesDirect", "top cotes direct", 10),
    ("topChevaux", "top chevaux", 10),
    ("topPalmares", "top palmares", 10),
    ("topForme", "top forme", 10),
    ("topClasse", "top classe", 10),
    ("topDrivers", "top drivers", 10),
    ("topEntraineurs", "top entraineurs", 10),
    ("aptitude1er", "aptitude 1er", 10),
    ("aptitudePlace", "aptitude place", 10),
    ("topChronos", "top chronos", 10),
    ("topPosition", "top position", 10),
    ("ecarts", "ecarts chevaux", 10),
    ("incontournables", "incontournables", 10),
    ("pourUnePlace", "pour une place", 10),
    ("outsiders", "outsiders", 10),
    ("synthese", "la synthese", 8),
]


def _norm(s):
    s = unicodedata.normalize("NFD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s)
    return s.lower()


def parse_tops(html):
    txt = _norm(html)
    anchor = txt.find("top10")
    pos = []
    for key, label, mx in LABELS:
        idx = txt.find(label)
        while idx >= 0 and idx < anchor:
            idx = txt.find(label, idx + 1)
        if idx >= 0:
            pos.append((key, idx + len(label), mx))
    pos.sort(key=lambda x: x[1])
    out = {}
    for i, (key, start, mx) in enumerate(pos):
        end = len(txt)
        for _, label, _ in LABELS:
            j = txt.find(label, start)
            if j >= 0:
                end = min(end, j)
        seg = txt[start:end]
        nums = [int(x) for x in re.findall(r"\d+", seg) if 1 <= int(x) <= 30][:mx]
        out[key] = nums
    return out


def fetch_tops(date, reunion, course, pays="FRANCE"):
    r = requests.get(BASE, params={"view": "detail", "date": date, "reunion": reunion,
                                   "course": course, "pays": pays},
                     headers=HDRS, timeout=25)
    r.encoding = "utf-8"
    html = r.text
    if not html or len(html) < 5000:
        raise ValueError("empty page")
    tops = parse_tops(html)
    if not tops.get("synthese"):
        raise ValueError("no synthese")
    return tops
