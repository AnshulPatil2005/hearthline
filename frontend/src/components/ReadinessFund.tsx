import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type ReadinessMine, type ReadinessStart } from '../api'
import { money, parseTime } from '../format'

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback)

/** A monthly gift to the readiness fund through PayPal Subscriptions: cash that's there before the next disaster. */
export function ReadinessFund() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const data = useQuery({ queryKey: ['readiness'], queryFn: () => api<ReadinessMine>('/donors/me/readiness') })
  const [monthly, setMonthly] = useState<string | null>(null)
  const start = useMutation({
    mutationFn: (amount: string) =>
      api<ReadinessStart>('/donors/me/readiness', { method: 'POST', body: JSON.stringify({ monthly: amount }) }),
    onSuccess: (r) => {
      if (r.approval_url) window.location.assign(r.approval_url)
    },
  })
  const stop = useMutation({
    mutationFn: (id: number) => api<ReadinessMine>(`/donors/me/readiness/${id}/stop`, { method: 'POST' }),
    onSuccess: (r) => queryClient.setQueryData(['readiness'], r),
  })
  const d = data.data
  if (!d) return null
  const pool = d.pool
  const mine = d.mine
  const chosen = monthly ?? pool.tiers[1] ?? pool.tiers[0]
  return (
    <section aria-labelledby="readiness-title" className="panel p-5">
      <h2 id="readiness-title" className="text-lg font-semibold">
        {t('readiness.title')}
      </h2>
      <p className="mt-1 max-w-3xl text-sm text-ink-soft">{t('readiness.intro')}</p>
      <dl className="mt-4 grid gap-3 sm:grid-cols-3">
        <div className="rounded-lg border border-line bg-surface px-4 py-3">
          <dt className="kicker text-ink-faint">{t('readiness.ready')}</dt>
          <dd className="figure mt-0.5 text-2xl font-semibold">{money(pool.balance)}</dd>
        </div>
        <div className="rounded-lg border border-line bg-surface px-4 py-3">
          <dt className="kicker text-ink-faint">{t('readiness.givers')}</dt>
          <dd className="figure mt-0.5 text-2xl font-semibold">
            {pool.givers.toLocaleString(i18n.resolvedLanguage)}
            <span className="ml-1.5 font-sans text-sm font-normal text-ink-soft">
              {t('readiness.perMonth', { amount: money(pool.monthly) })}
            </span>
          </dd>
        </div>
        <div className="rounded-lg border border-line bg-surface px-4 py-3">
          <dt className="kicker text-ink-faint">{t('readiness.released')}</dt>
          <dd className="figure mt-0.5 text-2xl font-semibold">{money(pool.released)}</dd>
        </div>
      </dl>

      {mine ? (
        <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line px-4 py-3">
          <div>
            <p className="font-medium">
              {mine.status === 'active'
                ? t('readiness.mineActive', { amount: money(mine.monthly) })
                : t('readiness.minePending', { amount: money(mine.monthly) })}
            </p>
            <p className="text-sm text-ink-soft">
              {t('readiness.mineSince', {
                date: parseTime(mine.activated_at ?? mine.created_at).toLocaleDateString(i18n.resolvedLanguage, {
                  dateStyle: 'medium',
                }),
                given: money(mine.given, { cents: true }),
              })}
            </p>
          </div>
          <button
            onClick={() => stop.mutate(mine.id)}
            disabled={stop.isPending}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-ink-soft hover:bg-sunken disabled:opacity-40"
          >
            {t('readiness.stop')}
          </button>
        </div>
      ) : (
        <div className="mt-4 flex flex-wrap items-center gap-2">
          <span id="readiness-amount" className="text-sm font-medium">
            {t('readiness.choose')}
          </span>
          <div role="radiogroup" aria-labelledby="readiness-amount" className="flex gap-1">
            {pool.tiers.map((tier) => (
              <button
                key={tier}
                role="radio"
                aria-checked={chosen === tier}
                onClick={() => setMonthly(tier)}
                className={`rounded-lg border px-3 py-1.5 text-sm ${
                  chosen === tier ? 'border-ember bg-ember-soft font-medium text-ember' : 'border-line hover:bg-sunken'
                }`}
              >
                {t('readiness.tier', { amount: money(tier) })}
              </button>
            ))}
          </div>
          <button
            onClick={() => start.mutate(chosen)}
            disabled={start.isPending}
            className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
          >
            {start.isPending ? t('readiness.opening') : t('readiness.give')}
          </button>
          <span className="text-xs text-ink-faint">{t('readiness.how')}</span>
        </div>
      )}
      {(start.isError || stop.isError) && (
        <p className="mt-2 text-sm text-danger">{errorText(start.error ?? stop.error, t('errors.generic'))}</p>
      )}
    </section>
  )
}
