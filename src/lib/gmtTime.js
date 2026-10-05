// Every time in this application is GMT.
//
// This is not a preference, it is the only reading that can be checked. A race
// start arrives from the programme as epoch milliseconds, which is an absolute
// instant, but every way of *printing* it that does not name a zone prints it in
// the zone of whatever machine happens to be looking — so the same race showed
// 14:35 in Paris and 12:35 in Rabat, and the delay printed next to it did not
// match the clock on the card. Morocco is on GMT, so GMT is what is printed,
// and the zone is written next to the number so nothing has to be inferred.
//
// Nothing here invents a time. It only chooses the zone the existing instant is
// shown in, and it says which zone that is.

// GMT is UTC+0 with no daylight saving, all year, which is what Africa/Casablanca
// is on today. 'UTC' is used rather than a city name because the city would drag
// its own summer rule in with it.
export const TZ = 'UTC'
export const TZ_LABEL = 'GMT'

const clock = new Intl.DateTimeFormat('fr-FR', {
  timeZone: TZ, hour: '2-digit', minute: '2-digit', hour12: false,
})
const dayShort = new Intl.DateTimeFormat('fr-FR', {
  timeZone: TZ, weekday: 'short', day: 'numeric', month: 'short',
})
const dayLong = new Intl.DateTimeFormat('fr-FR', {
  timeZone: TZ, weekday: 'long', day: 'numeric', month: 'long', year: 'numeric',
})

// The programme hands the start over three ways depending on where it came from:
// epoch milliseconds (the programme API), epoch seconds (older archive rows) and
// an ISO string. Anything under 1e11 as a number is seconds, because 1e11
// milliseconds is 1973 and no race in this archive is that old.
export function toMs(t) {
  if (t == null || t === '') return null
  if (typeof t === 'number') {
    if (!isFinite(t) || t <= 0) return null
    return t < 1e11 ? Math.round(t * 1000) : Math.round(t)
  }
  const s = String(t).trim()
  if (/^\d+$/.test(s)) return toMs(Number(s))
  const p = Date.parse(s)
  return isNaN(p) ? null : p
}

export function fmtClock(t) {
  const ms = toMs(t)
  return ms == null ? '' : clock.format(new Date(ms))
}

export function fmtClockZ(t) {
  const s = fmtClock(t)
  return s ? `${s} ${TZ_LABEL}` : ''
}

export function fmtDay(t) {
  const ms = toMs(t)
  return ms == null ? '' : dayShort.format(new Date(ms)).replace('.', '')
}

export function fmtDate(t) {
  const ms = toMs(t)
  return ms == null ? '' : dayLong.format(new Date(ms))
}

// Day and clock together, the form an audit line needs: an action is stamped
// and has to be readable against a race time on the same page.
const stampFmt = new Intl.DateTimeFormat('fr-FR', {
  timeZone: TZ, day: '2-digit', month: '2-digit',
  hour: '2-digit', minute: '2-digit', hour12: false,
})
export function fmtStamp(t) {
  const ms = toMs(t)
  return ms == null ? '' : `${stampFmt.format(new Date(ms))} ${TZ_LABEL}`
}

// A calendar day written on its own — '2026-09-26' — has no zone of its own.
// Read as local midnight it slips to the day before for anyone west of GMT,
// which is the whole reason this exists: it is anchored at GMT noon, so the day
// named is the day meant on every machine.
export function parseDay(day) {
  if (!day) return null
  const s = String(day).slice(0, 10)
  const p = Date.parse(s + 'T12:00:00Z')
  return isNaN(p) ? null : p
}

export function fmtDayString(day) {
  const ms = parseDay(day)
  return ms == null ? '' : dayLong.format(new Date(ms))
}

// The delay between the reading and the off, in minutes exactly, never banded.
// A negative delay is a reading made after the race had already gone; that is a
// real reading and it is printed as such rather than hidden.
export function leadText(leadMin) {
  if (leadMin == null) return `heure de départ inconnue`
  const m = Math.abs(Math.round(leadMin))
  if (m < 1) return `à l'instant du départ`
  const h = Math.floor(m / 60)
  const r = m % 60
  const parts = []
  if (h) parts.push(`${h} h`)
  if (r || !h) parts.push(`${r} min`)
  const d = parts.join(' ')
  return leadMin >= 0 ? `${d} avant le départ` : `${d} après le départ`
}
