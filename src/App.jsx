import { useState, useEffect } from 'react'
import { HashRouter, Routes, Route, Navigate } from 'react-router-dom'
import Layout from './components/Layout'
import Login from './pages/Login'
import AdminUsers from './pages/AdminUsers'
import { authMe, authLogout } from './services/api'

function OwnerOnly({ children }) {
  const phone = localStorage.getItem('bahja-phone');
  const token = localStorage.getItem('bahja-token');
  if (!token) return <Navigate to="/" replace />;
  if (!(phone === '0000000000' || phone === 'admin')) return <Navigate to="/trot" replace />;
  return children
}
import Programme from './pages/Programme'
import RaceDetails from './pages/RaceDetails'
import Archive from './pages/Archive'
import HorseSearch from './pages/HorseSearch'
import HorseDetail from './pages/HorseDetail'
import JockeySearch from './pages/JockeySearch'
import JockeyDetail from './pages/JockeyDetail'
import Analysis from './pages/Analysis'
import Synthese from './QUINTE/pages/SynthesePage'
import SyntheseEcarts from './QUINTE/pages/SyntheseEcartsPage'
import TrotPage from './TROT/pages/TrotPage'
import GalopPage from './GALOP/pages/GalopPage'
import CouplePage from './COUPLE/pages/CouplePage'
import FlipPage from './FLIP/pages/FlipPage'
import DnaCoursePage from './DNA_COURSE/pages/DnaCoursePage'
import Suivi from './SUIVI/Suivi'

export default function App() {
  const [authed, setAuthed] = useState(null)
  const isOwner = (localStorage.getItem('bahja-phone') === '0000000000' || localStorage.getItem('bahja-phone') === 'admin')

  useEffect(() => {
    // تحديث الصفحة = بقاء الدخول | إغلاق كامل = دخول من جديد
    const restarted = !sessionStorage.getItem('bahja-alive');
    sessionStorage.setItem('bahja-alive', '1');
    if (restarted) {
      authLogout()
      setAuthed(false)
    } else if (!localStorage.getItem('bahja-token')) {
      setAuthed(false)
    } else {
      authMe().then(() => setAuthed(true)).catch((e) => {
        const m = String(e?.message || '')
        if (/401|403|Session|session|bloqu|موقف|انتهت|reconnectez|connectez|no session|no user/i.test(m)) {
          authLogout(); setAuthed(false)
        } else {
          setAuthed(true)
        }
      })
    }
    const check = () => {
      authMe().catch((e) => {
        const m = String(e?.message || '')
        // طرد فقط إلا الجلسة مرفوضة فعلاً (401/403) - ماشي مشكل شبكة
        if (/401|403|Session|session|bloqu|موقف|انتهت|reconnectez|connectez/i.test(m)) {
          authLogout(); setAuthed(false)
        }
      })
    }
    const t = setInterval(check, 60000)
    const vis = () => { if (!document.hidden) check() }
    window.addEventListener('focus', check)
    document.addEventListener('visibilitychange', vis)
    check()
    return () => { clearInterval(t); window.removeEventListener('focus', check); document.removeEventListener('visibilitychange', vis) }
  }, [])

  if (authed === null) return <div style={{padding:40,textAlign:'center'}}>Chargement...</div>

  return (
    <HashRouter>
      <Routes>
        <Route path="/admin-users" element={<OwnerOnly><AdminUsers /></OwnerOnly>} />
        <Route path="*" element={authed ? (
          <Routes>
            <Route path="/" element={localStorage.getItem('bahja-phone') === '0000000000' || localStorage.getItem('bahja-phone') === 'admin' ? <OwnerOnly><Layout><Programme /></Layout></OwnerOnly> : <Navigate to="/trot" replace />} />
            <Route path="/race/:raceId" element={<Layout><RaceDetails /></Layout>} />
            <Route path="/archive" element={<OwnerOnly><Layout><Archive /></Layout></OwnerOnly>} />
            <Route path="/horses" element={<Layout><HorseSearch /></Layout>} />
            <Route path="/horse/:horseName" element={<Layout><HorseDetail /></Layout>} />
            <Route path="/jockeys" element={<Layout><JockeySearch /></Layout>} />
            <Route path="/jockey/:jockeyName" element={<Layout><JockeyDetail /></Layout>} />
            <Route path="/analysis/:raceId" element={<Layout><Analysis /></Layout>} />
            <Route path="/synthese" element={<Layout><Synthese /></Layout>} />
            <Route path="/synthese-ecarts" element={<Layout><SyntheseEcarts /></Layout>} />
            <Route path="/trot" element={<Layout><TrotPage /></Layout>} />
            <Route path="/galop" element={<Layout><GalopPage /></Layout>} />
            <Route path="/couple" element={<Layout><CouplePage /></Layout>} />
            <Route path="/flip" element={<Layout><FlipPage /></Layout>} />
            <Route path="/dna-course" element={<Layout><DnaCoursePage /></Layout>} />
            <Route path="/suivi" element={<OwnerOnly><Layout><Suivi /></Layout></OwnerOnly>} />
          </Routes>
        ) : <Login onOk={() => setAuthed(true)} />} />
      </Routes>
    </HashRouter>
  )
}
