import { useState, useEffect } from 'react'

export function useNow(ms = 30000) {
  const [now, setNow] = useState(() => Date.now())
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), ms)
    return () => clearInterval(t)
  }, [ms])
  return now
}

const C = {
  green: { fg: '#16a34a', bg: 'rgba(34,197,94,0.12)', bd: 'rgba(34,197,94,0.4)' },
  amber: { fg: '#d97706', bg: 'rgba(245,158,11,0.12)', bd: 'rgba(245,158,11,0.4)' },
  red: { fg: '#dc2626', bg: 'rgba(239,68,68,0.12)', bd: 'rgba(239,68,68,0.45)' },
  blue: { fg: '#0284c7', bg: 'rgba(2,132,199,0.10)', bd: 'rgba(2,132,199,0.35)' },
  gray: { fg: '#64748b', bg: 'rgba(100,116,139,0.10)', bd: 'rgba(100,116,139,0.3)' },
}

// The same four states on a dark or royal-blue ground. The foregrounds above are
// the 600-weight greens and ambers chosen for the app's light pages; on
// rgb(29,78,216) they measured 2.03, which is not readable. These are the
// tints that clear 4.5 on both grounds, and the grounds are solid rather than
// the 12% wash, because a wash over a solid frame lands on a third colour.
const CD = {
  green: { fg: '#86efac', bg: 'rgba(34,197,94,0.22)', bd: 'rgba(134,239,172,0.55)' },
  amber: { fg: '#fcd34d', bg: 'rgba(245,158,11,0.22)', bd: 'rgba(252,211,77,0.55)' },
  red: { fg: '#fca5a5', bg: 'rgba(239,68,68,0.22)', bd: 'rgba(252,165,165,0.55)' },
  blue: { fg: '#93c5fd', bg: 'rgba(2,132,199,0.25)', bd: 'rgba(147,197,253,0.55)' },
  gray: { fg: '#dbe4f0', bg: 'rgba(148,163,184,0.22)', bd: 'rgba(219,228,240,0.45)' },
}

export function countdownText(time, now) {
  if (time == null) return ''
  const t = typeof time === 'number' ? time : Date.parse(time)
  if (!t || isNaN(t)) return ''
  const d = Math.round((t - now) / 60000)
  if (d < -240) return ''
  if (d < 0) return 'parti'
  if (d > 15) return '' // العد العكسي يبدأ قبل 15 دقيقة فقط
  if (d === 0) return "D-0 min"
  return `D-${d} min`
}

export function raceStatus(c, now = Date.now()) {
  if (!c) return null
  const st = String(c.statut || '').toUpperCase()
  if (c.definitif || st.includes('DEFINITIV')) return { key: 'green', label: 'Définitif', ...C.green }
  if (st.includes('FIN_COURSE') || st.includes('ARRIVEE')) return { key: 'amber', label: 'Arrivée', ...C.amber }
  if (st.includes('EN_COURS') || st.includes('DEPART_CONFIRME') || st.includes('ROUGE')) {
    return { key: 'red', label: st.includes('ROUGE') ? 'Rouge aux partants' : 'En cours', ...C.red }
  }
  if (c.imminent) return { key: 'red', label: 'Départ imminent', ...C.red }
  if (st.includes('PROGRAMMEE') || c.time != null) {
    const cd = countdownText(c.time, now)
    if (cd === 'parti') return { key: 'amber', label: 'Parti…', ...C.amber }
    return { key: 'blue', label: cd || 'À venir', ...C.blue }
  }
  return null
}

// `onDark` is opt-in, so the pages that already work are not touched: without
// it the chip is exactly what it was. With it, the same four states are printed
// in tints that can be read on the dark panels and on the royal-blue frames.
export function statusChip(st, small = false, onDark = false) {
  if (!st) return null
  const k = onDark ? (CD[st.key] || CD.gray) : st
  return (
    <span style={{
      fontSize: small ? '0.5rem' : '0.62rem', fontWeight: 800, whiteSpace: 'nowrap',
      padding: small ? '1px 5px' : '2px 8px', borderRadius: 6,
      color: k.fg, background: k.bg, border: `1px solid ${k.bd}`,
    }}>
      {st.label}
    </span>
  )
}

export function meteoEmoji(label = '', code = '') {
  const l = `${label} ${code}`.toLowerCase()
  if (/pluie|averse|orage|rain/.test(l)) return '🌧️'
  if (/neige|neigeux/.test(l)) return '🌨️'
  if (/soleil|soleill|gage|clair|beau/.test(l)) return '☀️'
  if (/nuage|nuageux|couvert|cloud/.test(l)) return code === 'P4' ? '⛅' : '☁️'
  if (/brouillard|brume/.test(l)) return '🌫️'
  return '🌤️'
}

export function meteoText(meteo) {
  if (!meteo || meteo.temp == null) return null
  return `${meteoEmoji(meteo.label, meteo.code)} ${meteo.temp}°C`
}

export function FieldGateNote({ n, bet }) {
  if (!n) return null
  const ok = n <= 8
  return (
    <div style={{
      fontSize: '0.6rem', marginBottom: 8, padding: '6px 10px', borderRadius: 8,
      color: ok ? '#16a34a' : '#d97706',
      background: ok ? 'rgba(34,197,94,0.08)' : 'rgba(245,158,11,0.08)',
      border: ok ? '1px solid rgba(34,197,94,0.3)' : '1px solid rgba(245,158,11,0.35)',
    }}>
      {ok
        ? `Champ de ${n} — ${bet} éligible (mesuré SOREC, validation externe en attente).`
        : `Champ de ${n} — ${bet} déconseillé au-delà de 8 partants (mesuré SOREC : -12% à -100%). Validation externe en attente.`}
    </div>
  )
}

const COUNTRY_FLAGS = {
  FR: '🇫🇷', MA: '🇲🇦', US: '🇺🇸', GB: '🇬🇧', AR: '🇦🇷', ES: '🇪🇸',
  DE: '🇩🇪', BE: '🇧🇪', IT: '🇮🇹', AU: '🇦🇺', HK: '🇭🇰', HKG: '🇭🇰',
  KR: '🇰🇷', SE: '🇸🇪', AT: '🇦🇹', UY: '🇺🇾', CL: '🇨🇱', CH: '🇨🇭',
  IE: '🇮🇪', JP: '🇯🇵', ZA: '🇿🇦', NL: '🇳🇱', DK: '🇩🇰',
}

export function countryFlag(code) {
  if (!code) return ''
  return COUNTRY_FLAGS[String(code).toUpperCase()] || ''
}
