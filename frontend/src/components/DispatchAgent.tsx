import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type DispatchPlan } from '../api'
import { parseTime } from '../format'

const SITE_TIME_ZONE = 'America/Los_Angeles'
const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback)

/** The dispatch agent: plans a day of crew visits from the coordinator's instructions; a person accepts each one. */
export function DispatchAgent({ onChanged }: { onChanged: () => void }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const [instructions, setInstructions] = useState('')
  const latest = useQuery({
    queryKey: ['dispatch-plan'],
    queryFn: () => api<DispatchPlan | null>('/command/dispatch/plan'),
  })
  const save = (p: DispatchPlan) => {
    queryClient.setQueryData(['dispatch-plan'], p)
    onChanged()
  }
  const plan = useMutation({
    mutationFn: () =>
      api<DispatchPlan>('/command/dispatch/plan', { method: 'POST', body: JSON.stringify({ instructions }) }),
    onSuccess: save,
  })
  const decide = useMutation({
    mutationFn: ({ id, action }: { id: number; action: 'accept' | 'reject' }) =>
      api<DispatchPlan>(`/command/dispatch/proposals/${id}/${action}`, { method: 'POST' }),
    onSuccess: save,
  })
  const acceptAll = useMutation({
    mutationFn: (id: number) => api<DispatchPlan>(`/command/dispatch/plans/${id}/accept-all`, { method: 'POST' }),
    onSuccess: save,
  })
  const p = latest.data
  const time = (s: string | null) =>
    s
      ? parseTime(s).toLocaleTimeString(i18n.resolvedLanguage, {
          hour: 'numeric',
          minute: '2-digit',
          timeZone: SITE_TIME_ZONE,
        })
      : ''
  const open = p?.proposals.filter((x) => x.status === 'proposed') ?? []
  const error = plan.error ?? decide.error ?? acceptAll.error
  return (
    <section aria-labelledby="dispatch-title" className="panel p-4">
      <div className="flex flex-wrap items-start gap-4">
        <div className="min-w-0 flex-1">
          <h2 id="dispatch-title" className="text-lg font-semibold">
            {t('dispatch.title')}
          </h2>
          <p className="mt-1 max-w-3xl text-sm text-ink-soft">{t('dispatch.intro')}</p>
        </div>
        <form
          className="flex w-full max-w-xl flex-col gap-2 sm:flex-row sm:items-start"
          onSubmit={(e) => {
            e.preventDefault()
            plan.mutate()
          }}
        >
          <label htmlFor="dispatch-instructions" className="sr-only">
            {t('dispatch.instructionsLabel')}
          </label>
          <textarea
            id="dispatch-instructions"
            rows={2}
            maxLength={500}
            value={instructions}
            onChange={(e) => setInstructions(e.target.value)}
            placeholder={t('dispatch.instructionsPlaceholder')}
            className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
          />
          <button
            type="submit"
            disabled={plan.isPending}
            className="shrink-0 rounded-lg bg-ember px-3 py-2 text-sm font-medium text-on-ember disabled:opacity-40"
          >
            {plan.isPending ? t('dispatch.planning') : t('dispatch.plan')}
          </button>
        </form>
      </div>

      <div aria-live="polite">
        {error && <p className="mt-2 text-sm text-danger">{errorText(error, t('errors.generic'))}</p>}
        {p && (
          <div className="mt-3 space-y-2">
            <div className="flex flex-wrap items-center justify-between gap-2 rounded-lg bg-sunken px-3 py-2">
              <p className="text-sm">
                <span className="font-medium">
                  {t('dispatch.planFor', {
                    date: parseTime(`${p.day}T12:00:00`).toLocaleDateString(i18n.resolvedLanguage, {
                      weekday: 'long',
                      month: 'short',
                      day: 'numeric',
                    }),
                  })}
                </span>{' '}
                {p.by_ai && p.summary /* without the AI, the note below says so in the reader's language */}
                <span className="ml-1 text-xs text-ink-faint">
                  {p.by_ai ? t('dispatch.byAi') : t('dispatch.byRules')}
                </span>
              </p>
              {open.length > 0 && (
                <button
                  onClick={() => acceptAll.mutate(p.id)}
                  disabled={acceptAll.isPending}
                  className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
                >
                  {t('dispatch.acceptAll', { count: open.length })}
                </button>
              )}
            </div>
            <ul className="max-h-56 divide-y divide-line overflow-auto rounded-lg border border-line">
              {p.proposals.map((x) => (
                <li key={x.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 px-3 py-2 text-sm">
                  <span className="w-16 shrink-0 tabular-nums text-ink-soft">{time(x.starts_at) || '—'}</span>
                  <span className="min-w-0 flex-1 basis-48">
                    <span className="font-medium">
                      {t(`crews.short.${x.kind}`, { defaultValue: x.job })} · {x.household}
                    </span>
                    {x.crew && <span className="text-ink-soft"> → {x.crew}</span>}
                    <span className="block text-xs text-ink-soft">{x.reason}</span>
                  </span>
                  {x.status === 'proposed' ? (
                    <span className="flex shrink-0 gap-1">
                      <button
                        onClick={() => decide.mutate({ id: x.id, action: 'accept' })}
                        className="rounded-lg border border-line px-2.5 py-1 text-xs font-medium hover:bg-sunken"
                      >
                        {t('dispatch.accept')}
                      </button>
                      <button
                        onClick={() => decide.mutate({ id: x.id, action: 'reject' })}
                        className="rounded-lg px-2.5 py-1 text-xs text-ink-soft hover:bg-sunken"
                      >
                        {t('dispatch.reject')}
                      </button>
                    </span>
                  ) : (
                    <span className="shrink-0 rounded-full bg-sunken px-2 py-0.5 text-xs">
                      {t(`dispatch.status.${x.status}`)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          </div>
        )}
      </div>
    </section>
  )
}
