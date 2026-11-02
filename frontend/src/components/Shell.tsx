import { Suspense, useState, type ReactNode } from 'react'
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

export function LanguageSelect({ tone = 'paper' }: { tone?: 'paper' | 'night' }) {
  const { t, i18n } = useTranslation()
  return (
    <label className={`flex items-center gap-2 text-sm ${tone === 'night' ? 'text-on-night' : 'text-ink-soft'}`}>
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
        className={
          tone === 'night'
            ? 'rounded-sm border border-on-night/30 bg-night px-1.5 py-0.5 font-mono text-xs text-on-night'
            : 'rounded-md border border-line bg-paper px-2 py-1 text-ink'
        }
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
  'order-last -mx-1 flex w-full gap-4 overflow-x-auto px-1 [scrollbar-width:none] lg:order-none lg:mx-0 lg:w-auto lg:self-stretch lg:overflow-visible lg:px-0'
// Sections of the report: the current one is underlined in the signal color, like a newspaper's section rail
const navClass = ({ isActive }: { isActive: boolean }) =>
  `-mb-px flex shrink-0 items-center whitespace-nowrap border-b-2 py-3 text-sm ${
    isActive
      ? 'border-ember font-semibold text-ink'
      : 'border-transparent text-ink-soft hover:border-line hover:text-ink'
  }`

/** The dateline above the masthead: today's date, and that this is a demo in the PayPal sandbox. */
export function Dateline({ wide = false }: { wide?: boolean }) {
  const { t, i18n } = useTranslation()
  const [today] = useState(() => new Date())
  return (
    <div className="bg-night text-on-night">
      <div
        className={`kicker mx-auto flex ${wide ? 'max-w-7xl' : 'max-w-6xl'} items-center justify-between gap-4 px-4 py-1`}
      >
        <span className="shrink-0">
          {today.toLocaleDateString(i18n.resolvedLanguage, {
            weekday: 'short',
            day: 'numeric',
            month: 'short',
            year: 'numeric',
          })}
        </span>
        <span className="hidden min-w-0 flex-1 truncate text-center opacity-80 md:block">{t('app.demoNotice')}</span>
        <LanguageSelect tone="night" />
      </div>
    </div>
  )
}

export function Wordmark({ size = 'md' }: { size?: 'md' | 'lg' }) {
  return (
    <span
      className={`flex items-center gap-2 font-serif font-semibold tracking-tight text-ink ${size === 'lg' ? 'text-4xl sm:text-5xl' : 'text-[1.35rem]'}`}
    >
      <Logo className={size === 'lg' ? 'size-11 sm:size-12' : 'size-7'} />
      Hearthline
    </span>
  )
}

export function Shell({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const { t } = useTranslation()
  const { user, signOut } = useAuth()
  const navigate = useNavigate()

  return (
    <div className="flex min-h-svh flex-col">
      <header>
        <Dateline wide={wide} />
        <div className="border-b border-ink bg-paper">
          <div
            className={`mx-auto flex ${wide ? 'max-w-7xl' : 'max-w-6xl'} flex-wrap items-center gap-x-8 px-4 pt-2 lg:pt-0`}
          >
            <Link to="/" className="py-2">
              <Wordmark />
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
                    <NavLink to="/command/disasters" className={navClass}>
                      {t('nav.disasters')}
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
            <div className="ml-auto flex items-center gap-4 py-2">
              {user && (
                <div className="flex items-center gap-3">
                  <div className="hidden text-right sm:block">
                    <div className="text-sm font-semibold leading-tight">{user.name}</div>
                    <div className="kicker text-ink-faint">{t(`roles.${user.role}`)}</div>
                  </div>
                  <button
                    onClick={() => {
                      signOut()
                      navigate('/login')
                    }}
                    className="rounded-md border border-ink/70 px-3 py-1.5 text-sm font-medium text-ink hover:bg-ink hover:text-paper"
                  >
                    {t('nav.switchPersona')}
                  </button>
                </div>
              )}
            </div>
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
