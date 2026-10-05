import { useState, useEffect } from 'react'
import { useParams, useNavigate } from 'react-router-dom'
import { fmtClockZ } from '../lib/gmtTime'
import { fetchRaceDetails, fetchRaceRapports, fetchRaceCotes } from '../services/api'
import { RaceBetBadges } from '../components/BetBadges'

const SPECIALTY_COLORS = {
  ATTELE: '#ef4444', MONTE: '#22c55e', PLAT: '#3b82f6',
  HAIES: '#f97316', STEEPLE: '#a855f7'
}

// GMT, always: the start is an instant and the printed number must not depend on the zone of the machine looking at it.
function formatTime(t) { return fmtClockZ(t) }
function formatGain(g) { if (!g) return '-'; return g.toLocaleString('fr-FR') + ' \u20AC' }
function formatMontant(v) { if (v == null) return '-'; return v.toLocaleString('fr-FR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }) + '\u00A0\u20AC' }
function getDeferreLabel(d) { if (!d) return ''; const labels = { PF: 'Pieds nus', PD: 'Postérieurs', DD: 'Déferré', DF: 'Antérieurs' }; return labels[d] || d }
function euroStr(v) { if (v == null) return ''; return v.toLocaleString('fr-FR', { style: 'currency', currency: 'EUR', minimumFractionDigits: 0, maximumFractionDigits: 2 }) }

function sexeLabel(s) { if (!s) return ''; if (s === 'HONGRE') return 'H'; if (s === 'MALE') return 'M'; if (s === 'FEMELLE') return 'F'; return s }
function getArtificeIcons(p) {
  const icons = []
  if (p.oeilleres === 'A') icons.push({ icon: '\u{1F441}', title: 'Oeillères australiennes' })
  else if (p.oeilleres) icons.push({ icon: '\u{1F441}', title: 'Oeillères' })
  if (p.bonnet) icons.push({ icon: '\u{1F3A7}', title: 'Bonnet' })
  if (p.attache_langue) icons.push({ icon: '\u{1F445}', title: 'Attache-langue' })
  if (p.premiere_fois_oeilleres) icons.push({ icon: '\u2728', title: 'Oeillères (1ère fois)' })
  if (p.premiere_fois_bonnet) icons.push({ icon: '\u2728', title: 'Bonnet (1ère fois)' })
  if (p.premiere_fois_attache_langue) icons.push({ icon: '\u2728', title: 'Attache-langue (1ère fois)' })
  if (p.premiere_fois_deferre) icons.push({ icon: '\u2728', title: 'Déferré (1ère fois)' })
  return icons
}
function getMusiqueParts(p) {
  if (!p.musique) return null
  return p.musique.split(/(?<=[pahdse])|(?=\()/).filter(Boolean)
}
function formatPoids(p) {
  if (p.poids == null) return '-'
  let s = String(p.poids)
  if (p.decharge) s += '(' + p.decharge + ')'
  return s
}

const TAB_PARTANTS = 0, TAB_ARRIVEE = 1, TAB_PROBABLES = 2
const API = window.location.port === '5173' ? '' : 'https://backend-production-f0139.up.railway.app'

function ArchiveSaveButton({ raceId }) {
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [checkDone, setCheckDone] = useState(false)
  useEffect(() => {
    fetch(`${API}/api/archive/check/${raceId}`).then(r => r.json()).then(d => { setSaved(d.archived); setCheckDone(true) }).catch(() => setCheckDone(true))
  }, [raceId])
  function handleSave() {
    setSaving(true)
    fetch(`${API}/api/archive/save/${raceId}`, { method: 'POST' }).then(r => { if (r.ok) setSaved(true); setSaving(false) }).catch(() => setSaving(false))
  }
  if (!checkDone) return null
  return (
    <button onClick={handleSave} disabled={saving || saved} style={{
      padding: '6px 14px', borderRadius: 6, border: saved ? '1px solid #22c55e' : 'none',
      background: saved ? 'rgba(34,197,94,0.1)' : '#fff',
      color: saved ? '#22c55e' : '#0f172a',
      fontWeight: 600, fontSize: 12, cursor: saving ? 'wait' : (saved ? 'default' : 'pointer'),
    }}>
      {saving ? 'Sauvegarde...' : saved ? 'Archivé ✓' : 'Sauvegarder'}
    </button>
  )
}

export default function RaceDetails() {
  const { raceId } = useParams()
  const navigate = useNavigate()
  const [partantsData, setPartantsData] = useState(null)
  const [rapportsData, setRapportsData] = useState(null)
  const [cotesData, setCotesData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState(null)
  const [activeTab, setActiveTab] = useState(TAB_PARTANTS)

  useEffect(() => {
    setLoading(true); setError(null); setActiveTab(TAB_PARTANTS)
    Promise.all([fetchRaceDetails(raceId), fetchRaceRapports(raceId), fetchRaceCotes(raceId)])
      .then(([p, r, c]) => { setPartantsData(p); setRapportsData(r); setCotesData(c); setLoading(false) })
      .catch(e => { setError(e.message); setLoading(false) })
  }, [raceId])

  if (loading) {
    return (
      <div style={{ textAlign: 'center', padding: '80px 20px', color: '#94a3b8' }}>
        <div className="spinner" style={{ margin: '0 auto 16px' }} />
        Chargement...
      </div>
    )
  }

  if (error) {
    return (
      <div style={{ background: '#fef2f2', border: '1px solid #fecaca', borderRadius: 'var(--radius)', padding: 24, color: '#dc2626', textAlign: 'center' }}>
        Erreur : {error}
        <br /><br />
        <button onClick={() => navigate('/')} className="btn btn-primary">Retour au programme</button>
      </div>
    )
  }

  if (!partantsData) return null

  const { reunion, course, participants } = partantsData
  const tabs = [
    { index: TAB_PARTANTS, label: 'Partants / Pronos' },
    { index: TAB_ARRIVEE, label: 'Arrivée / Rapports', disabled: !rapportsData },
    { index: TAB_PROBABLES, label: 'Rapports probables', disabled: !cotesData }
  ]

  return (
    <>
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'space-between',
        marginBottom: 16, gap: 12,
      }}>
        <div>
          <button onClick={() => navigate(-1)} className="btn btn-ghost btn-sm" style={{ marginBottom: 8 }}>
            &larr; Retour
          </button>
          <h1 style={{ fontSize: 20, fontWeight: 700, color: '#0f172a' }}>
            {course.prix || `R${reunion.num}C${course.num}`}
          </h1>
          <div style={{ fontSize: 13, color: '#64748b', marginTop: 2 }}>
            {reunion.hippodrome} • {formatTime(course.time)} • R{reunion.num}C{course.num}
          </div>
        </div>
        <div style={{ display: 'flex', gap: 8 }}>
          <button
            onClick={() => navigate(`/analysis/${raceId}`)}
            style={{
              padding: '6px 14px', borderRadius: 6, border: 'none',
              background: '#0f172a', color: '#fff', fontWeight: 600, fontSize: 12,
              cursor: 'pointer',
            }}
          >
            Analyse IA
          </button>
          <ArchiveSaveButton raceId={raceId} />
        </div>
      </div>

      <div style={{
        background: '#fff', borderRadius: 'var(--radius)', padding: '12px 16px',
        marginBottom: 16, boxShadow: 'var(--shadow)',
        display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center', fontSize: 13,
      }}>
        <span className="specialty-badge" style={{ background: SPECIALTY_COLORS[course.specialty] || '#94a3b8' }}>
          {course.specialty} {course.discipline}
        </span>
        <span style={{ color: '#475569' }}>{course.distance}m</span>
        <span style={{ color: '#475569' }}>{course.surface} {course.going?.toLowerCase()}</span>
        {course.corde && <span style={{ color: '#475569' }}>Corde: {course.corde === 'G' ? 'Gauche' : 'Droite'}</span>}
        {course.depart && <span style={{ color: '#475569' }}>Départ: {course.depart === 'AUTOSTART' ? 'Autostart' : course.depart}</span>}
        <span style={{ color: '#475569' }}>{course.runners} partants</span>
        <RaceBetBadges race={course} />
        {course.condition && <span style={{ color: '#94a3b8', width: '100%', fontStyle: 'italic', fontSize: 12 }}>{course.condition}</span>}
      </div>

      <div style={{ display: 'flex', gap: 0, marginBottom: 16, borderBottom: '2px solid #e2e8f0' }}>
        {tabs.map(t => (
          <button
            key={t.index}
            disabled={t.disabled}
            onClick={() => setActiveTab(t.index)}
            style={{
              padding: '10px 18px', border: 'none',
              borderBottom: activeTab === t.index ? '2px solid #0f172a' : '2px solid transparent',
              marginBottom: -2, background: 'transparent',
              cursor: t.disabled ? 'default' : 'pointer',
              fontWeight: activeTab === t.index ? 700 : 500,
              color: t.disabled ? '#cbd5e1' : activeTab === t.index ? '#0f172a' : '#64748b',
              fontSize: 13, transition: 'all 0.15s',
              opacity: t.disabled ? 0.5 : 1,
            }}
          >
            {t.label}
          </button>
        ))}
      </div>

      {activeTab === TAB_PARTANTS && <PartantsTab participants={participants} course={course} pronostics={partantsData.pronostics} />}
      {activeTab === TAB_ARRIVEE && <ArriveeRapportsTab rapportsData={rapportsData} />}
      {activeTab === TAB_PROBABLES && <RapportsProbablesTab cotesData={cotesData} />}
    </>
  )
}

function PartantsTab({ participants, course, pronostics }) {
  const navigate = useNavigate()
  const [sortBy, setSortBy] = useState('num')
  const [sortAsc, setSortAsc] = useState(true)

  const sorted = [...(participants || [])].sort((a, b) => {
    let valA, valB
    switch (sortBy) {
      case 'num': valA = a.num; valB = b.num; break
      case 'cote': valA = a.cote_pmu || a.cote_geny || 999; valB = b.cote_pmu || b.cote_geny || 999; break
      case 'age': valA = a.age || 0; valB = b.age || 0; break
      case 'gain': valA = a.gain || 0; valB = b.gain || 0; break
      case 'valeur': valA = a.valeur || 0; valB = b.valeur || 0; break
      case 'poids': valA = a.poids || 0; valB = b.poids || 0; break
      case 'corde': valA = a.corde || 99; valB = b.corde || 99; break
      case 'rang': valA = a.rang || 99; valB = b.rang || 99; break
      default: valA = a.num; valB = b.num
    }
    return sortAsc ? (valA > valB ? 1 : -1) : (valA < valB ? 1 : -1)
  })

  const SortButton = ({ field, label }) => (
    <button
      onClick={() => { if (sortBy === field) setSortAsc(!sortAsc); else { setSortBy(field); setSortAsc(true) } }}
      style={{
        padding: '4px 10px', borderRadius: 6, border: '1px solid',
        borderColor: sortBy === field ? '#0f172a' : '#e2e8f0',
        fontSize: 12, fontWeight: sortBy === field ? 700 : 500, cursor: 'pointer',
        background: sortBy === field ? '#0f172a' : '#fff',
        color: sortBy === field ? '#fff' : '#64748b',
      }}
    >
      {label} {sortBy === field ? (sortAsc ? '\u25B2' : '\u25BC') : ''}
    </button>
  )

  return (
    <div style={{ background: '#fff', borderRadius: 'var(--radius)', padding: 16, boxShadow: 'var(--shadow)' }}>
      <div style={{ display: 'flex', gap: 8, flexWrap: 'wrap', marginBottom: 12 }}>
        <SortButton field="num" label="N\u00B0" />
        <SortButton field="corde" label="Corde" />
        <SortButton field="cote" label="Cote" />
        <SortButton field="valeur" label="Valeur" />
        <SortButton field="poids" label="Poids" />
        <SortButton field="age" label="\u00C2ge" />
        <SortButton field="gain" label="Gains" />
        <SortButton field="rang" label="Arriv\u00E9e" />
      </div>

      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {sorted.map(p => {
          const cote = p.cote_pmu || p.cote_geny
          const artifices = getArtificeIcons(p)
          return (
            <div key={p.num} style={{
              display: 'flex', alignItems: 'center', gap: 8,
              padding: '8px 12px', borderRadius: 8, background: '#fff',
              border: '1px solid #f1f5f9',
              borderLeft: p.valeur ? '3px solid' : '3px solid transparent',
              borderLeftColor: p.valeur ? (p.valeur >= 40 ? '#ef4444' : p.valeur >= 35 ? '#f59e0b' : '#22c55e') : 'transparent',
            }}>
              <div style={{
                width: 28, height: 28, borderRadius: 6, background: '#0f172a',
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                color: '#fff', fontWeight: 800, fontSize: 13, flexShrink: 0
              }}>{p.num}</div>

              {p.casaque && (
                <div style={{ width: 22, height: 22, flexShrink: 0, display: 'flex', alignItems: 'center' }}>
                  <img src={p.casaque} alt="" style={{ width: 22, height: 22, objectFit: 'contain' }} onError={e => { e.target.style.display = 'none' }} />
                </div>
              )}

              <div style={{ flex: 1, minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a', display: 'flex', alignItems: 'center', gap: 4, flexWrap: 'wrap' }}>
                  <button
                    onClick={(e) => { e.stopPropagation(); navigate(`/horse/${encodeURIComponent(p.horse)}`) }}
                    style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', color: '#0f172a', fontWeight: 700, fontSize: 14, textAlign: 'left' }}
                    onMouseEnter={e => e.currentTarget.style.color = '#ef4444'}
                    onMouseLeave={e => e.currentTarget.style.color = '#0f172a'}
                  >{p.horse}</button>
                  {artifices.map((a, i) => (
                    <span key={i} style={{ fontSize: 12, cursor: 'help' }} title={a.title}>{a.icon}</span>
                  ))}
                  {p.deferre && (
                    <span style={{ fontSize: 10, color: '#f97316', fontWeight: 600, padding: '1px 4px', borderRadius: 3, background: '#fffbeb' }}>
                      {getDeferreLabel(p.deferre)}
                    </span>
                  )}
                  {p.premiere_fois_deferre && (
                    <span style={{ fontSize: 9, color: '#fff', background: '#ef4444', padding: '1px 4px', borderRadius: 3, fontWeight: 600 }}>1re</span>
                  )}
                  {p.incident && (
                    <span style={{ color: '#dc2626', fontSize: 11, fontWeight: 500 }}>({p.incident.replace(/_/g, ' ')})</span>
                  )}
                </div>
                <div style={{ fontSize: 11, color: '#64748b', marginTop: 1, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
                  {p.jockey && <span>J: {p.jockey}</span>}
                  {p.trainer && <span>E: {p.trainer}</span>}
                  {p.age && <span>{p.age} ans {sexeLabel(p.sexe)}</span>}
                  {p.musique && (
                    <span style={{ fontFamily: 'monospace', fontSize: 10, color: '#64748b' }}>
                      {getMusiqueParts(p)?.map((part, i) => {
                        const isParen = part.startsWith('(')
                        return (
                          <span key={i} style={{
                            color: isParen ? '#94a3b8' : part.endsWith('p') ? '#166534' : part.endsWith('h') ? '#f97316' : part.endsWith('a') ? '#8b5cf6' : part.endsWith('d') ? '#dc2626' : part.endsWith('s') ? '#0284c7' : part.endsWith('e') ? '#0891b2' : '#64748b',
                            fontWeight: isParen ? 400 : 600
                          }}>{part} </span>
                        )
                      })}
                    </span>
                  )}
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: 10, flexShrink: 0 }}>
                {p.corde != null && (
                  <div style={{ textAlign: 'center', minWidth: 22 }}>
                    <div style={{ fontSize: 9, color: '#94a3b8' }}>Corde</div>
                    <div style={{ fontWeight: 700, fontSize: 13 }}>{p.corde}</div>
                  </div>
                )}
                {p.valeur != null && (
                  <div style={{ textAlign: 'center', minWidth: 28 }}>
                    <div style={{ fontSize: 9, color: '#94a3b8' }}>Val.</div>
                    <div style={{ fontWeight: 700, fontSize: 13 }}>{p.valeur}</div>
                  </div>
                )}
                {p.poids != null && (
                  <div style={{ textAlign: 'center', minWidth: 28 }}>
                    <div style={{ fontSize: 9, color: '#94a3b8' }}>Poids</div>
                    <div style={{ fontWeight: 600, fontSize: 13 }}>{p.poids}{p.decharge ? '(' + p.decharge + ')' : ''}</div>
                  </div>
                )}
                {cote && (
                  <div style={{ textAlign: 'center', minWidth: 36 }}>
                    <div style={{ fontSize: 9, color: '#94a3b8' }}>Cote</div>
                    <span style={{
                      padding: '2px 8px', borderRadius: 4,
                      background: cote <= 5 ? '#dcfce7' : cote <= 15 ? '#fef9c3' : '#fee2e2',
                      color: cote <= 5 ? '#166534' : cote <= 15 ? '#854d0e' : '#991b1b',
                      fontWeight: 700, fontSize: 13
                    }}>{cote}</span>
                  </div>
                )}
                {p.gain != null && (
                  <div style={{ textAlign: 'center', minWidth: 60 }}>
                    <div style={{ fontSize: 9, color: '#94a3b8' }}>Gains</div>
                    <div style={{ fontSize: 11, color: '#475569', fontWeight: 600 }}>{formatGain(p.gain)}</div>
                  </div>
                )}
                {p.rang != null && p.rang > 0 && (
                  <div style={{ textAlign: 'center', minWidth: 22 }}>
                    <div style={{ fontSize: 9, color: '#94a3b8' }}>Rang</div>
                    <span style={{ fontWeight: 800, fontSize: 16, color: p.rang <= 3 ? '#166534' : '#475569' }}>
                      {p.rang}<span style={{ fontSize: 10 }}>e</span>
                    </span>
                  </div>
                )}
              </div>
            </div>
          )
        })}
      </div>

      {pronostics && <PronosticsSection pronostics={pronostics} />}
    </div>
  )
}

function PronosticsSection({ pronostics }) {
  const navigate = useNavigate()
  const geny = pronostics.geny || {}
  const syntheseTableRonde = (pronostics.syntheseTableRonde?.liste) || []
  const synthesePresse = (pronostics.synthesePresse?.liste) || []
  const presse = pronostics.presse || []
  const tableRonde = pronostics.tableRonde || []
  const metaData = geny.metaData || {}
  const listeBase = metaData.listeBase || []
  const listeBelleChance = metaData.listeBelleChance || []
  const listeOutsiders = metaData.listeOutsiders || []
  const listeDeclas = metaData.listeDeclas || []
  const [showFullPress, setShowFullPress] = useState(false)
  const maxPress = showFullPress ? presse.length : Math.min(presse.length, 4)

  return (
    <div style={{ marginTop: 24 }}>
      <div style={{
        background: '#0f172a', color: '#fff', padding: '10px 16px',
        borderRadius: '10px 10px 0 0', fontWeight: 700, fontSize: 14,
      }}>
        Pronostics et synthèses
      </div>
      <div style={{
        background: '#fff', border: '1px solid #e2e8f0', borderTop: 'none',
        borderRadius: '0 0 10px 10px', padding: 16, marginBottom: 16,
      }}>
        {geny.titre && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a', marginBottom: 8 }}>Pronostic Geny</div>
            <div style={{ fontWeight: 600, fontSize: 13, color: '#334155', marginBottom: 4 }}>{geny.titre}</div>
          </div>
        )}
        {listeBase.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontWeight: 600, fontSize: 13, color: '#ef4444', marginBottom: 6 }}>Favoris</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {listeBase.map(h => (
                <span key={h.idCheval} style={{ padding: '3px 10px', borderRadius: 6, background: '#fef2f2', border: '1px solid #fecaca', fontWeight: 700, fontSize: 13, color: '#dc2626' }}>
                  {h.numero}. {h.nomCheval}
                </span>
              ))}
            </div>
          </div>
        )}
        {listeBelleChance.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontWeight: 600, fontSize: 13, color: '#f59e0b', marginBottom: 6 }}>Opposants</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {listeBelleChance.map(h => (
                  <span key={h.idCheval} style={{ padding: '3px 10px', borderRadius: 6, background: '#fffbeb', border: '1px solid #fde68a', fontWeight: 700, fontSize: 13, color: '#854d0e' }}>
                  {h.numero}. {h.nomCheval}
                </span>
              ))}
            </div>
          </div>
        )}
        {listeOutsiders.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontWeight: 600, fontSize: 13, color: '#3b82f6', marginBottom: 6 }}>Outsiders</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {listeOutsiders.map(h => (
                <span key={h.idCheval} style={{ padding: '3px 10px', borderRadius: 6, background: '#eff6ff', border: '1px solid #bfdbfe', fontWeight: 700, fontSize: 13, color: '#1d4ed8' }}>
                  {h.numero}. {h.nomCheval}
                </span>
              ))}
            </div>
          </div>
        )}
        {listeDeclas.length > 0 && (
          <div style={{ marginBottom: 12 }}>
            <div style={{ fontWeight: 600, fontSize: 13, color: '#64748b', marginBottom: 6 }}>Délaissés</div>
            <div style={{ display: 'flex', gap: 6, flexWrap: 'wrap' }}>
              {listeDeclas.map(h => (
                <span key={h.idCheval} style={{ padding: '3px 10px', borderRadius: 6, background: '#f8fafc', border: '1px solid #e2e8f0', fontWeight: 600, fontSize: 13, color: '#64748b' }}>
                  {h.numero}. {h.nomCheval}
                </span>
              ))}
            </div>
          </div>
        )}
        {tableRonde.length > 0 && (
          <div style={{ marginBottom: 16 }}>
            <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a', marginBottom: 8 }}>Sélections de la rédaction ({tableRonde.length})</div>
            {tableRonde.slice(0, 5).map((t, i) => (
              <div key={i} style={{ padding: '8px 12px', marginBottom: 6, borderRadius: 8, background: '#f8fafc', border: '1px solid #f1f5f9' }}>
                <div style={{ fontWeight: 600, fontSize: 12, color: '#0f172a', marginBottom: 4 }}>
                  {t.interviewe ? `${t.interviewe.prenom || ''} ${t.interviewe.nom || ''}`.trim() : (t.redacteur ? (typeof t.redacteur === 'string' ? t.redacteur : `${t.redacteur.prenom || ''} ${t.redacteur.nom || ''}`.trim()) : 'Rédacteur ' + (i + 1))}
                </div>
                {t.selections && (
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {t.selections.map((sel, j) => (
                      <span key={j} style={{ padding: '2px 7px', borderRadius: 4, background: '#fff', border: '1px solid #e2e8f0', fontWeight: 700, fontSize: 12, color: '#334155' }}>
                        {sel.numero}. {sel.nomCheval || sel.cheval?.nom || ''}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
        {syntheseTableRonde.length > 0 && <SyntheseTable title="Synthèse de la rédaction" items={syntheseTableRonde} max={8} />}
        {synthesePresse.length > 0 && <SyntheseTable title="Synthèse de la presse" items={synthesePresse} max={8} />}
        {presse.length > 0 && (
          <div style={{ marginTop: 16 }}>
            <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a', marginBottom: 8 }}>Sélections de nos confrères ({presse.length})</div>
            {presse.slice(0, maxPress).map((s, i) => (
              <div key={i} style={{ padding: '8px 12px', marginBottom: 6, borderRadius: 8, background: '#f8fafc', border: '1px solid #f1f5f9' }}>
                <div style={{ fontWeight: 600, fontSize: 12, color: '#0f172a', marginBottom: 4 }}>
                  {s.redacteur ? (typeof s.redacteur === 'string' ? s.redacteur : `${s.redacteur.prenom || ''} ${s.redacteur.nom || ''}`.trim() || s.redacteur.titre || 'Source ' + (i + 1)) : ('Source ' + (i + 1))}
                </div>
                {s.selections && (
                  <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap' }}>
                    {s.selections.map((sel, j) => (
                      <span key={j} style={{ padding: '2px 7px', borderRadius: 4, background: '#fff', border: '1px solid #e2e8f0', fontWeight: 700, fontSize: 12, color: '#334155' }}>
                        {sel.numero}. {sel.nomCheval || sel.cheval?.nom || ''}
                      </span>
                    ))}
                  </div>
                )}
              </div>
            ))}
            {presse.length > 4 && (
              <button onClick={() => setShowFullPress(!showFullPress)} className="btn btn-ghost btn-sm" style={{ marginTop: 8 }}>
                {showFullPress ? 'Voir moins' : 'Voir les ' + presse.length + ' sources'}
              </button>
            )}
          </div>
        )}
      </div>
    </div>
  )
}

function SyntheseTable({ title, items, max }) {
  const displayItems = items.slice(0, max)
  return (
    <div style={{ marginBottom: 16 }}>
      <div style={{ fontWeight: 700, fontSize: 14, color: '#0f172a', marginBottom: 8 }}>{title}</div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 3 }}>
        {displayItems.map((item, i) => (
          <div key={i} style={{
            display: 'flex', alignItems: 'center', gap: 8, padding: '4px 10px', borderRadius: 6,
            background: i < 3 ? (i === 0 ? '#fffbeb' : '#f0fdf4') : '#f8fafc',
            border: '1px solid', borderColor: i < 3 ? (i === 0 ? '#f59e0b' : '#86efac') : '#f1f5f9',
          }}>
            <div style={{ width: 22, height: 22, borderRadius: 4, background: '#0f172a', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, fontSize: 11, flexShrink: 0 }}>
              {item.numero || item.cheval?.numero || '-'}
            </div>
            <div style={{ flex: 1, fontWeight: 600, fontSize: 13 }}>{item.nomCheval || item.cheval?.nom || ''}</div>
            {item.points != null && (
              <div style={{ fontSize: 12, fontWeight: 700, color: '#0f172a', padding: '2px 8px', borderRadius: 4, background: '#f1f5f9' }}>
                {item.points} pts
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

const ORGANIZER_LABELS = { PMH: 'PMH', PMU: 'PMU', PMU_ONLINE: 'PMU en ligne', GENY: 'Genybet' }
const BET_TYPE_LABELS = {
  SIMPLE: 'Simple', E_SIMPLE: 'Simple', GB_SIMPLE_GAGNANT: 'Simple Gagnant', GB_SIMPLE_PLACE: 'Simple Placé',
  COUPLE: 'Couplé', E_COUPLE: 'Couplé', GB_COUPLE_GAGNANT: 'Couplé Gagnant', GB_COUPLE_PLACE: 'Couplé Placé',
  GB_COUPLE_ORDRE: 'Couplé Ordre', DEUX_SUR_QUATRE: '2 sur 4', GB_2_SUR_4: '2 sur 4',
  TRIO: 'Trio', TIERCE: 'Tiercé', QUARTE_PLUS: 'Quarté+', QUINTE_PLUS: 'Quinté+',
  MULTI: 'Multi', GB_MULTI: 'Multi', PICK5: 'Pick5'
}
const RAPPORT_TYPE_LABELS = {
  GAGNANT: 'Gagnant', PLACE: 'Placé', ORDRE: 'Ordre', DESORDRE: 'Désordre',
  STANDARD: 'Standard', BONUS: 'Bonus', GENY: 'Genybet', BONUS_4_SUR_5: 'Bonus 4 sur 5',
  BONUS_4: 'Bonus 4', BONUS_3: 'Bonus 3'
}
const BET_DISPLAY_ORDER = [
  'SIMPLE', 'E_SIMPLE', 'GB_SIMPLE_GAGNANT', 'GB_SIMPLE_PLACE',
  'COUPLE', 'E_COUPLE', 'GB_COUPLE_GAGNANT', 'GB_COUPLE_PLACE', 'GB_COUPLE_ORDRE',
  'DEUX_SUR_QUATRE', 'GB_2_SUR_4', 'TRIO', 'TIERCE', 'QUARTE_PLUS', 'MULTI', 'GB_MULTI', 'QUINTE_PLUS', 'PICK5'
]

function ArriveeRapportsTab({ rapportsData }) {
  const navigate = useNavigate()
  if (!rapportsData) return <div style={{ textAlign: 'center', color: '#94a3b8', padding: 40, background: '#fff', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow)' }}>Résultats non disponibles</div>
  const arriveeParticipants = (rapportsData.participants || []).filter(p => p.rang != null && p.rang > 0).sort((a, b) => a.rang - b.rang)
  return (
    <div style={{ background: '#fff', borderRadius: 'var(--radius)', padding: 16, boxShadow: 'var(--shadow)' }}>
      {arriveeParticipants.length > 0 && (
        <div style={{ marginBottom: 20 }}>
          <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', margin: '0 0 10px' }}>Arrivée</h3>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 4 }}>
            {arriveeParticipants.map(p => (
              <div key={p.num} style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '8px 12px', borderRadius: 8,
                background: p.rang <= 3 ? (p.rang === 1 ? '#fffbeb' : '#f0fdf4') : '#fff',
                border: '1px solid', borderColor: p.rang === 1 ? '#f59e0b' : p.rang <= 3 ? '#86efac' : '#f1f5f9',
              }}>
                <div style={{ width: 28, height: 28, borderRadius: 6, background: '#0f172a', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, fontSize: 13, flexShrink: 0 }}>{p.num}</div>
                  <div style={{ flex: 1 }}>
                    <button
                      onClick={(e) => { e.stopPropagation(); navigate(`/horse/${encodeURIComponent(p.horse)}`) }}
                      style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontWeight: 700, fontSize: 14, color: '#0f172a', textAlign: 'left' }}
                      onMouseEnter={e => e.currentTarget.style.color = '#ef4444'}
                      onMouseLeave={e => e.currentTarget.style.color = '#0f172a'}
                    >{p.horse}</button>
                    <div style={{ fontSize: 11, color: '#64748b' }}>{p.jockey && <span>J: {p.jockey} </span>}{p.red_km && <span>{p.red_km} </span>}</div>
                  </div>
                <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-end', gap: 1 }}>
                  <span style={{ fontWeight: 800, fontSize: 18, color: p.rang === 1 ? '#f59e0b' : '#334155' }}>{p.rang}<span style={{ fontSize: 11 }}>e</span></span>
                  {p.cote_pmu && <span style={{ fontSize: 11, color: '#64748b' }}>{p.cote_pmu}</span>}
                </div>
              </div>
            ))}
          </div>
        </div>
      )}
      {rapportsData.rapports && <RapportsSection rapports={rapportsData.rapports} />}
    </div>
  )
}

function RapportsSection({ rapports }) {
  const organizers = ['PMH', 'PMU', 'GENY']
  const [activeOrg, setActiveOrg] = useState('PMU')
  const orgData = rapports[activeOrg]
  if (!orgData) return <div style={{ textAlign: 'center', color: '#94a3b8', padding: 20 }}>Aucun rapport disponible</div>
  return (
    <div>
      <h3 style={{ fontSize: 16, fontWeight: 700, color: '#0f172a', margin: '0 0 10px' }}>Rapports</h3>
      <div style={{ display: 'flex', gap: 4, marginBottom: 12 }}>
        {organizers.map(org => rapports[org] && (
          <button key={org} onClick={() => setActiveOrg(org)} style={{
            padding: '5px 14px', borderRadius: 6, border: '1px solid', cursor: 'pointer',
            borderColor: activeOrg === org ? '#0f172a' : '#e2e8f0',
            background: activeOrg === org ? '#0f172a' : '#fff',
            color: activeOrg === org ? '#fff' : '#64748b', fontWeight: 600, fontSize: 12,
          }}>{ORGANIZER_LABELS[org] || org}</button>
        ))}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {BET_DISPLAY_ORDER.map(betType => {
          const entries = orgData[betType]
          if (!entries || entries.length === 0) return null
          return (
            <div key={betType} style={{ background: '#f8fafc', borderRadius: 10, padding: '10px 14px' }}>
              <div style={{ fontWeight: 700, fontSize: 13, color: '#0f172a', marginBottom: 6, textTransform: 'uppercase' }}>{BET_TYPE_LABELS[betType] || betType}</div>
              {entries.map((e, i) => (
                <div key={i} style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', padding: '4px 0', borderBottom: i < entries.length - 1 ? '1px solid #f1f5f9' : 'none', fontSize: 13 }}>
                  <div>
                    <span style={{ fontWeight: 600 }}>{e.texteCombinaison}</span>
                    {e.typeRapport !== 'GENY' && e.typeRapport !== 'STANDARD' && <span style={{ color: '#64748b', marginLeft: 8, fontSize: 11 }}>({RAPPORT_TYPE_LABELS[e.typeRapport] || e.typeRapport})</span>}
                    {e.texteAssocie && <span style={{ color: '#f97316', marginLeft: 8, fontSize: 11, fontStyle: 'italic' }}>{e.texteAssocie}</span>}
                  </div>
                  <span style={{ fontWeight: 700, color: e.remboursement ? '#94a3b8' : '#166534', fontSize: 14 }}>
                    {e.remboursement ? 'Remb.' : formatMontant(e.gainAssocie)}
                  </span>
                </div>
              ))}
              <div style={{ fontSize: 10, color: '#94a3b8', marginTop: 4 }}>Pour {euroStr(entries[0].miseDeBase)}</div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function RapportsProbablesTab({ cotesData }) {
  const navigate = useNavigate()
  if (!cotesData) return <div style={{ textAlign: 'center', color: '#94a3b8', padding: 40, background: '#fff', borderRadius: 'var(--radius)', boxShadow: 'var(--shadow)' }}>Cotes non disponibles</div>
  const cotes = cotesData.cotes || []
  const sorted = [...cotes].sort((a, b) => a.numero - b.numero)
  return (
    <div style={{ background: '#fff', borderRadius: 'var(--radius)', padding: 16, boxShadow: 'var(--shadow)' }}>
      <div style={{ marginBottom: 12, display: 'flex', gap: 16, fontSize: 12, color: '#64748b' }}>
        {cotesData.heureDerniereCotePmu && <span>Dernière cote PMU: {cotesData.heureDerniereCotePmu}</span>}
        {cotesData.heureDerniereCoteGenybet && <span>Dernière cote Genybet: {cotesData.heureDerniereCoteGenybet}</span>}
      </div>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
        {sorted.map(p => {
          const pmu = p.cotesPmu || {}
          const geny = p.cotesGenybet || {}
          const lastCote = pmu.derniereCote || geny.derniereCote
          return (
            <div key={p.numero} style={{ display: 'flex', alignItems: 'center', gap: 12, padding: '10px 14px', borderRadius: 10, background: '#f8fafc', border: '1px solid #f1f5f9' }}>
              <div style={{ width: 32, height: 32, borderRadius: 8, background: '#0f172a', display: 'flex', alignItems: 'center', justifyContent: 'center', color: '#fff', fontWeight: 800, fontSize: 14, flexShrink: 0 }}>{p.numero}</div>
              <div style={{ flex: 1, minWidth: 0 }}>
                <button
                  onClick={(e) => { e.stopPropagation(); navigate(`/horse/${encodeURIComponent(p.nomCheval)}`) }}
                  style={{ background: 'none', border: 'none', padding: 0, cursor: 'pointer', fontWeight: 700, fontSize: 14, color: '#0f172a', textAlign: 'left' }}
                  onMouseEnter={e => e.currentTarget.style.color = '#ef4444'}
                  onMouseLeave={e => e.currentTarget.style.color = '#0f172a'}
                >{p.nomCheval}</button>
                <div style={{ fontSize: 12, color: '#64748b', marginTop: 2 }}>{p.jockey?.prenom && p.jockey?.nom && <span>J: {p.jockey.prenom} {p.jockey.nom}</span>}</div>
              </div>
              <div style={{ display: 'flex', gap: 12, alignItems: 'center', flexShrink: 0 }}>
                {pmu.derniereCote > 0 && (
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 10, color: '#94a3b8' }}>PMU</div>
                    <span style={{ padding: '2px 8px', borderRadius: 4, background: pmu.derniereCote <= 5 ? '#dcfce7' : pmu.derniereCote <= 15 ? '#fef9c3' : '#fee2e2', color: pmu.derniereCote <= 5 ? '#166534' : pmu.derniereCote <= 15 ? '#854d0e' : '#991b1b', fontWeight: 700, fontSize: 13 }}>{pmu.derniereCote}</span>
                    {pmu.evolution != null && pmu.evolution > 0 && <div style={{ fontSize: 10, color: '#dc2626' }}>{'\u25B2'} {pmu.evolution > 1 ? '+' : ''}{pmu.evolution}</div>}
                  </div>
                )}
                {geny.derniereCote > 0 && (
                  <div style={{ textAlign: 'center' }}>
                    <div style={{ fontSize: 10, color: '#94a3b8' }}>Geny</div>
                    <span style={{ padding: '2px 8px', borderRadius: 4, background: geny.derniereCote <= 5 ? '#dcfce7' : geny.derniereCote <= 15 ? '#fef9c3' : '#fee2e2', color: geny.derniereCote <= 5 ? '#166534' : geny.derniereCote <= 15 ? '#854d0e' : '#991b1b', fontWeight: 700, fontSize: 13 }}>{geny.derniereCote}</span>
                  </div>
                )}
                {!lastCote && <span style={{ color: '#cbd5e1' }}>-</span>}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}
