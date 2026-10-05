const REMOTE = 'https://lbahja-sa--bahja-backend-flask-app.modal.run'
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
    // Serveur froid (Modal se réveille après inactivité) : le 1er request
    // dépasse le timeout, le 2e passe. On retente avant d'abandonner.
    if (error.name === 'AbortError' || error.message === 'Failed to fetch') {
      try { return await once(BASE, '/api/dna/extract', request, 180000) } catch (e2) {
        if (e2.name === 'AbortError') throw new Error('Délai dépassé — réessayez')
        error = e2
      }
    }
    if (alternate && alternate !== BASE) {
      try { return await once(alternate, '/api/dna/extract', request) } catch { throw error }
    }
    throw error
  }
}

export async function healthDnaCourse() {
  return once(BASE, '/api/dna/health', {}, 10000)
}
