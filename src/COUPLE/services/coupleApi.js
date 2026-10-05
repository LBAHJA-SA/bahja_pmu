const REMOTE = 'https://lbahja-sa--bahja-backend-flask-app.modal.run'
const LOCALB = window.location.port === '5173' ? '' : ''
const BASE = window.location.port === '5173' ? '' : REMOTE
async function once(base, url, opts = {}, timeout = 30000){
  const ctrl = new AbortController()
  const timer = setTimeout(()=>ctrl.abort(), timeout)
  try{
    const headers = { ...(opts.headers || {}), 'X-Session-Token': localStorage.getItem('bahja-token') || '', 'X-Phone': localStorage.getItem('bahja-phone') || '' }
    const r=await fetch(`${base}${url}`, {...opts, headers, signal: ctrl.signal})
    if(!r.ok){ const e=await r.json().catch(()=>({})); const err=new Error(e.error||`Erreur ${r.status}`); err.status=r.status; throw err }
    return r.json()
  }finally{ clearTimeout(timer)}
}
async function req(url, opts={}){
  const alt = BASE === REMOTE ? LOCALB : REMOTE
  try{ return await once(BASE, url, opts) }
  catch(e){
    if(e.name==='AbortError' || e.message==='Failed to fetch'){
      try{ return await once(BASE, url, opts, 90000) }catch{}
    }
    if(alt && alt !== BASE){ try{ return await once(alt, url, opts) }catch(e2){ throw e } }
    throw e
  }
}
export async function fetchCoupleStats(limit=3000){ return req(`/api/couple/stats?limit=${limit}`)}
export async function extractCouple(participants, date, extra = {}){ return req('/api/couple/extract',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({participants, date: date || null, ...extra})})}
