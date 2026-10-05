import { useEffect, useState } from 'react'
import { Crown, Scale, Hash, Calendar, RefreshCw, Heart, Flag } from 'lucide-react'
import { fetchMeetings, fetchRace, analyzeCoupSurRegret } from '../../services/api'
import { fetchAlfarajStats, extractAlfaraj } from '../../QUINTE/services/alfarajApi'
import { extractCouple } from '../../COUPLE/services/coupleApi'
import { RaceBetBadges } from '../../components/BetBadges'
import { useNow, raceStatus, statusChip, meteoText, countryFlag, FieldGateNote } from '../../lib/raceStatus.jsx'
import { fmtClock } from '../../lib/gmtTime'

function KV({k,v}){ return <span style={{fontSize:'0.76rem',padding:'3px 8px',borderRadius:7,background:'rgba(255,255,255,0.04)',border:'1px solid var(--border)',margin:2}}><b style={{color:'var(--neon-cyan)'}}>{k}</b> {v}</span>}

const FAMILY='GALOP'
const DISCS=['PLAT','HAIE','STEEPLE','CROSS']
function isFamily(c){ const d=(c.discipline||c.specialty||'').toUpperCase(); return DISCS.some(x=>d.includes(x)) }

export default function GalopPage(){
  const [date,setDate]=useState(()=>new Date().toISOString().slice(0,10))
  const [meetings,setMeetings]=useState([])
  const [selReu,setSelReu]=useState(null)
  const [sel,setSel]=useState(null)
  const [raceData,setRaceData]=useState(null)
  const [stats,setStats]=useState(null)
  const [matches,setMatches]=useState(null)
  const [trio,setTrio]=useState(null)
  const [brave,setBrave]=useState(null)
  const [couple,setCouple]=useState(null)
  const [regret,setRegret]=useState(null)
  const [loading,setLoading]=useState(false)
  const [analyzing,setAnalyzing]=useState(false)
  const [pending,setPending]=useState(false)
  const [pendingCouple,setPendingCouple]=useState(false)
  const [pendingRegret,setPendingRegret]=useState(false)
  const [coupleErr,setCoupleErr]=useState(null)
  const [regretErr,setRegretErr]=useState(null)
  const [err,setErr]=useState(null)
  const now=useNow(30000)
  const isOwnerSuivi = localStorage.getItem('bahja-phone') === '0000000000' || localStorage.getItem('bahja-phone') === 'admin'

  const loadStats=async()=>{ try{ const s=await fetchAlfarajStats(4054,'',FAMILY); setStats(s)}catch(e){ setErr(e.message)}}
  useEffect(()=>{ loadStats()},[])
  const loadMeetings=async(d=date)=>{ setLoading(true); setErr(null); try{ const r=await fetchMeetings(d); setMeetings(r.meetings||[])}catch(e){ setErr(e.message)}finally{ setLoading(false)}}
  useEffect(()=>{ loadMeetings(date)},[])
  const pick=async(m,c)=>{ setSel({date,rnum:m.num,cnum:c.num,meeting:m,course:c}); setRaceData(null); setMatches(null); setTrio(null); setBrave(null); setCouple(null); setRegret(null); setTrackedId(null); setCoupleErr(null); setRegretErr(null); setPendingCouple(false); setPendingRegret(false); setPendingCouple(false); try{ const d=await fetchRace(date,m.num,c.num); setRaceData(d)}catch(e){ setErr(e.message)}}
  const [trackedId,setTrackedId]=useState(null)
  const suivre=async()=>{
    if(!sel||!raceData?.participants?.length) return
    const tickets={}
    const slim=(arr)=>(arr||[]).map(x=>({target_pos:x.target_pos??null,num:x.num,horse:x.horse,cote:x.cote??null,score:x.score??x.ecart??null}))
    if(trio?.length) tickets.trio=slim(trio)
    if(matches?.length) tickets.quinte=slim(matches.filter(m=>!m.reserve))
    if(brave?.length) tickets.forme=slim(brave)
    if(couple?.length){ const c0=couple[0]; tickets.couple=(c0.horses||[]).map(h=>({target_pos:null,num:h.num,horse:h.horse,cote:null,score:c0.count??null})) }
    try{
      const _base=window.location.port==='5173'?'':'https://lbahja-sa--bahja-backend-flask-app.modal.run'
      const r=await fetch(`${_base}/api/track/log`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({race:{date,rnum:sel.rnum,cnum:sel.cnum,hippodrome:hippoOf(sel.meeting),discipline:sel.course.discipline||sel.course.specialty||'',distance:sel.course.distance,runners:raceData.participants.length,time:sel.course.time||null},tickets})})
      const j=await r.json()
      if(!r.ok) throw new Error(j.error||'Erreur')
      setTrackedId(j.tracked_id); setErr(null)
    }catch(e){ setErr(e.message)}
  }
  const hippoOf=(m)=>{ if(!m) return ''; if(typeof m.hippodrome==='string'&&m.hippodrome) return m.hippodrome; if(m.hippodrome_full) return m.hippodrome_full; if(m.hippodrome?.libelleLong) return m.hippodrome.libelleLong; if(m.hippodrome?.libelleCourt) return m.hippodrome.libelleCourt; return '' }
  const run=async()=>{
    if(!raceData?.participants?.length) return
    const meeting=meetings.find(m=>m.num===selReu)
    const hippodrome=hippoOf(meeting)
    setAnalyzing(true); setErr(null); setPendingCouple(true); setPendingRegret(true); setPending(true)
    try{
      const c=sel.course
      const pAl = extractAlfaraj(raceData.participants, hippodrome, FAMILY, sel.course?.distance, sel.course?.runners||raceData.participants.length).then(al=>{
        setMatches(al.matches||[]); setTrio(al.trio||[]); setBrave(al.brave||[])
        if(al.hist) setStats(al.hist)
        if(al.message) setErr(al.message)
      }).catch(e=>{ setErr(e.message||'Erreur ALFARAJ') })
      const pCp = extractCouple(raceData.participants).then(cp=>{
        setCouple(cp.matches||[])
      }).catch(e=>{ setCoupleErr(e.message||'Erreur Couple') }).finally(()=>setPendingCouple(false))
      const pRg = analyzeCoupSurRegret(raceData.participants, c.hippodrome?.code||hippo, c.distance, date, c.discipline||c.specialty, c.runners||raceData.participants.length).then(rg=>{
        setRegret(rg)
      }).catch(e=>{ setRegretErr(e.message||'Erreur REGRET') }).finally(()=>setPendingRegret(false))
      await Promise.allSettled([pAl,pCp,pRg])
    }catch(e){ setErr(e.message)}finally{ setAnalyzing(false); setPending(false)}
  }
  const gMeetings=meetings.map(m=>({...m, courses:(m.courses||[]).filter(isFamily)})).filter(m=>m.courses.length>0)
  const jockeyOf=(num)=>{ const p=(raceData?.participants||[]).find(x=>x.num===num); return p ? (p.jockey||p.driver||'') : '' }
  const fieldN=raceData?.participants?.length || 0
  return (
    <div className="neon-theme">
      <div className="page-tag galop">GALOP <small>Plat · Haie · Steeple · Couple · Trio · Regret · Quinté</small></div>
      <h2 className="neon-title" style={{display:'flex',alignItems:'center',gap:8,marginBottom:4}}><Crown size={26}/> GALOP — PLAT + HAIE + STEEPLE <span style={{fontSize:'0.76rem',color:'var(--text-muted)'}}>Couple · Trio · Regret · Quinté 7</span></h2>
      <p style={{color:'var(--text-dim)',fontSize:'0.86rem',margin:'0 0 14px'}}>Page dédiée GALOP — tous les tickets filtrés par discipline. Objectif prioritaire: Trio (P1→P3).</p>
      {isOwnerSuivi && <div className="neon-card" style={{marginBottom:14,borderColor:'rgba(168,85,247,0.3)'}}>
        <h3 style={{fontSize:'0.95rem',color:'#a855f7',marginBottom:8,display:'flex',alignItems:'center',gap:6}}><Scale size={14}/> Race DNA — GALOP</h3>
        {stats ? <><div style={{display:'flex',flexWrap:'wrap',gap:6}}><KV k="Portée" v={FAMILY}/><KV k="Quinté" v={stats.total_quinte_races}/><KV k="Top" v={stats.race_dna_most ? `${stats.race_dna_most[0]} (${stats.race_dna_most[1]}×)` : '—'}/></div><div style={{marginTop:6,fontSize:'0.95rem',color:'var(--text-muted)'}}>Familles: {(stats.family_top||[]).slice(0,3).map(([k,v])=>`${k} ${v}×`).join(' · ')}</div></> : <span style={{fontSize:'0.76rem',color:'var(--text-muted)'}}>Chargement…</span>}
      </div>}
      <div className="neon-card" style={{marginBottom:14}}>
        <h3 style={{fontSize:'0.95rem',color:'var(--neon-cyan)',marginBottom:8,display:'flex',alignItems:'center',gap:6}}><Calendar size={14}/> Courses du jour — GALOP</h3>
        <div style={{display:'flex',gap:10,flexWrap:'wrap',alignItems:'center'}}>
          <input type="date" value={date} onChange={e=>setDate(e.target.value)} style={{background:'var(--bg-primary)',color:'var(--text-primary)',border:'1px solid var(--border)',borderRadius:8,padding:'8px 12px',fontSize:'0.86rem'}}/>
          <button onClick={()=>loadMeetings(date)} disabled={loading} style={{display:'flex',alignItems:'center',gap:6,background:'linear-gradient(135deg, #a855f7, #ec4899)',color:'#fff',fontWeight:800,border:'none',borderRadius:10,padding:'9px 18px',cursor:'pointer',fontSize:'0.83rem'}}><RefreshCw size={14}/>{loading?'…':`Charger ${date}`}</button>
          <span style={{fontSize:'0.76rem',color:'var(--text-muted)'}}>{gMeetings.length} réunions GALOP</span>
        </div>
        <div style={{display:'flex',flexWrap:'wrap',gap:8,marginTop:10}}>
          {gMeetings.map(m=>{ const active=selReu===m.num; const hippoName=(m.hippodrome_full||m.hippodrome?.libelleLong||m.hippodrome||`R${m.num}`).toString(); const mt=meteoText(m.meteo); const fl=countryFlag(m.country); return <button key={m.num} onClick={()=>setSelReu(active?null:m.num)} style={{minWidth:84,padding:'10px 14px',borderRadius:12,border:active?'1.5px solid #a855f7':m.country==='MA'?'1px solid rgba(193,39,45,0.5)':'1px solid var(--border)',background:active?'rgba(168,85,247,0.15)':'rgba(255,255,255,0.03)',color:active?'#a855f7':'var(--text-primary)',fontWeight:900,fontSize:'0.86rem',cursor:'pointer'}}><div>R{m.num}{fl && <span style={{marginLeft:4}}>{fl}</span>}{mt && <span style={{fontSize:'0.66rem',fontWeight:600,marginLeft:4}} title={m.meteo.label||''}>{mt}</span>}</div><div style={{fontSize:'0.64rem',color:'var(--text-muted)',maxWidth:90,overflow:'hidden',textOverflow:'ellipsis',whiteSpace:'nowrap'}}>{hippoName}</div><div style={{fontSize:'0.64rem'}}>{m.courses.length} courses</div></button> })}
        </div>
        {selReu!=null && (()=>{ const m=gMeetings.find(x=>x.num===selReu); if(!m) return null; return <div style={{marginTop:12,borderTop:'1px solid rgba(255,255,255,0.06)',paddingTop:12}}><div style={{display:'flex',flexWrap:'wrap',gap:8}}>{m.courses.map(c=>{ const act=sel&&sel.rnum===m.num&&sel.cnum===c.num; const st=raceStatus(c,now); return <button key={c.num} onClick={()=>pick(m,c)} style={{minWidth:78,padding:'8px 10px',borderRadius:10,border:act?'1.5px solid #a855f7':'1px solid var(--border)',background:act?'rgba(168,85,247,0.12)':'rgba(255,255,255,0.03)',color:act?'#a855f7':'var(--text-secondary)',fontWeight:800,fontSize:'0.83rem',cursor:'pointer'}}>C{c.num} {c.time ? new Date(typeof c.time==='number'?c.time:Date.parse(c.time)).toLocaleTimeString('fr-FR',{hour:'2-digit',minute:'2-digit'}) : ''}<div style={{marginTop:2}}>{statusChip(st,true)}</div><div style={{fontSize:'0.64rem',color:'var(--text-muted)'}}>{c.discipline||''} {c.distance}m</div><RaceBetBadges race={c}/></button>})}</div></div>})()}
      </div>
      {sel && <div className="neon-card" style={{marginBottom:14}}><h3 style={{fontSize:'0.95rem',color:'#a855f7',marginBottom:8}}>R{sel.rnum}C{sel.cnum} — {sel.course.libelle||''} {(() => { const st=raceStatus(sel.course,now); return statusChip(st) })()}{(() => { const mm=(meetings.find(x=>x.num===sel.rnum)||{}).meteo; const t=meteoText(mm); return t ? <span title={mm.label||''} style={{fontSize:'0.76rem',marginLeft:6}}>{t}</span> : null })()}</h3><RaceBetBadges race={sel.course}/>{raceData && <div style={{display:'flex',flexWrap:'wrap',gap:4,marginBottom:10}}>{raceData.participants.slice(0,20).map(p=> <span key={p.num} style={{fontSize:'0.86rem',padding:'3px 6px',borderRadius:6,background:'rgba(255,255,255,0.04)',border:'1px solid var(--border)'}}><b style={{color:'#a855f7'}}>{p.num}</b> {p.horse}</span>)}</div>}<button onClick={run} disabled={analyzing} style={{display:'flex',alignItems:'center',gap:8,background:'linear-gradient(135deg,#a855f7,#ec4899)',color:'#fff',fontWeight:900,border:'none',borderRadius:10,padding:'10px 18px',cursor:analyzing?'wait':'pointer',fontSize:'0.86rem',opacity:analyzing?0.7:1}}>{analyzing?'Analyse…':'Analyser — Couple · Trio · Regret · Quinté 7'}</button> {isOwnerSuivi && <button onClick={suivre} disabled={(!matches&&!trio)||analyzing||pendingCouple||pending} title={(analyzing||pendingCouple||pending)?'Attendez la fin de toutes les analyses':''} style={{background:'rgba(168,85,247,0.12)',color:'#c084fc',border:'1px solid rgba(168,85,247,0.4)',borderRadius:10,padding:'10px 18px',cursor:'pointer',fontSize:'0.86rem',fontWeight:800,opacity:(analyzing||pendingCouple||pending)?0.5:1}}>{trackedId?`Suivi #${trackedId} ✓`:(analyzing||pendingCouple||pending)?'Analyses en cours…':'Suivre cette course'}</button>}{err && <div style={{color:'var(--neon-red)',fontSize:'0.86rem',marginTop:8}}>{err}</div>}</div>}
      {trio && trio.length>0 && <div className="neon-card" style={{borderColor:'rgba(168,85,247,0.35)',marginBottom:14}}><h3 style={{fontSize:'0.95rem',color:'#a855f7',marginBottom:8,display:'flex',alignItems:'center',gap:6}}><Hash size={14}/> Trio — P1→P3 ({trio.length})</h3><FieldGateNote n={fieldN} bet="Trio Ordre"/><div style={{display:'flex',flexWrap:'wrap',gap:8,opacity:fieldN>8?0.45:1}}>{trio.map(m=>{ const j=jockeyOf(m.num); return <div key={m.num} style={{width:138,padding:'8px',borderRadius:12,border:'1px solid var(--border)',background:'rgba(168,85,247,0.06)',textAlign:'center'}}><div style={{fontWeight:900,fontSize:'0.95rem',color:'#a855f7'}}>{String(m.num).padStart(2,'0')} {(m.horse||'').slice(0,11)} → P{m.target_pos}</div>{j && <div style={{fontSize:'0.66rem',color:'var(--text-muted)'}}>{j}</div>}<div style={{fontSize:'0.86rem',color:'var(--text-primary)',marginTop:2}}>{m.cote} · {m.layer} → {m.target_layer} · <b>score {m.score}</b></div></div>})}</div></div>}
      {pendingCouple && <div className="neon-card" style={{marginBottom:14}}><div style={{fontSize:'0.76rem',color:'var(--text-muted)'}}>Analyse Couple en cours…</div></div>}
      {coupleErr && !pendingCouple && <div className="neon-card" style={{marginBottom:14}}><div style={{color:'var(--neon-red)',fontSize:'0.76rem'}}>Couple indisponible : {coupleErr}</div></div>}
      {pendingRegret && <div className="neon-card" style={{marginBottom:14}}><div style={{fontSize:'0.76rem',color:'var(--text-muted)'}}>Analyse Regret en cours…</div></div>}
      {regretErr && !pendingRegret && <div className="neon-card" style={{marginBottom:14}}><div style={{color:'var(--neon-red)',fontSize:'0.76rem'}}>Regret indisponible : {regretErr}</div></div>}
      {regret && <div className="neon-card" style={{borderColor:'rgba(249,115,22,0.35)',marginBottom:14}}><h3 style={{fontSize:'0.95rem',color:'#f97316',marginBottom:8,display:'flex',alignItems:'center',gap:6}}><Flag size={14}/> Regret</h3>{regret.picks?.regret ? <div style={{fontSize:'0.95rem',color:'var(--text-primary)'}}><b>#{regret.picks.regret.num} {regret.picks.regret.nom}</b>{regret.picks.regret.jockey && <span style={{fontSize:'0.95rem',color:'var(--text-muted)'}}> — {regret.picks.regret.jockey}</span>} - score {regret.picks.regret.score} - {regret.picks.regret.grade}</div> : <span style={{fontSize:'0.76rem',color:'var(--text-muted)'}}>Aucun regret éligible</span>}</div>}
      {couple && couple.length>0 && <div className="neon-card" style={{borderColor:'rgba(236,72,153,0.35)',marginBottom:14}}><h3 style={{fontSize:'0.95rem',color:'#ec4899',marginBottom:8,display:'flex',alignItems:'center',gap:6}}><Heart size={16}/> Couple ({couple.length})</h3><FieldGateNote n={fieldN} bet="Couplé"/><div style={{display:'flex',flexWrap:'wrap',gap:8,opacity:fieldN>8?0.45:1}}>{couple.slice(0,3).map((mm,i)=><div key={i} style={{padding:'8px',borderRadius:12,border:'1px solid var(--border)',background:'rgba(236,72,153,0.06)'}}><div style={{fontSize:'0.95rem',fontWeight:800,color:'#ec4899'}}>{mm.type} {mm.key} — {mm.count}×</div><div style={{display:'flex',gap:6,marginTop:4}}>{(mm.horses||[]).map(h=><span key={h.num} style={{fontSize:'0.95rem',padding:'3px 6px',borderRadius:6,background:'rgba(255,255,255,0.04)',border:'1px solid var(--border)'}}><b>{h.num}</b> {h.horse.slice(0,10)}</span>)}</div></div>)}</div></div>}
      {brave && brave.length>0 && <div className="neon-card" style={{borderColor:'rgba(168,85,247,0.45)',marginBottom:14}}><h3 style={{fontSize:'0.95rem',color:'#a855f7',marginBottom:8,display:'flex',alignItems:'center',gap:6}}><Hash size={14}/> Forme — sans cotes ({brave.length})</h3><div style={{fontSize:'0.86rem',color:'var(--text-muted)',marginBottom:8}}>Basé uniquement sur la forme (musique). Fonctionne même quand les cotes ne sont pas publiées. P1 mesuré ~8% ≈ hasard — descripteur.</div><div style={{display:'flex',flexWrap:'wrap',gap:8}}>{brave.map(b=>{ const j=jockeyOf(b.num); return <div key={b.num} style={{width:138,padding:'8px',borderRadius:12,border:b.weak?'1px dashed var(--border)':'1px solid rgba(168,85,247,0.4)',background:b.weak?'rgba(255,255,255,0.02)':'rgba(168,85,247,0.07)',textAlign:'center',opacity:b.weak?0.75:1}}><div style={{fontWeight:900,fontSize:'0.95rem',color:'#a855f7'}}>{String(b.num).padStart(2,'0')} {(b.horse||'').slice(0,11)} → P{b.target_pos}{b.weak?' (fragile)':''}</div>{j && <div style={{fontSize:'0.66rem',color:'var(--text-muted)'}}>{j}</div>}<div style={{fontSize:'0.86rem',color:'var(--text-primary)',marginTop:2}}>écart <b>{b.ecart}</b></div><div style={{fontSize:'0.64rem',color:'var(--text-muted)',marginTop:2}}>{(b.reasons||[]).slice(0,2).join(' · ')||'—'}</div></div>})}</div></div>}
      {matches && <div className="neon-card" style={{borderColor:'rgba(234,179,8,0.35)'}}><h3 style={{fontSize:'0.95rem',color:'#eab308',marginBottom:8,display:'flex',alignItems:'center',gap:6}}><Hash size={14}/> Quinté 5 + 2 réserves ({matches.filter(m=>!m.reserve).length}+{matches.filter(m=>m.reserve).length})</h3><div style={{display:'flex',flexWrap:'wrap',gap:8}}>{matches.map(m=>{ const j=jockeyOf(m.num); return <div key={m.num} style={{width:138,padding:'8px',borderRadius:12,border:m.reserve?'1px dashed rgba(234,179,8,0.5)':m.weak?'1px dashed var(--border)':'1px solid var(--border)',background:m.reserve?'rgba(234,179,8,0.03)':m.weak?'rgba(255,255,255,0.02)':'rgba(234,179,8,0.06)',textAlign:'center',opacity:(m.weak||m.reserve)?0.8:1}}><div style={{fontWeight:900,fontSize:'0.95rem',color:'#eab308'}}>{String(m.num).padStart(2,'0')} {(m.horse||'').slice(0,11)} {m.reserve?'· RÉSERVE':`→ P${m.target_pos}`}{m.weak?' (faible)':''}</div>{j && <div style={{fontSize:'0.66rem',color:'var(--text-muted)'}}>{j}</div>}<div style={{fontSize:'0.86rem',color:'var(--text-primary)',marginTop:2}}>{m.cote} · {m.layer}{m.target_layer?` → ${m.target_layer}`:''} · <b>{m.score}</b></div></div>})}</div></div>}
    </div>
  )
}
