const BET_LABELS = {
  SIMPLE_GAGNANT: 'Simple',
  SIMPLE_GAGNANT_PLACE: 'Simple G/P',
  SIMPLE_PLACE: 'Simple placé',
  COUPLE: 'Jumelé',
  COUPLE_ORDRE: 'Couplé ordre',
  COUPLE_PLACE: 'Jumelé placé',
  COUPLE_GAGNANT: 'Jumelé',
  COUPLE_GAGNANT_PLACE: 'Jumelé G/P',
  JUMELE_ORDRE: 'Jumelé ordre',
  TRIO: 'Trio',
  TRIO_ORDRE: 'Trio ordre',
  E_TRIO: 'Trio',
  E_TRIO_ORDRE: 'Trio ordre',
  TIERCE: 'Tiercé',
  TIERCE_DESORDRE: 'Tiercé désordre',
  QUARTE: 'Quarté',
  QUARTE_PLUS: 'Quarté+',
  E_QUARTE_PLUS: 'Quarté+',
  QUINTE: 'Quinté',
  QUINTE_PLUS: 'Quinté+',
  E_QUINTE_PLUS: 'Quinté+',
  DEUX_SUR_QUATRE: '2sur4',
  SUPER_QUATRE: 'Super4',
  MULTI: 'Multi',
  MULTI4: 'Multi 4',
  MULTI5: 'Multi 5',
  MULTI6: 'Multi 6',
  MULTI7: 'Multi 7',
  ZONE_TURF: 'Zone Turf',
  PICK5: 'Pick5',
  REPORT_PLUS: 'Report+',
}

function normCode(s) {
  return String(s || '').toUpperCase().replace(/[^A-Z0-9_]/g, '_')
}

function labelFor(bet) {
  if (typeof bet === 'string') return BET_LABELS[normCode(bet)] || bet.toUpperCase()
  if (bet && typeof bet === 'object') {
    const code = String(bet.code || bet.typePari || bet.libelleCourt || bet.nom || bet.libelle || '').toUpperCase()
    return BET_LABELS[normCode(code)] || (code || '?')
  }
  return '?'
}

// `light` and `dark` are both opt-in, and neither is the default. The default
// path is what the theme tokens give, which is a near-black meant for the app's
// light pages: on a dark panel it measured 1.09 and was invisible. A page that
// puts its cards on a dark ground says so, instead of the colour being guessed.
export function RaceBetBadges({ race, light, dark }) {
  const types = Array.isArray(race?.types_pari) ? race.types_pari :
                (Array.isArray(race?.paris) ? race.paris.map(p => (p && p.typePari) || p) : []);
  const filtered = [];
  const seenLabels = new Set();
  for (const t of types) {
    const lbl = labelFor(t);
    if (seenLabels.has(lbl)) continue;
    seenLabels.add(lbl);
    filtered.push(t);
  }
  if (!race?.quinte && filtered.length === 0) return null
  const txtDim = dark ? '#dbe4f0' : (light ? '#64748b' : 'var(--text-dim, #0f172a)')
  const border = dark ? 'rgba(255,255,255,0.14)' : (light ? '#e2e8f0' : 'var(--border)')
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: light ? 0 : 3 }}>
      {race?.quinte && (
        <span style={{
          padding: '1px 6px', borderRadius: 3, fontSize: '0.55rem', fontWeight: 700,
          background: 'rgba(239,68,68,0.15)', color: dark ? '#fecaca' : '#ef4444', border: '1px solid rgba(239,68,68,0.35)',
        }}>Q+</span>
      )}
      {filtered.slice(0, 6).map((t, i) => (
        <span key={i} style={{
          padding: '1px 6px', borderRadius: 3, fontSize: '0.55rem', fontWeight: 700,
          background: light ? 'rgba(0,0,0,0.04)' : 'rgba(255,255,255,0.06)',
          color: txtDim, border: `1px solid ${border}`,
        }}>{labelFor(t)}</span>
      ))}
    </div>
  )
}

export function MeetingHighlights({ reunion }) {
  const courses = reunion?.courses || []
  const quinte = courses.some((c) => c.quinte || (c.paris && c.paris.some(p => p.typePari && p.typePari.includes('QUINTE'))))
  const specialty = [...new Set(courses.map((c) => c.specialty || c.specialite || c.discipline).filter(Boolean))]
  if (!quinte && specialty.length === 0) return null
  const formatDiscipline = (s) => {
    const map = {
      TROT_ATTELE: "Trot-Attelé", TROT_MONTE: "Trot-Monté", PLAT: "Plat",
      ATTELE: "Attelé", MONTE: "Monté", OBSTACLE: "Obstacle", CROSS: "Cross"
    };
    return map[s] || s;
  };
  return (
    <div style={{ display: 'flex', gap: 4, flexWrap: 'wrap', marginTop: 5 }}>
      {quinte && (
        <span style={{
          padding: '1px 6px', borderRadius: 3, fontSize: '0.55rem', fontWeight: 700,
          background: 'rgba(239,68,68,0.15)', color: '#ef4444', border: '1px solid rgba(239,68,68,0.35)',
        }}>Q+</span>
      )}
      {specialty.slice(0, 3).map((s) => (
        <span key={s} style={{
          padding: '1px 6px', borderRadius: 3, fontSize: '0.55rem', fontWeight: 700,
          background: 'rgba(0,229,255,0.1)', color: 'var(--neon-cyan)', border: '1px solid rgba(0,229,255,0.25)',
        }}>{formatDiscipline(s)}</span>
      ))}
    </div>
  )
}
