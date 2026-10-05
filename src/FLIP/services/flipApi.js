const REMOTE = 'https://backend-production-f0139.up.railway.app'
const LOCALB = ''
const BASE = window.location.port === '5173' ? '' : REMOTE

async function once(base, url, opts = {}) {
  const headers = {
    ...(opts.headers || {}),
    'X-Session-Token': localStorage.getItem('bahja-token') || '',
    'X-Phone': localStorage.getItem('bahja-phone') || '',
  }
  const r = await fetch(`${base}${url}`, { ...opts, headers })
  if (!r.ok) {
    const e = await r.json().catch(() => ({}))
    throw new Error(e.error || `Erreur ${r.status}`)
  }
  return r.json()
}

async function req(url, opts = {}) {
  const alt = BASE === REMOTE ? LOCALB : REMOTE
  try {
    return await once(BASE, url, opts)
  } catch (e) {
    if (alt && alt !== BASE) {
      try { return await once(alt, url, opts) } catch { throw e }
    }
    throw e
  }
}

export async function flipHealth() { return req('/api/flip/health') }
export async function flipDates(limit = 21) { return req(`/api/flip/dates?limit=${limit}`) }
export async function measureFlip(date) { return req(`/api/flip/measure?date=${date}`) }

// Records what the engine says about one field, now. Nothing is scored here —
// the race has usually not run yet. /api/flip/log fills in the result later.
export async function saveFlipPick(payload) {
  return req('/api/flip/pick', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload),
  })
}

export async function fetchFlipLog() { return req('/api/flip/log') }

// The recorded predictions cannot be regenerated later — if the rule changes,
// a re-run would answer differently than it did on the day. So the call has to
// carry the word the backend is looking for.
export async function clearFlipLog() {
  return req('/api/flip/log/clear', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ confirm: 'EFFACER' }),
  })
}
export async function extractFlip(participants, date, extra = {}) {
  return req('/api/flip/extract', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ participants, date: date || null, ...extra }),
  })
}
