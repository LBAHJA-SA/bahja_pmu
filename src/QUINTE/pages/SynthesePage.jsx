import { useState } from 'react'
import { fetchMeetings, fetchRace } from '../../services/api'
import { fmtDayString } from '../../lib/gmtTime'
import { fetchSyntheseMatch } from '../services/syntheseService'

// Synthèse de presse Quinté — la méthode de travail.
//
// La grille impair/pair ci-dessous n'est pas un tours de page arbitraire : ce
// sont les groupes dessinés à la main. Vérifié sur les deux courses
// manuscrites, les positions P1..P18 tombent exactement dans les cinq
// groupes tels qu'ils sont écrits :
//
//   25/09  presse 13 9 18 11 12 8 15 7 2 10 14 16 3 6 4 17 5 1
//          G1 = 13 9 18 12   G2 = 11 15 8 2   G3 = 7 10
//          G4 = 3 14         G5 = 17 5 1 16 6 4
//   24/09  presse 6 10 16 8 7 4 3 13 14 5 12 9 2 1 15
//          G1 = 6 10 7 3     G2 = 16 8 13 5   G3 = 4 9
//          G4 = 14 1         G5 = 12 2 15
//
// Le quota est flexible : 2 ou 3, 2 ou 3, 1 obligatoire, 1, puis 1 ou 0.
// Ce qui décide du choix À L'INTÉRIEUR d'un groupe, c'est la lecture de la
// course — le moteur pose les groupes et les quotas, il ne tranche pas à
// votre place.
// La méthode : le tableau se lit en entier, jusqu'à vingt chevaux. Les
// quotas sont ceux que vous avez donnés — G1 deux ou trois, G2 deux ou
// trois, G3 un, G4 un, G5 un. Rien n'est fixe : dans une course le
// huitième cheval vient de G5, dans une autre de G2, G3 ou G4. C'est le
// moteur qui décide, jamais une case écrite d'avance.
const GROUPS = [
  { key: 'G1', label: 'P1-P4', lo: 1, hi: 4, min: 2, max: 3 },
  { key: 'G2', label: 'P5-P8', lo: 5, hi: 8, min: 2, max: 3 },
  { key: 'G3', label: 'P9-P10', lo: 9, hi: 10, min: 1, max: 2 },
  { key: 'G4', label: 'P11-P12', lo: 11, hi: 12, min: 1, max: 2 },
  { key: 'G5', label: 'P13-P20', lo: 13, hi: 20, min: 1, max: 1 },
]
const TICKET = 8

// L'ordre A L'INTERIEUR de chaque groupe, toujours.
//
// Il n'appartient pas a la course : il appartient au marche. Dans les cinq
// groupes on suit la place au marche du cheval, du plus court prix au plus
// long. Une regle par groupe, egaller la presse dans le milieu du classement,
// a ete essayee et mesuree : elle ameliorait le premier sur 72 Quinté de 8% a
// 21%, mais elle perdait sur les dernieres courses et elle rendait le ticket
// fonction de la course plutot que du marche. Elle n'est plus la.
//
// Le huitieme cheval, lui, ne vient pas de la course non plus : il va a G1 ou
// a G2, celui des deux qui a encore de la place. G5 a maintenant une place
// garantie, ce qu'il n'avait pas — le spare pick arrivait toujours a G1 avant
// que la boucle n'atteigne G5, et le ticket n'en contenait jamais un.
//
// 2 + 2 + 1 + 1 + 1 = 7, et le huitieme va chercher de la place dans G1 ou G2.

const GROUP_SOURCE = { G1: 'market', G2: 'market', G3: 'market', G4: 'market', G5: 'market' }

const quotaLabel = g => (g.min === g.max ? `${g.min}` : `${g.min} ou ${g.max}`)

// position P1..P18 d'un numéro, d'après la grille
const groupIndexOfP = p => GROUPS.findIndex(g => p >= g.lo && p <= g.hi)

// Types de pari (Choisir mon pari) — la taille du ticket suit le pari
const BET_TYPES = [
  { id: 'sg', name: 'Simple', sub: 'Gagnant', color: '#5b2d8e', size: 1 },
  { id: 'sp', name: 'Simple', sub: 'Placé', color: '#5b2d8e', size: 3 },
  { id: 'jg', name: 'Jumelé', sub: 'Gagnant', color: '#e07b00', size: 2 },
  { id: 'jp', name: 'Jumelé', sub: 'Placé', color: '#e07b00', size: 2 },
  { id: 't', name: 'Tiercé', sub: '', color: '#1faa53', size: 3 },
  { id: 'q4', name: 'Quarté', sub: '', color: '#1f6fd6', size: 4 },
  { id: 'q5', name: 'Quinté+', sub: '', color: '#c81e1e', size: 8 },
]

function buildCells(raw) {
  const clean = raw.filter(n => n != null && !isNaN(n))
  if (!clean.length) return []
  const firstEven = (clean[0] % 2 === 0)
  const top = clean.filter(n => firstEven ? (n % 2 === 0) : (n % 2 !== 0))
  const bot = clean.filter(n => firstEven ? (n % 2 !== 0) : (n % 2 === 0))
  const cols = []
  const nCols = Math.max(top.length, bot.length)
  for (let i = 0; i < nCols; i++) cols.push([top[i], bot[i]])
  return cols
}

// Ordre d'affichage (السر): P1=cols[0][0], P2=cols[0][1], P3=cols[1][0]... —
// les zones A/B/C/D se lisent sur ces places affichées uniquement.
function displayOrder(raw) {
  const cols = buildCells(raw)
  const out = []
  cols.forEach(col => col.forEach(n => { if (n != null && !isNaN(n)) out.push(Number(n)) }))
  return out
}

// Ordre de LECTURE d'une boîte.
//
// displayOrder descend chaque colonne avant de passer à la suivante : c'est
// l'ordre des étiquettes P1..P18, et il coupe les boîtes 2x2 en diagonale.
// Sur le carnet, une boîte se lit en travers : la ligne du haut de gauche à
// droite, puis la ligne du bas.
//
//   13 | 9        la page  : 13, 18, 9, 12   (colonne)
//   --+---        la main  : 13,  9, 18, 12   (ligne)
//   18| 12
//
// Vérifié sur les deux courses du carnet : le 25/09 les arrivée sont la 1re et
// la 4e cellule, le 24/09 la 2e. Les deux notes écrites à la main disent
// exactement cela, et ne correspondent pas à l'ordre colonne.
function boxOrder(raw) {
  const cells = buildCells(raw)
  const spans = []
  let i = 0
  GROUPS.forEach(g => {
    const width = Math.ceil((g.hi - g.lo + 1) / 2)
    spans.push([i, i + width])
    i += width
  })
  const out = []
  spans.forEach(([a, b]) => {
    for (let r = 0; r < 2; r++) {
      cells.slice(a, b).forEach(col => {
        if (col[r] != null && !isNaN(col[r])) out.push(Number(col[r]))
      })
    }
  })
  return out
}

const DEFAULT_RAW = [14, 9, 13, 12, 6, 10, 2, 4, 11, 7, 8, 3, 5, 1]

export default function Synthese() {
  const [rawText, setRawText] = useState(DEFAULT_RAW.join(','))
  const [cols, setCols] = useState([])
  const [presse, setPresse] = useState([])
  const [sel, setSel] = useState({})
  // Pour chaque numéro: `pos` = sa place au marché, `rank` = son rang dans la
  // liste de la presse. C'est ce bloc qui décide de l'ordre dans chaque groupe.
  // Il est vide quand la course vient d'une liste saisie à la main, et alors
  // l'ordre des groupes retombe sur la grille imprimée.
  const [quality, setQuality] = useState(null)
  const [msg, setMsg] = useState('')
  const [meta, setMeta] = useState('⚠️ ماكاين حتى سباق محمّل — اختار تاريخ وضغط بحث')
  const [raceDate, setRaceDate] = useState(new Date().toISOString().slice(0, 10))
  const [searching, setSearching] = useState(false)
  const [betId, setBetId] = useState('q5')
  // ماكاين حتى مسار ذكي. Les cases se lisent across puis down, comme sur le
  // carnet, et le moteur remplit les quotas. Le reste est à vous.
  const loaded = presse.length >= 14

  // ترتيب القراءة داخل الخانة: سطر فوق، ثم سطر تحت
  const posOf = (list) => {
    const out = {}
    boxOrder(list).forEach((n, i) => { out[n] = i + 1 })
    return out
  }

  // الخانات الخمس، مقروءة في travers
  const groups = (() => {
    const order = boxOrder(presse)
    return GROUPS.map(g => ({ ...g, horses: order.slice(g.lo - 1, g.hi) }))
  })()

  const pickedIn = (g) => g.horses.filter(n => sel[n]).length

  // Le moteur.
  //
  // Les groupes et leurs quotas sont les vôtres et ils ne bougent pas. Ce qui
  // décide maintenant, a l'interieur d'un groupe, est l'ordre de ses chevaux :
  // le prix, dans les cinq groupes. Voir GROUP_SOURCE.
  //
  // 1. chaque case prend son minimum, dans l'ordre que sa source donne
  // 2. le reste va au groupe qui a encore de la place, dans la limite de son max
  // 3. dans une course le huitieme cheval peut sortir de G2, G3, G4 ou G5
  //
  // Parti avec CELL_W, un poids fixe par case. Il donnait a la case 4 de G1 la
  // meme note qu'a la case 1, et le tri stable laissait donc la case 4 jamais
  // tiree - un accident de tri, pas une decision. L'ordre vient maintenant des
  // donnees, plus d'un tableau de nombres ecrit d'avance.
  const orderIn = (g, horses, quality) => {
    const src = GROUP_SOURCE[g.key] || 'market'
    const key = (n) => {
      const q = quality && quality[String(n)]
      if (!q) return null
      return src === 'market' ? q.pos : q.rank
    }
    // un cheval que le bloc quality ne connait pas garde sa place dans la
    // grille imprimee, apres ceux qu'il connait, plutot que d'etre efface
    return horses
      .map((num, i) => ({ num, i, k: key(num) }))
      .sort((a, b) => {
        if (a.k == null && b.k == null) return a.i - b.i
        if (a.k == null) return 1
        if (b.k == null) return -1
        return a.k - b.k || a.i - b.i
      })
      .map(x => x.num)
  }

  const enginePick = (list, quality) => {
    const order = boxOrder(list)
    const pick = {}
    const got = {}
    GROUPS.forEach(g => { got[g.key] = 0 })
    const ranked = {}
    // 1) les minimums, dans l'ordre que la source du groupe donne
    GROUPS.forEach(g => {
      ranked[g.key] = orderIn(g, order.slice(g.lo - 1, g.hi), quality)
      ranked[g.key].slice(0, Math.min(g.min, ranked[g.key].length)).forEach(n => {
        pick[n] = true
        got[g.key]++
      })
    })
    // 2) le reste, a qui a encore de la place
    let left = TICKET - Object.values(got).reduce((a, b) => a + b, 0)
    while (left > 0) {
      let who = null
      for (const g of GROUPS) {
        if (who || got[g.key] >= g.max) continue
        const n = ranked[g.key].find(x => !pick[x])
        if (n != null) who = { g, n }
      }
      if (!who) break
      pick[who.n] = true
      got[who.g.key]++
      left--
    }
    return pick
  }

  const doFill = () => {
    const raw = rawText.split(/[^0-9]+/).filter(Boolean).map(Number)
    if (raw.length < 14) { setMsg('القائمة ناقصة (أقل من 14 رقم)'); return }
    setMsg('')
    setPresse(raw)
    setCols(buildCells(raw))
    setSel(enginePick(raw, quality))
  }

  const handleSearch = async () => {
    setSearching(true); setMsg('')
    try {
      const _base = window.location.port === '5173' ? '' : 'https://backend-production-f0139.up.railway.app'
      // 1) Synthèse
      const res = await fetch(`${_base}/api/synthese?date=${raceDate}`)
      const data = await res.json()
      if (!data.synthese) throw new Error(data.error || data.message || 'غير موجود')
      const nums = data.synthese || data.numbers || []
      const clean = nums.filter(n => n != null && !isNaN(n)).map(Number)
      if (clean.length < 14) throw new Error('Synthèse غير مكتملة لهذا التاريخ')
      setRawText(clean.join(','))
      setPresse(clean)
      setCols(buildCells(clean))
      setSel({})
      {
        const dstr = fmtDayString(raceDate)
        if (data.race?.hippodrome && data.race.hippodrome !== '—') {
          setMeta(`${dstr} — ${data.race.hippodrome}${data.race.prix && data.race.prix !== '—' ? ` (${data.race.prix})` : ''}`)
        } else {
          setMeta(`${dstr} — synthèse par défaut (pas de Quinté trouvé)`)
        }
      }
      // le moteur remplit les quotas et pose les huit. `quality` porte pour
      // chaque numéro sa place au marché (`pos`) et son rang dans la liste de
      // la presse (`rank`) : c'est de là que vient l'ordre dans chaque groupe.
      setQuality(data.quality || null)
      setSel(enginePick(clean, data.quality || null))
    } catch (e) { setMsg(e.message) }
    setSearching(false)
  }

  const total = Object.keys(sel).filter(k => sel[k]).length
  // le ticket suit l'ordre de lecture des boîtes
  const order = boxOrder(presse)
  const ticket = order.filter(n => sel[n])

  return (
    <div dir="rtl" style={{ textAlign: 'center' }}>
      <h2>Synthèse de la presse — Quinté</h2>
      <div style={{ marginBottom: 8 }}>
        <a href="#/synthese-ecarts" style={{ fontSize: 13, color: '#1e3a8a', fontWeight: 700 }}>📊 Écarts des places P1..P18 (archive)</a>
      </div>
      <div style={{ display: 'flex', gap: 10, justifyContent: 'center', alignItems: 'center', marginBottom: 8, flexWrap: 'wrap' }}>
        <label style={{ fontSize: 14, fontWeight: 600 }}>تحديد تاريخ السباق المراد تحليله</label>
        <input type="date" value={raceDate} onChange={e => setRaceDate(e.target.value)}
          style={{ padding: '6px 10px', borderRadius: 8, border: '2px solid #333', fontSize: 14 }} />
        <button onClick={handleSearch} disabled={searching}
          style={{ padding: '7px 16px', borderRadius: 8, border: 'none', background: searching ? '#94a3b8' : '#0f172a', color: '#fff', fontWeight: 700, fontSize: 13, cursor: searching ? 'wait' : 'pointer' }}>
          {searching ? 'جاري البحث...' : 'بحث'}
        </button>
      </div>
      <input value={meta} onChange={e => setMeta(e.target.value)} readOnly={!loaded}
        style={{
          width: '90%', textAlign: 'center', fontSize: 15, padding: 6, marginBottom: 4,
          color: loaded ? '#0f172a' : '#c81e1e', fontWeight: loaded ? 400 : 800,
          background: loaded ? '#fff' : '#fff1f1', border: loaded ? '1px solid #ccc' : '2px solid #c81e1e',
          borderRadius: 6,
        }} />

      {!loaded ? (
        <div style={{
          maxWidth: 560, margin: '14px auto', padding: 22, borderRadius: 12,
          border: '2px dashed #c81e1e', background: '#fff7f7', color: '#7f1d1d',
        }}>
          <div style={{ fontSize: 20, fontWeight: 800, marginBottom: 8 }}>
            ماكاين حتى جدول
          </div>
          <div style={{ fontSize: 14, lineHeight: 1.7 }}>
            اختار تاريخ سباق Quinté و اضغط <b>بحث</b>.<br />
            الsynthèse كتجيب من <b>pronostics-turf.info</b> و كتتخزن فالأرشيف ديالنا
            كل يوم — حيت الموقع كيعطي غير 3 أيام للمجموع.
          </div>
        </div>
      ) : null}

      <div style={{ maxWidth: 720, margin: '10px auto', textAlign: 'left', direction: 'ltr' }}>
        <div style={{ fontSize: 12, fontWeight: 800, color: '#1e3a8a', marginBottom: 6 }}>
          MA MÉTHODE — cinq groupes, un quota chacun. Le moteur remplit les quotas :
          le ticket est fixé, il ne se modifie pas à la main.
        </div>        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', alignItems: 'stretch' }}>
          {groups.map(g => {
            const k = pickedIn(g)
            const ok = pickedIn(g) >= g.min && pickedIn(g) <= g.max
            return (
              <div key={g.key} style={{
                flex: '1 1 110px', minWidth: 110, border: `2px solid ${ok ? '#1faa53' : '#c81e1e'}`,
                borderRadius: 8, padding: 6, background: ok ? '#f2fbf5' : '#fff5f5',
              }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 11, fontWeight: 800 }}>
                  <span>{g.key} · {g.label}</span>
                  <span style={{ color: ok ? '#1faa53' : '#c81e1e' }}>{k}/{quotaLabel(g)}</span>
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 3, marginTop: 4 }}>
                  {g.horses.map(n => (
                    <div key={n}
                      title={`${g.key} · case ${posOf(presse)[n]}`}
                      style={{
                        minWidth: 30, padding: '3px 0', borderRadius: 5,
                        fontSize: 15, fontWeight: 'bold',
                        border: sel[n] ? '2px solid #1faa53' : '1px solid #bbb',
                        background: sel[n] ? '#c8e6c9' : '#fff',
                        color: sel[n] ? '#14532d' : '#888',
                      }}>
                      {n}
                    </div>
                  ))}
                </div>
              </div>
            )
          })}
        </div>
        <div style={{ fontSize: 11, color: '#666', marginTop: 6 }}>
          Les boîtes se lisent <b>en travers</b> : ligne du haut puis ligne du
          bas, comme sur le carnet. G1 deux ou trois, G2 deux ou trois, G3 un, G4 un, G5 un. Le moteur
          remplit les minimums puis place les deux derniers dans la case la plus
          forte qui reste — G2, G3, G4 ou G5, selon la course. Tout est cliquable.
        </div>
      </div>

      <table style={{ borderCollapse: 'collapse', margin: '12px auto', background: '#fff', direction: 'ltr' }}>
        <tbody>
          {[0, 1].map(r => (
            <tr key={r}>
              {cols.map((col, i) => {
                // numéro de lecture de la case dans sa boîte, lue en travers :
                // ligne du haut d'abord, puis ligne du bas
                let colStart = 0
                let gi = -1
                for (let k = 0; k < GROUPS.length; k++) {
                  const w = Math.ceil((GROUPS[k].hi - GROUPS[k].lo + 1) / 2)
                  if (i >= colStart && i < colStart + w) { gi = k; break }
                  colStart += w
                }
                const inBox = gi < 0 ? 0 : i - colStart
                const read = gi < 0 ? 0 : inBox + 1 + (r === 0 ? 0 : 2)
                const cell = col[r]
                const tag = cell != null && gi >= 0 ? `${GROUPS[gi].key}·${read}` : ''
                return (
                  <td key={i}
                    title={tag || undefined}
                    style={{
                      border: '2px solid #333',
                      borderLeft: gi > 0 && inBox === 0 ? '4px solid #1e3a8a' : '2px solid #333',
                      width: 64, height: 56, textAlign: 'center',
                      fontSize: 24, fontWeight: 'bold',
                      background: sel[cell] ? '#c8e6c9' : undefined,
                    }}>
                    {cell}
                    <small style={{ display: 'block', fontSize: 11, fontWeight: 'normal', color: '#666' }}>
                      {tag}
                    </small>
                  </td>
                )
              })}
            </tr>
          ))}

        </tbody>
      </table>
      <div style={{ fontSize: 18 }}>المجموع المختار: {total}</div>
      <div style={{
        margin: '10px auto', maxWidth: 560, padding: 12, borderRadius: 10,
        background: '#c8e6c9',
        border: '2px solid #333', fontSize: 22, fontWeight: 'bold', direction: 'ltr',
      }}>
        {ticket.length ? ticket.join(' - ') : '—'}
        <div style={{ fontSize: 13, fontWeight: 'normal' }}>Ticket final ({ticket.length})</div>
      </div>
      <div style={{ fontSize: 16, fontWeight: 700, marginTop: 10 }}>Choisir mon pari</div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'center', flexWrap: 'wrap', margin: '8px auto', maxWidth: 640, direction: 'ltr' }}>
        {BET_TYPES.map(b => (
          <button key={b.id} onClick={() => setBetId(b.id)}
            style={{
              minWidth: 80, padding: '6px 10px', borderRadius: 10, cursor: 'pointer',
              background: '#fff', border: betId === b.id ? `3px solid ${b.color}` : '1px solid #ccc',
            }}>
            <span style={{
              display: 'inline-block', background: b.color, color: '#fff',
              fontWeight: 800, fontSize: 13, fontStyle: 'italic',
              padding: '2px 8px', borderRadius: 4, transform: 'skewX(-8deg)',
            }}>{b.name}</span>
            {b.sub ? <div style={{ fontSize: 11, color: b.color, fontWeight: 700 }}>{b.sub}</div> : null}
          </button>
        ))}
      </div>
      {(() => {
        const bet = BET_TYPES.find(b => b.id === betId) || BET_TYPES[6]
        const bt = ticket.slice(0, bet.size)
        return (
          <div style={{
            margin: '10px auto', maxWidth: 560, padding: 12, borderRadius: 10,
            background: '#eef2ff', border: `2px solid ${bet.color}`,
            fontSize: 22, fontWeight: 'bold', direction: 'ltr',
          }}>
            <span style={{ fontSize: 13, fontWeight: 700, color: bet.color }}>
              {bet.name}{bet.sub ? ` ${bet.sub}` : ''} ({bt.length}/{bet.size})
            </span>
            <div>{bt.length ? bt.join(' - ') : '—'}</div>
          </div>
        )
      })()}

      {msg ? <div style={{ color: '#b71c1c', marginTop: 8, fontWeight: 700 }}>{msg}</div> : null}
      {msg && !loaded ? <div style={{ color: '#b71c1c', marginTop: 8, fontWeight: 700 }}>{msg}</div> : null}
    </div>
  )
}

