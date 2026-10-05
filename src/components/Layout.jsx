import { useState, useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import { fmtDate, TZ_LABEL } from '../lib/gmtTime'

const ALL_NAV = [
  { label: 'Programme', path: '/', owner: true, children: [
    { label: 'Programme', path: '/', owner: true },
    { label: 'Archives', path: '/archive', owner: true },
  ]},
  { label: 'Chevaux', path: '/horses', children: [
    { label: 'Chevaux', path: '/horses' },
    { label: 'Jockeys', path: '/jockeys' },
  ]},
  { label: 'DNA COURSE', path: '/dna-course', owner: true },
  { label: 'Synthèse', path: '/synthese' },
  { label: 'COUPLE', path: '/couple' },
  { label: 'FLIP', path: '/flip' },
            { label: 'TROT', path: '/trot' },
  { label: 'GALOP', path: '/galop' },
  { label: 'SUIVI', path: '/suivi', owner: true },
]

const LOGO = 'data:image/svg+xml,' + encodeURIComponent('<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 32 32"><rect width="32" height="32" rx="8" fill="#ef4444"/><text x="16" y="22" text-anchor="middle" fill="#fff" font-size="18" font-weight="800" font-family="Inter,sans-serif">B</text></svg>')

export default function Layout({ children }) {
  const navigate = useNavigate()
  const location = useLocation()
  const _ph = localStorage.getItem('bahja-phone')
  const isOwner = _ph === '0000000000' || _ph === 'admin'
  const NAV_ITEMS = ALL_NAV.filter(i => !i.owner || isOwner)
  const [openMenu, setOpenMenu] = useState(null)
  useEffect(() => { setOpenMenu(null) }, [location.pathname])
  const isActivePath = (path) => path === '/'
    ? location.pathname === '/'
    : location.pathname.startsWith(path)
  const btnStyle = (active, accent) => ({
    padding: '6px 14px',
    borderRadius: 6,
    border: active && accent ? `1px solid ${accent}` : '1px solid transparent',
    background: active ? (accent ? accent + '22' : 'rgba(255,255,255,0.1)') : 'transparent',
    color: active ? (accent || '#fff') : 'rgba(255,255,255,0.6)',
    fontWeight: active ? 700 : 450,
    fontSize: 13,
    cursor: 'pointer',
    transition: 'all 0.15s',
    whiteSpace: 'nowrap',
  })

  return (
    <div style={{
      minHeight: '100vh',
      background: 'var(--bg)',
      fontFamily: 'var(--font)',
    }}>
      <header style={{
        background: '#0f172a',
        position: 'sticky',
        top: 0,
        zIndex: 100,
        borderBottom: '1px solid rgba(255,255,255,0.06)',
      }}>
        <div className="app-header-inner" style={{
          maxWidth: 1120,
          margin: '0 auto',
          padding: '0 20px',
          height: 56,
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'space-between',
        }}>
          <div className="app-header-left" style={{ display: 'flex', alignItems: 'center', gap: 32, minWidth: 0, flex: 1 }}>
            <button
              onClick={() => navigate('/')}
              style={{
                display: 'flex', alignItems: 'center', gap: 10,
                background: 'none', border: 'none', cursor: 'pointer', padding: 0,
              }}
            >
              <img src={LOGO} alt="" width={28} height={28} />
              <span style={{
                color: '#fff', fontWeight: 700, fontSize: 16, letterSpacing: '-0.3px',
              }}>Bahja</span>
            </button>
            <nav className="app-nav" style={{ display: 'flex', gap: 4, minWidth: 0, flex: 1, flexWrap: 'wrap', overflow: 'visible' }}>
              {NAV_ITEMS.map(item => {
                const kids = (item.children || []).filter(c => !c.owner || isOwner)
                const accent = { '/trot': '#22c55e', '/galop': '#a855f7', '/dna-course': '#4ade80', '/suivi': '#22c55e' }[item.path]
                if (!kids.length) {
                  const active = isActivePath(item.path)
                  return (
                    <button
                      key={item.path}
                      onClick={() => navigate(item.path)}
                      style={btnStyle(active, accent)}
                      onMouseEnter={e => { if (!active) e.currentTarget.style.color = '#fff' }}
                      onMouseLeave={e => { if (!active) e.currentTarget.style.color = 'rgba(255,255,255,0.6)' }}
                    >
                      {item.label}
                    </button>
                  )
                }
                const active = isActivePath(item.path) || kids.some(c => isActivePath(c.path))
                const open = openMenu === item.label
                return (
                  <div key={item.path} style={{ position: 'relative', flexShrink: 0 }}>
                    <button
                      onClick={() => setOpenMenu(open ? null : item.label)}
                      style={btnStyle(active, accent)}
                      onMouseEnter={e => { if (!active) e.currentTarget.style.color = '#fff' }}
                      onMouseLeave={e => { if (!active) e.currentTarget.style.color = 'rgba(255,255,255,0.6)' }}
                    >
                      {item.label} ▾
                    </button>
                    {open && (
                      <div style={{
                        position: 'absolute', top: 'calc(100% + 6px)', right: 0, minWidth: 150,
                        background: '#0f172a', border: '1px solid rgba(255,255,255,0.12)',
                        borderRadius: 8, padding: 4, zIndex: 200,
                        boxShadow: '0 8px 24px rgba(0,0,0,0.4)',
                      }}>
                        {kids.map(c => {
                          const ca = isActivePath(c.path)
                          return (
                            <button
                              key={c.path}
                              onClick={() => { navigate(c.path); setOpenMenu(null) }}
                              style={{
                                display: 'block', width: '100%', textAlign: 'right',
                                padding: '8px 12px', borderRadius: 6, border: 'none',
                                background: ca ? 'rgba(255,255,255,0.1)' : 'transparent',
                                color: ca ? '#fff' : 'rgba(255,255,255,0.7)',
                                fontWeight: ca ? 700 : 450, fontSize: 13, cursor: 'pointer',
                              }}
                            >
                              {c.label}
                            </button>
                          )
                        })}
                      </div>
                    )}
                  </div>
                )
              })}
            </nav>
          </div>
          <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
            {isOwner && (
            <button
              onClick={() => navigate('/admin-users')}
              title="Admin"
              style={{
                background: location.pathname.startsWith('/admin-users') ? 'rgba(239,68,68,0.2)' : 'rgba(255,255,255,0.08)',
                color: '#fff', border: location.pathname.startsWith('/admin-users') ? '1px solid #ef4444' : '1px solid rgba(255,255,255,0.15)',
                borderRadius: 6, padding: '4px 10px', fontSize: 12, fontWeight: 700, cursor: 'pointer'
              }}
            >Admin</button>
            )}
            {isOwner && (
            <button
              onClick={async () => {
                const p = prompt('كلمة السر الجديدة (4+ حروف):')
                if (!p) return
                if (p.length < 4) { alert('قصيرة — خاصها 4 حروف على الأقل'); return }
                const again = prompt('عاود كتبها مرة أخرى للتأكيد:')
                if (again !== p) { alert('ما تطابقوش — ما تبدلات والو'); return }
                try {
                  const { authChangePassword } = await import('../services/api')
                  await authChangePassword(p)
                  alert('✓ تبدلات كلمة السر - دخول من جديد')
                  localStorage.removeItem('bahja-token'); localStorage.removeItem('bahja-phone'); window.location.reload()
                } catch (e) { alert('خطأ: ' + e.message) }
              }}
              title="تبديل كلمة السر ديالك"
              style={{ background: 'rgba(255,255,255,0.08)', color: '#fff', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 6, padding: '4px 10px', fontSize: 12, fontWeight: 700, cursor: 'pointer' }}
            >🔑 كلمة السر</button>
            )}
            <button
              onClick={async () => {
                try { const { authServerLogout } = await import('../services/api'); await authServerLogout() } catch {}
                localStorage.removeItem('bahja-token'); localStorage.removeItem('bahja-phone'); window.location.reload()
              }}
              title="تسجيل الخروج"
              style={{ background: 'rgba(255,255,255,0.08)', color: '#fff', border: '1px solid rgba(255,255,255,0.15)', borderRadius: 6, padding: '4px 10px', fontSize: 12, cursor: 'pointer' }}
            >خروج</button>
          </div>
          <div className="app-date" style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{
              // the navbar is dark, so the date is the light tint: white at 30%
              // measured 2.70 on the navbar and could not be read
              color: 'rgba(255,255,255,0.72)', fontSize: 12, fontWeight: 400,
            }}>
              {fmtDate(Date.now())} {TZ_LABEL}
            </span>
          </div>
        </div>
      </header>
      <main style={{ maxWidth: 1120, margin: '0 auto', padding: '24px 20px' }}>
        {children}
      </main>
    </div>
  )
}
