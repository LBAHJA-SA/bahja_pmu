import { useEffect, useMemo, useState } from 'react'
import { Dna, Calendar, RefreshCw, Crown, Users, Layers, Target, FlaskConical, Settings2, TrendingUp, AlertTriangle, Info } from 'lucide-react'
import { fmtClockZ } from '../../lib/gmtTime'
import { fetchMeetings, fetchRace } from '../../services/api'
import { extractDnaCourse } from '../services/dnaApi'
import { RaceBetBadges } from '../../components/BetBadges'
import { useNow, raceStatus, statusChip, meteoText, countryFlag } from '../../lib/raceStatus.jsx'

const DEFAULT_LIMITS = { F: 5, S: 10, O: 20, O2: 30 }
const BAND_COLORS = { F: '#ef4444', S: '#f59e0b', O: '#22c55e', O2: '#a855f7', T: '#38bdf8', UNK: '#94a3b8' }
const ZONE_META = {
  A: { label: 'CORE', color: '#22c55e', description: 'قوية / أساسية' },
  B: { label: 'VALUE', color: '#eab308', description: 'Favori + Outsider' },
  C: { label: 'SPECULATIVE', color: '#a855f7', description: 'Outsider / Tocard' },
  D: { label: 'EXTREME', color: '#f97316', description: 'Tocard avec signal' },
}

function hippoOf(meeting) {
  if (!meeting) return ''
  if (typeof meeting.hippodrome === 'string' && meeting.hippodrome) return meeting.hippodrome
  if (meeting.hippodrome_full) return meeting.hippodrome_full
  if (meeting.hippodrome?.libelleLong) return meeting.hippodrome.libelleLong
  if (meeting.hippodrome?.libelleCourt) return meeting.hippodrome.libelleCourt
  return ''
}

function courseTime(course) {
  if (!course?.time) return ''
  const value = typeof course.time === 'number' ? course.time : Date.parse(course.time)
  if (!value || Number.isNaN(value)) return ''
  return fmtClockZ(value)
}

function pct(value) {
  if (value == null || Number.isNaN(Number(value))) return '—'
  return `${Math.round(Number(value) * 100)}%`
}

function numList(value) {
  return Array.isArray(value) ? value.join(' · ') : '—'
}

function BandBadge({ band }) {
  const color = BAND_COLORS[band] || BAND_COLORS.UNK
  return <span style={{ display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: '0.62rem', fontWeight: 900, color, background: `${color}18`, border: `1px solid ${color}66`, borderRadius: 6, padding: '2px 6px' }}>{band || 'UNK'}</span>
}

function Metric({ label, value, hint, color = '#00e5ff' }) {
  return (
    <div style={{ padding: '9px 10px', borderRadius: 10, background: 'rgba(0,229,255,0.06)', border: '1px solid rgba(0,229,255,0.22)' }}>
      <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: '1.05rem', fontWeight: 900, color, marginTop: 3 }}>{value}</div>
      {hint && <div style={{ fontSize: '0.6rem', color: 'var(--text-muted)', marginTop: 2 }}>{hint}</div>}
    </div>
  )
}

function Card({ title, subtitle, icon, children, accent = '#4ade80', style }) {
  return (
    <div className="neon-card" style={{ marginBottom: 14, borderColor: `${accent}55`, ...style }}>
      {title && (
        <h3 style={{ fontSize: '0.95rem', color: accent, marginBottom: subtitle ? 2 : 8, display: 'flex', alignItems: 'center', gap: 6 }}>
          {icon}{title}
        </h3>
      )}
      {subtitle && <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginBottom: 9 }}>{subtitle}</div>}
      {children}
    </div>
  )
}

function Notice({ tone = 'info', icon, children }) {
  const map = {
    info: { c: '#38bdf8', bg: 'rgba(56,189,248,0.08)' },
    warn: { c: '#f59e0b', bg: 'rgba(245,158,11,0.08)' },
    good: { c: '#4ade80', bg: 'rgba(74,222,128,0.08)' },
  }
  const t = map[tone] || map.info
  return (
    <div style={{ display: 'flex', gap: 8, alignItems: 'flex-start', padding: '9px 11px', borderRadius: 10, background: t.bg, border: `1px solid ${t.c}44`, fontSize: '0.7rem', color: 'var(--text-secondary)', lineHeight: 1.5 }}>
      <span style={{ color: t.c, flexShrink: 0, marginTop: 1 }}>{icon || <Info size={13} />}</span>
      <span>{children}</span>
    </div>
  )
}

function ValidationTable({ validation }) {
  if (!validation?.available) {
    return <div style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>Validation indisponible ({validation?.reason || 'historique insuffisant'}).</div>
  }
  const rows = [
    { key: 'top1', label: 'Gagnant' },
    { key: 'couple_top2', label: 'Couplé exact (top2)' },
    { key: 'couple_top5', label: 'Couplé placé (top5)' },
    { key: 'trio_top3', label: 'Trio exact (top3)' },
    { key: 'trio_top5', label: 'Trio placé (top5)' },
  ]
  const surfaces = [
    { key: 'outsider', label: 'Outsider retrouvé dans le top5' },
    { key: 'tocard', label: 'Tocard retrouvé dans le top5' },
  ]
  const cell = (v, good) => (
    <td style={{ padding: '5px 8px', textAlign: 'right', fontFamily: 'ui-monospace, monospace', fontWeight: 800, color: good ? '#4ade80' : 'var(--text-dim)' }}>
      {v == null ? '—' : `${(v * 100).toFixed(1)}%`}
    </td>
  )
  return (
    <div style={{ overflowX: 'auto' }}>
      <div style={{ fontSize: '0.66rem', color: 'var(--text-muted)', marginBottom: 7 }}>
        Backtest chronologique 70/30 · {validation.train} courses en training / {validation.test} en test ·{' '}
        arrêt au {validation.train_before}
      </div>
      <table style={{ width: '100%', borderCollapse: 'collapse', fontSize: '0.74rem' }}>
        <thead>
          <tr style={{ color: 'var(--text-muted)', fontSize: '0.66rem' }}>
            <th style={{ textAlign: 'left', padding: '4px 8px' }}>Métrique</th>
            <th style={{ textAlign: 'right', padding: '4px 8px' }}>Moteur</th>
            <th style={{ textAlign: 'right', padding: '4px 8px' }}>Marché seul</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const c = validation[`core_${r.key}`]
            const m = validation[`market_${r.key}`]
            return (
              <tr key={r.key} style={{ borderTop: '1px solid rgba(255,255,255,0.06)' }}>
                <td style={{ padding: '5px 8px' }}>{r.label}</td>
                {cell(c, c != null && m != null && c >= m)}
                {cell(m, false)}
              </tr>
            )
          })}
          {surfaces.map((r) => {
            const s = validation[`surface_${r.key}`]
            const m = validation[`market_${r.key}`]
            return (
              <tr key={r.key} style={{ borderTop: '1px solid rgba(245,158,11,0.28)', background: 'rgba(245,158,11,0.05)' }}>
                <td style={{ padding: '5px 8px', color: '#fbbf24', fontWeight: 700 }}>{r.label}</td>
                {cell(s, s != null && m != null && s > m)}
                {cell(m, false)}
              </tr>
            )
          })}
        </tbody>
      </table>
      <div style={{ fontSize: '0.64rem', color: 'var(--text-muted)', marginTop: 8, lineHeight: 1.55 }}>
        Le classement principal suit le marché : le moteur n&apos;ajoute aucun gain sur le gagnant,
        le couplé ni le trio. Les deux surfaces du bas sont des listes filtrées (bandes O/O2/T
        et T uniquement, score de forme seul, aucun terme de marché) — un favori ne peut pas y
        entrer. Mesuré sur ces mêmes listes :{' '}
        {validation.content_outsider != null && `${(validation.content_outsider * 100).toFixed(0)}%`} des
        places de la surface outsider sont de vrais outsiders, et{' '}
        {validation.content_tocard != null && `${(validation.content_tocard * 100).toFixed(0)}%`} de
        la surface tocard sont de vrais tocards.
      </div>
    </div>
  )
}

function SurfaceList({ title, rows, accent, measured, baseline }) {
  if (!rows?.length) {
    return (
      <div>
        <div style={{ fontSize: '0.72rem', fontWeight: 800, color: accent, marginBottom: 5 }}>{title}</div>
        <div style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>Aucun cheval dans cette bande pour cette course.</div>
      </div>
    )
  }
  return (
    <div>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', gap: 8, marginBottom: 6, flexWrap: 'wrap' }}>
        <span style={{ fontSize: '0.72rem', fontWeight: 800, color: accent }}>{title}</span>
        {measured != null && (
          <span style={{ fontSize: '0.63rem', color: 'var(--text-muted)' }}>
            retrouve {Math.round(measured * 100)}% de ceux qui finissent top5
            {baseline != null && ` · marché ${Math.round(baseline * 100)}%`}
          </span>
        )}
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(196px, 1fr))', gap: 7 }}>
        {rows.map((s, i) => (
          <div key={s.num} style={{ padding: '8px 10px', borderRadius: 10, background: `${accent}0d`, border: `1px solid ${accent}44` }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
              <b style={{ color: accent }}>{i + 1}. {String(s.num).padStart(2, '0')} {s.horse}</b>
              <b style={{ color: 'var(--text-primary)', fontSize: '0.82rem' }}>{Number(s.selection_score || 0).toFixed(0)}</b>
            </div>
            <div style={{ display: 'flex', gap: 5, marginTop: 5, alignItems: 'center', flexWrap: 'wrap' }}>
              <BandBadge band={s.band} />
              <span style={{ fontSize: '0.62rem', color: 'var(--text-muted)' }}>
                cote {s.cote} · marché #{s.market_rank}
              </span>
              {s.cote_band_hit_rate != null && (
                <span style={{ fontSize: '0.6rem', color: accent, border: `1px solid ${accent}55`, borderRadius: 5, padding: '1px 5px' }}
                      title="taux de réussite mesuré pour cette fourchette de cotes">
                  {Math.round(s.cote_band_hit_rate * 100)}% à cette cote
                </span>
              )}
            </div>
            <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)', marginTop: 4 }}>
              {s.runs_n} courses · Top3 {Math.round((s.top3_rate || 0) * 100)}%
            </div>
            <div style={{ fontSize: '0.6rem', color: s.signals ? accent : 'var(--text-muted)', marginTop: 2 }}>
              {s.signals ? `signaux : ${s.signal_names.join(', ')}` : 'aucun signal'}
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}

export default function DnaCoursePage() {
  const [date, setDate] = useState(() => new Date().toISOString().slice(0, 10))
  const [meetings, setMeetings] = useState([])
  const [selReu, setSelReu] = useState(null)
  const [sel, setSel] = useState(null)
  const [raceData, setRaceData] = useState(null)
  const [result, setResult] = useState(null)
  const [loading, setLoading] = useState(false)
  const [analyzing, setAnalyzing] = useState(false)
  const [err, setErr] = useState(null)
  const [limits, setLimits] = useState(DEFAULT_LIMITS)
  const [formNudge, setFormNudge] = useState(0.06)
  const now = useNow(30000)

  const loadMeetings = async (value = date) => {
    setLoading(true)
    setErr(null)
    try {
      const data = await fetchMeetings(value)
      setMeetings(data.meetings || [])
    } catch (e) {
      setErr(e.message)
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => { loadMeetings(date) }, [])

  const pick = async (meeting, course) => {
    setSel({ date, rnum: meeting.num, cnum: course.num, meeting, course })
    setRaceData(null)
    setResult(null)
    setErr(null)
    try {
      const data = await fetchRace(date, meeting.num, course.num)
      setRaceData(data)
    } catch (e) {
      setErr(e.message)
    }
  }

  const run = async () => {
    if (!raceData?.participants?.length || !sel) return
    setAnalyzing(true)
    setErr(null)
    try {
      const bands = [
        { label: 'F', max: Number(limits.F) || 5 },
        { label: 'S', max: Number(limits.S) || 10 },
        { label: 'O', max: Number(limits.O) || 20 },
        { label: 'O2', max: Number(limits.O2) || 30 },
        { label: 'T', max: 1000000 },
      ]
      const data = await extractDnaCourse(raceData.participants, {
        hippodrome: hippoOf(sel.meeting),
        disc: sel.course.discipline || sel.course.specialty || '',
        distance: sel.course.distance,
        surface: sel.course.surface || raceData.course?.surface || '',
        date,
        runners: sel.course.runners || raceData.participants.length,
        config: { bands, form_nudge: Number(formNudge) || 0 },
      })
      setResult(data)
    } catch (e) {
      setErr(e.message)
    } finally {
      setAnalyzing(false)
    }
  }

  const field = result?.individual || []
  const byMarket = useMemo(
    () => [...field].sort((a, b) => (a.market_rank || 99) - (b.market_rank || 99)),
    [field]
  )
  const outsiderSurface = result?.outsider_surface || []
  const tocardSurface = result?.tocard_surface || []
  const pairs = result?.pairs || []
  const ordered = result?.ordered_trios || []
  const market = result?.market_dna || {}
  const zones = result?.zones || {}
  const injection = result?.outsider_injection || {}
  const validation = result?.validation || {}
  // NB: must come after `validation` is initialised, otherwise reading it here
  // throws a temporal-dead-zone ReferenceError and blanks the whole page.
  const bandRates = validation.band_hit_rate || null
  const coteRates = validation.cote_bucket_hit_rate || null
  const structures = result?.structures || []
  const marketProfile = market.current_profile || result?.market_profile || {}
  const history = result?.history || {}
  const profileBands = useMemo(() => Object.entries(marketProfile), [marketProfile])
  const patternMax = Math.max(1, ...(market.historical_patterns || []).map(([, n]) => n))

  return (
    <div className="neon-theme dna-course-theme">
      <div className="page-tag dna" style={{ display: 'inline-flex', alignItems: 'center', gap: 6, background: 'rgba(34,197,94,0.15)', color: '#4ade80', border: '1px solid #4ade80' }}>
        <Dna size={14} /> DNA COURSE <small>Marché-ancré · Individual · Pair · Trio · Market</small>
      </div>
      <h2 className="neon-title" style={{ display: 'flex', alignItems: 'center', gap: 8, marginBottom: 4, flexWrap: 'wrap' }}>
        <Dna size={24} style={{ color: '#4ade80' }} /> RACE DNA ENGINE
        <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>v{result?.version || '3.1'}</span>
      </h2>
      <p style={{ color: 'var(--text-dim)', fontSize: '0.84rem', margin: '0 0 14px' }}>
        Le classement principal est ancré sur le marché, parce que c&apos;est le seul signal mesuré
        comme fiable. Les couches DNA expliquent la course et alimentent des surfaces
        outsider / tocard à forte variance.
      </p>

      <Card title="Bandes de marché & dosage du modèle" icon={<Settings2 size={14} />} accent="#4ade80">
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center', marginBottom: 8 }}>
          {['F', 'S', 'O', 'O2'].map((band) => (
            <label key={band} style={{ display: 'flex', alignItems: 'center', gap: 5, fontSize: '0.72rem', color: BAND_COLORS[band] }}>
              {band} ≤
              <input type="number" step="0.5" value={limits[band]} onChange={(e) => setLimits((o) => ({ ...o, [band]: e.target.value }))}
                style={{ width: 66, background: '#0d1424', color: '#fff', border: '1px solid var(--border)', borderRadius: 7, padding: '5px 7px' }} />
            </label>
          ))}
          <span style={{ fontSize: '0.7rem', color: 'var(--text-muted)' }}>T &gt; {limits.O2}</span>
          <button onClick={() => setLimits(DEFAULT_LIMITS)} className="neon-btn outline" style={{ padding: '5px 9px', fontSize: '0.68rem' }}>Réinitialiser</button>
        </div>
        <label style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.72rem', color: 'var(--text-secondary)' }}>
          Poids de la forme dans le classement
          <input type="range" min="0" max="0.25" step="0.01" value={formNudge} onChange={(e) => setFormNudge(e.target.value)} style={{ flex: 1, maxWidth: 220 }} />
          <b style={{ color: '#4ade80', fontFamily: 'ui-monospace, monospace' }}>{Math.round(formNudge * 100)}%</b>
        </label>
        <div style={{ fontSize: '0.63rem', color: 'var(--text-muted)', marginTop: 4 }}>
          0 % = classement purement marché. Au-delà, la forme ne fait que dégrader la performance
          mesurée — c&apos;est pour cela que la valeur par défaut reste très basse.
        </div>
      </Card>

      <Card title="Courses du jour" icon={<Calendar size={14} />} accent="#00e5ff">
        <div style={{ display: 'flex', gap: 10, flexWrap: 'wrap', alignItems: 'center' }}>
          <input type="date" value={date} onChange={(e) => setDate(e.target.value)} className="neon-input" />
          <button onClick={() => loadMeetings(date)} disabled={loading} className="neon-btn neon-btn-lg" style={{ background: 'linear-gradient(135deg, #4ade80, #06b6d4)', border: 'none', color: '#04121a' }}>
            <RefreshCw size={14} /> {loading ? '…' : `Charger ${date}`}
          </button>
          <span style={{ fontSize: '0.76rem', color: 'var(--text-muted)' }}>{meetings.length} réunions</span>
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
          {meetings.map((meeting) => {
            const active = String(selReu) === String(meeting.num)
            const name = (meeting.hippodrome_full || meeting.hippodrome?.libelleLong || meeting.hippodrome || `R${meeting.num}`).toString()
            return (
              <button key={meeting.num} onClick={() => setSelReu(active ? null : meeting.num)}
                style={{ minWidth: 145, padding: '10px 12px', borderRadius: 12, border: active ? '1.5px solid #4ade80' : '1px solid var(--border)', background: active ? 'rgba(34,197,94,0.12)' : 'rgba(255,255,255,0.03)', color: active ? '#4ade80' : 'var(--text-primary)', fontWeight: 900, fontSize: '0.84rem', cursor: 'pointer', textAlign: 'left' }}>
                <div>R{meeting.num}{countryFlag(meeting.country) && <span style={{ marginLeft: 4 }}>{countryFlag(meeting.country)}</span>}{meteoText(meeting.meteo) && <span style={{ fontSize: '0.66rem', fontWeight: 600, marginLeft: 4 }}>{meteoText(meeting.meteo)}</span>}</div>
                <div style={{ fontSize: '0.64rem', color: 'var(--text-muted)', maxWidth: 175, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{name}</div>
                <div style={{ fontSize: '0.64rem' }}>{(meeting.courses || []).length} courses</div>
              </button>
            )
          })}
        </div>
        {selReu != null && (() => {
          const meeting = meetings.find((i) => String(i.num) === String(selReu))
          if (!meeting) return null
          return (
            <div style={{ marginTop: 12, borderTop: '1px solid rgba(255,255,255,0.06)', paddingTop: 12 }}>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {(meeting.courses || []).map((course) => {
                  const active = sel?.rnum === meeting.num && sel?.cnum === course.num
                  const status = raceStatus(course, now)
                  return (
                    <button key={course.num} onClick={() => pick(meeting, course)}
                      style={{ minWidth: 104, padding: '8px 10px', borderRadius: 10, border: active ? '1.5px solid #4ade80' : '1px solid var(--border)', background: active ? 'rgba(34,197,94,0.12)' : 'rgba(255,255,255,0.03)', color: active ? '#4ade80' : 'var(--text-secondary)', fontWeight: 800, fontSize: '0.82rem', cursor: 'pointer', textAlign: 'left' }}>
                      <div>C{course.num} {courseTime(course)}</div>
                      <div style={{ marginTop: 2 }}>{statusChip(status, true)}</div>
                      <div style={{ fontSize: '0.64rem', color: 'var(--text-muted)' }}>{course.discipline || course.specialty || ''} {course.distance}m</div>
                      <RaceBetBadges race={course} />
                    </button>
                  )
                })}
              </div>
            </div>
          )
        })()}
      </Card>

      {sel && (
        <Card accent="#4ade80">
          <h3 style={{ fontSize: '0.95rem', color: '#4ade80', marginBottom: 8, display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap' }}>
            <Crown size={15} /> R{sel.rnum}C{sel.cnum} — {sel.course.libelle || sel.course.discipline || sel.course.specialty}{' '}
            {statusChip(raceStatus(sel.course, now))}
          </h3>
          <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
            <RaceBetBadges race={sel.course} />
            <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)' }}>{hippoOf(sel.meeting)}</span>
          </div>
          {raceData && (
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 10 }}>
              {raceData.participants.slice(0, 20).map((p) => (
                <span key={p.num} style={{ fontSize: '0.86rem', padding: '3px 6px', borderRadius: 6, background: 'rgba(255,255,255,0.04)', border: '1px solid var(--border)' }}>
                  <b style={{ color: '#4ade80' }}>{p.num}</b> {p.horse}
                </span>
              ))}
            </div>
          )}
          <button onClick={run} disabled={analyzing || !raceData?.participants?.length} className="neon-btn neon-btn-lg"
            style={{ background: 'linear-gradient(135deg, #4ade80, #06b6d4)', border: 'none', color: '#04121a', opacity: analyzing || !raceData?.participants?.length ? 0.6 : 1 }}>
            {analyzing ? 'RACE DNA ENGINE…' : 'Lancer RACE DNA ENGINE'}
          </button>
          {err && <div style={{ color: 'var(--neon-red)', fontSize: '0.84rem', marginTop: 8 }}>{err}</div>}
        </Card>
      )}

      {result && (
        <>
          <Card title="Fiabilité mesurée" icon={<FlaskConical size={15} />} accent="#a855f7"
            subtitle="Backtest chronologique sur le même contexte de course, sans fuite de données.">
            <ValidationTable validation={validation} />
            <div style={{ fontSize: '0.63rem', color: 'var(--text-muted)', marginTop: 9, display: 'flex', gap: 12, flexWrap: 'wrap' }}>
              <span>Archive : {history.archive || '—'}</span>
              <span>Chevaliers connus : {history.field_known}/{field.length}</span>
              <span>Courses de contexte : {history.context_races ?? '—'}</span>
            </div>
          </Card>

          <Card title="Market DNA" icon={<Target size={15} />} accent="#00e5ff"
            subtitle="Structure de marché observée dans l’historique de ce type de course. Décrit la course — ne prédit pas le résultat.">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(140px, 1fr))', gap: 8 }}>
              <Metric label="DNA (top 3)" value={market.dna || '—'} hint={`support ${market.pattern_support || 0}`} />
              <Metric label="DNA (top 5)" value={market.top5_dna || '—'} hint={`support ${market.top5_support || 0}`} />
              {profileBands.map(([band, count]) => (
                <div key={band} style={{ padding: '9px 10px', borderRadius: 10, background: `${BAND_COLORS[band] || BAND_COLORS.UNK}12`, border: `1px solid ${BAND_COLORS[band] || BAND_COLORS.UNK}44` }}>
                  <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)' }}>{band} dans le field</div>
                  <div style={{ fontSize: '1.05rem', fontWeight: 900, color: BAND_COLORS[band] || '#fff' }}>{count}</div>
                </div>
              ))}
            </div>
            {(market.historical_patterns || []).length > 0 && (
              <div style={{ marginTop: 10 }}>
                <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginBottom: 5 }}>Formes top-3 les plus fréquentes dans ce contexte</div>
                <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
                  {market.historical_patterns.slice(0, 6).map(([pat, n]) => (
                    <div key={pat} style={{ display: 'flex', alignItems: 'center', gap: 7 }}>
                      <span style={{ fontSize: '0.68rem', fontFamily: 'ui-monospace, monospace', width: 74, color: pat === market.dna ? '#4ade80' : 'var(--text-secondary)', fontWeight: pat === market.dna ? 900 : 500 }}>{pat}</span>
                      <div style={{ flex: 1, height: 6, borderRadius: 3, background: 'rgba(255,255,255,0.05)', overflow: 'hidden' }}>
                        <div style={{ width: `${(n / patternMax) * 100}%`, height: '100%', background: pat === market.dna ? '#4ade80' : '#0ea5e9' }} />
                      </div>
                      <span style={{ fontSize: '0.64rem', color: 'var(--text-muted)', width: 34, textAlign: 'right' }}>{n}</span>
                    </div>
                  ))}
                </div>
              </div>
            )}
            {(market.tilt || []).length > 0 && (
              <div style={{ marginTop: 9, fontSize: '0.72rem', color: 'var(--text-muted)' }}>
                Tilt historique : {market.tilt.slice(0, 5).map((t) => `${t.band} ${pct(t.share)}`).join(' · ')}
              </div>
            )}
          </Card>

          <Card title="Classement principal" icon={<Users size={15} />} accent="#4ade80"
            subtitle={`Ordre marché (pondération forme ${Math.round((result.ranking?.form_nudge ?? 0) * 100)}%). Le rang marché est la colonne de référence.`}>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(232px, 1fr))', gap: 8 }}>
              {byMarket.map((h) => {
                const form = h.form || {}
                return (
                  <div key={h.num} style={{ padding: '10px', borderRadius: 11, border: `1px solid ${BAND_COLORS[h.band] || '#334155'}66`, background: `${BAND_COLORS[h.band] || '#334155'}0d` }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6, alignItems: 'baseline' }}>
                      <div style={{ fontWeight: 900, color: BAND_COLORS[h.band] || '#fff' }}>
                        <span style={{ opacity: 0.55, fontSize: '0.72rem', marginRight: 4 }}>#{h.market_rank}</span>
                        {String(h.num).padStart(2, '0')} {h.horse}
                      </div>
                      <b style={{ color: '#4ade80', fontSize: '0.85rem' }}>{Number(h.score || 0).toFixed(1)}</b>
                    </div>
                    <div style={{ display: 'flex', gap: 5, flexWrap: 'wrap', marginTop: 6, alignItems: 'center' }}>
                      <BandBadge band={h.band} />
                      <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>cote {h.cote ?? '—'}</span>
                      {form.shrunk && <span style={{ fontSize: '0.6rem', color: '#f59e0b', border: '1px solid #f59e0b55', borderRadius: 5, padding: '1px 5px' }}>historique court</span>}
                    </div>
                    <div style={{ fontSize: '0.67rem', color: 'var(--text-secondary)', marginTop: 6 }}>
                      {form.runs_n || 0} courses · Top3 {(form.top3_rate * 100 || 0).toFixed(0)}% · Top5 {(form.top5_rate * 100 || 0).toFixed(0)}%
                      {form.confidence < 1 && <span style={{ color: 'var(--text-muted)' }}> (corrigé vers la moyenne)</span>}
                    </div>
                    <div style={{ fontSize: '0.63rem', color: 'var(--text-muted)', marginTop: 3 }}>
                      {(h.dna_reasons || h.reasons || []).slice(0, 4).join(' · ')}
                    </div>
                  </div>
                )
              })}
            </div>
          </Card>

          <Card title="Sélections outsider / tocard" icon={<TrendingUp size={15} />} accent="#f59e0b"
            subtitle="Sélections séparées par bande de prix, parce que ce ne sont pas les mêmes paris. Un outsider à 12/1 finit dans le top 5 une fois sur deux ; un tocard à 179/1, une fois sur dix.">
            <div style={{ marginBottom: 10 }}>
              <Notice tone="warn" icon={<AlertTriangle size={13} />}>
                Ces sélections ne remplacent pas le classement principal : elles perdent volontairement
                contre le marché sur le gagnant, le couplé et le trio. Utilisez-les pour les bets à cote
                élevée, pas pour la base. Les deux listes ne se recoupent jamais.
              </Notice>
            </div>
            <SurfaceList
              title="OUTSIDER — bandes O / O2"
              rows={outsiderSurface}
              accent="#22c55e"
              measured={validation.surface_outsider}
              baseline={validation.market_outsider}
            />
            <div style={{ height: 12 }} />
            <SurfaceList
              title="TOCARD — bande T"
              rows={tocardSurface}
              accent="#38bdf8"
              measured={validation.surface_tocard}
              baseline={validation.market_tocard}
            />
            {bandRates && (
              <div style={{ marginTop: 11, fontSize: '0.63rem', color: 'var(--text-muted)', lineHeight: 1.55 }}>
                Taux de réussite mesuré par bande, recalculé à chaque appel :{' '}
                {Object.entries(bandRates).map(([b, r]) => `${b} ${Math.round(r * 100)}%`).join(' · ')}.{' '}
                {coteRates && Object.keys(coteRates).length > 0 && (
                  <>
                    {' '}À l&apos;intérieur de la bande T, par fourchette de cotes :{' '}
                    {Object.entries(coteRates).map(([b, r]) => `${b}/1 → ${Math.round(r * 100)}%`).join(' · ')}.{' '}
                  </>
                )}
                C&apos;est ce qui décide de l&apos;ordre dans chaque liste : un tocard à 82/1 passe
                avant un tocard à 179/1 parce que la cote compte, pas seulement la bande.
              </div>
            )}
          </Card>

          <Card title="Couplés & trios" icon={<Layers size={15} />} accent="#ec4899"
            subtitle="Classement ancré sur le marché, enrichi par la synergie de co-courses lorsque l’historique existe.">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(258px, 1fr))', gap: 8 }}>
              {pairs.slice(0, 6).map((p, i) => (
                <div key={`p${i}`} style={{ padding: '9px 10px', borderRadius: 10, background: 'rgba(236,72,153,0.06)', border: '1px solid rgba(236,72,153,0.25)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                    <b style={{ color: '#ec4899' }}>{numList(p.nums)}</b>
                    <b style={{ color: '#4ade80', fontSize: '0.82rem' }}>{Number(p.score || 0).toFixed(1)}</b>
                  </div>
                  <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: 4 }}>
                    {p.band_pattern} · base {Number(p.market_base || 0).toFixed(0)} ·{' '}
                    {p.synergy_known ? `synergie ${p.synergy_score} (${p.historical_support} courses)` : 'pas d’historique commun'}
                  </div>
                </div>
              ))}
              {ordered.slice(0, 6).map((t, i) => (
                <div key={`t${i}`} style={{ padding: '9px 10px', borderRadius: 10, background: 'rgba(234,179,8,0.06)', border: '1px solid rgba(234,179,8,0.25)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between', gap: 6 }}>
                    <b style={{ color: '#eab308' }}>{numList(t.ordered_nums || t.nums)}</b>
                    <b style={{ color: '#4ade80', fontSize: '0.82rem' }}>{Number(t.ordered_score || 0).toFixed(1)}</b>
                  </div>
                  <div style={{ fontSize: '0.65rem', color: 'var(--text-muted)', marginTop: 4 }}>
                    {t.band_pattern} · zone {t.zone} · {t.synergy_known ? `${t.historical_support} courses communes` : 'pas d’historique commun'}
                  </div>
                </div>
              ))}
            </div>
          </Card>

          <Card title="Surfaces par zone" icon={<Layers size={15} />} accent="#fb923c"
            subtitle="Classement des combinaisons par nature de marché. Bon pour des Exactos et des combinaisons larges, pas pour une sélection resserrée.">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: 8 }}>
              {Object.keys(ZONE_META).map((z) => (
                <div key={z} style={{ padding: '9px', borderRadius: 10, background: `${ZONE_META[z].color}0d`, border: `1px solid ${ZONE_META[z].color}44` }}>
                  <div style={{ fontWeight: 900, color: ZONE_META[z].color }}>ZONE {z} · {ZONE_META[z].label}</div>
                  <div style={{ fontSize: '0.62rem', color: 'var(--text-muted)', margin: '4px 0 7px' }}>{ZONE_META[z].description}</div>
                  {(zones[z] || []).slice(0, 3).map((item, i) => (
                    <div key={i} style={{ fontSize: '0.7rem', marginTop: 4, display: 'flex', justifyContent: 'space-between' }}>
                      <span>{numList(item.nums)}</span>
                      <span style={{ color: 'var(--text-muted)' }}>{Number(item.score || 0).toFixed(1)}</span>
                    </div>
                  ))}
                  {!(zones[z] || []).length && <div style={{ fontSize: '0.66rem', color: 'var(--text-muted)' }}>—</div>}
                </div>
              ))}
            </div>
          </Card>

          <Card title="Piscines outsider / tocard" icon={<TrendingUp size={15} />} accent="#38bdf8"
            subtitle="Groupes consolidés pour construire vos combinaisons à cote élevée. Rappel : la value Surface est la plus volatile du moteur.">
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: 8, marginBottom: 9 }}>
              <Metric label="CORE" value={numList(injection.core)} color="#4ade80" />
              <Metric label="OUTSIDER_POOL" value={numList(injection.outsider_pool)} color="#22c55e" />
              <Metric label="TOCARD_POOL" value={numList(injection.tocard_pool)} color="#38bdf8" />
            </div>
            <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(238px, 1fr))', gap: 8 }}>
              {(injection.tickets || []).slice(0, 6).map((item, i) => (
                <div key={i} style={{ padding: '8px', borderRadius: 9, border: '1px solid rgba(56,189,248,0.3)', background: 'rgba(56,189,248,0.06)' }}>
                  <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                    <b style={{ color: '#38bdf8' }}>{numList(item.nums)}</b>
                    <b style={{ color: '#4ade80', fontSize: '0.82rem' }}>{Number(item.surface_score || 0).toFixed(1)}</b>
                  </div>
                  <div style={{ fontSize: '0.63rem', color: 'var(--text-muted)', marginTop: 4 }}>{(item.roles || []).join(' + ')} · {item.band_pattern}</div>
                </div>
              ))}
            </div>
          </Card>

          {structures.length > 0 && (
            <Card title="Structures compatibles" icon={<Layers size={15} />} accent="#fb923c"
              subtitle="Formes top-3 les plus fréquentes dans l’historique de ce contexte, avec les chevaux du field qui correspondent.">
              <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(232px, 1fr))', gap: 8 }}>
                {structures.slice(0, 8).map((item, i) => (
                  <div key={i} style={{ padding: '9px', borderRadius: 10, background: 'rgba(249,115,22,0.06)', border: '1px solid rgba(249,115,22,0.25)' }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between' }}>
                      <b style={{ color: '#fb923c' }}>{item.template}</b>
                      <b style={{ color: '#4ade80', fontSize: '0.82rem' }}>{Number(item.score || 0).toFixed(1)}</b>
                    </div>
                    <div style={{ fontSize: '0.68rem', color: 'var(--text-muted)', marginTop: 5 }}>
                      {numList(item.nums)} · support {item.template_support}
                    </div>
                  </div>
                ))}
              </div>
            </Card>
          )}
        </>
      )}
    </div>
  )
}
