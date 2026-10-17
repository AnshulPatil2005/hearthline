import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type PolicyAnswer, type PolicyInfo } from '../api'
import { Stat } from '../components/Milestones'
import { Progress } from '../components/PublicFrame'
import { VoiceButton } from '../components/VoiceButton'
import { money } from '../format'

const SAMPLE = '/samples/golden-poppy-homeowners-policy.pdf'

function Upload({ onDone, replacing }: { onDone: () => void; replacing: boolean }) {
  const { t } = useTranslation()
  const [file, setFile] = useState<File | null>(null)
  const [error, setError] = useState<string | null>(null)
  const send = useMutation({
    mutationFn: () => {
      const form = new FormData()
      form.append('file', file!)
      return api<PolicyInfo>('/households/me/policy', { method: 'POST', body: form })
    },
    onSuccess: () => {
      setError(null)
      setFile(null)
      onDone()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })
  return (
    <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <h2 className="font-semibold">{replacing ? t('insurance.replace') : t('insurance.uploadTitle')}</h2>
      {!replacing && <p className="mt-1 text-sm text-ink-soft">{t('insurance.uploadBody')}</p>}
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <input
          type="file"
          accept="application/pdf,.pdf"
          onChange={(e) => setFile(e.target.files?.[0] ?? null)}
          aria-label={t('insurance.file')}
          className="text-sm file:mr-3 file:rounded-lg file:border file:border-line file:bg-surface file:px-3 file:py-1.5"
        />
        <button
          onClick={() => send.mutate()}
          disabled={!file || send.isPending}
          className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
        >
          {send.isPending ? t('insurance.reading') : t('insurance.read')}
        </button>
        <a href={SAMPLE} download className="text-sm text-ember hover:underline">
          {t('insurance.sample')}
        </a>
      </div>
      {send.isPending && <p className="mt-2 text-sm text-ink-soft">{t('insurance.readingHint')}</p>}
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </section>
  )
}

function Ask() {
  const { t } = useTranslation()
  const [question, setQuestion] = useState('')
  const ask = useMutation({
    mutationFn: (q: string) => api<PolicyAnswer>('/households/me/policy/ask', { method: 'POST', body: JSON.stringify({ question: q }) }),
  })
  return (
    <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <h2 className="font-semibold">{t('insurance.askTitle')}</h2>
      <form
        className="mt-3 flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (question.trim().length >= 3) ask.mutate(question.trim())
        }}
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={t('insurance.askPlaceholder')}
          aria-label={t('insurance.askTitle')}
          className="min-w-64 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
        />
        <VoiceButton
          onText={(text, final) => {
            setQuestion(text)
            if (final && text.trim().length >= 3) ask.mutate(text.trim())
          }}
        />
        <button
          type="submit"
          disabled={ask.isPending || question.trim().length < 3}
          className="rounded-lg bg-ember px-3 py-2 text-sm font-medium text-on-ember disabled:opacity-40"
        >
          {ask.isPending ? t('command.ask.thinking') : t('insurance.ask')}
        </button>
      </form>
      {ask.data && (
        <div className="mt-3 space-y-2 text-sm" aria-live="polite">
          <p>
            <span className="mr-2 rounded bg-ember-soft px-1.5 py-0.5 text-xs font-medium text-ember">AI</span>
            {ask.data.answer}
          </p>
          {ask.data.quote && (
            <blockquote className="border-l-4 border-line pl-3 text-ink-soft">“{ask.data.quote}”</blockquote>
          )}
        </div>
      )}
      {ask.isError && (
        <p className="mt-2 text-sm text-danger">{ask.error instanceof ApiError ? ask.error.message : t('errors.generic')}</p>
      )}
      <p className="mt-3 text-xs text-ink-faint">{t('insurance.notAdvice')}</p>
    </section>
  )
}

/** The household's insurance policy, read by the Policy agent and compared with their inventory. */
export default function Insurance() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const policy = useQuery({
    queryKey: ['policy'],
    queryFn: () => api<PolicyInfo>('/households/me/policy'),
    retry: (count, e) => !(e instanceof ApiError && e.status === 404) && count < 1,
  })
  const p = policy.data
  const date = (d: string) => new Date(`${d}T12:00`).toLocaleDateString(i18n.resolvedLanguage, { month: 'long', day: 'numeric', year: 'numeric' })

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t('insurance.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('insurance.subtitle')}</p>
      </div>
      {policy.isPending && <div className="h-40 animate-pulse rounded-xl bg-sunken" />}
      {!policy.isPending && !p && <Upload onDone={() => void queryClient.invalidateQueries({ queryKey: ['policy'] })} replacing={false} />}
      {p && (
        <>
          <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
            <div className="flex flex-wrap items-start justify-between gap-2">
              <div>
                <h2 className="text-xl font-semibold">{p.summary.insurer}</h2>
                <p className="text-sm text-ink-soft">
                  {[p.summary.policy_number, t(`insurance.type.${p.summary.policy_type}`), p.summary.period].filter(Boolean).join(' · ')}
                </p>
              </div>
              <span className="text-xs text-ink-faint">{p.filename}</span>
            </div>
            <p className="mt-3 leading-relaxed">
              <span className="mr-2 rounded bg-ember-soft px-1.5 py-0.5 text-xs font-medium text-ember">AI</span>
              {p.summary.plain_summary}
            </p>
            <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
              {p.summary.coverages.map((c) => (
                <Stat key={c.name} label={c.name} value={c.limit === null ? '—' : money(c.limit)} hint={c.notes} />
              ))}
            </div>
            <p className="mt-3 text-sm text-ink-soft">
              {t('insurance.deductible', { amount: p.summary.deductible === null ? '—' : money(p.summary.deductible) })} ·{' '}
              {t(`insurance.settlement.${p.summary.contents_settlement}`)}
            </p>
          </section>

          <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
            <h2 className="font-semibold">{t('insurance.claimTitle')}</h2>
            {p.check.contents_limit && (
              <div className="mt-3">
                <Progress funded={Number(p.check.inventory_value)} target={Number(p.check.contents_limit)} />
                <p className="mt-2 text-sm">
                  {t('insurance.inventoryVsLimit', { inventory: money(p.check.inventory_value), limit: money(p.check.contents_limit) })}
                  {Number(p.check.contents_gap) > 0 && (
                    <span className="ml-1 font-medium text-danger">{t('insurance.gap', { gap: money(p.check.contents_gap) })}</span>
                  )}
                </p>
              </div>
            )}
            <ul className="mt-4 space-y-2">
              {p.check.sub_limits
                .filter((s) => s.items.length > 0)
                .map((s) => (
                  <li
                    key={s.what}
                    className={`rounded-lg p-3 text-sm ${Number(s.over_by) > 0 ? 'bg-danger-soft' : 'bg-sunken'}`}
                  >
                    <span className="font-medium">{s.what}</span>{' '}
                    {Number(s.over_by) > 0
                      ? t('insurance.overSubLimit', { value: money(s.items_value), limit: money(s.limit), over: money(s.over_by) })
                      : t('insurance.withinSubLimit', { value: money(s.items_value), limit: money(s.limit) })}
                    <span className="block text-xs text-ink-soft">{s.items.join(', ')}</span>
                  </li>
                ))}
            </ul>
            <p className="mt-3 text-xs text-ink-faint">{t('insurance.otherSubLimits', { count: p.check.sub_limits.filter((s) => s.items.length === 0).length })}</p>
          </section>

          <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
            <h2 className="font-semibold">{t('insurance.deadlinesTitle')}</h2>
            <ul className="mt-3 space-y-2">
              {p.check.deadlines.map((d) => (
                <li key={d.what} className="flex flex-wrap items-baseline justify-between gap-2 text-sm">
                  <span>
                    <span className="font-medium">{d.what}</span>
                    <span className="block text-xs text-ink-faint">“{d.text}”</span>
                  </span>
                  {d.due && (
                    <span className={d.days_left !== null && d.days_left <= 14 ? 'font-medium text-danger' : 'text-ink-soft'}>
                      {d.days_left !== null && d.days_left < 0
                        ? t('insurance.overdue', { date: date(d.due) })
                        : t('insurance.due', { date: date(d.due), count: d.days_left ?? 0 })}
                    </span>
                  )}
                </li>
              ))}
            </ul>
            <p className="mt-3 rounded-lg bg-amber-soft px-3 py-2 text-sm">{t('insurance.advanceTip')}</p>
          </section>

          <Ask />
          <Upload onDone={() => void queryClient.invalidateQueries({ queryKey: ['policy'] })} replacing />
        </>
      )}
    </div>
  )
}
