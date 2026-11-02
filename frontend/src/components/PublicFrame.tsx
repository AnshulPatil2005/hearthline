import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { Dateline, Wordmark } from './Shell'
import { Footer } from './Footer'

/** Pages anyone can open without signing in (registries, Reopen Funds, gift cards). */
export function PublicFrame({ children, wide = false }: { children: ReactNode; wide?: boolean }) {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-svh flex-col">
      <header>
        <Dateline wide={wide} />
        <div className="border-b border-ink bg-paper">
          <div
            className={`mx-auto flex w-full ${wide ? 'max-w-7xl' : 'max-w-5xl'} items-center justify-between gap-4 px-4 py-2.5`}
          >
            <Wordmark />
            <span className="flex items-center gap-4">
              <Link to="/price-watch" className="text-sm text-ink-soft hover:text-ink">
                {t('nav.priceWatch')}
              </Link>
            </span>
          </div>
        </div>
      </header>
      <main className={`mx-auto w-full ${wide ? 'max-w-7xl' : 'max-w-5xl'} flex-1 px-4 py-8`}>{children}</main>
      <Footer />
    </div>
  )
}

export function Progress({ funded, target }: { funded: number; target: number }) {
  const { t } = useTranslation()
  const pct = target > 0 ? Math.min(100, (funded / target) * 100) : 0
  return (
    <div
      className="h-1.5 overflow-hidden bg-sunken"
      role="progressbar"
      aria-label={t('a11y.progress', { pct: Math.round(pct) })}
      aria-valuenow={Math.round(pct)}
      aria-valuemin={0}
      aria-valuemax={100}
    >
      <div className={`h-full ${pct >= 100 ? 'bg-sage' : 'bg-ember'}`} style={{ width: `${pct}%` }} />
    </div>
  )
}
