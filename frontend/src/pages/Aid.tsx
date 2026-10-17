import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type HouseholdCase, type Verification } from '../api'
import type { Call } from '../components/VideoCalls'
import { VoiceButton } from '../components/VoiceButton'
import { money } from '../format'
import { ConnectPayPal } from '../components/ConnectPayPal'

const STATUS_TONE: Record<HouseholdCase['status'], string> = {
  in_review: 'bg-sunken text-ink',
  needs_info: 'bg-amber-soft text-amber',
  escalated: 'bg-sunken text-ink',
  approved: 'bg-sage-soft text-sage',
  rejected: 'bg-danger-soft text-danger',
}

function VerificationCard({ v }: { v: Verification }) {
  const { t } = useTranslation()
  return (
    <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <div className="flex items-center justify-between gap-3">
        <h2 className="font-semibold">{t('aid.verificationTitle')}</h2>
        <span className="rounded-full bg-sunken px-2.5 py-0.5 text-sm font-medium">
          {t(`review.levels.${v.level}`)}
        </span>
      </div>
      <ol className="mt-4 grid gap-2 sm:grid-cols-4">
        {[0, 1, 2, 3].map((level) => (
          <li
            key={level}
            className={`rounded-lg px-3 py-2 text-sm ${level <= v.level ? 'bg-sage-soft text-sage' : 'bg-sunken text-ink-faint'}`}
          >
            <span className="font-medium">{level <= v.level ? '✓ ' : ''}</span>
            {t(`aid.unlocks.${level}`)}
          </li>
        ))}
      </ol>
      {v.next_step && <p className="mt-3 text-sm text-ink-soft">{t(`aid.next.${v.next_step}`)}</p>}
    </section>
  )
}

function RequestCashAid({ onDone }: { onDone: () => void }) {
  const { t } = useTranslation()
  const [amount, setAmount] = useState('500')
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const submit = useMutation({
    mutationFn: () =>
      api('/households/me/cases', { method: 'POST', body: JSON.stringify({ kind: 'cash_aid', amount, note }) }),
    onSuccess: () => {
      setNote('')
      setError(null)
      onDone()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })
  return (
    <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <h2 className="font-semibold">{t('aid.requestTitle')}</h2>
      <p className="mt-1 text-sm text-ink-soft">{t('aid.requestBody')}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-[10rem_minmax(0,1fr)_auto] sm:items-start">
        <label className="flex items-center gap-1 rounded-lg border border-line bg-surface px-3 py-2">
          $
          <input
            type="number"
            min={1}
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            className="w-full bg-transparent outline-none"
            aria-label={t('aid.amount')}
          />
        </label>
        <div className="flex gap-2">
          <textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            rows={2}
            placeholder={t('aid.notePlaceholder')}
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
          />
          <VoiceButton onText={(text) => setNote(text)} />
        </div>
        <button
          onClick={() => submit.mutate()}
          disabled={submit.isPending || Number(amount) < 1}
          className="rounded-lg bg-ember px-4 py-2 text-sm font-medium text-on-ember disabled:opacity-40"
        >
          {t('aid.submit')}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </section>
  )
}

function CaseCard({ c, onChanged }: { c: HouseholdCase; onChanged: () => void }) {
  const { t, i18n } = useTranslation()
  const [reply, setReply] = useState('')
  const send = useMutation({
    mutationFn: () =>
      api(`/households/me/cases/${c.id}/reply`, { method: 'POST', body: JSON.stringify({ note: reply }) }),
    onSuccess: () => {
      setReply('')
      onChanged()
    },
  })
  return (
    <li className="rounded-xl border border-line bg-surface p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="font-medium">
            {t(`review.kind.${c.kind}`)}
            {Number(c.amount_requested) > 0 && ` · ${money(c.amount_requested)}`}
          </div>
          <div className="text-xs text-ink-faint">
            {new Date(c.created_at).toLocaleDateString(i18n.resolvedLanguage, { month: 'short', day: 'numeric' })}
          </div>
        </div>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_TONE[c.status]}`}>
          {t(`aid.status.${c.status}`)}
        </span>
      </div>
      <p className="mt-2 text-sm text-ink-soft">{t(`aid.explain.${c.status}`)}</p>
      {c.video_call_required && c.status === 'in_review' && (
        <p className="mt-1 text-sm text-ink-soft">{t('aid.videoNeeded')}</p>
      )}
      {c.status === 'needs_info' && (
        <div className="mt-3 space-y-2">
          {c.decision_note && <p className="rounded-lg bg-amber-soft px-3 py-2 text-sm">“{c.decision_note}”</p>}
          <textarea
            value={reply}
            onChange={(e) => setReply(e.target.value)}
            rows={2}
            placeholder={t('aid.replyPlaceholder')}
            className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
          />
          <button
            onClick={() => send.mutate()}
            disabled={reply.trim().length < 3 || send.isPending}
            className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
          >
            {t('aid.sendReply')}
          </button>
        </div>
      )}
      {c.status === 'rejected' && c.decision_note && <p className="mt-2 text-sm">“{c.decision_note}”</p>}
    </li>
  )
}

export default function Aid() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const verification = useQuery({
    queryKey: ['verification'],
    queryFn: () => api<Verification>('/households/me/verification'),
  })
  const cases = useQuery({ queryKey: ['my-cases'], queryFn: () => api<HouseholdCase[]>('/households/me/cases') })
  const calls = useQuery({ queryKey: ['my-calls'], queryFn: () => api<Call[]>('/households/me/appointments') })
  const refresh = () => {
    void queryClient.invalidateQueries({ queryKey: ['my-cases'] })
    void queryClient.invalidateQueries({ queryKey: ['verification'] })
  }

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t('aid.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('aid.subtitle')}</p>
      </div>
      {verification.data && <VerificationCard v={verification.data} />}
      {calls.data?.[0] && (
        <p className="rounded-xl border border-line bg-surface px-4 py-3 shadow-sm">
          {t('home.upcomingCall', {
            name: calls.data[0].reviewer_name.split(' ')[0],
            when: new Date(calls.data[0].starts_at).toLocaleString(undefined, {
              weekday: 'long',
              month: 'short',
              day: 'numeric',
              hour: 'numeric',
              minute: '2-digit',
            }),
          })}
        </p>
      )}
      <ConnectPayPal />
      <RequestCashAid onDone={refresh} />
      <section>
        <h2 className="text-lg font-semibold">{t('aid.casesTitle')}</h2>
        {cases.data?.length === 0 ? (
          <p className="mt-2 text-ink-soft">{t('aid.noCases')}</p>
        ) : (
          <ul className="mt-3 grid gap-3 lg:grid-cols-2">
            {cases.data?.map((c) => (
              <CaseCard key={c.id} c={c} onChanged={refresh} />
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}
