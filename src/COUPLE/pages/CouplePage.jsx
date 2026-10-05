// COUPLE — its own page and its own engine.
//
// The page follows the same shape as the other pages: pick the date, pick the
// MEETING first (R1, R2, R3…), then the course inside it (C1, C2, C3…). A flat
// list of courses is unreadable, because every meeting restarts at C1 and two
// meetings can both own an "R1C1".
//
// The engine, in one paragraph because the page shows its reasoning:
//
//   A field of ten runners or more takes the COHERENT path — the Couple comes
//   from the same ALFARAJ trio that feeds Trio and Quinté, so the tickets tell
//   one story. Its three pairs are P1-P2, P1-P3, P2-P3.
//
//   A field under ten takes the V3 PATTERN path — whole Top3 signatures are
//   stored in the history, and a candidate Top3 is scored against the patterns
//   that recurred, ranked by (level, support, -rank_dev, -prof_dev, rel_freq).
//   Level comes first on purpose: a specific pattern that recurred beats a
//   vaguer one, and support is only compared inside the same level.
//
// One extra comes back with it: the alternatives, when the caller asks for an
// explanation of the candidates that were not kept.
//
// The flipped tickets and the expert ranking used to sit on this page. They
// now have no home here: the flipped ones are being measured on their own page
// so the rule can be judged on real results, and the expert ranking was showing
// scores without ever being scored itself.
import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Crown, Calendar, Target, Sparkles, Flag } from 'lucide-react'
import { extractCouple, fetchCoupleStats } from '../services/coupleApi'
import { saveFlipPick } from '../../FLIP/services/flipApi'
import { fetchMeetings, fetchRace } from '../../services/api'
import { RaceBetBadges } from '../../components/BetBadges'
import { raceStatus, statusChip, useNow } from '../../lib/raceStatus.jsx'
import { fmtClock, fmtClockZ, leadText, TZ_LABEL } from '../../lib/gmtTime'

// One palette, shared with the FLIP page so the two read as the same
// application. Royal blue for the headings, the dark ground for anything that
// carries a number, and white text on both — a mid grey on either ground is
// unreadable, which is what the old card colours were.
const ROYAL = '#1d4ed8'
const ROYAL_EDGE = '#60a5fa'
const PANEL_BG = '#0a0d15'
const ON_DARK = '#ffffff'
const ON_DIM = '#dbe4f0'
const HAIRLINE = 'rgba(255,255,255,0.10)'
const BAD = '#fca5a5'
// Orange is kept for one thing only: the saddle numbers. It is the one accent
// the FLIP page also uses for a number, so a number means the same thing on
// both pages.
const ORANGE = '#fb923c'

// The venue as a race card writes it: the name alone, never the word
// HIPPODROME repeated on every row.
function shortHippo(name) {
  return String(name || '')
    .replace(/^HIPPODROME\s+/i, '')
    .replace(/^(DE|DES|DU|D')\s*/i, '')
    .trim() || '—'
}

function famColor(fam) {
  const f = String(fam || '').toUpperCase()
  if (f.startsWith('F')) return '#22c55e'
  if (f.startsWith('S')) return '#06b6d4'
  if (f.startsWith('O2')) return '#f97316'
  if (f.startsWith('O')) return '#ea580c'
  if (f.startsWith('T')) return '#ef4444'
  return ON_DIM
}

function Chip({ h, colour }) {
  if (!h) return null
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 6, margin: '0 6px 6px 0',
      padding: '5px 9px', borderRadius: 8,
      border: `1px solid ${h.fam ? famColor(h.fam) : HAIRLINE}`,
      background: 'rgba(255,255,255,0.04)',
    }}>
      <b style={{ fontSize: '0.95rem', color: colour || '#22c55e' }}>{String(h.num).padStart(2, '0')}</b>
      <span style={{ fontSize: '0.8rem', color: ON_DARK }}>{(h.horse || '').slice(0, 14)}</span>
      {h.fam ? (
        <span style={{
          fontSize: '0.62rem', fontWeight: 900, padding: '1px 5px', borderRadius: 4,
          background: famColor(h.fam), color: '#000',
        }}>{h.fam}</span>
      ) : null}
      {h.market_rank ? (
        <span style={{ fontSize: '0.64rem', color: ON_DIM }}>rang {h.market_rank}</span>
      ) : null}
    </span>
  )
}

// Same discipline vocabulary the other pages use, so the filter row reads the
// same everywhere. "TOUS" is kept because the Couple engine itself is trained
// on small fields of both families.
const FAMILIES = [
  { key: 'TOUS', label: 'TOUS', discs: null, colour: '#ec4899' },
]

const discOf = c => String(c?.discipline || c?.specialty || '').toUpperCase()

export default function CouplePage() {
  const now = useNow(30000)
  const navigate = useNavigate()
  const [date, setDate] = useState(new Date().toISOString().slice(0, 10))
  const [meetings, setMeetings] = useState([])
  const [selReu, setSelReu] = useState(null)
  const [sel, setSel] = useState(null)
  const [field, setField] = useState(null)
  const [out, setOut] = useState(null)
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState(null)
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)
  const [family, setFamily] = useState('TOUS')
  const [flipPick, setFlipPick] = useState(null)   // what the FLIP engine said
  const [picking, setPicking] = useState(false)
  const [confirmingPick, setConfirmingPick] = useState(false)

  const fam = FAMILIES.find(f => f.key === family) || FAMILIES[0]
  const keep = (c) => !fam.discs || fam.discs.some(x => discOf(c).includes(x))
  const shown = meetings
    .map(m => ({ ...m, courses: (m.courses || []).filter(keep) }))
    .filter(m => m.courses.length > 0)

  const loadStats = async () => {
    try { setStats(await fetchCoupleStats(3000)) } catch (e) { setStats({ error: e.message }) }
  }

  const loadMeetings = async (d) => {
    setLoading(true); setErr(null); setSelReu(null); setSel(null)
    setField(null); setOut(null)
    try {
      const r = await fetchMeetings(d)
      setMeetings((r.meetings || []).filter(m => (m.courses || []).length))
    } catch (e) { setErr(e.message) } finally { setLoading(false) }
  }

  const pick = async (m, c) => {
    setSel({ meeting: m, course: c }); setOut(null); setErr(null); setBusy(true)
    setField(null)
    // The FLIP confirmation belongs to the race it was recorded for. Leaving it
    // up when another race is selected means reading one race's answer as if it
    // were another's — which on this page is the difference between a recorded
    // bet and a fabricated one.
    setFlipPick(null); setConfirmingPick(false)
    try {
      const rd = await fetchRace(date, m.num, c.num)
      const parts = rd.participants || []
      setField(parts)
      // Called exactly as TROT and GALOP call it, with nothing extra. The
      // engine derives the field size from the participants it is given, and
      // every extra field narrows the history lookup — sending `runners` from
      // the programme, or a date, makes this page answer differently from the
      // other two on the same race. One engine, one call, one answer.
      setOut(await extractCouple(parts))
    } catch (e) { setErr(e.message) } finally { setBusy(false) }
  }

  // Freeze what the FLIP engine says about this field, today. The result is
  // filled in later by the FLIP page, so the log keeps the answer as it was
  // given rather than as the rule would answer it now.
  const savePick = async () => {
    if (!sel || picking) return
    setPicking(true); setFlipPick(null)
    try {
      const rd = await fetchRace(date, sel.meeting.num, sel.course.num)
      const parts = rd.participants || []
      const r = await saveFlipPick({
        date,
        meeting: sel.meeting.num,
        course: sel.course.num,
        hippodrome: (sel.meeting.hippodrome_full || sel.meeting.hippodrome?.libelleLong
          || sel.meeting.hippodrome || '').toString(),
        distance: sel.course.distance,
        disc: sel.course.discipline || sel.course.specialty || '',
        runners: sel.course.runners || parts.length,
        start_ms: sel.course.time,
        participants: parts,
      })
      setFlipPick({
        status: r.saved?.status,
        replaced: r.saved?.replaced,
        ok: r.ticket?.ok,
        reason_fr: r.ticket?.reason_fr,
        lead_min: r.saved?.lead_min,
        pairs: (r.ticket?.pairs || []).length,
        favourite: r.ticket?.favourite,
        outsiders: (r.ticket?.pairs || []).map(
          p => `${String(p.outsider.num).padStart(2, '0')} ${(p.outsider.horse || '').slice(0, 12)}`),
      })
    } catch (e) {
      setFlipPick({ error: e.message })
    } finally { setPicking(false) }
  }

  const hist = out?.hist || {}
  const pairs = out?.matches || []
  const fieldN = field?.length || 0
  const coherent = !!hist.coherent

  return (
    <div style={{ position: 'relative', minHeight: '100vh', padding: '12px 8px' }}>
      {/* the photograph, full viewport, at full strength — the same layer the
          FLIP page puts behind its own panels. No veil: the text over it always
          sits in its own solid frame, which is what keeps it readable. */}
      <div aria-hidden="true" style={{
        position: 'fixed', inset: 0, zIndex: 0, pointerEvents: 'none',
        backgroundImage: 'url(/hippodrome.jpg)',
        backgroundSize: 'cover',
        backgroundPosition: 'center center',
        backgroundRepeat: 'no-repeat',
      }} />
      <div style={{ position: 'relative', zIndex: 1 }}>
      <div style={{
        display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap',
        marginBottom: 10, padding: '10px 16px', borderRadius: 12,
        fontWeight: 900, fontSize: '1.1rem', letterSpacing: '0.3px',
        background: ROYAL, border: '1.5px solid ' + ROYAL_EDGE, color: '#fff',
        boxShadow: '0 2px 10px rgba(29,78,216,0.5)',
      }}>
        <Crown size={20} />
        COUPLE
        <small style={{ fontSize: '0.74rem', fontWeight: 700, opacity: 0.92 }}>
          Couple · Jumelé · Top3 patterns
        </small>
      </div>
      <div style={{
        display: 'inline-flex', alignItems: 'center', gap: 8,
        marginBottom: 12, padding: '8px 16px', borderRadius: 10,
        background: ROYAL, border: '1.5px solid ' + ROYAL_EDGE,
      }}>
        <Crown size={20} style={{ color: '#fff' }} />
        <b style={{ fontSize: '1.05rem', fontWeight: 900, color: '#fff' }}>COUPLE — DNA</b>
        <span style={{ fontSize: '0.8rem', color: '#fff', fontWeight: 700 }}>
          {coherent ? 'couples issus du trio' : 'motifs Top3 (V3)'}
        </span>
      </div>

      <div style={{
        display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap',
        margin: '0 0 12px', padding: '9px 12px', borderRadius: 10,
        background: PANEL_BG, border: '1px solid ' + HAIRLINE,
      }}>
        <input type="date" value={date}
          onChange={e => setDate(e.target.value)}
          style={{
            padding: '6px 10px', borderRadius: 8,
            border: '1px solid ' + HAIRLINE, background: 'rgba(255,255,255,0.05)',
            color: ON_DARK, colorScheme: 'dark',
          }} />
        <button onClick={() => loadMeetings(date)} disabled={loading}
          style={{
            padding: '8px 16px', borderRadius: 9, border: '1px solid ' + ROYAL_EDGE,
            cursor: loading ? 'wait' : 'pointer',
            background: ROYAL, color: '#fff',
            fontWeight: 900, fontSize: '0.84rem', opacity: loading ? 0.7 : 1,
          }}>
          {loading ? 'Chargement…' : 'Programme du jour'}
        </button>
        <button onClick={loadStats}
          style={{
            padding: '8px 14px', borderRadius: 9, cursor: 'pointer',
            background: 'rgba(255,255,255,0.09)', border: '1px solid ' + HAIRLINE,
            color: ON_DARK, fontWeight: 800, fontSize: '0.8rem',
          }}>
          Statistiques
        </button>
        {stats && !stats.error ? (
          <span style={{ fontSize: '0.74rem', color: ON_DARK, opacity: 0.85 }}>
            {stats.total ?? stats.n ?? stats.count ?? '—'} motifs en mémoire
          </span>
        ) : null}
        {stats?.error ? (
          <span style={{ fontSize: '0.74rem', color: '#fca5a5' }}>{stats.error}</span>
        ) : null}

        {/* the flip used to be a card on this page. It is measured on its own
            page now, so the way in is a button rather than a second block of
            numbers nobody could judge. */}
        <button onClick={() => navigate('/flip')}
          style={{
            marginLeft: 'auto', display: 'inline-flex', alignItems: 'center', gap: 6,
            padding: '8px 14px', borderRadius: 9, cursor: 'pointer',
            border: '1px solid ' + ROYAL_EDGE, background: 'rgba(255,255,255,0.14)',
            color: '#fff', fontWeight: 900, fontSize: '0.8rem',
          }}>
          <Flag size={14} /> FLIP mesuré ↗
        </button>
      </div>

      <div style={{
        display: 'flex', gap: 6, flexWrap: 'wrap', margin: '0 0 12px',
        padding: '7px 11px', borderRadius: 10,
        background: PANEL_BG, border: '1px solid ' + HAIRLINE,
      }}>
        {FAMILIES.map(f => {
          const act = family === f.key
          return (
            <button key={f.key} onClick={() => { setFamily(f.key); setSelReu(null); setSel(null) }}
              style={{
                padding: '6px 14px', borderRadius: 9, cursor: 'pointer',
                border: act ? '1.5px solid ' + ROYAL_EDGE : '1px solid ' + HAIRLINE,
                background: act ? ROYAL : 'rgba(255,255,255,0.05)',
                color: '#fff',
                fontWeight: 900, fontSize: '0.78rem',
              }}>
              {f.label}
            </button>
          )
        })}
      </div>

      {err ? (
        <div style={{ color: BAD, fontWeight: 800, marginBottom: 10, fontSize: '0.86rem' }}>{err}</div>
      ) : null}

      {shown.length ? (
        <div className="neon-card" style={{ background: PANEL_BG, border: '1px solid ' + HAIRLINE, marginBottom: 14 }}>
          {/* the same solid royal-blue heading the FLIP page uses, so the two
              pages read as one application and a heading is never a coloured
              word floating on a dark panel */}
          <h3 style={{
            fontSize: '0.95rem', marginBottom: 8,
            display: 'flex', alignItems: 'center', gap: 6,
            padding: '7px 12px', borderRadius: 9,
            background: ROYAL, border: '1.5px solid ' + ROYAL_EDGE, color: '#fff',
          }}>
            <Calendar size={14} /> Réunions du jour
            <span style={{ fontSize: '0.7rem', fontWeight: 700, marginLeft: 'auto' }}>
              les heures sont en {TZ_LABEL}
            </span>
          </h3>
          <div style={{ fontSize: '0.76rem', color: ON_DIM, marginBottom: 10 }}>
            {shown.length} réunions · choisissez la réunion, puis la course
          </div>
          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
            {shown.map(m => {
              const active = selReu === m.num
              // the venue as a race card writes it: the name alone, never the
              // word HIPPODROME repeated on every row
              const name = shortHippo(m.hippodrome_full || m.hippodrome?.libelleLong
                || m.hippodrome || `R${m.num}`)
              return (
                <button key={m.num} onClick={() => setSelReu(active ? null : m.num)}
                  style={{
                    minWidth: 96, padding: '10px 12px', borderRadius: 12, textAlign: 'left',
                    border: active ? '1.5px solid ' + ROYAL_EDGE : (m.country === 'MA' ? '1px solid rgba(193,39,45,0.5)' : '1px solid ' + HAIRLINE),
                    background: active ? ROYAL : 'rgba(255,255,255,0.05)',
                    color: '#fff', cursor: 'pointer',
                  }}>
                  <div style={{ fontWeight: 900, fontSize: '0.9rem' }}>R{m.num}</div>
                  <div style={{
                    fontSize: '0.64rem', color: ON_DIM, maxWidth: 120,
                    overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap',
                  }}>{name}</div>
                  <div style={{ fontSize: '0.64rem' }}>{m.courses.length} courses</div>
                </button>
              )
            })}
          </div>

          {selReu != null ? (() => {
            const m = shown.find(x => x.num === selReu)
            if (!m) return null
            return (
              <div style={{ marginTop: 12, borderTop: '1px solid ' + HAIRLINE, paddingTop: 12 }}>
                <div style={{ fontSize: '0.8rem', color: ON_DARK, marginBottom: 8, fontWeight: 800 }}>
                  R{m.num} — {shortHippo(m.hippodrome_full || m.hippodrome?.libelleLong || m.hippodrome || '')}
                </div>
                <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                  {m.courses.map(c => {
                    const act = sel && sel.meeting.num === m.num && sel.course.num === c.num
                    return (
                      <button key={c.num} onClick={() => pick(m, c)} disabled={busy}
                        style={{
                          minWidth: 90, padding: '8px 10px', borderRadius: 10, textAlign: 'left',
                          border: act ? '1.5px solid ' + ROYAL_EDGE : '1px solid ' + HAIRLINE,
                          background: act ? ROYAL : 'rgba(255,255,255,0.05)',
                          color: '#fff',
                          fontWeight: 800, fontSize: '0.83rem', cursor: 'pointer',
                        }}>
                        {/* the off, in GMT — the same clock the FLIP delay is
                            measured against, printed here so a reading can be
                            timed against the card it came from. */}
                        <div>C{c.num} {fmtClock(c.time)}</div>
                        <div style={{ marginTop: 2 }}>{statusChip(raceStatus(c, now), true, true)}</div>
                        <div style={{ fontSize: '0.64rem', color: ON_DIM }}>
                          {c.discipline || ''} {c.distance}m
                        </div>
                        <RaceBetBadges race={c} dark />
                      </button>
                    )
                  })}
                </div>
              </div>
            )
          })() : null}
        </div>
      ) : null}

      {sel ? (
        <div className="neon-card" style={{ background: PANEL_BG, border: '1px solid ' + HAIRLINE, marginBottom: 14 }}>
          <h3 style={{
            fontSize: '0.95rem', marginBottom: 8,
            display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
            padding: '7px 12px', borderRadius: 9,
            background: ROYAL, border: '1.5px solid ' + ROYAL_EDGE, color: '#fff',
          }}>
            <b>R{sel.meeting.num}C{sel.course.num}</b>
            <span>{sel.course.libelle || ''}</span>
            {statusChip(raceStatus(sel.course, now), false, true)}
            <span style={{ fontSize: '0.72rem', fontWeight: 800, marginLeft: 'auto' }}>
              départ {fmtClockZ(sel.course.time) || 'inconnu'}
            </span>
          </h3>
          <div style={{ fontSize: '0.76rem', color: ON_DIM, marginBottom: 8 }}>
            {sel.course.distance}m · {sel.course.discipline || sel.course.specialty || ''} ·{' '}
            {sel.course.runners || fieldN} partants
          </div>
          <RaceBetBadges race={sel.course} dark />
          {field?.length ? (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginTop: 8 }}>
              {field.slice(0, 20).map(p => (
                <span key={p.num} style={{
                  fontSize: '0.8rem', padding: '3px 6px', borderRadius: 6,
                  background: 'rgba(255,255,255,0.04)', border: '1px solid ' + HAIRLINE,
                  color: ON_DARK,
                }}>
                  {/* the saddle is a bare number and the name is white: on this
                      ground the theme's near-black measured 1.09 and vanished */}
                  <b style={{ color: ORANGE }}>{p.num}</b> {p.horse}
                </span>
              ))}
            </div>
          ) : null}

          {/* the per-course FLIP record. One press, the answer is kept as it was
              given; the comparison waits for the result. */}
          <div style={{
            marginTop: 12, paddingTop: 10, borderTop: '1px solid HAIRLINE',
            display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
          }}>
            <button onClick={savePick} disabled={picking}
              style={{
                display: 'inline-flex', alignItems: 'center', gap: 6,
                padding: '7px 14px', borderRadius: 9, cursor: picking ? 'wait' : 'pointer',
                border: '1.5px solid #fb923c', background: '#fb923c1f', color: '#fb923c',
                fontWeight: 900, fontSize: '0.8rem',
              }}>
              <Flag size={14} />
              {picking ? 'enregistrement…' : 'Enregistrer le FLIP de cette course'}
            </button>
            <span style={{ fontSize: '0.7rem', color: ON_DIM }}>
              garde la réponse du moteur aujourd'hui, la comparaison se fera quand
              le résultat sera là
            </span>
          </div>

          {flipPick?.error ? (
            <div style={{ color: BAD, fontSize: '0.8rem', marginTop: 8 }}>{flipPick.error}</div>
          ) : null}

          {flipPick && !flipPick.error ? (
            <div style={{
              marginTop: 10, padding: '10px 12px', borderRadius: 9,
              border: `1px solid ${flipPick.ok ? '#fb923c66' : HAIRLINE}`,
              background: 'rgba(255,255,255,0.03)',
            }}>
              <div style={{ fontSize: '0.74rem', color: '#fb923c', fontWeight: 900, marginBottom: 5 }}>
                {flipPick.replaced ? 'FLIP enregistré (remplace l\'enregistrement précédent)'
                  : 'FLIP enregistré'}
                {' · '}
                {flipPick.status === 'abstained' ? 'aucun billet' : 'en attente du résultat'}
                {/* the delay and the off, both in GMT, so the two numbers on this
                    line can be checked against each other without guessing a zone */}
                <span style={{ color: ON_DIM, fontWeight: 600 }}>
                  {'  ·  '}
                  départ {fmtClockZ(sel.course.time) || 'inconnu'} ({TZ_LABEL})
                  {'  ·  '}lu {leadText(flipPick.lead_min)}
                </span>
              </div>
              {flipPick.ok ? (
                <>
                  <div style={{ fontSize: '0.74rem', color: ON_DIM, marginBottom: 4 }}>
                    favori {String(flipPick.favourite?.num).padStart(2, '0')}{' '}
                    {(flipPick.favourite?.horse || '').slice(0, 16)} · {flipPick.pairs} paire(s)
                  </div>
                  {flipPick.outsiders?.length ? (
                    <div style={{ fontSize: '0.7rem', color: ON_DIM }}>
                      × {flipPick.outsiders.join('  ·  ')}
                    </div>
                  ) : null}
                </>
              ) : (
                <div style={{ fontSize: '0.74rem', color: ON_DIM }}>
                  {flipPick.reason_fr}
                </div>
              )}
              <button onClick={() => navigate('/flip')}
                style={{
                  marginTop: 8, background: 'none', border: 'none', cursor: 'pointer',
                  color: '#fb923c', fontSize: '0.72rem', fontWeight: 800, padding: 0,
                }}>
                voir le journal ↗
              </button>
            </div>
          ) : null}
          {err ? (
            <div style={{ color: BAD, fontSize: '0.84rem', marginTop: 8 }}>{err}</div>
          ) : null}
        </div>
      ) : null}

      {busy ? (
        <div className="neon-card" style={{ background: PANEL_BG, border: '1px solid ' + HAIRLINE, marginBottom: 14 }}>
          <div style={{ fontSize: '0.8rem', color: ON_DIM }}>
            Moteur COUPLE en cours…
          </div>
        </div>
      ) : null}

      {out ? (
        <>
          <div className="neon-card" style={{ background: PANEL_BG, border: '1px solid ' + HAIRLINE, marginBottom: 14 }}>
            <h3 style={{
              fontSize: '0.95rem', marginBottom: 8,
              display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap',
              padding: '7px 12px', borderRadius: 9,
              background: ROYAL, border: '1.5px solid ' + ROYAL_EDGE, color: '#fff',
            }}>
              <Target size={14} /> COUPLE
              <span style={{ fontSize: '0.7rem', fontWeight: 700, marginLeft: 'auto' }}>
                {coherent ? 'cohérent — trio ALFARAJ' : 'motifs Top3 (V3)'} · {pairs.length} paire(s)
              </span>
            </h3>
            {pairs.length ? pairs.map((m, i) => (
              <div key={i} style={{ marginBottom: 10 }}>
                <div style={{ fontSize: '0.72rem', color: ON_DIM, marginBottom: 4 }}>
                  {m.key}{m.sub_key ? ` · ${m.sub_key}` : ''}
                  {m.count ? ` · support ${m.count}` : ''}
                  {m.details?.pattern ? ` · ${m.details.pattern}` : ''}
                </div>
                {(m.horses || []).map((h, j) => <Chip key={j} h={h} colour={ORANGE} />)}
              </div>
            )) : (
              <span style={{ fontSize: '0.8rem', color: ON_DIM }}>Aucune paire retenue</span>
            )}
          </div>

          {(out.alternatives || []).length ? (
            <div className="neon-card" style={{ background: PANEL_BG, border: '1px solid ' + HAIRLINE, marginBottom: 14 }}>
              <h3 style={{
                fontSize: '0.95rem', marginBottom: 8,
                display: 'flex', alignItems: 'center', gap: 6,
                padding: '7px 12px', borderRadius: 9,
                background: ROYAL, border: '1.5px solid ' + ROYAL_EDGE, color: '#fff',
              }}>
                <Sparkles size={14} /> ALTERNATIVES
              </h3>
              {(out.alternatives || []).map((a, i) => (
                <div key={i} style={{ fontSize: '0.74rem', color: ON_DIM, marginBottom: 4 }}>
                  {JSON.stringify(a)}
                </div>
              ))}
            </div>
          ) : null}
        </>
      ) : null}
      </div>
    </div>
  )
}
