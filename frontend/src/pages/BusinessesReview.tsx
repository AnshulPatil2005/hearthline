import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, ApiError, type StaffBusiness, type Tranche } from '../api'
import { Progress } from '../components/PublicFrame'
import { money } from '../format'

const TONE: Record<StaffBusiness['verification'], string> = {
  pending: 'bg-amber-soft text-amber',
  verified: 'bg-sage-soft text-sage',
  rejected: 'bg-danger-soft text-danger',
}

function Decide({
  label,
  onDecide,
  busy,
}: {
  label: string
  onDecide: (approve: boolean, note: string) => void
  busy: boolean // a decision is on its way: a second click could send a payout request twice
}) {
  const { t } = useTranslation()
  const [note, setNote] = useState('')
  return (
    <div className="mt-3 flex flex-wrap items-center gap-2">
      <input
        value={note}
        onChange={(e) => setNote(e.target.value)}
        placeholder={t('businesses.notePlaceholder')}
        aria-label={t('businesses.note')}
        className="min-w-56 flex-1 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm"
      />
      <button
        onClick={() => onDecide(true, note)}
        disabled={busy}
        className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-50"
      >
        {label}
      </button>
      <button
        onClick={() => onDecide(false, note)}
        disabled={busy}
        className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken disabled:opacity-50"
      >
        {t('businesses.reject')}
      </button>
    </div>
  )
}

/** Staff side of the Reopen Fund: verify businesses, release the money they ask for, and run the deadline check. */
export default function BusinessesReview() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const list = useQuery({ queryKey: ['staff-businesses'], queryFn: () => api<StaffBusiness[]>('/command/businesses') })
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const done = () => {
    setError(null)
    void queryClient.invalidateQueries({ queryKey: ['staff-businesses'] })
  }
  const onError = (e: Error) => setError(e instanceof ApiError ? e.message : t('errors.generic'))
  const verify = useMutation({
    mutationFn: ({ id, approve, note }: { id: number; approve: boolean; note: string }) =>
      api(`/command/businesses/${id}/verify`, { method: 'POST', body: JSON.stringify({ approve, note }) }),
    onSuccess: done,
    onError,
  })
  const decide = useMutation({
    mutationFn: ({ id, approve, note }: { id: number; approve: boolean; note: string }) =>
      api<Tranche>(`/command/tranches/${id}/decide`, { method: 'POST', body: JSON.stringify({ approve, note }) }),
    onSuccess: done,
    onError,
  })
  const deadlines = useMutation({
    mutationFn: () => api<{ refunded_campaigns: number[] }>('/command/reopen/deadlines', { method: 'POST' }),
    onSuccess: (r) => {
      setNotice(t('businesses.deadlineResult', { count: r.refunded_campaigns.length }))
      done()
    },
    onError,
  })

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end justify-between gap-3">
        <div>
          <h1 className="text-4xl leading-tight tracking-tight text-balance">{t('businesses.title')}</h1>
          <p className="mt-1 text-ink-soft">{t('businesses.subtitle')}</p>
        </div>
        <button
          onClick={() => deadlines.mutate()}
          disabled={deadlines.isPending}
          className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken"
        >
          {t('businesses.runDeadlines')}
        </button>
      </div>
      {notice && <p className="text-sm text-ink-soft">{notice}</p>}
      {error && <p className="text-sm text-danger">{error}</p>}
      <ul className="space-y-4">
        {list.data?.map((b) => {
          const c = b.campaign
          const requested = c?.tranches.filter((s) => s.status === 'requested') ?? []
          return (
            <li key={b.id} className="panel p-5">
              <div className="flex flex-wrap items-start justify-between gap-3">
                <div>
                  <h2 className="text-lg font-semibold">{b.name}</h2>
                  <p className="text-sm text-ink-soft">
                    {b.owner_name} · {b.address} · {t('businesses.license', { number: b.license_number })}
                  </p>
                </div>
                <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE[b.verification]}`}>
                  {t(`businesses.verification.${b.verification}`)}
                </span>
              </div>
              {b.verification === 'pending' && (
                <>
                  <p className="mt-3 text-sm">{t('businesses.checkList')}</p>
                  <Decide
                    label={t('businesses.verify')}
                    onDecide={(approve, note) => verify.mutate({ id: b.id, approve, note })}
                    busy={verify.isPending}
                  />
                </>
              )}
              {c && (
                <div className="mt-4">
                  <Progress funded={Number(c.raised)} target={Number(c.goal_amount)} />
                  <p className="mt-2 text-sm text-ink-soft">
                    {t(`businesses.campaign.${c.status}`)} · {money(c.raised)} / {money(c.goal_amount)} ·{' '}
                    {t('businesses.inEscrow', { amount: money(c.escrow) })} ·{' '}
                    {t('reopen.reopensBy', {
                      date: new Date(c.reopen_by).toLocaleDateString(i18n.resolvedLanguage, {
                        month: 'short',
                        day: 'numeric',
                      }),
                    })}{' '}
                    ·{' '}
                    <Link to={`/reopen/${b.slug}`} target="_blank" className="text-ember hover:underline">
                      {t('businesses.publicPage')} ↗
                    </Link>
                  </p>
                </div>
              )}
              {requested.map((s) => (
                <div key={s.id} className="mt-4 rounded-lg bg-amber-soft p-4">
                  <p className="font-medium">{t('businesses.asks', { title: s.title, amount: money(s.amount) })}</p>
                  {s.request_note && <p className="mt-1 text-sm">“{s.request_note}”</p>}
                  <Decide
                    label={t('businesses.release', { amount: money(s.amount) })}
                    onDecide={(approve, note) => decide.mutate({ id: s.id, approve, note })}
                    busy={decide.isPending}
                  />
                </div>
              ))}
            </li>
          )
        })}
      </ul>
    </div>
  )
}
