import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { LanguageSelect, Logo } from './Shell'
import { Footer } from './Footer'

/** Pages anyone can open without signing in (registries, Reopen Funds, gift cards). */
export function PublicFrame({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-svh flex-col">
      <header className="border-b border-line bg-surface">
        <div className={`mx-auto flex w-full ${wide ? 'max-w-7xl' : 'max-w-5xl'} items-center justify-between gap-4 px-4 py-3`}>
          <span className="flex items-center gap-2 font-semibold">
            <Logo />
            Hearthline
          </span>
          <span className="flex items-center gap-4">
            <Link to="/price-watch" className="text-sm text-ink-soft hover:text-ink">
              {t('nav.priceWatch')}
            </Link>
            <LanguageSelect />
          </span>
        </div>
      </header>
      <main className={`mx-auto w-full ${wide ? 'max-w-7xl' : 'max-w-5xl'} flex-1 px-4 py-8`}>{children}</main>
      <Footer />
    </div>
  )
}

export function Progress({ funded, target }: { funded: number; target: number }) {
  const pct = target > 0 ? Math.min(100, (funded / target) * 100) : 0
  return (
    <div
      className="h-2 overflow-hidden rounded-full bg-sunken"
      role="progressbar"
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className={`h-full rounded-full ${pct >= 100 ? 'bg-sage' : 'bg-ember'}`} style={{ width: `${pct}%` }} />
    </div>
  )
}
