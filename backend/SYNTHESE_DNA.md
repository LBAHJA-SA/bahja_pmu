# Synthèse — où va le DNA, et ce que l'archive dit vraiment

Mesuré sur `archive.db` (1 544 054 participants, 133 672 courses, 65 806 en
Top5). Tout ce qui suit est reproductible :

```
py tools\dna_report.py --dead          # les règles, et celles qui meurent
py tools\dna_signal.py                 # AUC in-sample vs hors-temps
py tools\dna_stability.py              # AUC par famille sur 4 fenêtres
py tools\ab_decompose.py --n 300       # qui apporte quoi dans le WHO
py tools\ab_who.py --n 150             # ancien vs nouveau moteur
```

---

## 1. Les trois défauts du moteur actuel, mesurés

### 1.1 `W_RED` est mort à 100 %

`red_km` ne contient pas une distance. Il contient un **temps de record** :

```
red_km = "1'41''4"   "2'03''7"   "1'48''8"
_red_val(v) -> None   (float() sur une string de temps -> ValueError)
```

Amplitude mesurée du terme sur 399 champs réels : **0.0 point**. Il ne
s'exécute jamais. Le « shadow best on 300 / validated 22.6% on 500 » qui a
justifié `W_RED = 0.987` a donc ajusté une constante nulle.

### 1.2 `W_COTE` n'est pas un poids, c'est le marché

| | amplitude dans un champ de 14 |
|---|---|
| terme COTE | **55.0 points** |
| terme FORM | 4.9 points |
| terme RED | 0.0 points |

Rapport 11:1. Et sur 399 champs réels : le top-3 « weighted » est
**identique** à celui qu'on obtiendrait par la cote seule dans **27.1 %**
des cas. Ce n'est pas du scoring, c'est le marché avec un décor.

Pire : il **dis ment**, et l'archive le mesure.

| bande | P(top5) | lift | poids archive | `-W_COTE·cote` |
|---|---|---|---|---|
| 1-3 | 0.820 | 1.89 | **+0.81** | -0.62 |
| 3-7 | 0.681 | 1.78 | **+0.59** | -2.07 |
| 7-10 | 0.570 | 1.52 | **+0.42** | -3.53 |
| **10-18** | 0.448 | **1.18** | **+0.16** | **-5.81** |
| 18-31 | 0.377 | 0.87 | -0.13 | -10.16 |
| 31-50 | 0.278 | 0.64 | -0.37 | -16.80 |
| 50+ | 0.182 | 0.33 | -1.12 | -41.49 |

La bande **10-18 est la plus neutre de l'archive** (lift 1.18) et reçoit la
**deuxième plus lourde pénalité** du code. Le score est monotone en cote ;
l'archive ne l'est pas. Le palier 10→18, c'est précisément là que vivent les
outsiders, et c'est là que le code se trompe le plus.

### 1.3 Le DNA n'entre dans la décision qu'à un endroit

`target` n'est lu que par `nfav` → `need` → nombre de places.
`per_rank` n'est lu que par `_pos_score` → `_dna_best_score`, qui **n'est
jamais appelé**.

> Supprimez `_frequency_vote`, `target` et `per_rank` : le ticket ne change
> pas. Le DNA d'aujourd'hui est un **compteur de places**, pas une empreinte.

Et trois tableaux différents coexistent dans le même fichier (header
3-1-1-1-2, docstring de `france_zones` 4-1-1-2-1, docstring de
`synthese_match` 1..6/7..8/9..10/11..18).

---

## 2. Ce que l'archive dit sur le DNA — la réponse à la question DAI

### 2.1 Les règles qui survivent (fenêtre complète, champ complet)

```
COTE_BAND  c50+       -1.115  lift 0.33   top5 1730  champ 13240  1420 courses
COTE_BAND  c1-3       +0.811  lift 2.26   top5 1671  champ   405  1611
COTE_BAND  c3-7       +0.573  lift 1.78   top5 5458  champ  3186  3455
COTE_BAND  c7-10      +0.416  lift 1.52   top5 3474  champ  2963  2558
DAI_PATTERN3 00       +0.372  lift 1.47   top5  306  champ   279   174
COTE_BAND  c31-50     -0.367  lift 0.69   top5 1879  champ  5768  1596
DAI_DISC  same_disc   -0.334  lift 0.71   top5  502  champ  1487   445
DISC_MATCH 3-4        -0.308  lift 0.73   top5  582  champ  1661   336
ZERO_COUNT 2          -0.276  lift 0.76   top5 1764  champ  4791  1363
DISC_MATCH 1-2        -0.253  lift 0.77   top5 1102  champ  2904   872
TOP3_5 0              -0.230  lift 0.79   top5 3522  champ  8965  2377
SEASON_RUNS 1         +0.187  lift 1.21   top5 1673  champ  2226  1130
DAI_NEXT1 then_4+     -0.178  lift 0.84   top5 3568  champ  8436  2113
COTE_BAND  c10-18     +0.162  lift 1.18   top5 5228  champ  7281  3312
DAI_NEXT1 then_1      +0.123  lift 1.13   top5 1212  champ  1799  1028
```

Trois choses tombent, et elles sont tombées **seules** :

- **`DAI_COUNT` 0/1/2/3+ : les quatre Morton.** Compter les DAI ne dit rien.
- **`DAI_NEXT1` `then_1` survit** (+0.123, 1028 courses) — « DAI puis 1a »
  est réel et bien soutenu, mais l'effet est faible (lift 1.13) et
  `then_2` / `then_3` **meurent** (IC contient 0). Ce n'est donc pas
  « 1a vaut mieux que 2a » : c'est **spécifiquement 1a après un DAI**, plus
  la queue négative à 4+.
- **`DAI_DISC same_disc` = -0.334** alors que `other_disc` meurt
  (|w|=0.058). Un DAI nedit quelque chose **que s'il a eu lieu dans la
  discipline qu'on joue**. C'est exactement pourquoi le « compter les DAI »
  ne montre jamais rien : la feature moyenne un signal fort (même disc) et
  un signal nul (autre disc), et tombe à ~0.

Donc l'hypothèse DAI est **affinée**, pas confirmée : la signature n'est pas
« combien de DAI », c'est « ce qui a suivi le dernier DAI, et dans quelle
discipline ».

### 2.2 La forme est asymétrique : un filtre, pas une récompense

```
TOP3_5=0   -0.230  VIVANTE      TOP3_5=2   +0.091  MORTE (trop faible)
ZERO_COUNT=0 +0.068 MORTE       TREND flat +0.100  MORTE
VOL low     +0.097 MORTE        TOP1_5=0   -0.088  MORTE
```

L'archive ne sanctionne que le bas. Au-dessus de « zéro podium en 5
courses », tout est plat. `W_FORM · _form_score_shadow` dépense toute sa
dynamique sur le haut. Il n'est pas seulement saturé par la presse : il
place sa discrimination **à l'envers**.

### 2.3 Général / discipline

Seules **4 règles** survivent à l'exigence d'accord de signe entre PLAT et
ATTELE — et les quatre sont des bandes de cote.

```
ADN GÉNÉRAL : c50+ -1.072 | c3-7 +0.594 | c7-10 +0.437 | c31-50 -0.399
ADN PLAT    : 2 règles, toutes des bandes de cote
ADN ATTELE  : 19 règles, forme comprise — et les SIGNS s'inversent
              (TOP1_5=1 devient +0.139, TOP3_5=2 +0.131)
ADN MONTE   : rien
```

> **Le seul ADN général qui existe dans cet archive, c'est le marché.**
> Tout le reste est local à la discipline. Un `W_FORM` global applique donc
> la récompense d'ATTELE à des chevaux PLAT où l'archive ne dit rien.

---

## 3. Le verdict qui décide de tout : la stabilité

Entraîné sur le passé, testé sur l'année suivante, 4 fenêtres indépendantes.

| famille | 2019 | 2021 | 2023 | 2024 | verdict |
|---|---|---|---|---|---|
| TOUTES | 0.546 | 0.625 | 0.498 | **0.420** | bruit |
| COTE_BAND | 0.547 | 0.627 | 0.479 | **0.419** | bruit |
| ZERO_FAIL | 0.597 | 0.488 | 0.509 | 0.457 | bruit |
| TREND_VOL | 0.507 | 0.506 | 0.542 | 0.493 | instable |
| DISC | 0.481 | 0.531 | 0.483 | 0.501 | bruit |
| TOP | 0.492 | 0.505 | 0.512 | 0.466 | bruit |
| **DAI** | **0.479** | **0.472** | **0.480** | **0.485** | **INVERSE STABLE** |

- AUC in-sample **0.7332** → hors-temps **0.5522**. L'effondrement de 0.18
  d'AUC, c'est toute l'histoire.
- **La seule ligne stable est DAI, et elle est stablement à l'envers**
  (0.48, sous 0.5 les quatre années).
- Même la cote, « le signal évident », **bascule de 0.627 à 0.419** entre
  deux ans. C'est un régime, pas un signal.

Cela explique, d'un coup, tout ce qui a été mesuré avant :

| mesure d'origine | ce qu'elle vaut vraiment |
|---|---|
| `W_RED` best on 300, 22.6% on 500 | un terme mort à 100 % |
| `W_FORM` best on 300 | bruit, AUC 0.44 hors-temps |
| DNA-first pire sur 300 | on substituait du bruit à du bruit |
| adaptive 19.4% vs fixed 15.4% | **0.0 point** (re-mesuré, 300 courses) |

---

## 4. Ce que le moteur actuel apporte réellement (300 courses, 2025+)

```
ANCIEN       form actuel (_form_score_shadow)     79.0 %
SANS FORM    cote seul                            71.9 %
ANCIEN       quotas fixes                         79.0 %   <- 0.0
SANS FORM    quotas fixes                         71.9 %
LONGUEUR DE CARRIERE seule (1/(1+n))             79.3 %   <- reproduit le form
FORM CORRIGE (5 runs récents, dénominateur fixe)  79.7 %
```

Le gain de +7.1 du terme FORM **est entièrement de la longueur de
carrière**. Cause, dans `_form_score_shadow` :

- la moyenne est divisée par le **nombre de runs parsés** : un cheval avec
  une seule 1re place marque **10.0**, le maximum. Le score mesure
  `1/(1+n)`, pas la forme ;
- `runs[:6]` prend les **plus anciens** runs (la chaîne est
  ancien→récent, prouvé par le marqueur `(NN)` de changement de saison) ;
- `(25)` est parsé comme deux places (2 et 5) ;
- un DAI entre dans la moyenne comme un 0.

Le form corrigé n'est **pas** mesurablement meilleur (McNemar z = 1.09,
9 chevaux sur 1375) mais il est honnête : il lit le bon bout, n'a plus de
dépendance à la carrière, et sort les DAI de la moyenne.

---

## 5. Où va le DNA — le placement exact

```
WHERE  = le TABLEAU des places affichées.              FIGÉ
         A = P1..P4 (3) | B = P5..P6 (1) | C = P7..P8 (1)
         D = P9..P10 (1) | E = P11..P18 (2) = 8
         → ZONE_PLACES / ZONE_QUOTA dans synthese_who.py, source unique.
         Le DNA n'a AUCUN droit ici. Les quotas adaptatifs (nfav)
         sortent du décisionnel : mesurés à 0.0 point.

WHO    = l'ADN, à 100 %. Uniquement lui.
         Ni cote, ni form, ni red_km lus comme un score.
         → dna_score() dans dna.py.
```

Quatre lignes de code disent tout le reste :

```python
# engine actuel
a_pool.sort(key=lambda t: (-t[0], t[1], t[2]))   # t[0] = weighted = le marché
# engine ADN
cand = sorted(((h["dna"] + compo(...), h["market_rank"], n) ...),
              key=lambda t: (-t[0], t[1], t[2]))
```

La **porte d'entrée** est `fit_dna()` : une famille de features n'entre
dans le moteur que si, entraînée sur la moitié ancienne de la fenêtre, elle
classe mieux que le hasard sur la moitié récente (AUC ≥ 0.52). Ce qui est
refusé n'a aucun poids, donc aucune façon d'influencer le classement.

Aujourd'hui cette porte **refuse tout sauf le marché**, et refuse la forme.
C'est un résultat, pas un échec : le moteur ne doit pas chanter une règle
qui ne tient pas. Le jour où `DAI_NEXT1=then_1`_passera 0.52 sur deux
fenêtres consécutives, il rentrera tout seul, sans toucher au code.

---

## 6. Le garde-fou qui compte

`synthese_match` ne se rabat **jamais** sur l'ancien score. Si l'archive ne
produit aucune règle admise, il renvoie `[]` et
`support["error"] = "no_dna_rules"`. Un moteur qui se dégrade en silence
vers le marché est pire qu'un moteur qui s'arrête : il continue de produire
des tickets qui ont l'air d'être raisonables.

Corollaire opérationnel : `musique` est absente de **courses entières**
(ex. la course 1681994 du 2026-09-07 : 16/16 NULL). Couverture globale
96.8 %, mais par blocs. Le moteur le signale (`degraded`) au lieu de
deviner.
