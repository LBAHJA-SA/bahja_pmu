"""Scraper for https://www.pronostics-turf.info/ (presse Quinté synthèse).
Daily source: homepage shows tomorrow's Quinté + ordered 16-horse synthèse
(Position/Numéro/Fois cité) + today's result.
"""
import re
import requests
from datetime import datetime

BASE = "https://www.pronostics-turf.info"
HDRS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    )
}

MONTHS_FR = {
    "janvier": "01", "fevrier": "02", "février": "02", "mars": "03",
    "avril": "04", "mai": "05", "juin": "06", "juillet": "07",
    "aout": "08", "août": "08", "septembre": "09", "octobre": "10",
    "novembre": "11", "decembre": "12", "décembre": "12",
}


def _norm(s):
    import unicodedata
    s = unicodedata.normalize("NFD", str(s or ""))
    return "".join(c for c in s if not unicodedata.combining(c))


def parse_fr_date(s):
    """'Mardi 15 Septembre 2026' -> '2026-09-15'"""
    m = re.search(r"(\d{1,2})\s+([a-zéû]+)\s+(\d{4})", _norm(s), re.I)
    if not m:
        return None
    day, month, year = m.group(1), m.group(2).lower(), m.group(3)
    mm = MONTHS_FR.get(month)
    if not mm:
        return None
    return f"{year}-{mm}-{int(day):02d}"


def fetch_homepage():
    r = requests.get(BASE + "/", headers=HDRS, timeout=25)
    r.encoding = "utf-8"
    return r.text


def parse_quinte_label(html):
    """'QUINTE DE MEHUN-SUR-YEVRE A VINCENNES, le Jeudi 17 Septembre 2026'.
    Robust to &nbsp; entities and bad encodings (Y?VRE)."""
    import html as _html
    import unicodedata
    txt = _html.unescape(re.sub(r"<[^>]+>", " ", html))
    txt = txt.replace("’", "'").replace("‘", "'")
    txt = re.sub(r"\s+", " ", txt)
    m = None
    # Anchor near LISTE RECAPITULATIVE so page CSS/headers can't hijack the match.
    # Try each QUINTE occurrence (last first) — an early QUINTE inside promo text
    # would otherwise swallow the real label inside one long match.
    anchor = txt.find("LISTE RECAPITULATIVE")
    seg = txt[max(0, anchor - 600):anchor] if anchor >= 0 else txt
    starts = [mm.start() for mm in re.finditer(r"QUINTE", seg)]
    for s in sorted(starts, reverse=True):
        cand = re.match(r"QUINTE\s+(.+?)\s+A\s+([^,]+?),\s*le\s+(\w+\s+\d{1,2}\s+\S+\s+\d{4})", seg[s:s + 300])
        if cand and len(cand.group(1)) < 60 and len(cand.group(2)) < 30:
            m = cand
            break
    if not m:
        return {}
    prix = m.group(1).strip().replace("�", "E")
    hippo = re.sub(r"\s+", " ", m.group(2)).strip()
    date = parse_fr_date(m.group(3))
    if not date or len(prix) >= 60 or len(hippo) >= 30:
        return {}
    hippo = hippo.replace("?", "E")
    hippo = unicodedata.normalize("NFD", hippo)
    hippo = "".join(c for c in hippo if not unicodedata.combining(c))
    hippo = re.sub(r"[^A-Z\- ']", "", hippo.upper()).strip()
    return {"prix": prix, "hippodrome": hippo, "date": date}


def parse_synthese(html):
    """Ordered horse numbers from LISTE RECAPITULATIVE.
    Row: <img pronostic-N.gif> + <td class=big16>NUMERO</td> + <td>fois</td>."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        return []
    soup = BeautifulSoup(html, "html.parser")
    out = []
    for tr in soup.find_all("tr"):
        tds = tr.find_all("td")
        if len(tds) < 3:
            continue
        img = tds[0].find("img", src=re.compile(r"pronostic-\d+\.gif"))
        if not img:
            continue
        m = re.search(r"pronostic-(\d+)\.gif", img.get("src", ""))
        if not m:
            continue
        rank = int(m.group(1))
        try:
            num = int(re.sub(r"\D", "", tds[1].get_text()))
        except ValueError:
            continue
        if not 1 <= num <= 30:
            continue
        out.append((rank, num))
    out.sort(key=lambda x: x[0])
    seen = set()
    nums = []
    for rank, num in out:
        if 1 <= rank <= 16 and num not in seen:
            seen.add(num)
            nums.append(num)
    return nums


def parse_resultat(html):
    """"Résultat QUINTE d'aujourd'hui Lundi 14 Septembre 2026: 6 - 10 - 9 - 13 - 14\""""
    m = re.search(r"[Rr][eé]sultat\s+QUINTE.*?(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)\s*-\s*(\d+)",
                  html)
    if not m:
        return None, None
    # date near the result label
    dm = re.search(r"[Rr][eé]sultat\s+QUINTE\s+d'aujourd'hui\s+(\w+\s+\d{1,2}\s+\w+\s+\d{4})", html)
    date = parse_fr_date(dm.group(1)) if dm else None
    nums = [int(m.group(i)) for i in range(1, 6)]
    return date, nums


def fetch_daily():
    """Returns dict: {date, hippodrome, prix, synthese[16], resultat_date, resultat[5]}"""
    html = fetch_homepage()
    label = parse_quinte_label(html)
    nums = parse_synthese(html)
    res_date, res_nums = parse_resultat(html)
    return {
        "date": label.get("date"),
        "hippodrome": label.get("hippodrome"),
        "prix": label.get("prix"),
        "synthese": nums,
        "resultat_date": res_date,
        "resultat": res_nums,
        "fetched_at": datetime.utcnow().isoformat(),
    }
