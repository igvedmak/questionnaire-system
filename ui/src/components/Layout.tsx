import { NavLink, Outlet, useLocation } from 'react-router-dom'

export default function Layout() {
  const loc = useLocation()
  const isFill = loc.pathname.startsWith('/fill/')

  return (
    <div className="min-h-screen flex flex-col bg-slate-50">
      <header className="bg-slate-900 shadow-lg sticky top-0 z-40">
        <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div className="w-7 h-7 bg-indigo-500 rounded-lg flex items-center justify-center">
              <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2m-6 9l2 2 4-4" />
              </svg>
            </div>
            <span className="text-white font-semibold text-sm tracking-tight">Questionnaire Engine</span>
          </div>

          {!isFill && (
            <nav className="flex items-center gap-1">
              {[
                { to: '/', label: 'Templates' },
                { to: '/responses', label: 'Responses' },
              ].map(({ to, label }) => (
                <NavLink
                  key={to}
                  to={to}
                  end={to === '/'}
                  className={({ isActive }) =>
                    `px-3 py-1.5 rounded-md text-sm font-medium transition-colors ${
                      isActive
                        ? 'bg-indigo-600 text-white'
                        : 'text-slate-300 hover:text-white hover:bg-slate-700'
                    }`
                  }
                >
                  {label}
                </NavLink>
              ))}
            </nav>
          )}
        </div>
      </header>

      <main className="flex-1">
        <Outlet />
      </main>

      <footer className="border-t border-slate-200 bg-white mt-8">
        <div className="max-w-6xl mx-auto px-4 py-4 text-xs text-slate-400 text-center">
          Questionnaire Engine v0.3 · 8 question types · AI-powered
        </div>
      </footer>
    </div>
  )
}
