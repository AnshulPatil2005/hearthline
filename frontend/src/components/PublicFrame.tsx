import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { LanguageSelect, Logo } from './Shell'

/** Pages anyone can open without signing in (registries, Reopen Funds, gift cards). */
export function PublicFrame({ children }: { children: ReactNode }) {
  const { t } = useTranslation()
  return (
    <div className="flex min-h-svh flex-col">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex w-full max-w-5xl items-center justify-between px-4 py-3">
          <span className="flex items-center gap-2 font-semibold">
            <Logo />
            Hearthline
          </span>
          <LanguageSelect />
        </div>
      </header>
      <main className="mx-auto w-full max-w-5xl flex-1 px-4 py-8">{children}</main>
      <footer className="border-t border-line px-4 py-3 text-center text-xs text-ink-faint">{t('app.demoNotice')}</footer>
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
