import { useState, useEffect } from 'react'

// Écarts des places P1..P18 — archive: quelles places ont eu leur part du Quinté
// et lesquelles sont en retard (overdue). Lecture seule, ne touche pas au ticket.
export default function SyntheseEcarts() {
  const [data, setData] = useState(null)
  const [days, setDays] = useState(30)
  const [loading, setLoading] = useState(false)
  const [msg, setMsg] = useState('')

  const load = async (d) => {
    setLoading(true); setMsg('')
    try {
      const base = window.location.port === '5173' ? '' : (window.location.hostname === 'localhost' ? 'http://127.0.0.1:3000' : 'https://lbahja-sa--bahja-backend-flask-app.modal.run')
      const res = await fetch(`${base}/api/synthese/ecarts?days=${d}`)
      if (!res.ok) {
        const err = await res.text()
        throw new Error(err || 'erreur')
      }
      const j = await res.json()
      setData(j)
    } catch (e) { setMsg(e.message) }
    setLoading(false)
  }

  useEffect(() => { load(days) }, [])

  const places = data?.places || []
  return (
    <div dir="rtl" style={{ textAlign: 'center' }}>
      <h2>Écarts des places — Quinté (P1..P18)</h2>
      <div style={{ fontSize: 13, color: '#666', marginBottom: 8 }}>
        {data ? `${data.races} quintés analysés (dernier ${data.days}j) — dernière mise à jour: ${data.today}` : 'Chargement…'}
      </div>
      <div style={{ display: 'flex', gap: 8, justifyContent: 'center', marginBottom: 10 }}>
        {[14, 30, 90].map(d => (
          <button key={d} onClick={() => { setDays(d); load(d) }}
            style={{ padding: '5px 14px', borderRadius: 8, border: days === d ? '2px solid #0f172a' : '1px solid #ccc', background: days === d ? '#0f172a' : '#fff', color: days === d ? '#fff' : '#333', cursor: 'pointer', fontSize: 13 }}>
            {d}j
          </button>
        ))}
      </div>
      <table style={{ borderCollapse: 'collapse', margin: '0 auto', background: '#fff', direction: 'ltr', fontSize: 14 }}>
        <thead>
          <tr style={{ background: '#0f172a', color: '#fff' }}>
            <th style={{ padding: '6px 10px' }}>Place</th>
            <th style={{ padding: '6px 10px' }}>Hit</th>
            <th style={{ padding: '6px 10px' }}>Dernier hit</th>
            <th style={{ padding: '6px 10px' }}>Jours depuis</th>
            <th style={{ padding: '6px 10px' }}>État</th>
          </tr>
        </thead>
        <tbody>
          {places.map(p => (
            <tr key={p.place} style={{ background: p.hit ? '#e8f5e9' : '#fffde7', borderBottom: '1px solid #eee' }}>
              <td style={{ padding: '6px 10px', fontWeight: 'bold' }}>P{p.place}</td>
              <td style={{ padding: '6px 10px', textAlign: 'center', fontWeight: 'bold', color: p.hit ? '#2e7d32' : '#c62828' }}>
                {p.hit ? '✅ Oui' : '❌ Non'}
              </td>
              <td style={{ padding: '6px 10px' }}>{p.last_hit || '—'}</td>
              <td style={{ padding: '6px 10px', fontWeight: 'bold' }}>{p.days_since ?? '—'}</td>
              <td style={{ padding: '6px 10px' }}>
                {p.hit ? '✅ Vu' : (p.days_since != null ? `🔴 ${p.days_since}j` : '❓ Jamais')}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      <div style={{ color: '#b71c1c', marginTop: 8 }}>{loading ? 'Chargement…' : msg}</div>
    </div>
  )
}
