const REMOTE = 'https://lbahja-sa--bahja-backend-flask-app.modal.run'
const LOCALB = window.location.port === '5173' ? '' : ''
const BASE = window.location.port === '5173' ? '' : REMOTE
async function once(base, url, opts={}){
  const headers = { ...(opts.headers || {}), 'X-Session-Token': localStorage.getItem('bahja-token') || '', 'X-Phone': localStorage.getItem('bahja-phone') || '' }
  const r=await fetch(`${base}${url}`, {...opts, headers})
  if(!r.ok){ const e=await r.json().catch(()=>({})); throw new Error(e.error||`Erreur ${r.status}`)}
  return r.json()
}
async function req(url, opts={}){
  const alt = BASE === REMOTE ? LOCALB : REMOTE
  try{ return await once(BASE, url, opts) }
  catch(e){
    if(alt && alt !== BASE){ try{ return await once(alt, url, opts) }catch(e2){ throw e } }
    throw e
  }
}
export async function fetchCoupleStats(limit=3000){ return req(`/api/couple/stats?limit=${limit}`)}
export async function extractCouple(participants, date, extra = {}){ return req('/api/couple/extract',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({participants, date: date || null, ...extra})})}
