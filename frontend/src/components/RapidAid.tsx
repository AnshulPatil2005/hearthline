import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type RapidAidBoard, type RapidAidTrigger } from '../api'
import { money, parseTime } from '../format'

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback)

const SOURCE_TONE: Record<RapidAidTrigger['source'], string> = {
  nws: 'bg-danger-soft text-danger',
  declaration: 'bg-danger-soft text-danger',
  simulated: 'bg-sunken text-ink-soft',
}

function TriggerCard({ tr, onBoard }: { tr: RapidAidTrigger; onBoard: (b: RapidAidBoard) => void }) {
  const { t, i18n } = useTranslation()
  const [dismissing, setDismissing] = useState(false)
  const [note, setNote] = useState('')
  const approve = useMutation({
    mutationFn: () => api<RapidAidBoard>(`/command/rapid-aid/${tr.id}/approve`, { method: 'POST' }),
    onSuccess: onBoard,
  })
  const dismiss = useMutation({
    mutationFn: () =>
      api<RapidAidBoard>(`/command/rapid-aid/${tr.id}/dismiss`, { method: 'POST', body: JSON.stringify({ note }) }),
    onSuccess: onBoard,
  })
  const when = (s: string) =>
    parseTime(s).toLocaleString(i18n.resolvedLanguage, { dateStyle: 'medium', timeStyle: 'short' })
  const leftOut = Object.entries(tr.left_out)
  const error = approve.error ?? dismiss.error
  return (
    <li className="space-y-3 py-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="font-medium">{tr.headline}</p>
          <p className="text-xs text-ink-faint">
            <span className={`mr-2 rounded-full px-2 py-0.5 font-medium ${SOURCE_TONE[tr.source]}`}>
              {t(`rapid.source.${tr.source}`)}
            </span>
            {tr.event} · {when(tr.issued_at)}
          </p>
        </div>
        <span className="rounded-full bg-sunken px-2.5 py-0.5 text-xs font-medium">
          {t(`rapid.status.${tr.status}`)}
        </span>
      </div>

      {tr.status === 'proposed' && (
        <p className="text-sm">
          {t('rapid.wouldPay', { count: tr.households, total: money(tr.total), n: tr.households.toLocaleString() })}
        </p>
      )}
      {tr.batch && (
        <p className="text-sm">
          {tr.batch.status === 'sent'
            ? t('rapid.paid', { count: tr.batch.households, total: money(tr.batch.total), n: tr.batch.households })
            : t('rapid.notSent', { error: tr.batch.error ?? '' })}
          {tr.batch.paypal_batch_id && (
            <span className="ml-2 text-xs text-ink-faint">
              {t('rapid.paypalBatch', { id: tr.batch.paypal_batch_id })}
            </span>
          )}
        </p>
      )}
      {tr.decided_by && tr.decided_at && (
        <p className="text-xs text-ink-faint">
          {t('rapid.decided', { name: tr.decided_by, when: when(tr.decided_at) })}
          {tr.note && ` · “${tr.note}”`}
        </p>
      )}

      {tr.held.length > 0 && (
        <div className="rounded-lg bg-amber-soft px-3 py-2 text-sm">
          <p className="font-medium">{t('rapid.held', { count: tr.held.length })}</p>
          <ul className="mt-1 space-y-0.5">
            {tr.held.map((h) => (
              <li key={h.household_id}>
                {h.name}: <span className="text-ink-soft">{h.reason}</span>
              </li>
            ))}
          </ul>
        </div>
      )}
      {leftOut.length > 0 && (
        <p className="text-xs text-ink-faint">
          {t('rapid.leftOut')}{' '}
          {leftOut
            .map(([reason, n]) => `${t(`rapid.reason.${reason}`, { defaultValue: reason })}: ${n.toLocaleString()}`)
            .join(' · ')}
        </p>
      )}

      {tr.status === 'proposed' && (
        <div className="flex flex-wrap items-center gap-2">
          <button
            onClick={() => approve.mutate()}
            disabled={approve.isPending || tr.households === 0}
            className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
          >
            {approve.isPending ? t('rapid.paying') : t('rapid.approve', { total: money(tr.total) })}
          </button>
          {dismissing ? (
            <span className="flex flex-wrap items-center gap-2">
              <input
                id={`rapid-note-${tr.id}`}
                value={note}
                onChange={(e) => setNote(e.target.value)}
                placeholder={t('rapid.dismissWhy')}
                aria-label={t('rapid.dismissWhy')}
                className="rounded-lg border border-line bg-surface px-3 py-1.5 text-sm"
              />
              <button
                onClick={() => dismiss.mutate()}
                disabled={note.trim().length < 3 || dismiss.isPending}
                className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken disabled:opacity-40"
              >
                {t('rapid.dismiss')}
              </button>
            </span>
          ) : (
            <button onClick={() => setDismissing(true)} className="text-sm text-ink-soft hover:underline">
              {t('rapid.dismiss')}
            </button>
          )}
          <span className="text-xs text-ink-faint">{t('rapid.oneApproval')}</span>
        </div>
      )}
      {error && <p className="text-sm text-danger">{errorText(error, t('errors.generic'))}</p>}
    </li>
  )
}

/** First-72-hours aid: an official warning for the zone, who prepared and would be paid, one person's approval. */
export function RapidAid({ onPaid }: { onPaid: () => void }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const board = useQuery({ queryKey: ['rapid-aid'], queryFn: () => api<RapidAidBoard>('/command/rapid-aid') })
  const save = (b: RapidAidBoard) => {
    queryClient.setQueryData(['rapid-aid'], b)
    onPaid()
  }
  const disaster = board.data?.disasters[0]
  const check = useMutation({
    mutationFn: (kind: 'check' | 'simulate') =>
      api<RapidAidBoard>(`/command/rapid-aid/${kind}`, {
        method: 'POST',
        body: JSON.stringify({ disaster_id: disaster?.id }),
      }),
    onSuccess: (b) => queryClient.setQueryData(['rapid-aid'], b),
  })
  const b = board.data
  if (!b || !disaster) return null
  return (
    <section aria-labelledby="rapid-title" className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="max-w-3xl">
          <h2 id="rapid-title" className="text-lg font-semibold">
            {t('rapid.title')}
          </h2>
          <p className="mt-1 text-sm text-ink-soft">
            {t('rapid.intro', {
              disaster: disaster.name,
              base: money(b.base),
              perPerson: money(b.per_person),
              cap: money(b.cap),
            })}
          </p>
        </div>
        <div className="flex flex-wrap gap-2">
          <button
            onClick={() => check.mutate('check')}
            disabled={check.isPending}
            className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken disabled:opacity-40"
          >
            {t('rapid.check')}
          </button>
          <button
            onClick={() => check.mutate('simulate')}
            disabled={check.isPending}
            className="rounded-lg border border-line px-3 py-1.5 text-sm text-ink-soft hover:bg-sunken disabled:opacity-40"
          >
            {t('rapid.simulate')}
          </button>
        </div>
      </div>
      <div aria-live="polite">
        {check.isError && <p className="mt-2 text-sm text-danger">{errorText(check.error, t('errors.generic'))}</p>}
        {check.isSuccess && check.variables === 'check' && b.triggers.every((tr) => tr.source !== 'nws') && (
          <p className="mt-2 text-sm text-ink-soft">{t('rapid.noWarnings', { disaster: disaster.name })}</p>
        )}
      </div>
      {b.triggers.length > 0 && (
        <ul className="mt-2 divide-y divide-line">
          {b.triggers.map((tr) => (
            <TriggerCard key={tr.id} tr={tr} onBoard={save} />
          ))}
        </ul>
      )}
    </section>
  )
}
