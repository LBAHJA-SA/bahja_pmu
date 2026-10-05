import { useState, useEffect } from 'react'
import { useNavigate } from 'react-router-dom'
import { fmtClockZ } from '../lib/gmtTime'
import { fetchProgramme, fetchRaceDetails, saveArchive, fetchArchives, deleteArchiveFile, fetchArchiveDates, deleteArchivedRace, fetchArchiveRaces } from '../services/api'
import { RaceBetBadges } from '../components/BetBadges'

const SPECIALTY_COLORS = {
  ATTELE: '#ef4444', MONTE: '#22c55e', PLAT: '#3b82f6',
  HAIES: '#f97316', STEEPLE: '#a855f7'
}

// GMT, always: the start is an instant and the printed number must not depend on the zone of the machine looking at it.
function formatTime(t) { return fmtClockZ(t) }
function dayLabel(s) { if (!s) return s; const p = s.split('-'); return p.length === 3 ? `${p[2]}/${p[1]}/${p[0]}` : s }

export default function Archive() {
  const navigate = useNavigate()
  const today = new Date().toISOString().split('T')[0]
  const [date, setDate] = useState(today)
  const [view, setView] = useState('live')
  const [data, setData] = useState(null)
  const [archives, setArchives] = useState([])
  const [selR, setSelR] = useState(null)
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [liveSearch, setLiveSearch] = useState('')
  const [archSearch, setArchSearch] = useState('')
  const [toast, setToast] = useState(null)
  const [archiveDates, setArchiveDates] = useState([])
  const [selectedDate, setSelectedDate] = useState('')
  const [dayRaces, setDayRaces] = useState([])
  const [dayLoading, setDayLoading] = useState(false)

  const show = (msg, ok = true) => { setToast({ msg, ok }); setTimeout(() => setToast(null), 3000) }

  useEffect(() => { loadArch() }, [])
  useEffect(() => { if (view === 'live' && data === null) loadProg(today) }, [view])
  useEffect(() => { fetchArchiveDates().then(d => setArchiveDates(d.dates || [])).catch(() => {}) }, [])
  useEffect(() => {
    if (view !== 'saved' || !selectedDate) { setDayRaces([]); return }
    setDayLoading(true)
    fetchArchiveRaces({ date: selectedDate, limit: 200 })
      .then(r => setDayRaces(r.races || []))
      .catch(() => setDayRaces([]))
      .finally(() => setDayLoading(false))
  }, [view, selectedDate])

  const loadProg = async (d) => { try { setLoading(true); setData(await fetchProgramme(d)); setSelR(null) } catch (e) { show(e.message, false) } finally { setLoading(false) } }
  const loadArch = async () => { try { setArchives(await fetchArchives()) } catch (e) { console.error(e) } }

  const archRace = async (race) => {
    try { setBusy(true); const rd = await fetchRaceDetails(race.id); if (!rd || rd.error) throw new Error(rd?.error || 'Erreur'); await saveArchive({ race_id: race.id, data: rd }); show(`C${race.num} archivée`); loadArch() }
    catch (e) { show(e.message, false) } finally { setBusy(false) }
  }
  const archMeeting = async () => {
    try { setBusy(true); let c = 0; for (const race of selR.courses) { try { const rd = await fetchRaceDetails(race.id); if (rd && !rd.error) { await saveArchive({ race_id: race.id, data: rd }); c++ } } catch (_) {} }; show(`${c}/${selR.courses.length} courses archivées`); loadArch() }
    catch (e) { show(e.message, false) } finally { setBusy(false) }
  }
  const archAll = async () => {
    if (!data?.meetings?.length) return
    try { setBusy(true); let c = 0, t = 0; for (const m of data.meetings) { for (const race of m.courses) { t++; try { const rd = await fetchRaceDetails(race.id); if (rd && !rd.error) { await saveArchive({ race_id: race.id, data: rd }); c++ } } catch (_) {} } }; show(`${c}/${t} courses archivées`); loadArch() }
    catch (e) { show(e.message, false) } finally { setBusy(false) }
  }
  const del = async (h, f) => { if (!window.confirm(`Supprimer ${f} ?`)) return; try { await deleteArchiveFile(h, f); show('Supprimé'); loadArch() } catch (e) { show('Erreur', false) } }
  const delRace = async (raceId) => { if (!window.confirm('Supprimer cette course ?')) return; try { await deleteArchivedRace(raceId); show('Course supprimée'); loadArch() } catch (e) { show('Erreur', false) } }

  const total = archives.reduce((s, a) => s + a.total_races, 0)

  return (
    <>
      {toast && (
        <div style={{
          position: 'fixed', top: 20, left: '50%', transform: 'translateX(-50%)', zIndex: 9999,
          padding: '12px 24px', borderRadius: 8, fontWeight: 600, fontSize: 14,
          background: toast.ok ? '#f0fdf4' : '#fef2f2',
          border: toast.ok ? '1px solid #bbf7d0' : '1px solid #fecaca',
          color: toast.ok ? '#166534' : '#dc2626', boxShadow: '0 4px 12px rgba(0,0,0,0.15)'
        }}>{toast.msg}</div>
      )}

      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 20,
      }}>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#0f172a' }}>Archives</h1>
        <div style={{ display: 'flex', gap: 8 }}>
          <button onClick={() => setView('live')} style={{
            padding: '7px 16px', borderRadius: 8, border: 'none', cursor: 'pointer',
            fontSize: 13, fontWeight: 700,
            background: view === 'live' ? '#0f172a' : '#f1f5f9',
            color: view === 'live' ? '#fff' : '#475569',
          }}>Télécharger</button>
          <button onClick={() => setView('saved')} style={{
            padding: '7px 16px', borderRadius: 8, border: 'none', cursor: 'pointer',
            fontSize: 13, fontWeight: 700,
            background: view === 'saved' ? '#0f172a' : '#f1f5f9',
            color: view === 'saved' ? '#fff' : '#475569',
          }}>Stockés ({total})</button>
        </div>
      </div>

      {view === 'live' && <>
        <div style={{
          background: '#fff', borderRadius: 'var(--radius)', padding: 16, marginBottom: 16,
          boxShadow: 'var(--shadow)',
          display: 'flex', gap: 12, alignItems: 'center', flexWrap: 'wrap',
        }}>
          <input type="date" value={date} onChange={e => setDate(e.target.value)}
            className="input" style={{ width: 160 }} />
          <button onClick={() => loadProg(date)} className="btn btn-primary">
            Charger
          </button>
          <input type="text" placeholder="Rechercher hippodrome..." value={liveSearch}
            onChange={e => setLiveSearch(e.target.value)}
            className="input" style={{ flex: 1, minWidth: 160 }} />
          {data && !selR && (
            <button onClick={archAll} disabled={busy} className="btn btn-accent">
              {busy ? '...' : `Archiver tout (${data.meetings.length})`}
            </button>
          )}
        </div>

        {loading && (
          <div style={{ textAlign: 'center', padding: 60, color: '#94a3b8' }}>
            <div className="spinner" style={{ margin: '0 auto 16px' }} />
            Chargement...
          </div>
        )}

        {!selR && data && (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            {data.meetings.filter(m => !liveSearch || m.hippodrome.toLowerCase().includes(liveSearch.toLowerCase())).map((m, i) => {
              const n = m.courses?.length || 0
              const disciplines = [...new Set(m.courses?.map(c => c.specialty).filter(Boolean))]
              return (
                <div key={i} onClick={() => setSelR(m)} style={{
                  background: '#fff', borderRadius: 'var(--radius)', padding: 16, cursor: 'pointer',
                  boxShadow: 'var(--shadow)', transition: 'all 0.15s',
                  borderLeft: '4px solid', borderLeftColor: m.organizer === 'PMH' ? '#0f172a' : '#ef4444',
                }}>
                  <div style={{ display: 'flex', alignItems: 'flex-start', justifyContent: 'space-between', marginBottom: 8 }}>
                    <div style={{ width: 40, height: 40, borderRadius: 10, background: m.organizer === 'PMH' ? '#0f172a' : '#ef4444', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, fontSize: 18 }}>R{m.num}</div>
                    <span style={{ padding: '2px 8px', borderRadius: 4, fontSize: 11, fontWeight: 700, background: '#f1f5f9', color: '#64748b' }}>{n} course{n > 1 ? 's' : ''}</span>
                  </div>
                  <div style={{ fontWeight: 700, fontSize: '0.95rem', color: '#0f172a', marginBottom: 4 }}>{m.hippodrome}</div>
                  <div style={{ fontSize: '0.78rem', color: '#64748b', marginBottom: 8 }}>Début {formatTime(m.start_time)}</div>
                  {disciplines.length > 0 && (
                    <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4 }}>
                      {disciplines.map(d => <span key={d} className="specialty-badge" style={{ background: SPECIALTY_COLORS[d] || '#94a3b8' }}>{d}</span>)}
                    </div>
                  )}
                </div>
              )
            })}
          </div>
        )}

        {selR && (
          <div>
            <button onClick={() => setSelR(null)} className="btn btn-ghost btn-sm" style={{ marginBottom: 16 }}>
              &larr; Retour
            </button>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
              <h3 style={{ fontWeight: 800, fontSize: '1.1rem', color: '#0f172a', display: 'flex', alignItems: 'center', gap: 8 }}>
                <span style={{ width: 32, height: 32, borderRadius: 8, background: selR.organizer === 'PMH' ? '#0f172a' : '#ef4444', display: 'inline-flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, fontSize: 14 }}>R{selR.num}</span>
                {selR.hippodrome}
              </h3>
              <button onClick={archMeeting} disabled={busy} className="btn btn-accent">
                {busy ? '...' : 'Archiver toute'}
              </button>
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
              {selR.courses.map((race, i) => (
                <div key={i} style={{
                  display: 'flex', alignItems: 'center', gap: 12, padding: '12px 16px',
                  borderRadius: 10, background: '#fff', boxShadow: 'var(--shadow)',
                }}>
                  <div style={{
                    width: 38, height: 38, borderRadius: 10, flexShrink: 0,
                    background: 'linear-gradient(135deg, #3b82f6, #a855f7)',
                    display: 'flex', alignItems: 'center', justifyContent: 'center',
                    color: '#fff', fontWeight: 900, fontSize: '0.85rem',
                  }}>{race.num}</div>
                  <div style={{ flex: 1, minWidth: 0 }}>
                    <div style={{ fontWeight: 700, fontSize: '0.85rem', color: '#0f172a', display: 'flex', alignItems: 'center', gap: 6 }}>
                      {race.prix || `Course ${race.num}`}
                      <RaceBetBadges race={{ ...race, types_pari: typeof race.types_pari === 'string' ? JSON.parse(race.types_pari) : race.types_pari }} />
                    </div>
                    <div style={{ display: 'flex', gap: 8, marginTop: 3, fontSize: '0.7rem', color: '#64748b' }}>
                      <span>{formatTime(race.time)}</span>
                      <span>{race.distance ? `${race.distance}m` : ''}</span>
                      <span>{race.runners} partants</span>
                      <span className="specialty-badge" style={{ background: SPECIALTY_COLORS[race.specialty] || '#94a3b8' }}>{race.specialty}</span>
                    </div>
                  </div>
                  <button onClick={() => archRace(race)} disabled={busy} className="btn btn-primary btn-sm">
                    Archiver
                  </button>
                </div>
              ))}
            </div>
          </div>
        )}
      </>}

      {view === 'saved' && <>
        <div style={{ background: '#fff', borderRadius: 'var(--radius)', padding: 16, marginBottom: 16, boxShadow: 'var(--shadow)', display: 'flex', flexDirection: 'column', gap: 12 }}>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <button onClick={() => setSelectedDate('')} style={{
              padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
              fontSize: 13, fontWeight: !selectedDate ? 700 : 500,
              background: !selectedDate ? '#0f172a' : '#f1f5f9',
              color: !selectedDate ? '#fff' : '#475569',
            }}>Toutes les dates</button>
            {archiveDates.slice(0, 30).map(d => (
              <button key={d} onClick={() => setSelectedDate(d)} style={{
                padding: '6px 14px', borderRadius: 6, border: 'none', cursor: 'pointer',
                fontSize: 13, fontWeight: selectedDate === d ? 700 : 500,
                background: selectedDate === d ? '#0f172a' : '#f1f5f9',
                color: selectedDate === d ? '#fff' : '#475569',
              }}>{dayLabel(d)}</button>
            ))}
          </div>
          <div style={{ display: 'flex', gap: 8, alignItems: 'center', flexWrap: 'wrap' }}>
            <input type="text" placeholder="Rechercher hippodrome..." value={archSearch}
              onChange={e => setArchSearch(e.target.value)} className="input" style={{ flex: 1, minWidth: 160 }} />
            <input type="date" value={selectedDate} onChange={e => setSelectedDate(e.target.value)}
              className="input" style={{ width: 150 }} />
          </div>
        </div>

        {selectedDate ? (
          <div style={{ background: '#fff', borderRadius: 'var(--radius)', padding: 16, boxShadow: 'var(--shadow)' }}>
            <div style={{ fontWeight: 800, fontSize: '0.9rem', color: '#0f172a', marginBottom: 4 }}>
              {dayLabel(selectedDate)} — {dayLoading ? 'Chargement...' : `${dayRaces.length} course${dayRaces.length > 1 ? 's' : ''} archivée${dayRaces.length > 1 ? 's' : ''}`}
            </div>
            {!dayLoading && dayRaces.length === 0 && (
              <div style={{ color: '#94a3b8', fontSize: 13 }}>Aucune course pour cette date — vérifiez l'onglet "Télécharger" du {dayLabel(selectedDate)}.</div>
            )}
            <div style={{ display: 'flex', flexDirection: 'column', gap: 6, marginTop: 8 }}>
              {dayRaces.filter(r => !archSearch || String(r.hippodrome || '').replace(/_/g, ' ').toLowerCase().includes(archSearch.replace(/-/g, ' ').toLowerCase())).map(r => (
                <div key={r.race_id} style={{ display: 'flex', alignItems: 'center', gap: 10, padding: '8px 10px', borderRadius: 8, background: '#f8fafc', fontSize: '0.78rem' }}>
                  <b style={{ color: '#0f172a' }}>R{r.reunion_num}C{r.course_num}</b>
                  <span style={{ flex: 1, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>{String(r.hippodrome || '').replace(/_/g, ' ')} — {r.prix || ''}</span>
                  <span style={{ color: '#64748b' }}>{r.runners || '?'} partants</span>
                  {r.quinte ? <span style={{ fontSize: 11, fontWeight: 800, background: '#ffd700', borderRadius: 4, padding: '1px 6px' }}>Q</span> : null}
                  <button onClick={() => navigate(`/race/${r.date}/R${r.reunion_num}/C${r.course_num}`)} style={{ border: '1px solid #e2e8f0', background: '#fff', borderRadius: 6, padding: '3px 10px', cursor: 'pointer', fontSize: 12, fontWeight: 700 }}>Ouvrir</button>
                  <button onClick={() => delRace(r.race_id)} style={{ border: '1px solid #fecaca', background: '#fff', borderRadius: 6, padding: '3px 10px', cursor: 'pointer', fontSize: 12, color: '#dc2626' }}>×</button>
                </div>
              ))}
            </div>
          </div>
        ) : archives.length === 0 ? (
          <div style={{ background: '#fff', borderRadius: 'var(--radius)', padding: 60, textAlign: 'center', boxShadow: 'var(--shadow)', color: '#94a3b8' }}>
            Aucune course archivée
            <div style={{ fontSize: 13, marginTop: 8, color: '#94a3b8' }}>
              Utilisez l'onglet "Télécharger" pour archiver des courses depuis Geny.com
            </div>
          </div>
        ) : (
          <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fill, minmax(280px, 1fr))', gap: 12 }}>
            {archives.filter(a => !archSearch || String(a.hippodrome || '').replace(/_/g, ' ').toLowerCase().includes(archSearch.replace(/-/g, ' ').toLowerCase())).map(a => (
              <div key={a.hippodrome} style={{
                background: '#fff', borderRadius: 'var(--radius)', padding: 16,
                boxShadow: 'var(--shadow)', borderLeft: '4px solid #0f172a',
              }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 8 }}>
                  <div style={{ width: 40, height: 40, borderRadius: 10, background: '#0f172a', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, fontSize: 16 }}>{a.hippodrome[0]}</div>
                  <div style={{ flex: 1 }}>
                    <div style={{ fontWeight: 700, fontSize: '0.95rem', color: '#0f172a' }}>{a.hippodrome.replace(/_/g, ' ')}</div>
                    <div style={{ fontSize: '0.72rem', color: '#64748b' }}>
                      {a.total_races} course{a.total_races > 1 ? 's' : ''}
                    </div>
                  </div>
                </div>
              </div>
            ))}
          </div>
        )}
      </>}
    </>
  )
}
