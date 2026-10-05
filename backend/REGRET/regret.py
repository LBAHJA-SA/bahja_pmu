"""
REGRET - Architecture finale validée sur 63 races (R1+R2, 03-07/09).

SHALK = Primary Trio (ne pas toucher)
OLD DNA = Race-pattern confirmation (ne pas toucher)
P3 Gate = FAV-heavy → historical P3 OUT/TOC (65% vs 32.6%)
  ├── OUT → p3_out_selector: ranking par top3_4 DESC, tie-break form_avg (pas de bonus)
  │         Rank1 → P3 principal | Rank2 → secondary | Rank3+ → faible
  └── TOC → segmentation only, pas de selector

No bonus, no weights, no SHALK modification.
"""
from collections import Counter, defaultdict
from database import get_db
try:
    from .fingerprint import _ensure_perf_index, _band, _pct, _avg, _POIDS_BANDS, _VALEUR_BANDS
except ImportError:
    from fingerprint import _ensure_perf_index, _band, _pct, _avg, _POIDS_BANDS, _VALEUR_BANDS

# DNA historique : on garde race_dna comme référence conceptuelle,
# mais REGRET reste autonome (pas d'import croisé) pour éviter deux moteurs divergents.

_REGRET_CACHE = {"__all__": None}
_ODDS_BANDS = ((1.5, 3.0), (3.0, 5.0), (5.0, 8.0), (8.0, 12.0), (12.0, 20.0), (20.0, None))

def p3_out_selector(out_candidates):
    """P3 OUT selector — ranking فقط، لا bonus، لا score modification.
    candidates: list of dicts avec top3_4 et form_avg.
    Retourne le meilleur OUT pour P3.
    """
    if not out_candidates:
        return None
    return sorted(out_candidates, key=lambda h: (-(h.get("top3_4") or 0), h.get("form_avg", 999), h.get("num", 999)))[0]

def p3_toc_segmentation(toc_candidates):
    """TOC — segmentation فقط، pas de selector."""
    return toc_candidates  # pas de choix intelligent pour l'instant

def _horse_history_fast(conn, horse, cutoff_date=None):
    """Historique rapide pour REGRET : rides/wins/top3 + 5 dernières sorties (INDEXED BY)."""
    if not horse:
        return {"rides": 0, "wins": 0, "places23": 0, "win_rate": 0, "recent": []}
    key = str(horse).strip()
    if not key:
        return {"rides": 0, "wins": 0, "places23": 0, "win_rate": 0, "recent": []}
    # Une seule requête pour tout
    try:
        if cutoff_date:
            rows = conn.execute(
                "SELECT p.rang, p.cote_pmu, r.date, r.hippodrome, r.distance, p.poids, p.valeur "
                "FROM participants p INDEXED BY idx_participants_horse_nocase "
                "JOIN races r INDEXED BY sqlite_autoindex_races_1 ON r.race_id = p.race_id "
                "WHERE p.horse = ? COLLATE NOCASE AND r.date < ? ORDER BY r.date DESC LIMIT 5",
                (key, str(cutoff_date)[:10])
            ).fetchall()
            cnt = conn.execute(
                "SELECT COUNT(*) as rides, SUM(CASE WHEN p.rang=1 THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN p.rang IN (2,3) THEN 1 ELSE 0 END) as places "
                "FROM participants p INDEXED BY idx_participants_horse_nocase "
                "JOIN races r ON r.race_id = p.race_id WHERE p.horse = ? COLLATE NOCASE AND r.date < ?",
                (key, str(cutoff_date)[:10])
            ).fetchone()
        else:
            rows = conn.execute(
                "SELECT p.rang, p.cote_pmu, r.date, r.hippodrome, r.distance, p.poids, p.valeur "
                "FROM participants p INDEXED BY idx_participants_horse_nocase "
                "JOIN races r ON r.race_id = p.race_id WHERE p.horse = ? COLLATE NOCASE ORDER BY r.date DESC LIMIT 5",
                (key,)
            ).fetchall()
            cnt = conn.execute(
                "SELECT COUNT(*) as rides, SUM(CASE WHEN p.rang=1 THEN 1 ELSE 0 END) as wins, SUM(CASE WHEN p.rang IN (2,3) THEN 1 ELSE 0 END) as places "
                "FROM participants p INDEXED BY idx_participants_horse_nocase "
                "JOIN races r ON r.race_id = p.race_id WHERE p.horse = ? COLLATE NOCASE",
                (key,)
            ).fetchone()
        rides = cnt["rides"] or 0; wins = cnt["wins"] or 0; places = cnt["places"] or 0
        recent = [{"rang": r["rang"], "cote_pmu": r["cote_pmu"], "date": r["date"], "hippodrome": r["hippodrome"], "distance": r["distance"], "poids": r["poids"], "valeur": r["valeur"]} for r in rows]
        return {"rides": rides, "wins": wins, "places23": places, "win_rate": round(wins/rides*100,1) if rides else 0, "recent": recent}
    except Exception:
        return {"rides": 0, "wins": 0, "places23": 0, "win_rate": 0, "recent": []}

def _cat_odds(cote):
    if cote is None:
        return "UNK"
    try: v=float(cote)
    except: return "UNK"
    if v < 8: return "FAV"
    if v < 15: return "OUT"
    return "TOC"

def _profile_for_rows(rows):
    poids_bands = Counter(); valeur_bands = Counter(); odds_bands = Counter(); odds_vals = []
    for r in rows:
        pb = _band(r["poids"], _POIDS_BANDS)
        if pb: poids_bands[pb] += 1
        vb = _band(r["valeur"], _VALEUR_BANDS)
        if vb: valeur_bands[vb] += 1
        ob = _band(r["cote_pmu"], _ODDS_BANDS)
        if ob: odds_bands[ob] += 1
        if r["cote_pmu"] is not None:
            try: odds_vals.append(float(r["cote_pmu"]))
            except: pass
    top = lambda c: (c.most_common(1)[0][0] if c else None)
    return {
        "hits": len(rows), "avg_odds": _avg(odds_vals),
        "top_odds_band": top(odds_bands), "top_poids_band": top(poids_bands), "top_valeur_band": top(valeur_bands),
        "poids_bands": dict(poids_bands), "valeur_bands": dict(valeur_bands), "odds_bands": dict(odds_bands),
    }

def _regret_outsider_profile(rows, n_races):
    """Regret DNA مستقل: بصمة الأوتسايدرات الذين ضربوا البوديوم، لا كل Top3."""
    outs = [r for r in rows if r.get("cote_pmu") is not None and float(r["cote_pmu"]) >= 15]
    if not outs:
        return {"hits": 0, "outsider_rate": 0, "poids_bands": {}, "valeur_bands": {}, "odds_bands": {}, "top_odds_band": None, "top_poids_band": None, "top_valeur_band": None}
    prof = _profile_for_rows(outs)
    # أين يضرب الأوتسايدر أكثر: P1/P2/P3 ؟
    by_pos = Counter(r["rang"] for r in outs)
    prof["hits"] = len(outs)
    prof["outsider_rate"] = round(len(outs)/max(len(rows),1)*100,1)
    prof["by_pos"] = dict(by_pos)
    prof["by_pos_pct"] = {k: round(v/len(outs)*100,1) for k,v in by_pos.items()}
    return prof

def _top3_profile(rows, n_races):
    p1_rows = [r for r in rows if r["rang"] == 1]
    p2_rows = [r for r in rows if r["rang"] == 2]
    p3_rows = [r for r in rows if r["rang"] == 3]
    p1 = _profile_for_rows(p1_rows)
    p2 = _profile_for_rows(p2_rows)
    p3 = _profile_for_rows(p3_rows)
    by_race = defaultdict(list)
    for r in rows:
        by_race[r["race_id"]].append(r)
    scenario_counter = Counter()
    scenario_gaps = defaultdict(lambda: {"p1_p2": [], "p2_p3": [], "p1_p3": []})
    fav_counts = []; out_counts = []; toc_counts = []
    gap_p1_p2 = []; gap_p2_p3 = []; gap_p1_p3 = []
    price_dist = Counter()
    for rid, lst in by_race.items():
        d = {x["rang"]: x for x in lst}
        if not all(k in d for k in (1,2,3)):
            continue
        c1, c2, c3 = _cat_odds(d[1]["cote_pmu"]), _cat_odds(d[2]["cote_pmu"]), _cat_odds(d[3]["cote_pmu"])
        scen = f"P1={c1}+P2={c2}+P3={c3}"
        scenario_counter[scen] += 1
        cats = [c1,c2,c3]
        fav_counts.append(cats.count("FAV")); out_counts.append(cats.count("OUT")); toc_counts.append(cats.count("TOC"))
        for c in cats: price_dist[c] += 1
        try:
            o1, o2, o3 = float(d[1]["cote_pmu"] or 0), float(d[2]["cote_pmu"] or 0), float(d[3]["cote_pmu"] or 0)
            if o1 and o2:
                v = round(o2 - o1, 1); gap_p1_p2.append(v); scenario_gaps[scen]["p1_p2"].append(v)
            if o2 and o3:
                v = round(o3 - o2, 1); gap_p2_p3.append(v); scenario_gaps[scen]["p2_p3"].append(v)
            if o1 and o3:
                v = round(o3 - o1, 1); gap_p1_p3.append(v); scenario_gaps[scen]["p1_p3"].append(v)
        except: pass
    poids_bands = Counter(); valeur_bands = Counter(); odds_bands = Counter(); odds_vals=[]
    for r in rows:
        pb=_band(r["poids"], _POIDS_BANDS)
        if pb: poids_bands[pb]+=1
        vb=_band(r["valeur"], _VALEUR_BANDS)
        if vb: valeur_bands[vb]+=1
        ob=_band(r["cote_pmu"], _ODDS_BANDS)
        if ob: odds_bands[ob]+=1
        if r["cote_pmu"] is not None:
            try: odds_vals.append(float(r["cote_pmu"]))
            except: pass
    top=lambda c:(c.most_common(1)[0][0] if c else None)
    top_scenario = scenario_counter.most_common(1)[0][0] if scenario_counter else None
    def _avg_list(lst): return round(sum(lst)/len(lst),1) if lst else None
    def _gap_stats(lst):
        if not lst: return {"avg":None,"median":None,"p80":None}
        s=sorted(lst); return {"avg":_avg_list(lst),"median":s[len(s)//2],"p80":s[int(len(s)*0.8)] if len(s)>4 else s[-1],"min":min(lst),"max":max(lst)}
    regret_dna = _regret_outsider_profile(rows, n_races)
    return {
        "top3_hits": len(rows), "races_in_scope": n_races,
        "top3_rate_pct": _pct(len(rows), n_races), "avg_odds": _avg(odds_vals),
        "top_odds_band": top(odds_bands), "top_poids_band": top(poids_bands), "top_valeur_band": top(valeur_bands),
        "poids_bands": dict(poids_bands), "valeur_bands": dict(valeur_bands), "odds_bands": dict(odds_bands),
        "hippo_samples": len(rows),
        "p1": p1, "p2": p2, "p3": p3,
        "p1_rate": _pct(len(p1_rows), n_races), "p2_rate": _pct(len(p2_rows), n_races), "p3_rate": _pct(len(p3_rows), n_races),
        "regret_dna": regret_dna,
        "scenario_counter": dict(scenario_counter),
        "top_scenario": top_scenario,
        "scenario_top3": [{"scenario":k,"count":v,"pct":round(v/n_races*100,1) if n_races else 0} for k,v in scenario_counter.most_common(8)],
        "scenario_fingerprint": {
            "avg_fav_per_top3": _avg_list(fav_counts),
            "avg_out_per_top3": _avg_list(out_counts),
            "avg_toc_per_top3": _avg_list(toc_counts),
            "price_dist": dict(price_dist),
            "price_dist_pct": {k: round(v/len(rows)*100,1) if rows else 0 for k,v in price_dist.items()},
            "gap_p1_p2": _gap_stats(gap_p1_p2),
            "gap_p2_p3": _gap_stats(gap_p2_p3),
            "gap_p1_p3": _gap_stats(gap_p1_p3),
        },
        "scenario_gaps": {k: {gk: _gap_stats(v) for gk, v in gaps.items()} for k, gaps in scenario_gaps.items()},
    }

def _load_top3_raw(key, distance=None, discipline=None):
    from database import hippodrome_in_clause
    conn = get_db(); _ensure_perf_index(conn)
    # Phase 1 — race ids first (small, indexed), then participants by id.
    # The old single JOIN scanned ~1.5M participant rows per track.
    rwhere = ["runners >= 5"]
    rparams = []
    if key != "__all__":
        hclause, hparams = hippodrome_in_clause(conn, "hippodrome", key)
        if hclause != "1=1":
            rwhere.append(f"({hclause})")
            rparams.extend(hparams)
    if distance:
        try:
            d = float(distance)
            rwhere.append("distance BETWEEN ? AND ?")
            rparams.extend([d - 200, d + 200])
        except: pass
    if discipline:
        rwhere.append("UPPER(discipline) = UPPER(?)")
        rparams.append(str(discipline).strip())
    race_rows = conn.execute(
        "SELECT race_id, date FROM races WHERE " + " AND ".join(rwhere), tuple(rparams)).fetchall()
    race_ids = [r["race_id"] for r in race_rows]
    race_dates = [r["date"] for r in race_rows]
    date_of = {r["race_id"]: r["date"] for r in race_rows}
    rows = []
    for i in range(0, len(race_ids), 2000):
        chunk = race_ids[i:i + 2000]
        ph = ",".join("?" * len(chunk))
        rows.extend(conn.execute(
            "SELECT p.rang, p.poids, p.valeur, p.cote_pmu, p.race_id FROM participants p "
            f"WHERE p.race_id IN ({ph}) AND p.rang IN (1, 2, 3)", chunk).fetchall())
    dict_rows_all = [{"rang": r["rang"], "poids": r["poids"], "valeur": r["valeur"], "cote_pmu": r["cote_pmu"], "date": date_of.get(r["race_id"]), "race_id": r["race_id"]} for r in rows]
    # HISTORICAL RACE DNA : tous les Top3 (pas de filtre cote) — le filtre REGRET vient après
    dict_rows = dict_rows_all
    conn.close()
    n_races = len(race_dates)
    prof = _top3_profile(dict_rows, n_races)
    prof["scoped"] = key != "__all__"; prof["hippodrome_scope"] = None if key == "__all__" else key
    prof["_rows"] = dict_rows; prof["_rows_all"] = dict_rows_all; prof["_race_dates"] = race_dates
    return prof

def _top3_fingerprint(hippodrome=None, cutoff_date=None):
    from database import hippodrome_tokens
    toks = hippodrome_tokens(hippodrome)
    key = "+".join(sorted(toks)) if toks else "__all__"
    base = _REGRET_CACHE.get(key)
    if base is None:
        base = _load_top3_raw(key)
        _REGRET_CACHE[key] = base
    if not cutoff_date:
        out = {k:v for k,v in base.items() if not k.startswith("_")}
        return out
    cut = str(cutoff_date)[:10]
    rows = [r for r in base["_rows"] if str(r["date"] or "")[:10] < cut]
    n_races = sum(1 for d in base["_race_dates"] if str(d or "")[:10] < cut)
    return _top3_profile(rows, n_races)

def analyze_regret(participants, hippodrome="", distance=0, discipline="", race_date=None, min_odds=12.0,
                   coherent_top3=None, coherent_info=None, p2p3_allocation=False, audit=False):
    _audit = {"candidates": [], "outsiders": [], "by_band": {}, "ranked": []} if audit else None
    """coherent_top3: optional [p1_num, p2_num, p3_num] from COUPLE DNA V3.
    When provided, the Regret pick is derived from the SAME scenario
    (P4 = nearest following horse by market order), no separate DNA.
    p2p3_allocation: when True, the final pick strictly respects P2/P3
    allocation (P3 principal + P2 from target_p==p2) instead of ranked[:2].
    Default False (legacy) — enable only for A/B testing."""
    """Moteur REGRET DNA 4 étapes : Scenario actuel -> Match historique -> Allocation P -> Cheval."""
    if not participants:
        return None
    # --- Normalisation ---
    norm = []
    for p in participants:
        if not isinstance(p, dict): continue
        q = dict(p)
        q["horse"] = q.get("horse") or q.get("nom") or ""
        q["jockey"] = q.get("jockey") or q.get("driver") or ""
        q["num"] = q.get("num") or q.get("numPmu")
        try: q["cote_pmu"] = float(q.get("cote_pmu") if q.get("cote_pmu") is not None else q.get("cote") if q.get("cote") is not None else q.get("odds"))
        except: q["cote_pmu"] = None
        try:
            pv = float(q.get("poids")) if q.get("poids") is not None else None
            if pv is not None and pv > 300: pv = round(pv/10,1)
            if pv is not None and not (35 <= pv <= 100): pv = None
            q["poids"] = pv
        except: q["poids"] = None
        try: q["valeur"] = float(q.get("valeur")) if q.get("valeur") is not None else None
        except: q["valeur"] = None
        q["etat"] = str(p.get("etat") or p.get("status") or p.get("incident") or "").upper()
        norm.append(q)
    participants = [p for p in norm if p.get("num") is not None]
    participants = [p for p in participants if p.get("etat") not in ("NP", "NON_PARTANT", "FORFAIT", "DECLARED_NON_RUNNER")]
    fingerprint = _top3_fingerprint(hippodrome, cutoff_date=race_date)
    priced = sorted([(p["cote_pmu"], p["num"]) for p in participants if p["cote_pmu"] is not None and p["cote_pmu"] > 0])
    rank_by_num = {num: i+1 for i, (_, num) in enumerate(priced)}
    n_market = len(priced)

    # ============================================================
    # ÉTAPE 1 : Scenario actuel (marché)
    # ============================================================
    # Top3 marché actuel (par cote croissante)
    current_top3 = sorted([p for p in participants if p["cote_pmu"] is not None], key=lambda x: x["cote_pmu"])[:3]
    current_cats = [_cat_odds(p["cote_pmu"]) for p in current_top3]
    # Si marché mort (cote null partout), on ne peut pas construire scénario actuel -> on utilise distribution globale
    if len(current_cats) < 3:
        # fallback : on prend les 3 premiers par num
        current_cats = [_cat_odds(p.get("cote_pmu")) for p in participants[:3]]
    current_scenario = f"P1={current_cats[0] if len(current_cats)>0 else 'UNK'}+P2={current_cats[1] if len(current_cats)>1 else 'UNK'}+P3={current_cats[2] if len(current_cats)>2 else 'UNK'}"
    current_counts = Counter(current_cats)
    # gaps actuels
    try:
        cur_o = [float(p["cote_pmu"]) for p in current_top3 if p["cote_pmu"] is not None]
        cur_gap_p1_p2 = round(cur_o[1]-cur_o[0],1) if len(cur_o)>=2 else None
        cur_gap_p2_p3 = round(cur_o[2]-cur_o[1],1) if len(cur_o)>=3 else None
        cur_gap_p1_p3 = round(cur_o[2]-cur_o[0],1) if len(cur_o)>=3 else None
    except: cur_gap_p1_p2 = cur_gap_p2_p3 = cur_gap_p1_p3 = None
    current_distribution = dict(current_counts)

    # ============================================================
    # ÉTAPE 2 : Match vs TOUS les scénarios historiques (pas seulement top_scenario)
    # ============================================================
    scenario_counter = fingerprint.get("scenario_counter") or {}
    total_scen_races = fingerprint.get("races_in_scope") or 1
    # Pour chaque scénario historique, calculer similarité avec scénario actuel
    scenario_scores = []
    for scen, cnt in scenario_counter.items():
        # 2a. Similarité structurelle : combien de P matchent ?
        try:
            scen_parts = scen.split("+")  # P1=FAV etc.
            scen_cats = [s.split("=")[1] for s in scen_parts]
        except: scen_cats = []
        # current_cats vs scen_cats : nb positions identiques
        struct_match = sum(1 for a,b in zip(current_cats, scen_cats) if a==b) / 3.0  # 0..1
        # 2b. Fréquence historique
        freq = cnt / total_scen_races  # 0..1
        # 2c. Gap similarity
        hist_gap = fingerprint.get("scenario_fingerprint",{}).get("gap_p1_p2",{}).get("avg")
        gap_sim = 0.5
        if cur_gap_p1_p2 is not None and hist_gap is not None and hist_gap:
            try: gap_sim = max(0, 1 - abs(cur_gap_p1_p2 - hist_gap) / max(hist_gap, 5))
            except: gap_sim = 0.5
        # 2d. Distribution similarity (nb FAV/OUT/TOC)
        hist_dist = fingerprint.get("scenario_fingerprint",{}).get("price_dist",{})
        # current_counts vs hist price_dist : on compare pct
        # hist price_dist est global podium, pas par scénario, donc on approxime via scénario lui-même
        # Pour ce scénario, on compte ses FAV/OUT/TOC
        scen_fav = scen.count("FAV"); scen_out = scen.count("OUT"); scen_toc = scen.count("TOC")
        cur_fav = current_counts.get("FAV",0); cur_out = current_counts.get("OUT",0); cur_toc = current_counts.get("TOC",0)
        dist_sim = 1 - (abs(scen_fav-cur_fav)+abs(scen_out-cur_out)+abs(scen_toc-cur_toc))/6.0
        dist_sim = max(0, dist_sim)
        # Score global : structure 50% + fréquence 30% + gap 10% + dist 10%
        # Mais on veut que le scénario qui ressemble au marché actuel gagne, pas le plus fréquent
        match_pct = round((struct_match*0.5 + freq*0.3 + gap_sim*0.1 + dist_sim*0.1)*100,1)
        scenario_scores.append({"scenario": scen, "count": cnt, "rate": round(cnt/total_scen_races*100,1), "struct_match": round(struct_match*100,1), "freq": round(freq*100,1), "gap_sim": round(gap_sim*100,1), "dist_sim": round(dist_sim*100,1), "match_pct": match_pct, "gap_avg": hist_gap})
    scenario_scores.sort(key=lambda x: -x["match_pct"])
    best_scenario = scenario_scores[0] if scenario_scores else None
    # On garde top 3 scénarios pour fallback
    top_scenarios = scenario_scores[:3]

    # ============================================================
    # ÉTAPE 3 : Allocation P correcte (si FAV+FAV+TOC, FAV#1->P1, FAV#2->P2)
    # ============================================================
    # On doit allouer les chevaux actuels aux P du best_scenario sans écraser P1
    # Ex: best = FAV+FAV+TOC, current a 2 FAV (cote 4 et 5) -> #1->P1, #2->P2, TOC->P3
    # On trie les candidats actuels par cote (pour allocation marché)
    sorted_by_cote = sorted([p for p in participants if p["cote_pmu"] is not None], key=lambda x: x["cote_pmu"])
    # Map num -> target_p via allocation ordonnée
    alloc_map = {}
    if best_scenario:
        try:
            best_cats = [s.split("=")[1] for s in best_scenario["scenario"].split("+")]
        except: best_cats = ["FAV","OUT","TOC"]
        # Pour chaque catégorie dans best_scenario, allouer dans l'ordre du marché actuel
        # On parcourt P1,P2,P3 et on cherche le prochain cheval non alloué de cette catégorie
        used = set()
        for idx, cat_needed in enumerate(best_cats):
            pkey = f"p{idx+1}"
            # trouver le prochain cheval de cette catégorie non utilisé, dans l'ordre cote
            found = None
            for cand in sorted_by_cote:
                if cand["num"] in used: continue
                if _cat_odds(cand["cote_pmu"]) == cat_needed:
                    found = cand; break
            # si pas trouvé (ex: besoin TOC mais aucun TOC, prendre le plus proche)
            if not found:
                # prendre le prochain non utilisé
                for cand in sorted_by_cote:
                    if cand["num"] not in used:
                        found = cand; break
            if found:
                alloc_map[found["num"]] = pkey
                used.add(found["num"])
        # Pour les chevaux restants (hors top3 marché), allouer par proximité catégorie
        for cand in sorted_by_cote:
            if cand["num"] not in alloc_map:
                # trouver le P où sa catégorie apparaît, sinon p3
                c = _cat_odds(cand["cote_pmu"])
                # chercher où c apparaît dans best_cats
                if c in best_cats:
                    # allouer au premier P non pris de cette catégorie
                    for idx, bc in enumerate(best_cats):
                        pk = f"p{idx+1}"
                        if bc == c and pk not in alloc_map.values():
                            alloc_map[cand["num"]] = pk; break
                    else:
                        alloc_map[cand["num"]] = "p3"
                else:
                    alloc_map[cand["num"]] = "p3" if c == "TOC" else "p2" if c == "OUT" else "p1"
        # Pour les sans cote (NP déjà filtrés, mais au cas où)
        for p in participants:
            if p["num"] not in alloc_map:
                alloc_map[p["num"]] = "p3" if _cat_odds(p["cote_pmu"]) == "TOC" else "p2" if _cat_odds(p["cote_pmu"]) == "OUT" else "p1"
    else:
        # fallback : ancien mapping simple cat->P
        for p in participants:
            c = _cat_odds(p["cote_pmu"])
            alloc_map[p["num"]] = "p3" if c == "TOC" else "p2" if c == "OUT" else "p1"

    # ============================================================
    # ÉTAPE 4 : REGRET = DNA match dans le scénario (gap utilisé)
    # ============================================================
    p1_top_poids = fingerprint.get("p1",{}).get("top_poids_band")
    p1_top_valeur = fingerprint.get("p1",{}).get("top_valeur_band")
    p2_top_poids = fingerprint.get("p2",{}).get("top_poids_band")
    p2_top_valeur = fingerprint.get("p2",{}).get("top_valeur_band")
    p3_top_poids = fingerprint.get("p3",{}).get("top_poids_band")
    p3_top_valeur = fingerprint.get("p3",{}).get("top_valeur_band")

    # History rapide pour REGRET (évite "Aucun historique" sur MARTAGHALYA/BASQUIAT)
    hist_conn = None
    try:
        hist_conn = get_db()
        _ensure_perf_index(hist_conn)
    except:
        hist_conn = None
    # Plot tiebreak (intentions mesurées) — annotation + départage uniquement,
    # jamais de bonus de score (architecture REGRET: pas de bonus).
    plot_map = {}
    try:
        from signals.plot_signals import compute_field_plot
        if hist_conn is not None:
            plot_map = compute_field_plot(hist_conn, participants, before=race_date,
                                          cur_dist=distance or None)
    except Exception:
        plot_map = {}
    candidates = []
    for p in participants:
        num = p["num"]; cote = p["cote_pmu"]; rank = rank_by_num.get(num, 999 if n_market==0 else n_market+1)
        if cote is None and n_market >= 3:
            continue
        cat = _cat_odds(cote)
        is_outsider = (cote is not None and cote >= 15) or (rank >= 6)
        target_p = alloc_map.get(num, "p3")
        # Si scénario dominant n'a pas ce target_p, fallback
        if target_p not in ("p1","p2","p3"):
            target_p = "p3"
        # Historique du cheval (évite "Aucun historique" sur MARTAGHALYA)
        hist = _horse_history_fast(hist_conn, p["horse"], cutoff_date=race_date) if hist_conn else {"rides":0, "wins":0, "places23":0, "win_rate":0, "recent":[]}

        breakdown = {}; score = 0.0; points = {}
        # 1. DNA du scénario (le score vient du match, pas l'inverse)
        if best_scenario:
            scen_match = best_scenario["match_pct"]
            # Le score de base est le match du scénario (0-100 -> 0-18)
            scen_pts = round(scen_match * 0.18,1)
            breakdown["Scénario podium"] = f"{best_scenario['scenario']} match {scen_match}% ({best_scenario['count']} courses, {best_scenario['rate']}%) — {target_p} attendu {best_scenario['scenario'].split('+')[int(target_p[1])-1].split('=')[1]} (+{scen_pts})"
            score += scen_pts; points["scenario"] = scen_pts
            # Gap DNA : du scénario matched, pas global
            cur_gap = cur_gap_p1_p2 if target_p=="p2" else cur_gap_p1_p3 if target_p=="p3" else None
            scen_key = best_scenario.get("scenario") if best_scenario else None
            hist_gap_avg = None
            if scen_key:
                sg = fingerprint.get("scenario_gaps",{}).get(scen_key, {})
                hist_gap_avg = sg.get("p1_p2",{}).get("avg") if target_p=="p2" else sg.get("p1_p3",{}).get("avg")
            if hist_gap_avg is None:
                hist_gap_avg = fingerprint.get("scenario_fingerprint",{}).get("gap_p1_p2",{}).get("avg") if target_p=="p2" else fingerprint.get("scenario_fingerprint",{}).get("gap_p1_p3",{}).get("avg")
            if cur_gap is not None and hist_gap_avg:
                gap_diff = abs(cur_gap - hist_gap_avg)
                gap_pts = max(0, 6 - gap_diff*0.5)  # 6 max, -0.5 par point d'écart
                gap_pts = round(gap_pts,1)
                if gap_pts > 1:
                    breakdown[f"Gap {target_p}"] = f"écart actuel {cur_gap} vs hist {hist_gap_avg} (+{gap_pts})"
                    score += gap_pts; points["gap"] = gap_pts
        else:
            points["scenario"] = 0

        # 2. Empreinte P ciblée (poids/valeur/cote du P alloué)
        fp_pts = 0
        ref_poids = {"p1": p1_top_poids, "p2": p2_top_poids, "p3": p3_top_poids}.get(target_p)
        ref_valeur = {"p1": p1_top_valeur, "p2": p2_top_valeur, "p3": p3_top_valeur}.get(target_p)
        ref_profile = fingerprint.get(target_p, {}) if target_p else {}
        pb = _band(p.get("poids"), _POIDS_BANDS)
        vb = _band(p.get("valeur"), _VALEUR_BANDS)
        if pb and pb == ref_poids:
            fp_pts += 14; breakdown[f"Empreinte {target_p} poids"] = f"poids {p['poids']}kg bande {pb} = top {target_p} (+14)"
        elif pb and ref_profile.get("poids_bands",{}).get(pb,0) > 0:
            fp_pts += 7; breakdown[f"Empreinte {target_p} poids"] = f"poids {pb} présent {target_p} (+7)"
        if vb and vb == ref_valeur:
            fp_pts += 14; breakdown[f"Empreinte {target_p} valeur"] = f"valeur {vb} = top {target_p} (+14)"
        elif vb and ref_profile.get("valeur_bands",{}).get(vb,0) > 0:
            fp_pts += 7; breakdown[f"Empreinte {target_p} valeur"] = f"valeur {vb} présent {target_p} (+7)"
        ob = _band(cote, _ODDS_BANDS) if cote else None
        if ob and ref_profile.get("odds_bands",{}).get(ob,0) > 0:
            pct_p = ref_profile["odds_bands"][ob] / max(ref_profile.get("hits",1),1) *100
            add = 10 if pct_p >= 15 else 6 if pct_p >= 8 else 3
            fp_pts += add; breakdown[f"Empreinte {target_p} cote"] = f"bande cote {ob} {round(pct_p,1)}% des {target_p} (+{add})"
        score += fp_pts; points["empreinte_p"] = fp_pts; points["target_p"] = target_p

        if rank == 1 and n_market >= 3:
            malus = -2; score += malus; points["malus_favori"] = malus
            breakdown["Malus favori"] = "Favori n°1 — malus REGRET (-2)"

        grade = "Favori du marché" if rank == 1 else "Co-favori" if rank == 2 else "REGRET potentiel ⭐" if is_outsider and target_p in ("p2","p3") and fp_pts >= 14 else "Outsider podium" if is_outsider else "Hors scope"

        candidates.append({
            "num": num, "nom": p["horse"], "horse": p["horse"], "jockey": p["jockey"],
            "cote": cote, "odds_rank": rank, "runners": n_market or len(participants),
            "poids": p.get("poids"), "valeur": p.get("valeur"),
            "age": p.get("age"), "sexe": p.get("sexe"), "corde": p.get("corde"), "deferre": p.get("deferre",""),
            "gain": p.get("gain"), "musique": p.get("musique",""), "oeilleres": p.get("oeilleres"),
            "proprietaire": p.get("proprietaire",""), "trainer": p.get("trainer","") or p.get("entraineur",""),
            "score": round(score,1), "score_solide": round(score,1),
            "grade": grade, "breakdown": breakdown, "points": points,
            "eligible": is_outsider, "is_outsider": is_outsider, "target_p": target_p, "cat": cat,
            "history": hist, "jockey_stats": {}, "sire": None, "dam": None,
        })

    # Filtre par couche odds : pour REGRET on utilise regret_dna (outsiders qui ont frappé), pas tout Top3
    regret_dna = fingerprint.get("regret_dna") or {}
    # si regret_dna vide (peu d'outsiders), fallback sur Top3
    top3_hits = fingerprint.get("top3_hits") or 1
    if regret_dna.get("hits",0) >= 10:
        odds_bands_fp = regret_dna.get("odds_bands") or fingerprint.get("odds_bands") or {}
        band_pct = {band: cnt / max(regret_dna.get("hits",1),1) for band, cnt in odds_bands_fp.items()}
    else:
        odds_bands_fp = fingerprint.get("odds_bands") or {}
        band_pct = {band: cnt / top3_hits for band, cnt in odds_bands_fp.items()}
    for c in candidates:
        if not c["is_outsider"]: continue
        ob = _band(c["cote"], _ODDS_BANDS) if c["cote"] else None
        pct = band_pct.get(ob, 0) if ob else 0
        c["_fp_pct"] = round(pct*100,1); c["_fp_band"] = ob
        if pct < 0.06 and ob not in (fingerprint.get("top_odds_band"),) and c["cote"] is not None:
            c["breakdown"]["Couche rare"] = f"bande {ob} {round(pct*100,1)}% des podiums — moins fréquente"
    if _audit is not None:
        _audit["candidates"] = [(c.get("num"), c.get("target_p")) for c in candidates]
    outsiders = [c for c in candidates if c["is_outsider"]]
    if _audit is not None:
        _audit["outsiders"] = [(c.get("num"), c.get("target_p")) for c in outsiders]
    # Plot caché: meilleur profil contextuel parmi les outsiders (départage uniquement,
    # jamais de bonus — architecture REGRET).
    try:
        _h = sorted([c for c in outsiders
                     if (plot_map.get(c["num"]) or {}).get("ctx") is not None],
                    key=lambda c: -plot_map[c["num"]]["ctx"])
        for _i, _c in enumerate(_h, start=1):
            _c["_plot_hidden"] = _i
            if _i <= 2:
                _c["breakdown"]["Plot caché"] = f"profil caché outsiders #{_i} (forme contextuelle)"
        for c in outsiders:
            c.setdefault("_plot_hidden", 999)
            if (plot_map.get(c["num"]) or {}).get("first_d4"):
                c["_plot_d4"] = 1
                c["breakdown"]["Plot D4"] = "1er déferré des 4"
            else:
                c.setdefault("_plot_d4", 0)
    except Exception:
        for c in outsiders:
            c.setdefault("_plot_hidden", 999)
            c.setdefault("_plot_d4", 0)

    # by_band: legacy = one winner per band; experimental =
    # one slot per target (p2/p3) inside each band so a P2 never kills
    # a P3 (or vice versa) before final selection. Gated by p2p3_allocation
    # (legacy default) — same ordering, no new weights either way.
    by_band = {}
    for c in outsiders:
        band = c.get("_fp_band") or "sans cote"
        pkey = c.get("target_p") or "p3"
        slot = "p2" if pkey == "p2" else "p3"
        pb = _band(c.get("poids"), _POIDS_BANDS); vb = _band(c.get("valeur"), _VALEUR_BANDS)
        top_poids = {"p1": p1_top_poids, "p2": p2_top_poids, "p3": p3_top_poids}.get(pkey)
        top_valeur = {"p1": p1_top_valeur, "p2": p2_top_valeur, "p3": p3_top_valeur}.get(pkey)
        fp_match = (1 if pb == top_poids else 0) + (1 if vb == top_valeur else 0)
        c["_fp_match"] = fp_match
        bonus_out = 1 if c.get("odds_rank", 99) > 8 else 0
        c["_bonus_out"] = bonus_out
        # Pour départager même bande/même بصمة, on préfère la cote la plus proche de la moyenne historique du P ciblé (pas la plus haute ni la plus basse)
        p_avg = {"p1": fingerprint.get("p1",{}).get("avg_odds"), "p2": fingerprint.get("p2",{}).get("avg_odds"), "p3": fingerprint.get("p3",{}).get("avg_odds")}.get(pkey)
        # distance à la moyenne
        def _dist(cote, avg):
            try: return abs(float(cote)-float(avg)) if cote and avg else 999
            except: return 999
        if p2p3_allocation:
            cur = by_band.get(band, {}).get(slot)
            cur_avg = {"p1": fingerprint.get("p1",{}).get("avg_odds"), "p2": fingerprint.get("p2",{}).get("avg_odds"), "p3": fingerprint.get("p3",{}).get("avg_odds")}.get(cur.get("target_p") if cur else None) if cur else None
            if cur is None or fp_match > cur.get("_fp_match",0) or (fp_match == cur.get("_fp_match",0) and (bonus_out > cur.get("_bonus_out",0) or (bonus_out == cur.get("_bonus_out",0) and (_dist(c["cote"], p_avg) < _dist(cur["cote"], cur_avg) if c.get("cote") and cur.get("cote") and p_avg and cur_avg else band_pct.get(band,0) > band_pct.get(cur.get("_fp_band"),0))))):
                by_band.setdefault(band, {})[slot] = c
        else:
            cur = by_band.get(band)
            cur_avg = {"p1": fingerprint.get("p1",{}).get("avg_odds"), "p2": fingerprint.get("p2",{}).get("avg_odds"), "p3": fingerprint.get("p3",{}).get("avg_odds")}.get(cur.get("target_p") if cur else None) if cur else None
            if cur is None or fp_match > cur.get("_fp_match",0) or (fp_match == cur.get("_fp_match",0) and (bonus_out > cur.get("_bonus_out",0) or (bonus_out == cur.get("_bonus_out",0) and (_dist(c["cote"], p_avg) < _dist(cur["cote"], cur_avg) if c.get("cote") and cur.get("cote") and p_avg and cur_avg else band_pct.get(band,0) > band_pct.get(cur.get("_fp_band"),0))))):
                by_band[band] = c
    if p2p3_allocation:
        ranked = []
        for band_data in by_band.values():
            if band_data.get("p2"):
                ranked.append(band_data["p2"])
            if band_data.get("p3"):
                ranked.append(band_data["p3"])
    else:
        ranked = list(by_band.values())
    ranked = sorted(ranked, key=lambda x: (-x.get("_fp_match",0), -x.get("_bonus_out",0), -band_pct.get(x.get("_fp_band"), 0), -x.get("score",0), x.get("_plot_hidden",999), -x.get("_plot_d4",0), x.get("num",999)))
    if _audit is not None:
        if p2p3_allocation:
            _flat = {}
            for b, slots in by_band.items():
                for skey, c in (slots or {}).items():
                    if c:
                        _flat[f"{b}/{skey}"] = (c.get("num"), c.get("target_p"))
            _audit["by_band"] = _flat
        else:
            _audit["by_band"] = {b: (c.get("num"), c.get("target_p")) for b, c in by_band.items() if c}
        _audit["ranked"] = [(c.get("num"), c.get("target_p")) for c in ranked]
    # P3 Gate: si historical P3=OUT, appliquer p3_out_selector (top3_4 ranking) sans bonus
    gate_is_out = False
    sel_cand = None
    try:
        best_scen = fingerprint.get("top_scenario") or ""
        # check if Gate is OUT at P3 (from scenario_match best)
        gate_is_out = best_scen.endswith("OUT") if best_scen else False
        # also check current best_scenario from analyse
        if best_scenario and best_scenario.get("scenario","").endswith("OUT"):
            gate_is_out = True
        if gate_is_out:
            # Build OUT candidates for P3 with top3_4
            out_p3 = [c for c in outsiders if c.get("target_p")=="p3"]
            # enrich with top3_4 for ranking
            enriched=[]
            for c in out_p3:
                # find original participant to get top3_4
                p_orig = next((p for p in participants if p.get("num")==c["num"]), {})
                try:
                    from QUINTE.service import _horse_intrinsic as _hi
                    hi=_hi(p_orig)
                    top3_4=hi.get("top3_4")
                    form_avg=hi.get("form_avg")
                except: top3_4=None; form_avg=None
                enriched.append({"candidate":c, "top3_4":top3_4, "form_avg":form_avg, "num":c["num"]})
            sel = p3_out_selector(enriched)
            if sel:
                sel_cand = sel["candidate"]
                if sel_cand not in ranked:
                    ranked.insert(0, sel_cand)
    except: pass
    if p2p3_allocation:
        # P2-P3 allocation: P3 principal first, then P2 FROM target_p==p2.
        # Never two arbitrary outsiders.
        _p3_pick = sel_cand if gate_is_out and sel_cand else None
        if _p3_pick is None:
            _p3s = [c for c in outsiders if c.get("target_p") == "p3"]
            _p3_pick = sorted(_p3s, key=lambda x: (-x.get("_fp_match", 0), -x.get("_bonus_out", 0),
                                                  -band_pct.get(x.get("_fp_band"), 0), -x.get("score", 0),
                                                  x.get("_plot_hidden", 999), -x.get("_plot_d4", 0),
                                                  x.get("num", 999)))[0] if _p3s else None
        _p2s = [c for c in outsiders
                if c.get("target_p") == "p2" and c is not _p3_pick]
        _p2s_sorted = sorted(_p2s, key=lambda x: (-x.get("_fp_match", 0), -x.get("_bonus_out", 0),
                                                 -band_pct.get(x.get("_fp_band"), 0), -x.get("score", 0),
                                                 x.get("_plot_hidden", 999), -x.get("_plot_d4", 0),
                                                 x.get("num", 999)))
        _p2_pick = _p2s_sorted[0] if _p2s_sorted else None
        regret_picks = []
        if _p2_pick:
            regret_picks.append(_p2_pick)
        if _p3_pick:
            regret_picks.append(_p3_pick)
    else:
        regret_picks = ranked[:2]
    if len(regret_picks) < 2:
        remaining = [c for c in sorted(outsiders, key=lambda x: (-x.get("_fp_match",0), -x.get("_bonus_out",0), -x["score"], x.get("_plot_hidden",999), -x.get("_plot_d4",0), x.get("num",999))) if c not in regret_picks]
        regret_picks.extend(remaining[:2 - len(regret_picks)])
    regret_pick = regret_picks[0] if regret_picks else (max(candidates, key=lambda c: c["score"]) if candidates else None)
    if regret_pick and regret_pick["grade"] == "Favori du marché" and outsiders:
        alt = [c for c in outsiders if c["grade"] != "Favori du marché"]
        if alt: regret_pick = max(alt, key=lambda c: c["score"])

    # V3 scenario regret: P4 of the SAME coherent Top3 (no separate DNA).
    v3_regret = None
    if coherent_top3 and len(coherent_top3) == 3:
        try:
            top3set = set(coherent_top3)
            by_num = {p.get("num"): p for p in participants if p.get("num") is not None}
            ordered = sorted(
                [(p.get("cote_pmu") if p.get("cote_pmu") is not None else float("inf"), p.get("num"))
                 for p in participants
                 if p.get("num") not in top3set and p.get("cote_pmu") is not None],
                key=lambda x: (x[0], x[1]))
            if ordered:
                v3_cote, v3_num = ordered[0]
                vp = by_num.get(v3_num, {})
                info = coherent_info or {}
                v3_regret = {
                    "num": v3_num, "nom": vp.get("horse"), "horse": vp.get("horse"),
                    "jockey": vp.get("jockey") or vp.get("driver"),
                    "cote": v3_cote, "odds_rank": None, "runners": n_market or len(participants),
                    "score": info.get("support"), "score_solide": info.get("support"),
                    "grade": "P4 du scénario V3",
                    "breakdown": {
                        "Top3 V3": f"{' - '.join(str(n) for n in coherent_top3)} "
                                   f"(pattern {info.get('pattern')}, support {info.get('support')}, "
                                   f"niveau {info.get('level')})",
                        "P4": "premier cheval hors Top3 dans l'ordre du marché (même scénario, pas de DNA séparé)",
                    },
                    "points": {"scenario_v3": info.get("support")},
                    "eligible": True, "is_outsider": True, "target_p": "p4",
                    "cat": None, "history": {"rides": 0}, "jockey_stats": {},
                    "sire": None, "dam": None,
                }
        except Exception:
            v3_regret = None
    if v3_regret:
        regret_pick = v3_regret

    return {
        "filters": {"hippodrome": hippodrome, "distance": distance, "discipline": discipline, "date": race_date, "min_odds": min_odds},
        "market_summary": {"runners": n_market, "favourite_odds": priced[0][0] if priced else None, "priced_runners": n_market},
        "market_available": n_market >= 3,
        "global_fingerprint": fingerprint,
        "current_scenario": {"scenario": current_scenario, "counts": dict(current_counts), "gaps": {"p1_p2": cur_gap_p1_p2, "p2_p3": cur_gap_p2_p3, "p1_p3": cur_gap_p1_p3}, "distribution": current_distribution},
        "scenario_match": {"best": best_scenario, "top3": top_scenarios, "all": scenario_scores[:8]},
        "candidates": sorted(candidates, key=lambda c: (-c["score"], c["cote"] if c.get("cote") else 9999, c.get("num", 999))),
        "picks": {"regret": regret_pick, "regret2": regret_picks[1] if len(regret_picks) > 1 else None, "regret_picks": regret_picks, "solide": regret_pick,
                  "regret_source": ("v3-scenario" if v3_regret else "legacy")},
        "audit": _audit,
        "win_dna": {"n_control": 0, "n_winners_mined": fingerprint.get("top3_hits",0), "top_signatures": []},
    }
