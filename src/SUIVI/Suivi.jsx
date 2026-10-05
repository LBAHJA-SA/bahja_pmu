import { useEffect, useState } from 'react'

const API = window.location.port === '5173' ? '' : 'https://bahja-turf-api-production.up.railway.app'
async function req(url, opts = {}) {
  const r = await fetch(`${API}${url}`, opts)
  if (!r.ok) throw new Error(`Erreur ${r.status}`)
  return r.json()
}

function Avg({ v, suffix = '/3' }) {
  const col = v >= 2 ? '#4ade80' : v >= 1 ? '#fbbf24' : 'var(--text-muted)'
  return <b style={{ color: col }}>{v}{suffix}</b>
}

function StatTable({ title, data }) {
  const rows = Object.entries(data || {})
  if (!rows.length) return null
  return (
    <div style={{ marginBottom: 12 }}>
      <div style={{ fontSize: '0.78rem', fontWeight: 800, color: 'var(--text-primary)', marginBottom: 6 }}>{title}</div>
      {rows.map(([k, v]) => (
        <div key={k} style={{ display: 'flex', alignItems: 'center', gap: 8, fontSize: '0.72rem', padding: '4px 0', borderBottom: '1px solid rgba(255,255,255,0.05)' }}>
          <span style={{ minWidth: 110, color: 'var(--text-secondary)' }}>{k}</span>
          <span style={{ color: 'var(--text-muted)' }}>n={v.n}</span>
          <Avg v={v.avg} />
          {v.p1_avg != null && <span style={{ fontSize: '0.65rem', color: 'var(--text-muted)' }}>P1 {(100 * v.p1_avg).toFixed(0)}%</span>}
        </div>
      ))}
    </div>
  )
}

function ManualArrival({ id, onDone }) {
  const [vals, setVals] = useState(['', '', '', '', ''])
  const [busy, setBusy] = useState(false)
  const save = async () => {
    const top5 = vals.map(v => (v === '' ? null : parseInt(v, 10)))
    if (top5.slice(0, 3).some(v => v == null || isNaN(v))) return
    setBusy(true)
    try {
      const r = await fetch(`${API}/api/track/resolve-manual`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ tracked_id: id, top5 }),
      })
      if (!r.ok) throw new Error('Erreur')
      onDone()
    } catch (e) { /* silent, parent shows errors */ } finally { setBusy(false) }
  }
  return (
    <span style={{ display: 'inline-flex', gap: 4, alignItems: 'center', marginLeft: 8 }}>
      {[0, 1, 2, 3, 4].map(i => (
        <input key={i} value={vals[i]} placeholder={`P${i + 1}`} inputMode="numeric"
          onChange={e => { const v = [...vals]; v[i] = e.target.value.replace(/\D/g, '').slice(0, 2); setVals(v) }}
          style={{ width: 34, background: 'var(--bg-primary)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 6, padding: '3px 5px', fontSize: '0.7rem', textAlign: 'center' }} />
      ))}
      <button onClick={save} disabled={busy} style={{ fontSize: '0.65rem', background: 'rgba(34,197,94,0.12)', color: '#4ade80', border: '1px solid rgba(34,197,94,0.4)', borderRadius: 6, padding: '3px 8px', cursor: 'pointer' }}>OK</button>
    </span>
  )
}

export default function Suivi() {
  const [races, setRaces] = useState([])
  const [stats, setStats] = useState(null)
  const [loading, setLoading] = useState(false)
  const [err, setErr] = useState(null)

  const refresh = async () => {
    setLoading(true); setErr(null)
    try {
      const [l, s] = await Promise.all([
        req('/api/track/list'),
        req('/api/track/stats').catch(() => null),
      ])
      setRaces(l.races || [])
      setStats(s)
    } catch (e) { setErr(e.message) } finally { setLoading(false) }
  }
  useEffect(() => { refresh() }, [])

  const resolve = async (id) => {
    setLoading(true)
    try {
      await req(id ? '/api/track/resolve' : '/api/track/resolve', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(id ? { tracked_id: id } : {}),
      })
      await refresh()
    } catch (e) { setErr(e.message) } finally { setLoading(false) }
  }

  return (
    <div className="neon-theme">
      <div className="page-tag trot">SUIVI <small>journal des analyses · arrivées · failles par hippodrome</small></div>
      <p style={{ color: 'var(--text-dim)', fontSize: '0.78rem', margin: '0 0 14px' }}>
        Chaque course analysée (bouton «Suivre» dans TROT/GALOP) est archivée avec ses tickets.
        Après l'arrivée, <b>Résoudre</b> récupère le résultat et les stats révèlent où se situe la faille.
      </p>
      {err && <div style={{ color: 'var(--neon-red)', fontSize: '0.75rem', marginBottom: 12 }}>{err}</div>}
      <div style={{ display: 'flex', gap: 8, marginBottom: 14 }}>
        <button onClick={() => resolve(null)} disabled={loading} style={{ background: 'linear-gradient(135deg,#22c55e,#06b6d4)', color: '#000', fontWeight: 800, border: 'none', borderRadius: 10, padding: '9px 18px', cursor: 'pointer', fontSize: '0.78rem' }}>
          {loading ? '…' : 'Résoudre les arrivées'}
        </button>
        <button onClick={refresh} disabled={loading} style={{ background: 'rgba(255,255,255,0.06)', color: 'var(--text-primary)', border: '1px solid var(--border)', borderRadius: 10, padding: '9px 18px', cursor: 'pointer', fontSize: '0.78rem' }}>Rafraîchir</button>
        {stats && <span style={{ fontSize: '0.72rem', color: 'var(--text-muted)', alignSelf: 'center' }}>{stats.n} courses résolues</span>}
      </div>

      {stats && (
        <div className="neon-card" style={{ marginBottom: 14, borderColor: 'rgba(34,197,94,0.3)' }}>
          <h3 style={{ fontSize: '0.95rem', color: '#4ade80', marginBottom: 8 }}>Où est la faille ? (Top3 ensemble)</h3>
          <StatTable title="Par ticket" data={stats.by_ticket} />
          <StatTable title="Début vs fin de réunion (votre hypothèse)" data={stats.by_slot} />
          <StatTable title="Délai analyse → départ (fraîcheur des cotes)" data={stats.by_delay} />
          <StatTable title="Par hippodrome" data={stats.by_hippo} />
        </div>
      )}

      {races.map(r => {
        const actual = [r.p1, r.p2, r.p3].filter(v => v != null)
        const byTicket = {}
        ;(r.picks || []).forEach(p => { (byTicket[p.ticket] = byTicket[p.ticket] || []).push(p) })
        return (
          <div key={r.id} className="neon-card" style={{ marginBottom: 10 }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap', fontSize: '0.8rem', fontWeight: 800, color: 'var(--text-primary)' }}>
              <span>{r.date} R{r.reunion_num}C{r.course_num}</span>
              <span style={{ color: 'var(--text-muted)', fontWeight: 600 }}>{r.hippodrome}</span>
              {actual.length > 0
                ? <span style={{ color: '#4ade80' }}>Arrivée: {actual.join('-')}</span>
                : <><button onClick={() => resolve(r.id)} disabled={loading} style={{ fontSize: '0.68rem', background: 'rgba(34,197,94,0.12)', color: '#4ade80', border: '1px solid rgba(34,197,94,0.4)', borderRadius: 8, padding: '4px 10px', cursor: 'pointer' }}>Résoudre</button><ManualArrival id={r.id} onDone={refresh} /></>}
            </div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 8 }}>
              {Object.entries(byTicket).map(([t, ps]) => {
                const positioned = ps.some(p => p.target_pos != null)
                const nums = positioned
                  ? [1,2,3].map(pos => (ps.find(p => p.target_pos === pos) || {}).num)
                  : ps.map(p => p.num)
                const shown = nums.filter(n => n != null)
                const hits = shown.filter(n => actual.includes(n)).length
                const total = positioned ? 3 : Math.max(shown.length, 1)
                return (
                  <div key={t} style={{ fontSize: '0.7rem' }}>
                    <b style={{ color: 'var(--neon-cyan)' }}>{t}</b>{' '}
                    {shown.length ? shown.join('-') : '–-–-–'}
                    {actual.length > 0 && (
                      <span style={{ color: hits >= 2 ? '#4ade80' : 'var(--text-muted)', marginLeft: 6 }}>
                        {hits}/{total}
                      </span>
                    )}
                  </div>
                )
              })}
            </div>
          </div>
        )
      })}
      {races.length === 0 && !loading && (
        <div style={{ color: 'var(--text-muted)', fontSize: '0.78rem' }}>Aucune course suivie — utilisez «Suivre cette course» dans TROT ou GALOP après analyse.</div>
      )}
    </div>
  )
}
