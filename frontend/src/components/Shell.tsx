import { Suspense, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, NavLink, useNavigate } from 'react-router'
import { useAuth } from '../auth'
import { LANGUAGES } from '../i18n'
import { STAFF_ROLES } from '../paths'
import { Footer } from './Footer'

export function Logo({ className = 'size-7' }: { className?: string }) {
  return (
    <svg viewBox="0 0 32 32" className={className} aria-hidden="true">
      <path
        fill="#7c4a2d"
        d="M16 3 2.5 14.2a1.4 1.4 0 0 0 1.8 2.2L6 15v12.5A1.5 1.5 0 0 0 7.5 29h17a1.5 1.5 0 0 0 1.5-1.5V15l1.7 1.4a1.4 1.4 0 0 0 1.8-2.2z"
      />
      <path
        fill="#e8590c"
        d="M16 13c.9 2.8-1.7 4.2-1.7 6.8 0 1.2.7 2 1.7 2s1.7-.9 1.7-2c1.7 1.1 2.8 2.9 2.8 4.8 0 2.6-2 4.4-4.5 4.4s-4.5-1.8-4.5-4.4c0-2.6 1.7-4.1 2.6-6 1.1-2 1.4-3.9 1.9-5.6z"
      />
      <path
        fill="#ffd43b"
        d="M16 29.5c-1.5 0-2.6-1-2.6-2.5 0-1.5 1.1-2.3 1.8-3.6.3.9.9 1.3 1.6 1.3.6-.5.8-1.1.8-1.9.7.9.9 2 .9 3 0 1.7-1.1 2.7-2.5 2.7z"
      />
    </svg>
  )
}

export function LanguageSelect() {
  const { t, i18n } = useTranslation()
  return (
    <label className="flex items-center gap-2 text-sm text-ink-soft">
      <span className="sr-only">{t('nav.language')}</span>
      <svg
        viewBox="0 0 24 24"
        className="size-4"
        fill="none"
        stroke="currentColor"
        strokeWidth="1.8"
        aria-hidden="true"
      >
        <circle cx="12" cy="12" r="9" />
        <path d="M3 12h18M12 3c2.5 2.7 3.8 5.7 3.8 9s-1.3 6.3-3.8 9c-2.5-2.7-3.8-5.7-3.8-9S9.5 5.7 12 3z" />
      </svg>
      <select
        value={i18n.resolvedLanguage}
        onChange={(e) => void i18n.changeLanguage(e.target.value)}
        className="rounded-md border border-line bg-surface px-2 py-1 text-ink"
      >
        {LANGUAGES.map((l) => (
          <option key={l.code} value={l.code}>
            {l.label}
          </option>
        ))}
      </select>
    </label>
  )
}

// On phones the links get their own full-width row that scrolls sideways, so the page itself never does.
const navRow =
  'order-last -mx-1 flex w-full gap-1 overflow-x-auto px-1 [scrollbar-width:none] lg:order-none lg:mx-0 lg:w-auto lg:overflow-visible lg:px-0'
const navClass = ({ isActive }: { isActive: boolean }) =>
  `shrink-0 whitespace-nowrap rounded-md px-3 py-1.5 text-sm font-medium ${isActive ? 'bg-sunken text-ink' : 'text-ink-soft hover:text-ink'}`

export function Shell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const { t } = useTranslation()
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="flex min-h-svh flex-col">
      <header className="border-b border-line bg-surface">
        <div
          className={`mx-auto flex ${wide ? 'max-w-7xl' : 'max-w-6xl'} flex-wrap items-center gap-x-6 gap-y-2 px-4 py-3`}
        >
          <Link to="/" className="flex items-center gap-2 font-semibold text-ink">
            <Logo />
            Hearthline
          </Link>
          {user?.role === 'household' && (
            <nav className={navRow}>
              <NavLink to="/home" className={navClass}>
                {t('nav.home')}
              </NavLink>
              <NavLink to="/inventory" className={navClass}>
                {t('nav.inventory')}
              </NavLink>
              <NavLink to="/registry" className={navClass}>
                {t('nav.registry')}
              </NavLink>
              <NavLink to="/insurance" className={navClass}>
                {t('nav.insurance')}
              </NavLink>
              <NavLink to="/rebuild" className={navClass}>
                {t('nav.rebuild')}
              </NavLink>
              <NavLink to="/money" className={navClass}>
                {t('nav.money')}
              </NavLink>
              <NavLink to="/aid" className={navClass}>
                {t('nav.aid')}
              </NavLink>
            </nav>
          )}
          {user?.role === 'donor' && (
            <nav className={navRow}>
              <NavLink to="/giving" className={navClass}>
                {t('nav.giving')}
              </NavLink>
              <NavLink to="/price-watch" className={navClass}>
                {t('nav.priceWatch')}
              </NavLink>
            </nav>
          )}
          {user?.role === 'business' && (
            <nav className={navRow}>
              <NavLink to="/business" className={navClass}>
                {t('nav.reopenFund')}
              </NavLink>
            </nav>
          )}
          {user?.role === 'contractor' && (
            <nav className={navRow}>
              <NavLink to="/contractor" className={navClass}>
                {t('nav.projects')}
              </NavLink>
            </nav>
          )}
          {user && STAFF_ROLES.includes(user.role) && (
            <nav className={navRow}>
              {(user.role === 'org_admin' || user.role === 'supervisor') && (
                <>
                  <NavLink to="/command" end className={navClass}>
                    {t('nav.command')}
                  </NavLink>
                  <NavLink to="/command/crews" className={navClass}>
                    {t('nav.crews')}
                  </NavLink>
                  <NavLink to="/command/businesses" className={navClass}>
                    {t('nav.businesses')}
                  </NavLink>
                  <NavLink to="/command/disputes" className={navClass}>
                    {t('nav.disputes')}
                  </NavLink>
                  <NavLink to="/command/books" className={navClass}>
                    {t('nav.books')}
                  </NavLink>
                  <NavLink to="/price-watch" className={navClass}>
                    {t('nav.priceWatch')}
                  </NavLink>
                </>
              )}
              <NavLink to="/review" end className={navClass}>
                {t('nav.review')}
              </NavLink>
              <NavLink to="/review/calendar" className={navClass}>
                {t('nav.calendar')}
              </NavLink>
              <NavLink to="/review/board" className={navClass}>
                {t('nav.board')}
              </NavLink>
            </nav>
          )}
          <div className="ml-auto flex items-center gap-4">
            <LanguageSelect />
            {user && (
              <div className="flex items-center gap-3">
                <div className="hidden text-right sm:block">
                  <div className="text-sm font-medium leading-tight">{user.name}</div>
                  <div className="text-xs text-ink-faint">{t(`roles.${user.role}`)}</div>
                </div>
                <button
                  onClick={() => {
                    signOut()
                    navigate('/login')
                  }}
                  className="rounded-md border border-line px-3 py-1.5 text-sm text-ink-soft hover:bg-sunken hover:text-ink"
                >
                  {t('nav.switchPersona')}
                </button>
              </div>
            )}
          </div>
        </div>
      </header>
      <main className={`mx-auto w-full ${wide ? 'max-w-7xl' : 'max-w-6xl'} flex-1 px-4 py-8`}>
        <Suspense fallback={<div className="h-96 animate-pulse rounded-xl bg-sunken" />}>{children}</Suspense>
      </main>
      <Footer />
    </div>
  )
}
