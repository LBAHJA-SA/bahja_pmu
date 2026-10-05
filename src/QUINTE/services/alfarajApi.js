const REMOTE = 'https://backend-production-f0139.up.railway.app'
const LOCALB = window.location.port === '5173' ? '' : ''
const BASE = window.location.port === '5173' ? '' : REMOTE
async function once(base, url, opts={}, timeout=30000) {
  const ctrl=new AbortController()
  const timer=setTimeout(()=>ctrl.abort(), timeout)
  try{
    const headers = { ...(opts.headers || {}), 'X-Session-Token': localStorage.getItem('bahja-token') || '', 'X-Phone': localStorage.getItem('bahja-phone') || '' }
    const r=await fetch(`${base}${url}`, {...opts, headers, signal: ctrl.signal})
    if(!r.ok){ const e=await r.json().catch(()=>({})); const err=new Error(e.error||`Erreur ${r.status}`); err.status=r.status; throw err }
    return r.json()
  }finally{ clearTimeout(timer)}
}
async function req(url, opts={}, timeout=30000) {
  const alt = BASE === REMOTE ? LOCALB : REMOTE
  try{
    return await once(BASE, url, opts, timeout)
  }catch(e){
    if(e.name==='AbortError') throw new Error('Délai dépassé — serveur occupé, réessayez')
    if(alt && alt !== BASE){
      try{ return await once(alt, url, opts, 10000) }catch(e2){ throw e }
    }
    throw e
  }
}
export async function fetchAlfarajStats(limit=4054, hippodrome, disc){ return req(`/api/alfaraj/stats?limit=${limit}&hippodrome=${hippodrome || ''}&disc=${disc || ''}`)}
export async function extractAlfaraj(participants, hippodrome, disc, distance, runners, date){ return req('/api/alfaraj/extract',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({participants, hippodrome, disc, distance, runners, date: date || null})}, 180000)}
export async function healthAlfaraj(){ return req('/api/alfaraj/health')}
