import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import { api, ApiError, mediaUrl, type CaseDetail } from '../api'
import RiskBadge from '../components/RiskBadge'
import VideoCalls from '../components/VideoCalls'
import { money } from '../format'

const SEVERITY: Record<string, string> = {
  high: 'border-danger/40 bg-danger-soft text-danger',
  medium: 'border-amber/40 bg-amber-soft text-amber',
  low: 'border-line bg-sunken text-ink-soft',
}

function Panel({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <h2 className="text-sm font-semibold tracking-wide text-ink-faint uppercase">{title}</h2>
      <div className="mt-3">{children}</div>
    </section>
  )
}

function Fact({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex justify-between gap-4 py-1.5 text-sm">
      <dt className="text-ink-soft">{label}</dt>
      <dd className="text-right font-medium">{children}</dd>
    </div>
  )
}

function Decision({ c }: { c: CaseDetail }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const decide = useMutation({
    mutationFn: (decision: 'approve' | 'reject' | 'request_info') =>
      api(`/review/cases/${c.id}/decision`, { method: 'POST', body: JSON.stringify({ decision, reason }) }),
    onSuccess: () => {
      setReason('')
      setError(null)
      void queryClient.invalidateQueries({ queryKey: ['case', String(c.id)] })
      void queryClient.invalidateQueries({ queryKey: ['review-queue'] })
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })

  if (!c.awaiting_me) {
    return (
      <p className="text-sm text-ink-soft">
        {t(`review.notYourTurn.${c.status}`, { defaultValue: t('review.notYourTurn.default') })}
      </p>
    )
  }
  return (
    <div className="space-y-3">
      {c.video_call_required && (
        <p className="rounded-lg bg-amber-soft px-3 py-2 text-sm text-amber">{t('review.videoFirst')}</p>
      )}
      <textarea
        value={reason}
        onChange={(e) => setReason(e.target.value)}
        rows={3}
        placeholder={t('review.reasonPlaceholder')}
        className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
      />
      <div className="flex flex-wrap gap-2">
        <button
          onClick={() => decide.mutate('approve')}
          disabled={decide.isPending}
          className="rounded-lg bg-sage px-4 py-2 text-sm font-medium text-white disabled:opacity-40"
        >
          {t('review.approve')}
        </button>
        <button
          onClick={() => decide.mutate('request_info')}
          disabled={decide.isPending}
          className="rounded-lg border border-line px-4 py-2 text-sm font-medium hover:bg-sunken"
        >
          {t('review.requestInfo')}
        </button>
        <button
          onClick={() => decide.mutate('reject')}
          disabled={decide.isPending}
          className="rounded-lg border border-danger/50 px-4 py-2 text-sm font-medium text-danger hover:bg-danger-soft"
        >
          {t('review.reject')}
        </button>
      </div>
      <p className="text-xs text-ink-faint">{t('review.reasonRule')}</p>
      {error && <p className="text-sm text-danger">{error}</p>}
    </div>
  )
}

export default function ReviewCase() {
  const { id } = useParams()
  const { t, i18n } = useTranslation()
  const detail = useQuery({ queryKey: ['case', id], queryFn: () => api<CaseDetail>(`/review/cases/${id}`) })
  const c = detail.data

  if (detail.isError) return <p className="rounded-lg bg-danger-soft px-4 py-3 text-danger">{t('errors.generic')}</p>
  if (!c) return <div className="h-64 animate-pulse rounded-xl bg-sunken" />

  return (
    <div className="space-y-6">
      <div>
        <Link to="/review" className="text-sm text-ember hover:underline">
          ← {t('review.back')}
        </Link>
        <div className="mt-2 flex flex-wrap items-center gap-3">
          <h1 className="text-3xl font-semibold tracking-tight">
            {t(`review.kind.${c.kind}`)} · {c.household_name}
          </h1>
          <RiskBadge tier={c.risk_tier} score={c.risk_score} />
          <span className="rounded-full bg-sunken px-2.5 py-0.5 text-xs font-medium">
            {t(`review.status.${c.status}`)}
          </span>
          {c.random_audit && (
            <span className="rounded-full bg-sunken px-2.5 py-0.5 text-xs">{t('review.randomAudit')}</span>
          )}
        </div>
        <p className="mt-1 text-ink-soft">
          {Number(c.amount_requested) > 0 && `${money(c.amount_requested)} · `}
          {t('review.needs', { done: c.reviews_done, required: c.required_reviews })}
          {c.video_call_required && ` · ${t('review.videoRequired')}`}
        </p>
      </div>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
        <div className="space-y-6">
          <Panel title={t('review.sentinelTitle')}>
            <p className="leading-relaxed">{c.sentinel_summary}</p>
            {c.sentinel_questions.length > 0 && (
              <>
                <h3 className="mt-4 text-sm font-semibold">{t('review.askThem')}</h3>
                <ul className="mt-1 list-disc space-y-1 pl-5 text-sm text-ink-soft">
                  {c.sentinel_questions.map((q) => (
                    <li key={q}>{q}</li>
                  ))}
                </ul>
              </>
            )}
            <p className="mt-4 text-xs text-ink-faint">{t('review.sentinelNote')}</p>
          </Panel>

          <Panel title={t('review.flagsTitle', { count: c.flags.length })}>
            {c.flags.length === 0 ? (
              <p className="text-sm text-ink-soft">{t('review.noFlags')}</p>
            ) : (
              <ul className="space-y-2">
                {c.flags.map((f) => (
                  <li key={f.code} className={`rounded-lg border px-3 py-2 text-sm ${SEVERITY[f.severity]}`}>
                    <span className="font-semibold">{t(`review.flag.${f.code}`, { defaultValue: f.code })}</span>
                    <span className="text-ink"> · {f.message}</span>
                  </li>
                ))}
              </ul>
            )}
          </Panel>

          {c.photos.length > 0 && (
            <Panel title={t('review.photosTitle')}>
              <ul className="grid grid-cols-2 gap-3 sm:grid-cols-4">
                {c.photos.map((p) => (
                  <li key={p.media_id}>
                    <img src={mediaUrl(p.url) ?? ''} alt="" className="aspect-[4/3] w-full rounded-lg object-cover" />
                    <p className="mt-1 text-xs text-ink-faint">
                      {p.captured_at
                        ? new Date(p.captured_at).toLocaleDateString(i18n.resolvedLanguage)
                        : t('review.noDate')}
                    </p>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          {c.note && (
            <Panel title={t('review.householdNote')}>
              <p className="whitespace-pre-line text-sm">{c.note}</p>
            </Panel>
          )}
        </div>

        <div className="space-y-6">
          <Panel title={t('review.decisionTitle')}>
            <Decision c={c} />
            {c.decision_note && (
              <p className="mt-3 text-sm text-ink-soft">
                {t('review.lastNote')}: {c.decision_note}
              </p>
            )}
            {c.paypal_ref && (
              <p className="mt-2 text-xs text-ink-faint">{t('purchases.paypalRef', { ref: c.paypal_ref })}</p>
            )}
          </Panel>

          {c.video_call_required && (
            <Panel title={t('calls.title')}>
              <VideoCalls caseId={c.id} canBook={c.my_role !== null && ['in_review', 'escalated'].includes(c.status)} />
            </Panel>
          )}

          <Panel title={t('review.householdTitle')}>
            <dl className="divide-y divide-line">
              <Fact label={t('review.address')}>{c.address}</Fact>
              <Fact label={t('review.inZone')}>
                <span className={c.in_disaster_zone ? 'text-sage' : 'text-danger'}>
                  {c.in_disaster_zone ? t('review.yes') : t('review.no')}
                </span>
              </Fact>
              <Fact label={t('review.level')}>{t(`review.levels.${c.verification_level}`)}</Fact>
              <Fact label={t('review.payout')}>{c.payout_email ?? '—'}</Fact>
              <Fact label={t('review.inventory')}>
                {t('rooms.items', { count: c.inventory_items })} · {money(c.inventory_value)}
              </Fact>
              {c.registry_slug && (
                <Fact label={t('review.registry')}>
                  <Link to={`/r/${c.registry_slug}`} target="_blank" className="text-ember hover:underline">
                    /r/{c.registry_slug} ↗
                  </Link>
                </Fact>
              )}
              {c.vouch_note && <Fact label={t('review.vouch')}>{c.vouch_note}</Fact>}
            </dl>
          </Panel>

          <Panel title={t('review.trailTitle')}>
            <p className="text-sm text-ink-soft">{t('review.assigned', { names: c.reviewers.join(', ') })}</p>
            <ul className="mt-3 space-y-2 text-sm">
              {c.reviews.map((r, i) => (
                <li key={i}>
                  <span className="font-medium">{r.reviewer_name}</span>{' '}
                  <span className="text-ink-soft">{t(`review.decided.${r.decision}`)}</span>
                  {r.reason && <span className="block text-ink-faint">“{r.reason}”</span>}
                </li>
              ))}
              {c.reviews.length === 0 && <li className="text-ink-faint">{t('review.noReviews')}</li>}
            </ul>
          </Panel>
        </div>
      </div>
    </div>
  )
}
