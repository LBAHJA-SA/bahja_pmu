// FLIP — its own page, its own engine, and its own score sheet.
//
// This page exists to answer one question with numbers: does the flipped ticket
// (market favourite x a horse the market wrote off) actually win anything? So
// nothing is shown without its result beside it. Pick a date, and for every
// finished race of that date the page shows what the rule said and what the
// finish order was.
//
// The engine gives three couples and nothing else: F-O1, F-O2, F-O3, being the
// favourite against the first, second and third best hidden outsider. A couplé
// wins when both horses are in the top 2, order free. Nothing else is drawn
// from the field, and nothing is added at display time — what is shown is
// exactly what the engine returned and exactly what gets scored.
//
// The caveats are printed on the page, not buried in a comment. The COUPLE
// engine's own weights were fitted on races this page also scores, so the rate
// below describes that fit — it is not a validated edge, and not a promise.
import { useEffect, useState } from 'react'
import { Flag, Calendar, Heart, TriangleAlert, NotebookPen, Scale, RefreshCw } from 'lucide-react'
import { FieldGateNote } from '../../lib/raceStatus.jsx'
import { fmtClockZ, leadText, TZ_LABEL } from '../../lib/gmtTime'
import { fetchFlipLog, clearFlipLog } from '../services/flipApi'

const ORANGE = '#f97316'
const PINK = '#ec4899'
const GREEN = '#22c55e'

// The journal reads as a score sheet: a dark ground with the numbers carrying
// the only light. The app itself runs light, so every colour used on these
// grounds is named here rather than taken from the theme — a theme token here
// would be dark text on a dark panel.
const ROW_BG = 'linear-gradient(90deg, #16110b 0%, #0f0c15 55%, #090d18 100%)'
const PANEL_BG = '#0a0d15'
// Two colours only, and which one applies is decided by the ground underneath.
// On the dark grounds the text is pure white; on the app's light page it is
// near-black. A mid grey on either one of those grounds is unreadable, which
// is what the third tier was doing.
const ON_DARK = '#ffffff'        // on #0a0d15 and on the dark row gradient
const ON_LIGHT = '#0f172a'       // on the photograph

// The photo is at full strength, so text lying on it needs its own contrast.
// A white halo does that without touching the image, where a veil over the
// image would flatten it.
const HALO = '0 1px 2px rgba(255,255,255,0.95), 0 0 7px rgba(255,255,255,0.85), 0 0 14px rgba(255,255,255,0.7)'
const HAIRLINE = 'rgba(255,255,255,0.10)'

// Royal blue, solid. Used for every heading and for every line that would
// otherwise sit straight on the photograph — opaque on purpose, so the text
// never competes with the picture and the picture is not veiled to suit it.
const ROYAL = '#1d4ed8'
const ROYAL_EDGE = '#60a5fa'
const RED = '#ef4444'

// Text-shadow is the whole trick: no library, no blur layer, and it survives
// on a plain div. The strong variant is for the two numbers a bet is actually
// made on — the favourite and where it landed.
// A single tight halo. The three stacked shadows this had reached 32px and
// smudged the digits into one another; at this size the number stays a number
// and still lifts off the dark ground.
const glow = (colour, strong) => ({
  color: colour,
  fontWeight: 900,
  textShadow: strong
    ? `0 0 3px ${colour}aa, 0 0 6px ${colour}55`
    : `0 0 2px ${colour}88`,
})

function Mark({ ok }) {
  if (ok == null) return <span style={{ color: ON_DARK }}>—</span>
  return (
    <span style={{
      fontSize: '0.64rem', fontWeight: 900, padding: '1px 6px', borderRadius: 4,
      background: ok ? `${GREEN}22` : `${RED}22`, color: ok ? GREEN : RED,
      border: `1px solid ${ok ? GREEN : RED}55`,
    }}>{ok ? 'RÉUSSI' : 'RATÉ'}</span>
  )
}

// The delay in minutes, exactly, never banded. Both ends are instants, so the
// number is the same in any zone; the clock it is measured against is printed
// in GMT next to it, and the word GMT is repeated here so the two are never
// read as two different clocks. Null when the start was never known, and the
// page says so rather than showing 0.
function Lead({ min }) {
  if (min == null) return <span style={{ color: ON_DARK }}>heure de départ inconnue</span>
  return (
    <span style={{ color: min < 0 ? '#f87171' : ON_DARK }}>
      {leadText(min)} <span style={{ opacity: 0.75 }}>({TZ_LABEL})</span>
    </span>
  )
}

// The archive and the PMU both write the venue as "HIPPODROME D'AUTEUIL" or
// "HIPPODROME DE SON PARDO PALMA". Every row of a table repeating the word
// HIPPODROME is noise; the name alone says it.
function shortHippo(name) {
  return String(name || '')
    .replace(/^HIPPODROME\s+/i, '')
    .replace(/^(DE|DES|DU|D')\s*/i, '')
    .trim() || '—'
}

// The clock of the race, from the epoch milliseconds the log kept, printed in
// GMT — the zone the delay next to it is measured in, so the two can be
// checked against each other. Shown at the end of the row so the eye reads
// race → prediction → result → when.
function clockOf(startMs) {
  return fmtClockZ(startMs) || '—'
}

function Rate({ label, k, pct, note }) {
  return (
    <div style={{
      flex: '1 1 150px', minWidth: 140, padding: '10px 12px', borderRadius: 10,
      background: PANEL_BG, border: '1px solid ' + HAIRLINE,
    }}>
      <div style={{ fontSize: '0.68rem', color: ON_DARK, marginBottom: 3 }}>{label}</div>
      <div style={{ fontSize: '1.25rem', fontWeight: 900, color: ON_DARK }}>
        {pct}<span style={{ fontSize: '0.8rem' }}>%</span>
      </div>
      <div style={{ fontSize: '0.66rem', color: ON_DARK }}>
        {k} sur {note}
      </div>
    </div>
  )
}

function Horse({ num, horse, rank, colour }) {
  return (
    <span style={{
      display: 'inline-flex', alignItems: 'center', gap: 5, margin: '0 5px 4px 0',
      padding: '3px 7px', borderRadius: 6,
      border: `1px solid ${colour}66`, background: PANEL_BG,
    }}>
      <b style={{ fontSize: '0.85rem', color: colour }}>{String(num).padStart(2, '0')}</b>
      <span style={{ fontSize: '0.75rem', color: ON_DARK }}>
        {(horse || '').slice(0, 15)}
      </span>
      {rank != null ? (
        <span style={{
          fontSize: '0.62rem', fontWeight: 900,
          color: rank <= 2 ? GREEN : rank <= 3 ? ORANGE : ON_DARK,
        }}>{rank}{rank === 1 ? 'er' : 'e'}</span>
      ) : null}
    </span>
  )
}

export default function FlipPage() {
  const [log, setLog] = useState(null)
  const [logBusy, setLogBusy] = useState(false)
  const [logErr, setLogErr] = useState(null)
  const [sort, setSort] = useState('date')
  const [confirmClear, setConfirmClear] = useState(false)

  // The journal is the live record: predictions written when a course was
  // analysed, scored as soon as the archive has the result. It is the tab that
  // fills up towards the sample the page is meant to be developed on, so it is
  // what the page opens on.
  const loadLog = async () => {
    setLogBusy(true); setLogErr(null)
    try { setLog(await fetchFlipLog()) } catch (e) { setLogErr(e.message) } finally { setLogBusy(false) }
  }

  useEffect(() => { loadLog() }, [])

  const doClear = async () => {
    setLogBusy(true); setLogErr(null)
    try {
      await clearFlipLog()
      setConfirmClear(false)
      setLog(null)
      await loadLog()
    } catch (e) { setLogErr(e.message) } finally { setLogBusy(false) }
  }

  // The delay the log already computed, in minutes, exactly. Kept as the
  // backend sent it so the page and the record can never disagree. Both ends of
  // it are instants, so the number is the same whatever zone it is read in; the
  // zone is only named so the clock printed beside it can be compared with it.
  const leadOf = (e) => e?.lead_min ?? null


  return (
    <div style={{ position: 'relative', minHeight: '100vh', padding: '12px 8px' }}>
      {/* the photograph, full viewport, always behind and never scrolling away */}
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
        background: ROYAL,
        border: '1.5px solid ' + ROYAL_EDGE, color: '#fff',
        boxShadow: '0 2px 10px rgba(29,78,216,0.5)',
      }}>
        <Flag size={20} />
        FLIP
        <small style={{ fontSize: '0.74rem', fontWeight: 700, opacity: 0.92 }}>
          les 3 couples du moteur COUPLE — enregistrés et notés
        </small>
      </div>
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap',
        marginBottom: 10,
      }}>
        <span style={{
          display: 'inline-flex', alignItems: 'center', gap: 8,
          padding: '8px 16px', borderRadius: 10,
          background: ROYAL, border: '1.5px solid ' + ROYAL_EDGE,
        }}>
          <Flag size={20} style={{ color: '#fff' }} />
          <b style={{ fontSize: '1.1rem', fontWeight: 900, color: ON_DARK, letterSpacing: '0.3px' }}>
            FLIP
          </b>
          <span style={{ fontSize: '0.8rem', color: ON_DARK, fontWeight: 700 }}>
            les 3 couples du moteur COUPLE
          </span>
        </span>
      </div>

      {/* Same ground as the caveat panels: a dark block with the orange rule, so
          the description reads as a description and not as another reading. */}
      <div style={{
        fontSize: '0.82rem', color: ON_DARK, background: PANEL_BG,
        border: '1px solid rgba(255,255,255,0.09)', borderLeft: `3px solid ${ORANGE}`,
        borderRadius: 9, padding: '11px 13px', margin: '10px 0 14px', lineHeight: 1.65,
      }}>
        Ce que fait le moteur, exactement&nbsp;: le <b style={{ color: PINK }}>COUPLE</b> donne trois
        paires — <b style={{ color: ORANGE }}>P1-P2, P1-P3, P2-P3</b> — prises sur le trio ALFARAJ à
        partir de 10 partants, ou sur les motifs Top3 en dessous. Ce sont les
        mêmes trois paires que montrent les pages TROT et GALOP, appelées de la
        même façon. <b>Rien n'est ajouté</b>&nbsp;: ni trio, ni outsiders, ni
        autre combinaison.
        <br /><br />
        La page n'enregistre rien d'autre. Chaque lecture d'une course est
        numérotée et empilée sous les autres de la même course, pour voir si
        l'heure change le billet. Le billet n'est jamais affiché sans son
        résultat réel à côté. Un couple réussit si ses deux chevaux sont dans
        le <b style={{ color: GREEN }}>top 2</b>, ordre libre.
      </div>

      <>
          {logErr ? (
            <div style={{ color: 'var(--neon-red)', fontWeight: 800, marginBottom: 10, fontSize: '0.86rem' }}>{logErr}</div>
          ) : null}

          {logBusy && !log ? (
            <div className="neon-card"><div style={{ fontSize: '0.82rem', color: ON_DARK }}>Lecture du journal…</div></div>
          ) : null}

          {log ? (
            <>
              <div className="neon-card" style={{ borderColor: `${ORANGE}59`, marginBottom: 14 }}>
                <div style={{
                  display: 'flex', alignItems: 'center', gap: 10, flexWrap: 'wrap',
                  marginBottom: 10, padding: '8px 13px', borderRadius: 10,
                  background: ROYAL, border: '1.5px solid ' + ROYAL_EDGE,
                }}>
                  <span style={{
                    display: 'inline-flex', alignItems: 'center', gap: 6,
                    color: '#fff', fontWeight: 900, fontSize: '0.95rem',
                  }}>
                    <NotebookPen size={14} /> Journal
                  </span>
                  <span style={{ fontSize: '0.78rem', color: ON_DARK, fontWeight: 800 }}>
                    {log.counts.total} enregistrée(s) · {log.counts.scored} notée(s) ·{' '}
                    {log.counts.pending} en attente · {log.counts.abstained} sans billet
                  </span>
                </div>

                {/* The one destructive action on the page. It asks twice, and the
                    second press says exactly how many records are about to go:
                    a recorded prediction is the only thing here that cannot be
                    produced again, because the rule will have moved on. */}
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                  {confirmClear ? (
                    <>
                      <span style={{ fontSize: '0.74rem', color: RED, fontWeight: 800 }}>
                        Effacer {log?.counts?.total ?? 0} enregistrement(s) ?
                        Ils ne pourront pas être refaits.
                      </span>
                      <button onClick={doClear} disabled={logBusy}
                        style={{
                          padding: '4px 12px', borderRadius: 8, cursor: 'pointer',
                          border: `1.5px solid ${RED}`, background: `${RED}26`,
                          color: RED, fontWeight: 900, fontSize: '0.7rem',
                        }}>
                        Oui, tout effacer
                      </button>
                      <button onClick={() => setConfirmClear(false)}
                        style={{
                          padding: '4px 12px', borderRadius: 8, cursor: 'pointer',
                          border: '1px solid ' + HAIRLINE, background: PANEL_BG,
                          color: ON_DARK, fontWeight: 800, fontSize: '0.7rem',
                        }}>
                        Annuler
                      </button>
                    </>
                  ) : (
                    <button onClick={() => setConfirmClear(true)}
                      style={{
                        padding: '6px 13px', borderRadius: 8, cursor: 'pointer',
                        // a solid frame, not a 14% white wash: a wash lets the
                        // light page through and the label measured 1.12 on it
                        border: '1.5px solid ' + ROYAL_EDGE, background: ROYAL,
                        color: '#fff', fontWeight: 800, fontSize: '0.74rem',
                      }}>
                      Vider le journal
                    </button>
                  )}
                </div>

                {log.tally?.races ? (
                  <>
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                      <Rate label="≥1 couple gagnant" k={log.tally.any_couple.k} pct={log.tally.any_couple.pct} note={log.tally.races} />
                      <Rate label="≥1 paire top 3" k={log.tally.any_both_top3.k} pct={log.tally.any_both_top3.pct} note={log.tally.races} />
                    </div>
                    {Object.keys(log.tally.per_key || {}).length ? (
                      <div style={{
                        fontSize: '0.78rem', marginTop: 10, fontWeight: 800,
                        padding: '7px 12px', borderRadius: 9,
                        background: ROYAL, border: '1.5px solid ' + ROYAL_EDGE,
                        color: '#fff',
                      }}>
                        par paire&nbsp;:&nbsp;
                        {Object.entries(log.tally.per_key).map(([k, v]) => (
                          <span key={k} style={{ marginRight: 14 }}>
                            <b style={{ color: '#fde68a' }}>{k}</b> top2 {v.couple_pct}% ({v.n})
                          </span>
                        ))}
                      </div>
                    ) : null}
                    <div style={{
                      fontSize: '0.72rem', marginTop: 8, fontWeight: 700,
                      padding: '7px 12px', borderRadius: 9,
                      background: ROYAL, border: '1.5px solid ' + ROYAL_EDGE,
                      color: '#dbeafe',
                    }}>
                      sur {log.tally.races} course(s) notée(s) · aucun seuil n'est fixé,
                      c'est vous qui décidez quand le nombre suffit
                    </div>
                  </>
                ) : (
                  // the empty state sits on the photograph with nothing behind
                  // it, so it carries its own dark ground rather than trusting
                  // whatever is behind the panel
                  <div style={{
                    fontSize: '0.82rem', color: ON_DARK,
                    padding: '10px 13px', borderRadius: 9,
                    background: PANEL_BG, border: '1px solid ' + HAIRLINE,
                  }}>
                    {log.counts.total
                      ? 'Aucune course notée pour l\'instant — le résultat n\'est pas encore dans l\'archive.'
                      : 'Journal vide. Sur la page COUPLE, analylez une course puis appuyez sur « Enregistrer le FLIP de cette course ».'}
                  </div>
                )}

                {/* The caveats are printed rather than buried, but they are a
                    footnote and not part of the reading. A dark ground with a
                    rule above it keeps them legible on their own terms and
                    clearly outside the numbers, which grey-on-dark at 0.68rem
                    was not. */}
                <div style={{
                  marginTop: 10, padding: '9px 11px', borderRadius: 9,
                  background: PANEL_BG,
                  border: '1px solid rgba(255,255,255,0.09)',
                  borderLeft: `3px solid ${ORANGE}66`,
                  fontSize: '0.72rem', lineHeight: 1.6,
                  color: ON_DARK,
                }}>
                  {(log.caveats || []).map((c, i) => (
                    <div key={i} style={{ display: 'flex', gap: 6, marginBottom: i ? 4 : 0 }}>
                      <span style={{ color: ORANGE, flexShrink: 0 }}>·</span>
                      <span>{c}</span>
                    </div>
                  ))}
                </div>
              </div>

              {/* the entries, prediction beside result. Sortable by delay, and
                  the delay is never banded — sorting shows the spread without
                  deciding where the cut-offs should be. */}
              <div style={{
                display: 'flex', gap: 8, margin: '0 0 10px', alignItems: 'center',
                flexWrap: 'wrap', padding: '8px 12px', borderRadius: 10,
                background: ROYAL, border: '1.5px solid ' + ROYAL_EDGE,
              }}>
                <span style={{ fontSize: '0.72rem', color: '#fff', fontWeight: 800 }}>trier par</span>
                {[
                  { key: 'date', label: 'date' },
                  { key: 'lead', label: 'délai avant le départ' },
                ].map(o => (
                  <button key={o.key} onClick={() => setSort(o.key)}
                    style={{
                      padding: '3px 10px', borderRadius: 7, cursor: 'pointer',
                      // white on the royal frame, not orange: #f97316 on
                      // rgb(29,78,216) measured 2.39
                      border: sort === o.key ? '1.5px solid #fff' : '1px solid ' + ROYAL_EDGE,
                      background: sort === o.key ? 'rgba(255,255,255,0.20)' : 'rgba(0,0,0,0.18)',
                      color: '#fff',
                      fontWeight: 800, fontSize: '0.7rem',
                    }}>
                    {o.label}{sort === o.key ? ' ↓' : ''}
                  </button>
                ))}
                <span style={{ fontSize: '0.7rem', color: '#dbeafe' }}>
                  le délai est en minutes, tel quel, mesuré en {TZ_LABEL}
                </span>
              </div>

              {/* One race, then every reading of it, one under the other. That
                  stacking is the whole point: the same race read six hours
                  early and read half an hour before the off gives two different
                  tickets, and only seeing them together says which hour was
                  worth it. */}
              {(log.groups || []).map(g => {
                const last = g.attempts[g.attempts.length - 1]
                const res = (last && last.result) || null
                return (
                  <div key={g.race_key} style={{
                    marginBottom: 12, padding: '11px 13px', borderRadius: 13,
                    background: ROW_BG,
                    border: '1px solid rgba(255,255,255,0.08)',
                  }}>
                    <div style={{ display: 'flex', alignItems: 'baseline', gap: 9, flexWrap: 'wrap' }}>
                      <b style={{ fontSize: '0.95rem', ...glow(ORANGE) }}>R{g.meeting}C{g.course}</b>
                      <span style={{ fontSize: '0.82rem', color: ON_DARK, fontWeight: 700 }}>
                        {shortHippo(g.hippodrome)}
                      </span>
                      {g.distance ? <span style={{ fontSize: '0.74rem', color: ON_DARK }}>{g.distance}m</span> : null}
                      {g.disc ? <span style={{ fontSize: '0.74rem', color: ON_DARK }}>{g.disc}</span> : null}
                      <span style={{ fontSize: '0.68rem', color: ON_DARK }}>{g.race_date}</span>
                      {/* the off, in GMT, and named as GMT. The delay printed
                          under every reading is measured against this instant,
                          so the two have to be read in the same zone. */}
                      {(g.attempts || []).some(a => a.start_ms) ? (
                        <span style={{ fontSize: '0.72rem', color: ON_DARK, fontWeight: 800 }}>
                          départ {clockOf((g.attempts.find(a => a.start_ms) || {}).start_ms)}
                        </span>
                      ) : null}
                      <span style={{
                        marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 8,
                      }}>
                        <span style={{
                          fontSize: '0.9rem', fontWeight: 800, color: PINK,
                          display: 'inline-flex', alignItems: 'center', gap: 5,
                        }}>
                          <Heart size={13} />
                          Couple
                        </span>
                        <span style={{
                          fontSize: '0.66rem', fontWeight: 900,
                          padding: '2px 7px', borderRadius: 5,
                          background: 'rgba(249,115,22,0.14)', color: ORANGE,
                          border: '1px solid rgba(249,115,22,0.4)',
                        }}>
                          {g.attempts.length} lecture{g.attempts.length > 1 ? 's' : ''}
                        </span>
                      </span>
                    </div>

                    {/* the arrival heads the race: every reading below is read
                        against this same finish order */}
                    <div style={{
                      display: 'flex', alignItems: 'baseline', gap: 10, flexWrap: 'wrap',
                      marginTop: 7, paddingBottom: 7,
                      borderBottom: '1px solid rgba(255,255,255,0.07)',
                      fontSize: '0.78rem',
                    }}>
                      <span style={{ color: ON_DARK }}>
                        arrivée{res ? ` (${res.source === 'pmu' ? 'PMU' : 'archive'})` : ''}
                      </span>
                      {res ? (
                        <span style={{ display: 'flex', gap: 10, alignItems: 'center' }}>
                          {(res.podium || []).slice(0, 3).map(([n], i) => (
                            <b key={n} style={glow(ORANGE, i < 2)}>{String(n).padStart(2, '0')}</b>
                          ))}
                        </span>
                      ) : (
                        <span style={glow(ORANGE)}>en attente du résultat</span>
                      )}
                    </div>

                    <FieldGateNote n={(g.attempts[0] || {}).ticket?.field_n} bet="Couplé" />

                    {g.attempts.map(a => {
                      const tk = a.ticket || {}
                      const pairs = tk.pairs || []
                      const ap = a.result && a.result.podium
                      const rows = (a.result && a.result.rows) || []
                      const place = (n) => {
                        if (!ap) return null
                        const hit = ap.find(q => q[0] === n)
                        return hit ? hit[1] : null
                      }
                      return (
                        <div key={a.log_key} style={{
                          marginTop: 7, display: 'flex', alignItems: 'center',
                          gap: 8, flexWrap: 'wrap',
                        }}>
                          <b style={{
                            fontSize: '0.78rem', color: '#fb923c',
                            padding: '2px 9px', borderRadius: 6,
                            background: PANEL_BG, border: '1px solid ' + HAIRLINE,
                          }}>
                            L{a.attempt}
                          </b>
                          <span style={{
                            fontSize: '0.74rem', minWidth: 128, color: ON_DARK,
                            fontWeight: 800, padding: '2px 8px', borderRadius: 6,
                            background: PANEL_BG, border: '1px solid ' + HAIRLINE,
                          }}>
                            <Lead min={leadOf(a)} />
                          </span>

                          {pairs.length ? (
                            <>
                              {/* TROT dims this panel past eight runners, which
                                  is right there: the ticket is one line among
                                  many and dimming says so. Here every line is a
                                  reading being compared, and dimming them would
                                  hide exactly the thing the page exists to
                                  show. The warning stays, once per race, where
                                  TROT puts it. */}
                              <div style={{
                                display: 'flex', flexWrap: 'wrap', gap: 6,
                              }}>
                                {pairs.slice(0, 3).map((mm, i) => {
                                  const sc = rows.find(q => q.key === mm.key)
                                  const x = mm.horses[0], y = mm.horses[1]
                                  const rx = place(x.num), ry = place(y.num)
                                  const hit = rx != null && ry != null && rx <= 2 && ry <= 2
                                  return (
                                    <span key={mm.key || i} style={{
                                      display: 'inline-flex', alignItems: 'center', gap: 5,
                                      flex: '0 1 auto',
                                      padding: '4px 9px', borderRadius: 7,
                                      fontSize: '0.82rem', whiteSpace: 'nowrap',
                                      background: 'rgba(236,72,153,0.07)',
                                      border: `1px solid ${hit ? `${GREEN}77` : HAIRLINE}`,
                                    }}>
                                      <b style={glow(PINK)}>{x.num}</b>
                                      <span style={{ color: ON_DARK }}>×</span>
                                      <b style={glow(ORANGE)}>{y.num}</b>
                                      <span style={{ color: ON_DARK }}>
                                        {(x.horse || '').slice(0, 10)}
                                      </span>
                                      <b style={glow(hit ? GREEN : '#c9d4e4')}>
                                        {rx != null ? `${rx}e` : '—'}·{ry != null ? `${ry}e` : '—'}
                                      </b>
                                      {a.status === 'scored' && sc ? (
                                        <Mark ok={!!sc.couple_hit} />
                                      ) : null}
                                    </span>
                                  )
                                })}
                              </div>
                            </>
                          ) : (
                            <div style={{
                              fontSize: '0.78rem', color: ON_DARK,
                              padding: '7px 10px', borderRadius: 8,
                              background: 'rgba(255,255,255,0.03)',
                              border: '1px solid ' + HAIRLINE,
                            }}>
                              {tk.reason_fr || 'aucun billet'}
                            </div>
                          )}
                        </div>
                      )
                    })}
                  </div>
                )
              })}

              {!(log.entries || []).length ? null : (
                <div style={{ fontSize: '0.7rem', color: ON_DARK, marginTop: 6 }}>
                  {log.newly_scored
                    ? `${log.newly_scored} course(s) viennent d'être notée(s).`
                    : log.counts.pending
                      ? `${log.counts.pending} en attente — « Rafraîchir les résultats » ne cherche que le résultat, il ne recalcule aucun billet.`
                      : ''}
                </div>
              )}
            </>
          ) : null}
        </>
      </div>
    </div>
  )
}
