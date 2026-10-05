import { useState } from 'react'
import { authLogin } from '../services/api'

export default function Login({ onOk }) {
  const [phone, setPhone] = useState('')
  const [pw, setPw] = useState('')
  const [err, setErr] = useState('')
  const [loading, setLoading] = useState(false)

  const submit = async (e) => {
    e.preventDefault()
    setErr(''); setLoading(true)
    try {
      await authLogin(phone.trim(), pw)
      onOk()
    } catch (e2) { setErr(e2.message || 'خطأ في الدخول') }
    setLoading(false)
  }

  return (
    <div style={{minHeight:'100vh',display:'flex',alignItems:'center',justifyContent:'center',background:'#0f172a',padding:20}}>
      <form onSubmit={submit} autoComplete="off" style={{background:'#fff',borderRadius:16,padding:28,width:'100%',maxWidth:360}}>
        <div style={{textAlign:'center',marginBottom:6}}>
          <div style={{fontWeight:900,fontSize:24}}>Bahja <span style={{color:'#22c55e'}}>PMU</span></div>
          <div style={{color:'#64748b',fontSize:13,marginTop:4}}>دخول المشتركين - رقم الهاتف + كلمة السر</div>
        </div>
        <label style={{fontSize:13,fontWeight:700}}>رقم الهاتف</label>
        <input value={phone} onChange={e=>setPhone(e.target.value)} placeholder="06 XX XX XX XX" autoComplete="off" style={{width:'100%',padding:10,margin:'6px 0 12px',border:'1px solid #cbd5e1',borderRadius:8}} required />
        <label style={{fontSize:13,fontWeight:700}}>كلمة السر (لا تحفظ أبداً)</label>
        <input type="password" value={pw} onChange={e=>setPw(e.target.value)} placeholder="••••••" autoComplete="new-password" style={{width:'100%',padding:10,margin:'6px 0 12px',border:'1px solid #cbd5e1',borderRadius:8}} required />
        {err && <div style={{background:'#fef2f2',color:'#dc2626',padding:8,borderRadius:8,fontSize:13,marginBottom:10}}>{err}</div>}
        <button type="submit" disabled={loading} style={{width:'100%',padding:12,borderRadius:8,border:0,background:'#22c55e',color:'#000',fontWeight:800,cursor:'pointer'}}>
          {loading ? 'جاري الدخول...' : 'دخول'}
        </button>
        <div style={{fontSize:11,color:'#94a3b8',textAlign:'center',marginTop:10}}>جهاز واحد فقط لكل حساب • تواصل واتساب للاشتراك</div>
      </form>
    </div>
  )
}
