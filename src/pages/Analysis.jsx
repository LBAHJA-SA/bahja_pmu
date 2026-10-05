import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { fetchRaceAnalysis } from '../services/api'

export default function Analysis() {
  const { raceId } = useParams()
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)

  useEffect(() => {
    setLoading(true); setError(null)
    fetchRaceAnalysis(raceId)
      .then(d => { setData(d); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [raceId])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 20px', color: '#94a3b8' }}>
        <div className="spinner" style={{ margin: '0 auto 16px' }} />
        Analyse IA en cours...
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 8, padding: 24, color: '#dc2626', textAlign: 'center' }}>
        Erreur : {error}
      </div>
    )
  }

  if (!data || (!data.bases && !data.complementaires && !(data.regret?.length))) {
    return (
      <div style={{ textAlign: 'center', padding: 40, color: '#94a3b8' }}>
        Aucune analyse disponible pour cette course.
      </div>
    )
  }

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', gap: 12, marginBottom: 24 }}>
        <button onClick={() => navigate(-1)} className="btn btn-ghost btn-sm">&larr; Retour à la course</button>
        <h1 style={{ fontSize: 20, fontWeight: 700, color: '#0f172a', margin: 0 }}>Analyse IA</h1>
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 24 }}>
        {data.dna && <DnaPanel dna={data.dna} />}
        {data.market_dna && <MarketDnaPanel mkt={data.market_dna} />}

        {data.bases?.length > 0 && (
          <Section title="Bases" color="#22c55e" icon="★" horses={data.bases} />
        )}
        {data.complementaires?.length > 0 && (
          <Section title="Complémentaires" color="#f59e0b" icon="◆" horses={data.complementaires} />
        )}
        {data.regret?.length > 0 && (
          <div style={{ background: '#fff', borderRadius: 12, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
            <div style={{ fontSize: 13, fontWeight: 700, color: '#ef4444', marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
              <span style={{ fontSize: 16 }}>▲</span> Regret
            </div>
            <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
              {data.regret.map((h, i) => <HorseCard key={h.num || i} horse={h} color="#ef4444" />)}
            </div>
          </div>
        )}
      </div>

      {data.infos?.length > 0 && (
        <div style={{ marginTop: 24, background: '#fffbeb', border: '1px solid #fde68a', borderRadius: 12, padding: 16 }}>
          <div style={{ fontSize: 13, fontWeight: 700, color: '#854d0e', marginBottom: 8 }}>Notes</div>
          {data.infos.map((info, i) => (
            <p key={i} style={{ fontSize: 13, color: '#92400e', margin: '2px 0', lineHeight: 1.5 }}>{info}</p>
          ))}
        </div>
      )}
    </div>
  )
}

function DnaPanel({ dna }) {
  const featLabels = { gain: 'Gains (carrière)', valeur: 'Valeur', age: 'Âge', corde: 'Corde', poids: 'Poids', musique: 'Musique (forme)' }
  const featColors = { gain: '#22c55e', valeur: '#3b82f6', age: '#a855f7', corde: '#f59e0b', poids: '#14b8a6', musique: '#ef4444' }
  const ctx = dna.context || {}
  const base = dna.base || {}
  const baseTop3 = base.top3 != null ? Math.round(base.top3 * 100) : null
  const qLabels = { Q1: 'Rang faible', Q2: '25-50%', Q3: '50-75%', Q4: 'Rang élevé' }

  return (
    <div style={{ background: '#fff', borderRadius: 12, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 16 }}>🧬</span> ADN de la course
      </div>
      <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 10 }}>
        {dna.hippodrome} · {dna.distance}m · {dna.discipline} · basé sur {dna.n_samples} courses
      </div>

      {(ctx.classe || ctx.surface || ctx.going || ctx.runners_avg || ctx.prix_avg) && (
        <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap', marginBottom: 12 }}>
          {ctx.classe && <span style={{ padding: '2px 8px', borderRadius: 4, background: '#f1f5f9', fontSize: 11, color: '#475569' }}>{ctx.classe}</span>}
          {ctx.surface && <span style={{ padding: '2px 8px', borderRadius: 4, background: '#f1f5f9', fontSize: 11, color: '#475569' }}>Surface: {ctx.surface}</span>}
          {ctx.going && <span style={{ padding: '2px 8px', borderRadius: 4, background: '#f1f5f9', fontSize: 11, color: '#475569' }}>Terrain: {ctx.going}</span>}
          {ctx.runners_avg && <span style={{ padding: '2px 8px', borderRadius: 4, background: '#f1f5f9', fontSize: 11, color: '#475569' }}>≈ {ctx.runners_avg} partants</span>}
          {ctx.prix_avg && <span style={{ padding: '2px 8px', borderRadius: 4, background: '#f1f5f9', fontSize: 11, color: '#475569' }}>≈ {Number(ctx.prix_avg).toLocaleString('fr-FR')} €</span>}
        </div>
      )}

      {baseTop3 != null && (
        <div style={{ fontSize: 12, color: '#475569', marginBottom: 12 }}>
          Probabilité de base d'un cheval d'entrer dans le trio :{' '}
          <strong style={{ color: '#0f172a' }}>{baseTop3}%</strong>
          {' '}<span style={{ color: '#94a3b8' }}>({base.n} chevaux observés)</span>
        </div>
      )}

      <div style={{ fontSize: 11, color: '#64748b', marginBottom: 8 }}>
        Chances de Top 3 selon le rang de la caractéristique dans le peloton (Q1 = rang le plus bas, Q4 = rang le plus haut)
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 10 }}>
        {Object.entries(dna.features || {}).filter(([, f]) => f?.weight > 0).map(([k, f]) => {
          const qu = f.quartiles || {}
          const color = featColors[k]
          const ordered = ['Q4', 'Q3', 'Q2', 'Q1']
          return (
            <div key={k} style={{ border: '1px solid #f1f5f9', borderRadius: 10, padding: 10 }}>
              <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', marginBottom: 6 }}>
                <span style={{ fontSize: 12, fontWeight: 700, color: '#0f172a' }}>{featLabels[k] || k}</span>
                <span style={{ fontSize: 10, fontWeight: 700, color: color, background: '#f8fafc', border: '1px solid #e2e8f0', borderRadius: 4, padding: '0 5px' }}>
                  importance {(f.weight * 100).toFixed(0)}%
                </span>
              </div>
              {ordered.map(q => {
                const d = qu[q]
                const rate = d?.top3 != null ? d.top3 : null
                return (
                  <div key={q} style={{ marginBottom: 3 }}>
                    <div style={{ display: 'flex', justifyContent: 'space-between', fontSize: 10, color: '#64748b', marginBottom: 1 }}>
                      <span>{q} · {qLabels[q]}</span>
                      <span style={{ fontWeight: 700 }}>{rate != null ? `${Math.round(rate * 100)}%` : '—'}</span>
                    </div>
                    <div style={{ height: 4, borderRadius: 2, background: '#f1f5f9', overflow: 'hidden' }}>
                      <div style={{
                        height: '100%', borderRadius: 2, background: color, opacity: 0.8,
                        width: rate != null ? `${Math.min(rate / (baseTop3 != null ? Math.max(baseTop3 / 100, 0.001) : 0.001) * 50, 100).toFixed(0)}%` : '0%',
                      }} />
                    </div>
                  </div>
                )
              })}
            </div>
          )
        })}
      </div>

      {Object.keys(dna.pos_weights || {}).length > 0 && (
        <div style={{ marginTop: 12, fontSize: 11, color: '#94a3b8', lineHeight: 1.6 }}>
          Poids par place (stabilité apprise des données) :{' '}
          {Object.entries(dna.pos_weights).map(([pos, w]) => `${pos} ${(w * 100).toFixed(0)}%`).join(' · ')}
        </div>
      )}
    </div>
  )
}

function MarketDnaPanel({ mkt }) {
  const catColors = { FAV: '#39ff14', OUT: '#ff6b35', TOC: '#ffab00', BIG_TOC: '#ff3333' }
  const labels = { FAV: 'Favori', OUT: 'Outsider', TOC: 'Tocard', BIG_TOC: 'Longshot' }
  const base = mkt.base || {}
  const baseTop3 = base.top3 != null ? Math.round(base.top3 * 100) : null

  return (
    <div style={{ background: '#fff', borderRadius: 12, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
      <div style={{ fontSize: 13, fontWeight: 700, color: '#0f172a', marginBottom: 4, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 16 }}>🎯</span> ADN du Marché (cotes réelles)
      </div>
      <div style={{ fontSize: 11, color: '#94a3b8', marginBottom: 10 }}>
        basé sur {base.n_races} courses avec cotes réelles · {base.n} chevaux observés
      </div>

      {baseTop3 != null && (
        <div style={{ fontSize: 12, color: '#475569', marginBottom: 12 }}>
          Probabilité de base d'entrer dans le trio : <strong style={{ color: '#0f172a' }}>{baseTop3}%</strong>
        </div>
      )}

      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {Object.entries(mkt.categories || {}).map(([cat, d]) => {
          const t3 = d.top3 != null ? Math.round(d.top3 * 100) : null
          return (
            <div key={cat} style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              <span style={{ width: 90, fontSize: 11, fontWeight: 700, color: catColors[cat] }}>{cat} · {labels[cat]}</span>
              <div style={{ flex: 1, height: 12, borderRadius: 4, background: '#f1f5f9', overflow: 'hidden' }}>
                <div style={{ height: '100%', borderRadius: 4, background: catColors[cat], opacity: 0.8, width: `${Math.min(t3 || 0, 60)}%` }} />
              </div>
              <span style={{ width: 110, fontSize: 11, color: '#64748b', textAlign: 'right' }}>
                {t3 != null ? `${t3}% top3` : '—'} · <strong>P1 {d.P1 != null ? Math.round(d.P1 * 100) : '—'}%</strong>
              </span>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function Section({ title, color, icon, horses }) {
  return (
    <div style={{ background: '#fff', borderRadius: 12, padding: 20, boxShadow: '0 1px 3px rgba(0,0,0,0.06)' }}>
      <div style={{ fontSize: 13, fontWeight: 700, color, marginBottom: 12, display: 'flex', alignItems: 'center', gap: 6 }}>
        <span style={{ fontSize: 16 }}>{icon}</span> {title}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {horses.map((h, i) => (
          <HorseCard key={h.numero || i} horse={h} color={color} />
        ))}
      </div>
    </div>
  )
}

function HorseCard({ horse, color }) {
  const cote = horse.cote_pmu || horse.cote_geny
  const scores = horse.scores || {}
  const pct = (v) => (v * 100).toFixed(0) + '%'
  return (
    <div style={{
      display: 'flex', alignItems: 'flex-start', gap: 12,
      padding: '12px 14px', borderRadius: 10,
      border: '1px solid #f1f5f9', background: '#fafafa',
    }}>
      <div style={{
        width: 32, height: 32, borderRadius: 8,
        background: color, opacity: 0.9,
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        color: '#fff', fontWeight: 800, fontSize: 15, flexShrink: 0,
      }}>{horse.num || horse.numero || '?'}</div>

      <div style={{ flex: 1, minWidth: 0 }}>
        <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a' }}>
          {horse.horse || horse.nom || horse.nomCheval || `Cheval #${horse.num || horse.numero}`}
        </div>

        {horse.scores?.total != null && (
          <div style={{ margin: '4px 0', fontSize: 11, color: '#64748b' }}>
            Score total: <strong>{horse.scores.total.toFixed(1)}</strong>
            {' | '}Marché: <strong style={{color}}>{horse.categorie}</strong>
            {' | '}Forme: {horse.scores.form}
            {' | '}ADN: {horse.scores.dna}
          </div>
        )}

        {horse.scores?.p1 != null && (
          <div style={{ margin: '0 0 4px', fontSize: 11, color: '#475569' }}>
            Prob. Top3 : <strong style={{ color: '#16a34a' }}>P1 {horse.scores.p1}%</strong>
            {' · '}<strong style={{ color: '#0284c7' }}>P2 {horse.scores.p2}%</strong>
            {' · '}<strong style={{ color: '#d97706' }}>P3 {horse.scores.p3}%</strong>
          </div>
        )}

        {horse.form_details?.length > 0 && (
          <div style={{ marginTop: 2, display: 'flex', flexWrap: 'wrap', gap: 8, fontSize: 11, color: '#64748b' }}>
            {horse.form_details.map((d, i) => <span key={i}>{d}</span>)}
          </div>
        )}

        {horse.affinity_details?.length > 0 && (
          <div style={{ marginTop: 1, fontSize: 11, color: '#94a3b8' }}>
            {horse.affinity_details.map((d, i) => <span key={i}>{d}{i < horse.affinity_details.length - 1 ? ' | ' : ''}</span>)}
          </div>
        )}

        {horse.categorie === 'OUT' && (
          <div style={{ marginTop: 2, fontSize: 11, color: '#94a3b8', fontStyle: 'italic' }}>
            Outsider — confiance réduite
          </div>
        )}

        {horse.musique && (
          <div style={{ marginTop: 2, fontFamily: 'monospace', fontSize: 11, color: '#64748b' }}>
            {horse.musique}
          </div>
        )}

        <div style={{ marginTop: 4, display: 'flex', gap: 6, flexWrap: 'wrap' }}>
          {horse.jockey && (
            <span style={{ padding: '1px 8px', borderRadius: 4, background: '#f1f5f9', fontSize: 11, color: '#64748b' }}>
              J: {horse.jockey}
            </span>
          )}
          {horse.trainer && (
            <span style={{ padding: '1px 8px', borderRadius: 4, background: '#f1f5f9', fontSize: 11, color: '#64748b' }}>
              E: {horse.trainer}
            </span>
          )}
          {horse.age && (
            <span style={{ padding: '1px 8px', borderRadius: 4, background: '#f1f5f9', fontSize: 11, color: '#64748b' }}>
              {horse.age} ans
            </span>
          )}
        </div>

        {horse.history_summary?.total > 0 && (
          <div style={{ marginTop: 4, display: 'flex', gap: 10, fontSize: 11, color: '#64748b' }}>
            <span>Courses: {horse.history_summary.total}</span>
            <span>Victoires: {horse.history_summary.wins} ({pct(horse.history_summary.win_rate)})</span>
            <span>Top5: {pct(horse.history_summary.top5_rate)}</span>
          </div>
        )}
      </div>
    </div>
  )
}
