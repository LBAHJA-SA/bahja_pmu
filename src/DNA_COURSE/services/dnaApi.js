const REMOTE = 'https://backend-production-f0139.up.railway.app'
const BASE = window.location.port === '5173' ? '' : REMOTE

async function once(base, url, options = {}, timeout = 120000) {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), timeout)
  try {
    const response = await fetch(`${base}${url}`, {
      ...options,
      headers: {
        ...(options.headers || {}),
        'X-Session-Token': localStorage.getItem('bahja-token') || '',
        'X-Phone': localStorage.getItem('bahja-phone') || '',
      },
      signal: controller.signal,
    })
    if (!response.ok) {
      const payload = await response.json().catch(() => ({}))
      const error = new Error(
        payload.error
          ? `${payload.error}${payload.detail ? ` — ${payload.detail}` : ''}`
          : `Erreur ${response.status}`
      )
      error.status = response.status
      throw error
    }
    return response.json()
  } finally {
    clearTimeout(timer)
  }
}

export async function extractDnaCourse(participants, options = {}) {
  const request = {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ participants, ...options }),
  }
  const alternate = BASE === REMOTE ? '' : REMOTE
  try {
    return await once(BASE, '/api/dna/extract', request)
  } catch (error) {
    if (error.name === 'AbortError') throw new Error('Délai dépassé — réessayez')
    if (alternate && alternate !== BASE) {
      try { return await once(alternate, '/api/dna/extract', request) } catch { throw error }
    }
    throw error
  }
}

export async function healthDnaCourse() {
  return once(BASE, '/api/dna/health', {}, 10000)
}
