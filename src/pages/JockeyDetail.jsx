import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { fmtClockZ } from '../lib/gmtTime'
import { fetchJockeyRaces } from '../services/api'

const SPECIALTY_COLORS = {
  ATTELE: '#ef4444', MONTE: '#22c55e', PLAT: '#3b82f6',
  HAIES: '#f97316', STEEPLE: '#a855f7'
}

function formatDate(d) { if (!d) return '-'; const p = d.split('-'); return p.length === 3 ? `${p[2]}/${p[1]}/${p[0]}` : d }
// GMT, always: the start is an instant and the printed number must not depend on the zone of the machine looking at it.
function formatTime(t) { return fmtClockZ(t) }

export default function JockeyDetail() {
  const { jockeyName } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    setLoading(true)
    fetchJockeyRaces(jockeyName)
      .then(d => { setData(d); setLoading(false) })
      .catch(() => { setData(null); setLoading(false) })
  }, [jockeyName])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 20px', color: '#94a3b8' }}>
        <div className="spinner" style={{ margin: '0 auto 16px' }} />
        Chargement...
      </div>
    )
  }

  if (!data?.found) {
    return (
      <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8', background: '#fff', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow)' }}>
        <div style={{ fontSize: 40, marginBottom: 12, opacity: 0.3 }}>&#x1F3C7;</div>
        <div style={{ fontSize: 16, fontWeight: 700, color: '#64748b', marginBottom: 8 }}>
          {decodeURIComponent(jockeyName)}
        </div>
        <div style={{ fontSize: 13, marginBottom: 16 }}>
          Aucune course archivée trouvée pour ce jockey.
        </div>
        <div style={{ fontSize: 12, color: '#94a3b8', marginBottom: 20, lineHeight: 1.6 }}>
          Les données proviennent des courses archivées dans la base de données.<br />
          Archivez d'abord des courses avec ce jockey pour voir son historique.
        </div>
        <div style={{ display: 'flex', gap: 8, justifyContent: 'center' }}>
          <button onClick={() => navigate('/jockeys')} className="btn btn-primary">
            Rechercher un jockey
          </button>
          <button onClick={() => navigate('/archive')} className="btn btn-ghost">
            Aller aux archives
          </button>
        </div>
      </div>
    )
  }

  const races = data.races
  const total = races.length
  const wins = races.filter(r => r.rang === 1).length
  const top3 = races.filter(r => r.rang && r.rang >= 1 && r.rang <= 3).length
  const top5 = races.filter(r => r.rang && r.rang >= 1 && r.rang <= 5).length

  const grouped = {}
  races.forEach(r => {
    const key = r.date || 'inconnue'
    if (!grouped[key]) grouped[key] = []
    grouped[key].push(r)
  })
  const sortedDates = Object.keys(grouped).sort().reverse()

  return (
    <>
      <button onClick={() => navigate(-1)} className="btn btn-ghost btn-sm" style={{ marginBottom: 12 }}>
        &larr; Retour
      </button>

      <div style={{
        background: '#fff', borderRadius: 'var(--radius)', padding: 20, marginBottom: 16,
        boxShadow: 'var(--shadow)',
      }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 16, marginBottom: 16 }}>
          <div style={{
            width: 52, height: 52, borderRadius: 12,
            background: 'linear-gradient(135deg, #0f172a, #3b82f6)',
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            color: '#fff', fontWeight: 900, fontSize: 22, flexShrink: 0,
          }}>
            {data.jockey[0]}
          </div>
          <div>
            <h1 style={{ fontSize: 22, fontWeight: 800, color: '#0f172a' }}>{data.jockey}</h1>
            <div style={{ fontSize: 13, color: '#64748b', marginTop: 2 }}>
              Jockey
            </div>
          </div>
        </div>

        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(120px, 1fr))', gap: 10 }}>
          <div style={{ background: '#f1f5f9', borderRadius: 8, padding: '10px 14px', textAlign: 'center' }}>
            <div style={{ fontSize: 11, color: '#64748b' }}>Courses</div>
            <div style={{ fontWeight: 800, fontSize: 20, color: '#0f172a' }}>{total}</div>
          </div>
          <div style={{ background: '#f0fdf4', borderRadius: 8, padding: '10px 14px', textAlign: 'center' }}>
            <div style={{ fontSize: 11, color: '#64748b' }}>Victoires</div>
            <div style={{ fontWeight: 800, fontSize: 20, color: '#166534' }}>{wins}</div>
            <div style={{ fontSize: 11, color: '#64748b' }}>{total ? Math.round(wins/total*100) : 0}%</div>
          </div>
          <div style={{ background: '#fffbeb', borderRadius: 8, padding: '10px 14px', textAlign: 'center' }}>
            <div style={{ fontSize: 11, color: '#64748b' }}>Top 3</div>
            <div style={{ fontWeight: 800, fontSize: 20, color: '#92400e' }}>{top3}</div>
          </div>
          <div style={{ background: '#fef2f2', borderRadius: 8, padding: '10px 14px', textAlign: 'center' }}>
            <div style={{ fontSize: 11, color: '#64748b' }}>Top 5</div>
            <div style={{ fontWeight: 800, fontSize: 20, color: '#991b1b' }}>{top5}</div>
          </div>
        </div>
      </div>

      {data.specialty && (
        <div style={{
          background: '#fff', borderRadius: 'var(--radius)', padding: 20, marginBottom: 16,
          boxShadow: 'var(--shadow)',
        }}>
          <h2 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', marginBottom: 16 }}>
            Profil du jockey
          </h2>

          {data.specialty.discipline && Object.keys(data.specialty.discipline).length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#64748b', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                Disciplines
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
                {Object.entries(data.specialty.discipline).sort((a, b) => b[1].runs - a[1].runs).map(([d, s]) => (
                  <div key={d} style={{
                    padding: '8px 14px', borderRadius: 8,
                    background: SPECIALTY_COLORS[d] || '#f1f5f9',
                    color: SPECIALTY_COLORS[d] ? '#fff' : '#334155',
                    fontSize: 12, fontWeight: 600,
                  }}>
                    <div style={{ fontWeight: 800 }}>{d}</div>
                    <div style={{ fontSize: 11, opacity: 0.9 }}>{s.runs}c {s.wins}V {s.win_rate}%</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.specialty.distance && Object.keys(data.specialty.distance).length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#64748b', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                Distances
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {Object.entries(data.specialty.distance).sort((a, b) => b[1].runs - a[1].runs).map(([d, s]) => (
                  <div key={d} style={{
                    padding: '6px 12px', borderRadius: 6,
                    background: s.win_rate >= 20 ? '#f0fdf4' : '#f8fafc',
                    border: s.win_rate >= 20 ? '1px solid #bbf7d0' : '1px solid #f1f5f9',
                    fontSize: 12,
                  }}>
                    <div style={{ fontWeight: 700, color: '#0f172a' }}>{d}</div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>{s.runs}c {s.wins}V {s.win_rate}%</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.specialty.surface && Object.keys(data.specialty.surface).length > 0 && (
            <div style={{ marginBottom: 16 }}>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#64748b', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                Terrains
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {Object.entries(data.specialty.surface).sort((a, b) => b[1].runs - a[1].runs).map(([s, st]) => (
                  <div key={s} style={{
                    padding: '6px 12px', borderRadius: 6,
                    background: st.win_rate >= 20 ? '#f0fdf4' : '#f8fafc',
                    border: st.win_rate >= 20 ? '1px solid #bbf7d0' : '1px solid #f1f5f9',
                    fontSize: 12,
                  }}>
                    <div style={{ fontWeight: 700, color: '#0f172a' }}>{s.replace(/_/g, ' ')}</div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>{st.runs}c {st.wins}V {st.win_rate}%</div>
                  </div>
                ))}
              </div>
            </div>
          )}

          {data.specialty.hippodrome && Object.keys(data.specialty.hippodrome).length > 0 && (
            <div>
              <div style={{ fontSize: 12, fontWeight: 700, color: '#64748b', marginBottom: 8, textTransform: 'uppercase', letterSpacing: 0.5 }}>
                Hippodromes
              </div>
              <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
                {Object.entries(data.specialty.hippodrome).sort((a, b) => b[1].runs - a[1].runs).map(([h, s]) => (
                  <div key={h} style={{
                    padding: '6px 12px', borderRadius: 6,
                    background: s.win_rate >= 20 ? '#f0fdf4' : '#f8fafc',
                    border: s.win_rate >= 20 ? '1px solid #bbf7d0' : '1px solid #f1f5f9',
                    fontSize: 12,
                  }}>
                    <div style={{ fontWeight: 700, color: '#0f172a' }}>{h.replace(/_/g, ' ')}</div>
                    <div style={{ fontSize: 11, color: '#64748b' }}>{s.runs}c {s.wins}V {s.win_rate}%</div>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}

      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 12,
      }}>
        <h2 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a' }}>
          Historique des courses ({total})
        </h2>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {sortedDates.map(date => {
          const dayRaces = grouped[date]
          return (
            <div key={date} style={{
              background: '#fff', borderRadius: 'var(--radius)', overflow: 'hidden',
              boxShadow: 'var(--shadow)',
            }}>
              <div style={{
                padding: '8px 16px', background: '#f8fafc', fontSize: 13,
                fontWeight: 700, color: '#0f172a', borderBottom: '1px solid #f1f5f9',
              }}>
                {formatDate(date)}
              </div>
              {dayRaces.map((r, i) => {
                const rangColor = r.rang === 1 ? '#22c55e' : r.rang === 2 ? '#3b82f6' : r.rang === 3 ? '#f59e0b' : r.rang && r.rang <= 5 ? '#f97316' : '#64748b'
                return (
                  <div
                    key={i}
                    onClick={() => navigate(`/race/${r.race_id}`)}
                    style={{
                      display: 'flex', alignItems: 'center', gap: 10,
                      padding: '10px 16px', cursor: 'pointer',
                      borderBottom: i < dayRaces.length - 1 ? '1px solid #f8fafc' : 'none',
                      transition: 'background 0.1s',
                    }}
                    onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
                    onMouseLeave={e => e.currentTarget.style.background = 'transparent'}
                  >
                    <div style={{
                      width: 32, height: 32, borderRadius: 8, flexShrink: 0,
                      background: r.rang && r.rang > 0 ? rangColor : '#f1f5f9',
                      display: 'flex', alignItems: 'center', justifyContent: 'center',
                      color: r.rang && r.rang > 0 ? '#fff' : '#94a3b8',
                      fontWeight: 800, fontSize: 12,
                    }}>
                      {r.rang && r.rang > 0 ? `${r.rang}e` : '-'}
                    </div>

                    <div style={{ flex: 1, minWidth: 0 }}>
                      <div style={{ fontWeight: 600, fontSize: 13, color: '#0f172a' }}>
                        {r.horse || ''}
                      </div>
                      <div style={{ display: 'flex', gap: 6, marginTop: 2, fontSize: 11, color: '#64748b', flexWrap: 'wrap' }}>
                        <span>{r.hippodrome?.replace(/_/g, ' ')} {r.reunion_num && r.course_num ? `R${r.reunion_num}C${r.course_num}` : ''}</span>
                        <span style={{
                          display: 'inline-block', padding: '0 4px', borderRadius: 3,
                          fontSize: 9, fontWeight: 700, color: '#fff',
                          background: SPECIALTY_COLORS[r.specialty] || '#94a3b8',
                        }}>{r.specialty}</span>
                        {r.distance && <span>{r.distance}m</span>}
                      </div>
                    </div>

                    <div style={{ textAlign: 'right', flexShrink: 0 }}>
                      <div style={{ fontSize: 11, color: '#64748b' }}>{formatTime(r.time) || ''}</div>
                      <div style={{ fontWeight: 700, fontSize: 12, color: '#0f172a' }}>
                        {r.cote_pmu ? r.cote_pmu : '-'}
                      </div>
                    </div>
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>
    </>
  )
}
