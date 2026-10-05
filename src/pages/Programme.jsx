import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { fmtClockZ, fmtDayString } from '../lib/gmtTime'
import { fetchProgramme, fetchDates, saveArchiveByDate } from '../services/api'
import { RaceBetBadges } from '../components/BetBadges'
import { useNow, raceStatus, statusChip, meteoText } from '../lib/raceStatus.jsx'

const SPECIALTY_COLORS = {
  ATTELE: '#ef4444',
  MONTE: '#22c55e',
  PLAT: '#3b82f6',
  HAIES: '#f97316',
  STEEPLE: '#a855f7'
}

const DISCIPLINE_ICONS = {
  TROT: 'Trot',
  GALOP: 'Galop'
}

const COUNTRY_FLAGS = {
  FR: '🇫🇷',
  MA: '🇲🇦',
  US: '🇺🇸',
  GB: '🇬🇧',
  AR: '🇦🇷',
  ES: '🇪🇸',
  DE: '🇩🇪',
  BE: '🇧🇪',
  IT: '🇮🇹',
  AU: '🇦🇺',
}

const COUNTRY_NAMES = {
  FR: 'France',
  MA: 'Maroc',
  US: 'États-Unis',
  GB: 'Royaume-Uni',
  AR: 'Argentine',
  ES: 'Espagne',
  DE: 'Allemagne',
  BE: 'Belgique',
  IT: 'Italie',
  AU: 'Australie',
}

function formatTime(t) {
  if (!t) return ''
  return fmtClockZ(t)
  return s.length > 5 ? s.slice(0, 5) : s
}

function dayLabel(s, today) {
  if (!s) return s
  if (s === today) return "Aujourd'hui"
  // GMT noon, not local midnight: a bare calendar day has no zone of its own
  // and local midnight lands on the day before for anyone west of GMT, which
  // would call today's programme "Hier".
  const d = new Date(s + 'T12:00:00Z')
  const now = new Date(today + 'T12:00:00Z')
  const diff = Math.round((d - now) / 86400000)
  if (diff === -1) return 'Hier'
  if (diff === 1) return 'Demain'
  return s.split('-').reverse().join('/')
}

function RaceChip({ race, onClick, now }) {
  const st = raceStatus(race, now)
  return (
    <button
      onClick={() => onClick(race.id)}
      style={{
        display: 'flex', alignItems: 'center', gap: 6,
        padding: '6px 10px', borderRadius: 8,
        background: '#f8fafc', border: '1px solid #e2e8f0',
        cursor: 'pointer', fontSize: 12,
        transition: 'all 0.15s',
        minWidth: 200,
      }}
      onMouseEnter={e => { e.currentTarget.style.borderColor = '#0f172a'; e.currentTarget.style.background = '#fff' }}
      onMouseLeave={e => { e.currentTarget.style.borderColor = '#e2e8f0'; e.currentTarget.style.background = '#f8fafc' }}
    >
      <span style={{
        fontWeight: 700, color: '#0f172a', minWidth: 28,
      }}>
        C{race.numOrdre}
      </span>
      <span style={{ color: '#64748b', fontWeight: 500 }}>
        {formatTime(race.time)}
      </span>
      {statusChip(st)}
      <span style={{
        display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
        background: SPECIALTY_COLORS[race.specialty] || '#94a3b8',
        flexShrink: 0
      }} />
      <RaceBetBadges race={race} light />
      {race.runners && (
        <span style={{ fontSize: 10, color: '#64748b' }}>
          {race.runners}p
        </span>
      )}
      {race.distance && (
        <span style={{ fontSize: 9, color: '#94a3b8' }}>
          {race.distance}m
        </span>
      )}
    </button>
  )
}

export default function Programme() {
  const navigate = useNavigate()
  const location = useLocation()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [dates, setDates] = useState({})
  const localToday = new Date().toISOString().slice(0, 10)
  const [selectedDate, setSelectedDate] = useState(localToday)
  const [filterOrg, setFilterOrg] = useState('all')
  const [filterDiscipline, setFilterDiscipline] = useState('all')
  const [archiving, setArchiving] = useState(false)
  const [archiveResult, setArchiveResult] = useState(null)
  const now = useNow(30000)

  useEffect(() => {
    fetchDates().then(d => {
      setDates(d)
      const params = new URLSearchParams(location.search)
      if (params.get('date')) setSelectedDate(params.get('date'))
    }).catch(() => {
      const fallback = new Date().toISOString().slice(0, 10)
      setDates({ today: fallback, yesterday: '', tomorrow: '' })
    })
  }, [])

  useEffect(() => {
    const params = new URLSearchParams(location.search)
    const urlDate = params.get('date')
    if (urlDate && urlDate !== selectedDate) setSelectedDate(urlDate)
  }, [location.search])

  useEffect(() => {
    if (!selectedDate) return
    setLoading(true); setError(null); setFilterOrg('all'); setFilterDiscipline('all')
    fetchProgramme(selectedDate).then(d => { setData(d || {meetings: []}); setLoading(false) }).catch(e => { setError(e.message); setLoading(false) })
  }, [selectedDate])

  const days = ['yesterday', 'today', 'tomorrow'].filter(k => dates[k])

  const meetings = data?.meetings || []
  const filteredMeetings = meetings.filter(m => {
    if (filterOrg !== 'all' && m.organizer !== filterOrg) return false
    const courses = Array.isArray(m.courses) ? m.courses : []
    if (filterDiscipline !== 'all') {
      const has = courses.some(c => c.specialty === filterDiscipline)
      if (!has) return false
    }
    return true
  })

  const orgCounts = {}
  meetings.forEach(m => { orgCounts[m.organizer] = (orgCounts[m.organizer] || 0) + 1 })

  return (
    <>
      {archiveResult && (
        <div style={{
          padding: '12px 16px', borderRadius: 8, marginBottom: 16, fontSize: 13, fontWeight: 600,
          background: archiveResult.type === 'success' ? '#f0fdf4' : '#fef2f2',
          border: archiveResult.type === 'success' ? '1px solid #bbf7d0' : '1px solid #fecaca',
          color: archiveResult.type === 'success' ? '#166534' : '#dc2626'
        }}>
          {archiveResult.type === 'success'
            ? `✓ ${archiveResult.saved}/${archiveResult.total} courses archivées${archiveResult.errors > 0 ? ` (${archiveResult.errors} erreurs)` : ''}`
            : `✗ Erreur : ${archiveResult.message}`}
        </div>
      )}

      <div style={{
        background: '#fff', borderRadius: 'var(--radius)',
        padding: '20px', marginBottom: 20,
        boxShadow: 'var(--shadow)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#0f172a' }}>
            Programme {selectedDate ? `du ${fmtDayString(selectedDate)}` : ''}
          </h1>
          <button
            onClick={async () => {
              if (archiving) return
              setArchiving(true); setArchiveResult(null)
              try {
                const res = await saveArchiveByDate(selectedDate)
                setArchiveResult({ type: 'success', saved: res.saved, total: res.total, errors: res.errors?.length || 0 })
              } catch (e) { setArchiveResult({ type: 'error', message: e.message }) }
              setArchiving(false)
              setTimeout(() => setArchiveResult(null), 5000)
            }}
            className="btn btn-accent"
            disabled={archiving}
          >
            {archiving ? 'Archivage...' : 'Archiver tout'}
          </button>
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginBottom: 16 }}>
          {days.map(k => (
            <button
              key={k}
              onClick={() => setSelectedDate(dates[k])}
              style={{
                padding: '7px 18px', borderRadius: 8, border: 'none',
                fontSize: 13, fontWeight: selectedDate === dates[k] ? 700 : 500,
                cursor: 'pointer',
                background: selectedDate === dates[k] ? '#0f172a' : '#f1f5f9',
                color: selectedDate === dates[k] ? '#fff' : '#475569',
                transition: 'all 0.15s',
              }}
            >
              {k === 'yesterday' ? 'Hier' : k === 'today' ? "Aujourd'hui" : 'Demain'}
            </button>
          ))}
          <input
            type="date"
            value={selectedDate}
            onChange={e => setSelectedDate(e.target.value)}
            className="input"
            style={{ width: 150 }}
          />
        </div>

        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
          {[{ v: 'all', l: 'Toutes les disciplines' }, { v: 'PLAT', l: 'Plat' }, { v: 'ATTELE', l: 'Attelé' }, { v: 'MONTE', l: 'Monté' }, { v: 'HAIES', l: 'Haies' }, { v: 'STEEPLE', l: 'Steeple' }].map(d => (
            <button
              key={d.v}
              onClick={() => setFilterDiscipline(d.v)}
              style={{
                padding: '5px 12px', borderRadius: 20, border: '1px solid',
                borderColor: filterDiscipline === d.v ? '#0f172a' : '#e2e8f0',
                fontSize: 12, fontWeight: filterDiscipline === d.v ? 600 : 450,
                cursor: 'pointer', background: filterDiscipline === d.v ? '#0f172a' : '#fff',
                color: filterDiscipline === d.v ? '#fff' : '#64748b',
                transition: 'all 0.15s',
              }}
            >
              {d.l}
            </button>
          ))}
          <div style={{ width: 1, background: '#e2e8f0', margin: '4px 4px' }} />
          {[{ v: 'all', l: 'Tous' }, { v: 'PMU', l: 'PMU' }, { v: 'PMH', l: 'PMH' }, { v: 'INTERNET', l: 'INTERNET' }].map(o => (
            <button
              key={o.v}
              onClick={() => setFilterOrg(o.v)}
              style={{
                padding: '5px 12px', borderRadius: 20, border: '1px solid',
                borderColor: filterOrg === o.v ? '#0f172a' : '#e2e8f0',
                fontSize: 12, fontWeight: filterOrg === o.v ? 600 : 450,
                cursor: 'pointer', background: filterOrg === o.v ? '#0f172a' : '#fff',
                color: filterOrg === o.v ? '#fff' : '#64748b',
                transition: 'all 0.15s',
              }}
            >
              {o.l}
            </button>
          ))}
        </div>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: '80px 20px', color: '#94a3b8' }}>
          <div className="spinner" style={{ margin: '0 auto 16px' }} />
          Chargement du programme...
        </div>
      )}

      {error && (
        <div style={{
          background: '#fef2f2', border: '1px solid #fecaca',
          borderRadius: 'var(--radius)', padding: 24,
          color: '#dc2626', textAlign: 'center'
        }}>
          Erreur : {error}
        </div>
      )}

      {!loading && !error && !data && (
        <div style={{
          textAlign: 'center', padding: '80px 20px', color: '#94a3b8',
          background: '#fff', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow)',
        }}>
          Aucune donnée disponible pour cette date
        </div>
      )}
      {!loading && !error && data && (
        <>
          {filteredMeetings.length === 0 ? (
            <div style={{
              textAlign: 'center', padding: '80px 20px', color: '#94a3b8',
              background: '#fff', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow)',
            }}>
              Aucune réunion trouvée pour cette date
            </div>
          ) : (
            <div style={{ display: 'flex', flexDirection: 'column', gap: 12 }}>
              {filteredMeetings.map(m => {
                const coursesArr = Array.isArray(m.courses) ? m.courses : []
                const disciplines = [...new Set(coursesArr.map(c => c.specialty).filter(Boolean))]
                return (
                  <div key={m.num} style={{
                    background: '#fff', borderRadius: 'var(--radius)',
                    boxShadow: 'var(--shadow)', overflow: 'hidden',
                  }}>
                    <div style={{
                      display: 'flex', alignItems: 'center', gap: 16,
                      padding: '16px 20px',
                      borderBottom: '1px solid #f1f5f9',
                    }}>
                      <div style={{
                        width: 42, height: 42, borderRadius: 10, flexShrink: 0,
                        background: m.organizer === 'PMH' ? '#0f172a' : '#ef4444',
                        display: 'flex', alignItems: 'center', justifyContent: 'center',
                        color: '#fff', fontWeight: 800, fontSize: 16,
                      }}>
                        R{m.num}
                      </div>
                      <div style={{ flex: 1, minWidth: 0 }}>
                        <div style={{ fontWeight: 700, fontSize: 15, color: '#0f172a', marginBottom: 2 }}>
                          {COUNTRY_FLAGS[m.country] && (
                            <span style={{ marginRight: 6 }}>{COUNTRY_FLAGS[m.country]}</span>
                          )}
                          {m.hippodrome}
                          {m.country && COUNTRY_NAMES[m.country] && (
                            <span style={{ fontSize: 12, fontWeight: 500, color: '#64748b', marginLeft: 8 }}>
                              {COUNTRY_NAMES[m.country]}
                            </span>
                          )}
                        </div>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: 12, color: '#64748b' }}>
                          <span>{(Array.isArray(m.courses) ? m.courses : []).length} courses</span>
                          <span>•</span>
                          <span>Début {formatTime(m.start_time)}</span>
                          {meteoText(m.meteo) && (
                            <span title={(m.meteo.label || '') + (m.meteo.vent != null ? ` · vent ${m.meteo.vent} km/h` : '')} style={{ fontWeight: 700, color: '#0f172a' }}>
                              {meteoText(m.meteo)}
                            </span>
                          )}
                          {disciplines.map(d => (
                            <span key={d} className="specialty-badge" style={{ background: SPECIALTY_COLORS[d] || '#94a3b8' }}>
                              {d}
                            </span>
                          ))}
                          <span style={{
                            fontSize: 11, fontWeight: 600, color: m.organizer === 'PMH' ? '#0f172a' : '#ef4444',
                          }}>
                            {m.organizer || 'PMU'}
                          </span>
                        </div>
                      </div>
                      <button
                        onClick={() => {
                          const first = Array.isArray(m.courses) ? m.courses[0] : null
                          if (first) navigate(`/race/${first.id}`)
                        }}
                        className="btn btn-ghost btn-sm"
                        style={{ flexShrink: 0 }}
                      >
                        Voir
                      </button>
                    </div>
                    <div style={{
                      padding: '12px 20px 16px',
                      display: 'flex', flexWrap: 'wrap', gap: 6,
                    }}>
                      {(Array.isArray(m.courses) ? m.courses : []).map(c => (
                        <RaceChip key={c.num} race={c} onClick={(id) => navigate(`/race/${id}`)} now={now} />
                      ))}
                    </div>
                  </div>
                )
              })}
            </div>
          )}

          <div style={{
            marginTop: 24, padding: '16px 20px', background: '#fff',
            borderRadius: 'var(--radius)', textAlign: 'center',
            fontSize: 12, color: '#94a3b8', boxShadow: 'var(--shadow)',
          }}>
            Données fournies par Geny.com • {data?.meetings?.length || 0} réunions • {data?.meetings?.reduce((a, m) => a + (Array.isArray(m.courses) ? m.courses.length : 0), 0) || 0} courses
          </div>
        </>
      )}
    </>
  )
}
