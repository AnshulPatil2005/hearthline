import { useQuery } from '@tanstack/react-query'
import type { ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, type Household, type InventorySummary } from '../api'
import { useAuth } from '../auth'
import AlertBanner, { SimulateAlertButton } from '../components/AlertBanner'
import { RecoveryNavigator } from '../components/RecoveryNavigator'
import type { Call } from '../components/VideoCalls'
import { money } from '../format'

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="panel p-5">
      <h2 className="kicker text-ink-faint">{title}</h2>
      <div className="mt-4">{children}</div>
    </section>
  )
}

function DisasterBanner({ home }: { home: Household }) {
  const { t } = useTranslation()
  if (!home.in_disaster_zone || !home.disaster_event) {
    return (
      <p className="border-l-4 border-line bg-sunken px-4 py-3 text-ink-soft">
        {t('home.notInZone')} {t('home.prepareHint')}
      </p>
    )
  }
  return (
    <p className="flex items-start gap-3 border-l-4 border-ember bg-ember-soft px-4 py-3 text-ink">
      <svg viewBox="0 0 24 24" className="mt-0.5 size-5 shrink-0 text-ember" fill="currentColor" aria-hidden="true">
        <path d="M12 2c.8 3.4-2.3 5.2-2.3 8.4 0 1.6 1 2.6 2.3 2.6s2.2-1.1 2.2-2.6c2.3 1.4 3.8 3.9 3.8 6.4C18 20.4 15.3 23 12 23s-6-2.6-6-6.2c0-3.5 2.3-5.6 3.5-8C10.9 6 11.4 3.9 12 2z" />
      </svg>
      <span>{t('home.inZone', { address: home.address_line, event: home.disaster_event.name })}</span>
    </p>
  )
}

function Coverage({ summary }: { summary: InventorySummary }) {
  const { t } = useTranslation()
  const total = Number(summary.total_value)
  const insured = summary.insured_contents_value === null ? null : Number(summary.insured_contents_value)
  const covered = insured === null || total === 0 ? 1 : Math.min(insured / total, 1)
  const gap = Number(summary.coverage_gap ?? 0)

  return (
    <Card title={t('coverage.title')}>
      <dl className="grid grid-cols-2 gap-4">
        <div>
          <dt className="text-sm text-ink-soft">{t('coverage.inventoryValue')}</dt>
          <dd className="figure text-3xl font-semibold">{money(total)}</dd>
        </div>
        <div>
          <dt className="text-sm text-ink-soft">{t('coverage.insured')}</dt>
          <dd className="figure text-3xl font-semibold">{money(insured)}</dd>
        </div>
      </dl>
      <div className="mt-4 h-1.5 overflow-hidden bg-sunken" aria-hidden="true">
        <div className={`h-full ${gap > 0 ? 'bg-amber' : 'bg-sage'}`} style={{ width: `${covered * 100}%` }} />
      </div>
      <p className={`mt-3 text-sm font-medium ${gap > 0 ? 'text-amber' : 'text-sage'}`}>
        {insured === null
          ? t('coverage.noPolicy')
          : gap > 0
            ? t('coverage.gap', { amount: money(gap) })
            : t('coverage.ok')}
      </p>
      <p className="mt-1 text-xs text-ink-faint">
        {t('coverage.counts', { count: summary.item_count, confirmed: summary.confirmed_count })}
      </p>
    </Card>
  )
}

function Rooms({ summary }: { summary: InventorySummary }) {
  const { t } = useTranslation()
  return (
    <Card title={t('rooms.title')}>
      {summary.by_room.length === 0 ? (
        <p className="text-ink-soft">{t('rooms.empty')}</p>
      ) : (
        <ul className="divide-y divide-line">
          {summary.by_room.map((r) => (
            <li key={r.room_id ?? 'none'} className="flex items-baseline justify-between py-2.5">
              <span>
                <span className="font-medium">{r.room_name}</span>
                <span className="ml-2 text-sm text-ink-faint">{t('rooms.items', { count: r.item_count })}</span>
              </span>
              <span className="font-mono text-sm">{money(r.total_value)}</span>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4 flex flex-wrap gap-2">
        <Link
          to="/inventory"
          className="rounded-lg bg-ember px-4 py-2 text-sm font-medium text-on-ember hover:opacity-90"
        >
          {t('actions.scanRoom')}
        </Link>
        {summary.item_count > 0 && (
          <Link to="/inventory" className="rounded-lg border border-line px-4 py-2 text-sm font-medium hover:bg-sunken">
            {t('actions.openInventory')}
          </Link>
        )}
      </div>
    </Card>
  )
}

export default function HouseholdHome() {
  const { t, i18n } = useTranslation()
  const { user } = useAuth()
  const home = useQuery({ queryKey: ['household'], queryFn: () => api<Household>('/households/me') })
  const calls = useQuery({ queryKey: ['my-calls'], queryFn: () => api<Call[]>('/households/me/appointments') })
  const summary = useQuery({
    queryKey: ['inventory-summary'],
    queryFn: () => api<InventorySummary>('/households/me/inventory-summary'),
  })

  if (home.isError || summary.isError) {
    return (
      <p role="alert" className="rounded-lg bg-danger-soft px-4 py-3 text-danger">
        {t('errors.generic')}
      </p>
    )
  }
  if (!home.data || !summary.data) return <div className="h-64 animate-pulse rounded-xl bg-sunken" />

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-4xl leading-tight tracking-tight text-balance">
          {t('home.greeting', { name: user?.name.split(' ')[0] })}
        </h1>
        <p className="mt-1 text-ink-soft">
          {home.data.name} · {home.data.address_line}, {home.data.city}, {home.data.state}
        </p>
      </div>
      <AlertBanner summary={summary.data} />
      {calls.data?.[0] && (
        <p className="panel px-4 py-3">
          {t('home.upcomingCall', {
            name: calls.data[0].reviewer_name.split(' ')[0],
            when: new Date(calls.data[0].starts_at).toLocaleString(i18n.resolvedLanguage, {
              weekday: 'long',
              month: 'short',
              day: 'numeric',
              hour: 'numeric',
              minute: '2-digit',
            }),
          })}
        </p>
      )}
      <DisasterBanner home={home.data} />
      <RecoveryNavigator />
      <div className="grid gap-6 lg:grid-cols-2">
        <Coverage summary={summary.data} />
        <Rooms summary={summary.data} />
      </div>
      <div className="flex justify-end">
        <SimulateAlertButton />
      </div>
    </div>
  )
}
