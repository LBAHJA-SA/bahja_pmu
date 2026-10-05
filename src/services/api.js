const REMOTE_API = 'https://lbahja-sa--bahja-backend-flask-app.modal.run'
// Repli local UNIQUEMENT quand on tourne vraiment en local (Vite = port 5173).
// En prod (port vide) le repli doit être '' : sinon chaque requête échouée
// repart sur http://127.0.0.1:3000 du navigateur de l'utilisateur, qui n'existe
// pas — double le délai + ERR_ABORTED dans la console, et l'app « ne marche pas ».
const LOCAL_API = window.location.port === '5173' ? '' : ''
const API_BASE = window.location.port === '5173' ? '' : REMOTE_API

async function reqWithBase(base, url, opts, timeout) {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), timeout)
  try {
    const headers = { ...(opts.headers || {}),
      'X-Session-Token': localStorage.getItem('bahja-token') || '',
      'X-Phone': localStorage.getItem('bahja-phone') || '' }
    const res = await fetch(`${base}${url}`, { ...opts, headers, signal: ctrl.signal })
    if (!res.ok) {
      const payload = await res.json().catch(() => ({}))
      const error = new Error(payload.error || `Erreur ${res.status}`)
      error.status = res.status
      throw error
    }
    return res.json()
  } finally {
    clearTimeout(timer)
  }
}

function deviceId(){
  let d = localStorage.getItem('bahja-device')
  if(!d){ d = 'dvc-' + Math.random().toString(36).slice(2,10); localStorage.setItem('bahja-device', d) }
  return d
}

async function req(url, opts = {}) {
  const timeout = opts.timeout || 30000
  try {
    return await reqWithBase(API_BASE, url, opts, timeout)
  } catch (e) {
    // Serveur froid (Modal se réveille après inactivité) : le 1er request
    // dépasse le timeout, le 2e passe tout seul. On retente une fois.
    const froid = e.name === 'AbortError' || e.message === 'Failed to fetch'
    if (froid) {
      try { return await reqWithBase(API_BASE, url, opts, 90000) } catch {}
    }
    // Repli local : seulement si on tourne en local (Vite port 5173).
    if (LOCAL_API && LOCAL_API !== API_BASE) {
      try { return await reqWithBase(LOCAL_API, url, opts, timeout) } catch {}
    }
    throw e
  }
}

export async function authLogin(phone, password) {
  const res = await req('/api/auth/login', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, password, device_id: deviceId() }) })
  localStorage.setItem('bahja-token', res.token)
  localStorage.setItem('bahja-phone', res.phone)
  return res
}

export async function authLoginLocal(phone, password) {
  const base = LOCAL_API || ''
  const res = await reqWithBase(base, '/api/auth/login', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ phone, password, device_id: deviceId() }) }, 8000)
  localStorage.setItem('bahja-token', res.token)
  localStorage.setItem('bahja-phone', res.phone)
  return res
}

export async function authMe() {
  return req('/api/auth/me')
}

export function authLogout() {
  localStorage.removeItem('bahja-token')
  localStorage.removeItem('bahja-phone')
}

export async function authServerLogout() {
  try {
    await req('/api/auth/logout', { method: 'POST',
      headers: { 'Content-Type': 'application/json' }, body: '{}' })
  } catch {}
}

export async function authChangePassword(newPassword) {
  return req('/api/auth/password', { method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ new_password: newPassword }) })
}

export async function analyzeCoupSurRegret(participants, hippodrome, distance, date, discipline, runners) {
  const options = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ participants, hippodrome, distance, date, discipline, runners }),
    timeout: 240000
  }
  try {
    return await req('/api/regret/analyze', options)
  } catch (e) {
    // Older Railway deployment still exposes the Regret engine under the
    // legacy host; keep the unified engine working during the migration.
    if (window.location.port !== '5173' && (e?.status === 404 || e?.status === 405)) {
      return reqWithBase(LEGACY_REMOTE_API, '/api/regret/analyze', options, options.timeout)
    }
    throw e
  }
}

export async function fetchProgramme(date) {
  try {
    return await req(`/api/programme/${date}`)
  } catch(e) {
    if(String(e.message).includes('401') || String(e.message).includes('session') || String(e.message).includes('402')) throw e
    throw e
  }
}

export async function fetchDates() {
  return req('/api/programme/dates')
}

export async function fetchRaceDetails(raceId) {
  return req(`/api/race/${raceId}`)
}

export async function fetchRaceRapports(raceId) {
  return req(`/api/race/${raceId}/rapports`)
}

export async function fetchRaceCotes(raceId) {
  return req(`/api/race/${raceId}/cotes`)
}

export async function saveArchive(data) {
  return req('/api/archive', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data)
  })
}

export async function fetchArchives() {
  return req('/api/archive')
}

export async function fetchArchiveRaces(params = {}) {
  const q = new URLSearchParams(params).toString()
  return req(`/api/archive?${q}`)
}

export async function deleteArchiveFile(hippodrome, filename) {
  return req(`/api/archive/${encodeURIComponent(hippodrome)}/${encodeURIComponent(filename)}`, { method: 'DELETE' })
}

export async function deleteArchivedRace(raceId) {
  return req(`/api/archive/races/${raceId}`, { method: 'DELETE' })
}

export async function fetchArchiveDates() {
  return req('/api/archive/dates')
}

export async function saveArchiveByDate(date) {
  return req(`/api/archive/save-date/${date}`, { method: 'POST', timeout: 120000 })
}

export async function searchHorses(q) {
  return req(`/api/horses/search?q=${encodeURIComponent(q)}`, { timeout: 30000 })
}

export async function fetchHorseNames(q = '') {
  return req(`/api/horses/names?q=${encodeURIComponent(q)}`)
}

export async function fetchHorseRaces(name) {
  return req(`/api/horses/${encodeURIComponent(name)}/races`, { timeout: 30000 })
}

export async function searchJockeys(q) {
  return req(`/api/jockeys/search?q=${encodeURIComponent(q)}`, { timeout: 30000 })
}

export async function fetchJockeyNames(q = '') {
  return req(`/api/jockeys/names?q=${encodeURIComponent(q)}`)
}

export async function fetchJockeyRaces(name) {
  return req(`/api/jockeys/${encodeURIComponent(name)}/races`, { timeout: 30000 })
}

export async function fetchRaceAnalysis(raceId) {
  return req(`/api/analysis/${raceId}`, { timeout: 30000 })
}


export async function fetchMeetings(date) {
  if (!date) return { meetings: [] }
  const data = await req(`/api/programme/${date}`)
  return { meetings: data?.meetings || [] }
}

export async function fetchRace(date, reunionNumber, raceNum) {
  return req(`/api/race/${date}/${reunionNumber}/${raceNum}`)
}
