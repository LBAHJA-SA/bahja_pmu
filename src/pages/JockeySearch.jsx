import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { searchJockeys, fetchJockeyNames } from '../services/api'

export default function JockeySearch() {
  const navigate = useNavigate()
  const [query, setQuery] = useState('')
  const [suggestions, setSuggestions] = useState([])
  const [results, setResults] = useState(null)
  const [loading, setLoading] = useState(false)
  const [searched, setSearched] = useState(false)

  useEffect(() => {
    if (query.length < 2) { setSuggestions([]); return }
    const timer = setTimeout(async () => { try { setSuggestions(await fetchJockeyNames(query)) } catch (_) { setSuggestions([]) } }, 250)
    return () => clearTimeout(timer)
  }, [query])

  const doSearch = async (q) => {
    const term = q || query
    if (!term.trim()) return
    setLoading(true); setSearched(true)
    try { setResults(await searchJockeys(term)) } catch (e) { setResults({ query: term, found: false, jockeys: [], total_appearances: 0 }) }
    setLoading(false); setSuggestions([])
  }

  return (
    <>
      <h1 style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', marginBottom: 16 }}>Recherche Jockeys</h1>

      <div style={{ background: '#fff', borderRadius: 'var(--radius)', padding: 16, marginBottom: 16, boxShadow: 'var(--shadow)' }}>
        <div style={{ position: 'relative' }}>
          <input type="text" value={query} onChange={e => setQuery(e.target.value)}
            placeholder="Nom du jockey..."
            onKeyDown={e => e.key === 'Enter' && doSearch()}
            className="input" style={{ width: '100%', padding: '10px 14px', fontSize: 14 }} />
          {suggestions.length > 0 && (
            <div style={{
              position: 'absolute', top: '100%', left: 0, right: 0, zIndex: 10,
              background: '#fff', border: '1px solid #e2e8f0', borderRadius: 8, marginTop: 4,
              maxHeight: 240, overflowY: 'auto', boxShadow: '0 4px 12px rgba(0,0,0,0.1)',
            }}>
              {suggestions.map(s => (
                <div key={s} onClick={() => { setQuery(s); doSearch(s) }} style={{
                  padding: '8px 14px', cursor: 'pointer', fontSize: 13, borderBottom: '1px solid #f1f5f9',
                }} onMouseEnter={e => e.currentTarget.style.background = '#f8fafc'}
                   onMouseLeave={e => e.currentTarget.style.background = '#fff'}>
                  {s}
                </div>
              ))}
            </div>
          )}
        </div>
        <button onClick={() => doSearch()} className="btn btn-primary" style={{ marginTop: 12 }}>
          Rechercher
        </button>
      </div>

      {loading && (
        <div style={{ textAlign: 'center', padding: 60, color: '#94a3b8' }}>
          <div className="spinner" style={{ margin: '0 auto 16px' }} />
          Recherche...
        </div>
      )}

      {searched && !loading && results && !results.found && (
        <div style={{ background: '#fff', borderRadius: 'var(--radius)', padding: 60, textAlign: 'center', boxShadow: 'var(--shadow)', color: '#94a3b8' }}>
          Aucun jockey trouvé pour "{results.query}"
        </div>
      )}

      {results?.found && results?.jockeys?.map(j => (
        <div key={j.nom} style={{
          background: '#fff', borderRadius: 'var(--radius)', padding: 16, marginBottom: 12,
          boxShadow: 'var(--shadow)', borderLeft: '4px solid #0f172a',
        }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 12 }}>
            <div style={{
              width: 44, height: 44, borderRadius: 10,
              background: 'linear-gradient(135deg, #0f172a, #3b82f6)',
              display: 'flex', alignItems: 'center', justifyContent: 'center',
              color: '#fff', fontWeight: 900, fontSize: 16, flexShrink: 0,
            }}>{j.nom[0]}</div>
            <div style={{ flex: 1 }}>
              <button
                onClick={(e) => { e.stopPropagation(); navigate(`/jockey/${encodeURIComponent(j.nom)}`) }}
                style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontWeight: 800, fontSize: '1.1rem', color: '#0f172a', textAlign: 'left' }}
                onMouseEnter={e => e.currentTarget.style.color = '#ef4444'}
                onMouseLeave={e => e.currentTarget.style.color = '#0f172a'}
              >{j.nom}</button>
              <div style={{ fontSize: '0.78rem', color: '#64748b' }}>
                {j.musique ? `${j.musique}` : ''}
              </div>
            </div>
            <div style={{ textAlign: 'right' }}>
              <div style={{ fontWeight: 800, fontSize: '1.3rem', color: '#0f172a' }}>{j.total_appearances}</div>
              <div style={{ fontSize: '0.7rem', color: '#64748b' }}>courses</div>
            </div>
          </div>

          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(140px, 1fr))', gap: 8, marginBottom: 12 }}>
            <div style={{ background: '#f0fdf4', borderRadius: 8, padding: '8px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: '0.7rem', color: '#64748b' }}>Victoires</div>
              <div style={{ fontWeight: 800, fontSize: '1.1rem', color: '#166534' }}>{j.wins}</div>
              <div style={{ fontSize: '0.7rem', color: '#64748b' }}>{j.win_rate}%</div>
            </div>
            <div style={{ background: '#fffbeb', borderRadius: 8, padding: '8px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: '0.7rem', color: '#64748b' }}>Top 3</div>
              <div style={{ fontWeight: 800, fontSize: '1.1rem', color: '#92400e' }}>{j.top3}</div>
              <div style={{ fontSize: '0.7rem', color: '#64748b' }}>{j.top3_rate}%</div>
            </div>
            <div style={{ background: '#fef2f2', borderRadius: 8, padding: '8px 12px', textAlign: 'center' }}>
              <div style={{ fontSize: '0.7rem', color: '#64748b' }}>Top 5</div>
              <div style={{ fontWeight: 800, fontSize: '1.1rem', color: '#991b1b' }}>{j.top5}</div>
            </div>
            {j.avg_odds && (
              <div style={{ background: '#f1f5f9', borderRadius: 8, padding: '8px 12px', textAlign: 'center' }}>
                <div style={{ fontSize: '0.7rem', color: '#64748b' }}>Cote moy.</div>
                <div style={{ fontWeight: 800, fontSize: '1.1rem', color: '#334155' }}>{j.avg_odds}</div>
              </div>
            )}
          </div>

          {j.last_appearance && (
            <div style={{ fontSize: '0.78rem', color: '#64748b', marginBottom: 8 }}>
              Dernière course: {j.last_appearance} à {j.last_hippodrome?.replace(/_/g, ' ') || '?'}
              {j.last_position ? ` (${j.last_position}e)` : ''}
            </div>
          )}

          {j.specialty && j.specialty.discipline && Object.keys(j.specialty.discipline).length > 0 && (
            <div style={{ borderTop: '1px solid #f1f5f9', paddingTop: 10, marginTop: 4 }}>
              <div style={{ fontWeight: 700, fontSize: '0.75rem', color: '#0f172a', marginBottom: 8, textTransform: 'uppercase', letterSpacing: '0.05em' }}>Profil du jockey</div>

              <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 8 }}>
                {Object.entries(j.specialty.discipline).map(([d, s]) => (
                  <span key={d} style={{ background: '#eff6ff', color: '#1e40af', borderRadius: 6, padding: '3px 8px', fontSize: '0.7rem', fontWeight: 600 }}>
                    {d} {s.win_rate}%
                  </span>
                ))}
                {Object.entries(j.specialty.surface).map(([s, st]) => (
                  <span key={s} style={{ background: '#fef3c7', color: '#92400e', borderRadius: 6, padding: '3px 8px', fontSize: '0.7rem', fontWeight: 600 }}>
                    {s.replace(/_/g, ' ')} {st.win_rate}%
                  </span>
                ))}
              </div>

              {Object.keys(j.specialty.distance).length > 0 && (
                <div style={{ marginBottom: 8 }}>
                  <div style={{ fontSize: '0.68rem', color: '#64748b', marginBottom: 4 }}>Distances</div>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {Object.entries(j.specialty.distance).sort((a, b) => b[1].runs - a[1].runs).map(([b, s]) => (
                      <span key={b} style={{
                        background: s.win_rate >= 15 ? '#dcfce7' : s.win_rate >= 5 ? '#fef9c3' : '#f1f5f9',
                        color: s.win_rate >= 15 ? '#166534' : s.win_rate >= 5 ? '#854d0e' : '#64748b',
                        borderRadius: 4, padding: '2px 6px', fontSize: '0.65rem',
                      }}>
                        {b}: {s.runs}c {s.wins}v
                      </span>
                    ))}
                  </div>
                </div>
              )}

              {j.specialty.hippodrome && Object.keys(j.specialty.hippodrome).length > 0 && (
                <div>
                  <div style={{ fontSize: '0.68rem', color: '#64748b', marginBottom: 4 }}>Hippodromes</div>
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {Object.entries(j.specialty.hippodrome).sort((a, b) => b[1].runs - a[1].runs).slice(0, 8).map(([h, s]) => (
                      <span key={h} style={{
                        background: '#f1f5f9', color: '#334155',
                        borderRadius: 4, padding: '2px 6px', fontSize: '0.65rem',
                      }}>
                        {h.replace(/_/g, ' ')}: {s.runs}c {s.wins}v
                      </span>
                    ))}
                  </div>
                </div>
              )}
            </div>
          )}
        </div>
      ))}
    </>
  )
}
