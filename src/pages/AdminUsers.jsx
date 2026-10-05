import { useState } from 'react'
import { fmtStamp } from '../lib/gmtTime'

const REMOTE_API = 'https://lbahja-sa--bahja-backend-flask-app.modal.run'
// Repli local UNIQUEMENT en local (Vite = 5173). En prod il doit être '' — sinon
// l'admin repart sur 127.0.0.1:3000 du navigateur, qui n'existe pas.
const LOCAL_API = window.location.port === '5173' ? '' : ''

async function adminFetch(base, url, opts = {}) {
  const key = localStorage.getItem('bahja-admin-key') || ''
  const res = await fetch(`${base}${url}`, { ...opts,
    headers: { 'Content-Type': 'application/json', 'X-Admin-Key': key, ...(opts.headers || {}) } })
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).error || res.status)
  return res.json()
}

async function adminReq(url, opts = {}) {
  const isLocal = window.location.port === '5173'
  if (isLocal) {
    // على 5173: المحلي أولاً (يظهر admin المحلي)
    try { return await adminFetch(LOCAL_API, url, opts) } catch (e) {
      const msg = String(e.message || '')
      if (msg.includes('403') || msg.includes('autorisé')) throw new Error('مفتاح الإدارة خاطئ')
      try { return await adminFetch(REMOTE_API, url, opts) } catch {}
      throw e
    }
  }
  try {
    return await adminFetch(REMOTE_API, url, opts)
  } catch (e) {
    const msg = String(e.message || '')
    if (msg.includes('403') || msg.includes('autorisé')) {
      throw new Error('مفتاح الإدارة خاطئ - أدخل مفتاح الإدارة الصحيح فوق')
    }
    try { return await adminFetch(LOCAL_API, url, opts) } catch {}
    throw e
  }
}

function parseTime(s) {
  if (!s) return NaN
  const t = /[Z+-]\d{2}:?\d{2}$|Z$/.test(s) ? s : s.replace(' ', 'T') + 'Z'
  return new Date(t).getTime()
}

function DurationEditor({ u, onSave }) {
  const [dFrom, setDF] = useState((u.trial_from || new Date().toISOString()).slice(0, 10))
  const [dTo, setDT] = useState((u.trial_until || '').slice(0, 10))
  const [open, setOpen] = useState(false)
  if (!open) return <button onClick={() => setOpen(true)} style={{padding:'4px 8px',borderRadius:6,border:'1px solid #e2e8f0',background:'#fff'}}>📅 المدة</button>
  return (
    <span style={{display:'inline-flex',gap:4,alignItems:'center',background:'#f8fafc',padding:4,borderRadius:8,border:'1px solid #e2e8f0'}}>
      <label style={{fontSize:11}}>من <input type="date" value={dFrom} onChange={e => setDF(e.target.value)} style={{padding:'4px',borderRadius:6,border:'1px solid #cbd5e1'}} /></label>
      <label style={{fontSize:11}}>إلى <input type="date" value={dTo} onChange={e => setDT(e.target.value)} style={{padding:'4px',borderRadius:6,border:'1px solid #cbd5e1'}} /></label>
      <button onClick={() => { if (dTo) { onSave(u.phone, dFrom, dTo); setOpen(false) } }} style={{padding:'4px 10px',borderRadius:6,border:0,background:'#22c55e',fontWeight:800}}>حفظ</button>
      <button onClick={() => setOpen(false)} style={{padding:'4px 8px',borderRadius:6,border:'1px solid #e2e8f0',background:'#fff'}}>✕</button>
    </span>
  )
}

function isOnline(u) {
  if (!u.last_seen) return false
  try { return (Date.now() - parseTime(u.last_seen)) < 5 * 60 * 1000 } catch { return false }
}

function fmtTime(s) {
  if (!s) return '-'
  try {
    const t = parseTime(s)
    const mins = Math.floor((Date.now() - t) / 60000)
    const base = fmtStamp(t)
    if (mins < 1) return base + ' (الآن)'
    if (mins < 60) return base + ` (منذ ${mins} د)`
    return base + ` (منذ ${Math.floor(mins / 60)} س)`
  } catch { return s }
}

export default function AdminUsers() {
  const [key, setKey] = useState(localStorage.getItem('bahja-admin-key') || '')
  const [users, setUsers] = useState([])
  const [phone, setPhone] = useState('')
  const [pw, setPw] = useState('')
  const [days, setDays] = useState(1)
  const [msg, setMsg] = useState('')
  const [attempts, setAttempts] = useState([])
  const [showAtt, setShowAtt] = useState(null)

  const loadAttempts = async (p) => {
    if (showAtt === p) { setShowAtt(null); return }
    try {
      const a = await adminReq(`/api/admin/attempts?phone=${encodeURIComponent(p)}`)
      setAttempts(a); setShowAtt(p)
    } catch (e) { setMsg('خطأ: ' + e.message) }
  }

  const load = async () => {
    localStorage.setItem('bahja-admin-key', key)
    try {
      // مزامنة تلقائية بدون STAR: اسحب المفقود فقط إذا نجح جلب المحلي
      try {
        const localList = await adminFetch(LOCAL_API, '/api/admin/users')
        const remoteList = await adminFetch(REMOTE_API, '/api/admin/users')
        const localPhones = new Set(localList.map(u=>u.phone))
        for (const u of remoteList) if (!localPhones.has(u.phone)) {
          try { await adminFetch(LOCAL_API, '/api/admin/users', { method: 'POST', body: JSON.stringify({ phone: u.phone, password: 'sync123', days: 365 }) }) } catch {}
        }
      } catch {}
      setUsers(await adminReq('/api/admin/users')); setMsg('')
    }
    catch (e) { setMsg('خطأ: ' + e.message) }
  }
  const create = async () => {
    try {
      // إنشاء على المحلي والبعيد معاً (محلي=خارجي) - بدون انتظار tunnel
      const body = JSON.stringify({ phone, password: pw, days: Number(days) })
      let localOk = false, remoteOk = false, errL='', errR=''
      try { await adminFetch(LOCAL_API, '/api/admin/users', { method: 'POST', body }); localOk = true } catch (e) { errL = e.message }
      try { await adminFetch(REMOTE_API, '/api/admin/users', { method: 'POST', body }); remoteOk = true } catch (e) { errR = e.message }
      if (localOk || remoteOk) {
        setMsg(`✓ ${phone} - محلي:${localOk?'✓':'✗'+errL} خارجي:${remoteOk?'✓':'✗'+errR} - ${days}ي`); setPhone(''); setPw(''); load()
      } else throw new Error(`محلي:${errL} خارجي:${errR}`)
    } catch (e) { setMsg('خطأ: ' + e.message) }
  }
  const syncFromRemote = async () => {
    try {
      const remote = await adminFetch(REMOTE_API, '/api/admin/users')
      let added=0
      for (const u of remote) {
        try { await adminFetch(LOCAL_API, '/api/admin/users', { method: 'POST', body: JSON.stringify({ phone: u.phone, password: 'sync123', days: 365 }) }) } catch {}
        // لا نعرف كلمة السر الأصلية، نضع sync123 ثم اطلب تغييرها
      }
      setMsg(`✓ سحب ${remote.length} من الخارجي إلى المحلي (كلمة السر sync123 للمستورد)`)
      load()
    } catch(e){ setMsg('خطأ سحب: '+e.message) }
  }
  const act = async (p, action, extra = {}) => {
    try { await adminReq(`/api/admin/users/${encodeURIComponent(p)}`, { method: 'POST', body: JSON.stringify({ action, ...extra }) }); load() }
    catch (e) { setMsg('خطأ: ' + e.message) }
  }

  return (
    <div style={{maxWidth:700,margin:'0 auto',padding:20}}>
      <button onClick={()=>{ const p = localStorage.getItem('bahja-phone'); window.location.hash = (p === '0000000000' || p === 'admin') ? '#/' : '#/trot' }} style={{marginBottom:10,padding:'6px 14px',borderRadius:8,border:'1px solid #e2e8f0',background:'#fff',cursor:'pointer'}}>→ رجوع للصفحات</button>
      <h2>إدارة المشتركين</h2>
      <div style={{display:'flex',gap:8,margin:'10px 0'}}>
        <input type="password" value={key} onChange={e=>setKey(e.target.value)} placeholder="مفتاح الإدارة" style={{flex:1,padding:8,border:'1px solid #cbd5e1',borderRadius:8}} />
        <button onClick={load} style={{padding:'8px 16px',borderRadius:8,border:0,background:'#0f172a',color:'#fff',fontWeight:700}}>عرض</button>
      </div>
      <div style={{background:'#fff',border:'1px solid #e2e8f0',borderRadius:12,padding:12,marginBottom:12}}>
        <b>حساب جديد (رقم الهاتف + كلمة سر تحددها)</b>
        <div style={{display:'flex',gap:8,marginTop:8,flexWrap:'wrap'}}>
          <input value={phone} onChange={e=>setPhone(e.target.value)} placeholder="06..." style={{padding:8,border:'1px solid #cbd5e1',borderRadius:8}} />
          <input value={pw} onChange={e=>setPw(e.target.value)} placeholder="كلمة السر" style={{padding:8,border:'1px solid #cbd5e1',borderRadius:8}} />
          <input type="number" value={days} onChange={e=>setDays(e.target.value)} style={{width:70,padding:8,border:'1px solid #cbd5e1',borderRadius:8}} title="أيام" />
          <button onClick={create} style={{padding:'8px 16px',borderRadius:8,border:0,background:'#22c55e',fontWeight:800}}>إنشاء (محلي+خارجي)</button>
          <button onClick={syncFromRemote} style={{padding:'8px 12px',borderRadius:8,border:'1px solid #0ea5e9',background:'#f0f9ff',fontSize:12}}>⬇ سحب من الخارجي</button>
        </div>
      </div>
      {msg && <div style={{padding:8,background:'#f0fdf4',borderRadius:8,fontSize:13,marginBottom:10}}>{msg}</div>}
      {users.map(u=>(
        <div key={u.phone} style={{background:u.active?'#fff':'#fef2f2',border:'1px solid #e2e8f0',borderRadius:8,padding:8,marginBottom:6,fontSize:13}}>
          <div style={{display:'flex',gap:8,alignItems:'center'}}>
            <span style={{width:10,height:10,borderRadius:99,background:isOnline(u)?'#22c55e':'#cbd5e1'}} title={isOnline(u)?'متصل الآن':'غير متصل'} />
            <b>{u.phone}</b>
            <span style={{color:isOnline(u)?'#065f46':'#64748b',fontSize:12}}>{isOnline(u)?'متصل':'غير متصل'}</span>
            <span style={{color:'#64748b'}}>{u.trial_from ? `من ${u.trial_from.slice(0,10)} ` : ''}إلى {u.trial_until ? u.trial_until.slice(0,10) : 'دائم'}</span>
            <span style={{marginInlineStart:'auto',display:'flex',gap:4}}>
              {u.active
                ? <button onClick={()=>act(u.phone,'block')} style={{padding:'4px 8px',borderRadius:6,border:'1px solid #fecaca',background:'#fff',color:'#dc2626'}}>بلوك</button>
                : <button onClick={()=>act(u.phone,'unblock')} style={{padding:'4px 8px',borderRadius:6,border:'1px solid #bbf7d0',background:'#fff',color:'#065f46'}}>تفعيل</button>}
              <DurationEditor u={u} onSave={(phone, date_from, date_to) => act(phone, 'set-expiry', { date_from, date_to })} />
              <button onClick={()=>act(u.phone,'logout')} title="تحرير الجلسة العالقة للدخول من جديد" style={{padding:'4px 8px',borderRadius:6,border:'1px solid #fde68a',background:'#fffbeb'}}>طرد</button>
              <button onClick={()=>{ if(confirm('فك ربط الجهاز لـ '+u.phone+'؟ (للتبديل لهاتف جديد)')) act(u.phone,'device-reset') }} title="السماح لجهاز جديد" style={{padding:'4px 8px',borderRadius:6,border:'1px solid #e2e8f0',background:'#fff'}}>🔓 جهاز</button>
              <button onClick={()=>{ const p=prompt('كلمة السر الجديدة لـ '+u.phone+':'); if(p) act(u.phone,'password',{password:p}) }} style={{padding:'4px 8px',borderRadius:6,border:'1px solid #e2e8f0',background:'#fff'}}>كلمة السر</button>
              <button onClick={()=>{ if(confirm('حذف '+u.phone+' نهائياً؟')) act(u.phone,'delete') }} style={{padding:'4px 8px',borderRadius:6,border:'1px solid #fecaca',background:'#fff',color:'#dc2626'}}>حذف</button>
              <button onClick={()=>loadAttempts(u.phone)} style={{padding:'4px 8px',borderRadius:6,border:'1px solid #e2e8f0',background:'#fff'}} title="سجل محاولات الدخول (IP)">🕵️ الدخول</button>
            </span>
          </div>
          <div style={{color:'#94a3b8',fontSize:11,marginTop:4}}>IP: {u.ip || '-'} • آخر ظهور: {fmtTime(u.last_seen)}</div>
          {showAtt === u.phone && (
            <div style={{marginTop:6,background:'#f8fafc',borderRadius:8,padding:8,fontSize:11}}>
              <b>محاولات الدخول الأخيرة:</b>
              {(()=>{ const devs=[...new Set(attempts.filter(a=>a.device).map(a=>a.device))]; return devs.length>1 ? <div style={{background:'#fef2f2',color:'#dc2626',fontWeight:800,padding:6,borderRadius:6,margin:'4px 0'}}>⚠️ {devs.length} أجهزة مختلفة على نفس الحساب: {devs.join(' ، ')}</div> : null })()}
              {attempts.length === 0 && <div style={{color:'#94a3b8'}}>لا شيء</div>}
              {(()=>{ const ref=(attempts.find(a=>a.result==='ok')||{}).device; return attempts.map((a, i)=>(
                <div key={i} style={{display:'flex',gap:6,padding:'2px 0',borderTop:'1px solid #e2e8f0',color: a.result === 'ok' ? '#065f46' : '#dc2626', background: ref && a.device && a.device!==ref ? '#fef2f2' : 'transparent', fontWeight: ref && a.device && a.device!==ref ? 800 : 400}}>
                  <span>{(a.at || '').slice(0,16).replace('T',' ')}</span>
                  <span>IP: {a.ip || '-'}</span>
                  <span>{a.device || ''}{ref && a.device && a.device!==ref ? ' ⚠️' : ''}</span>
                  <span>{a.result === 'ok' ? '✓ دخول' : '✗ ' + a.result}</span>
                </div>
              )) })()}
            </div>
          )}
        </div>
      ))}
    </div>
  )
}
