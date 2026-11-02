import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type Contractor, type Milestone, type Project } from '../api'
import {
  ContractorLine,
  GanttSlot,
  MilestoneStatusPill,
  PhotoStrip,
  SiteCheckView,
  Stat,
} from '../components/Milestones'
import { VoiceButton } from '../components/VoiceButton'
import { MoveInStat, ScheduleNotice } from '../components/WhatIf'
import { money } from '../format'
import { dateRange, paidOut } from '../rebuild'

function StartProject({ onStarted }: { onStarted: () => void }) {
  const { t } = useTranslation()
  const [title, setTitle] = useState(() => t('rebuild.defaultTitle'))
  const [error, setError] = useState<string | null>(null)
  const contractors = useQuery({ queryKey: ['contractors'], queryFn: () => api<Contractor[]>('/contractors') })
  const start = useMutation({
    mutationFn: (contractorId: number) =>
      api('/households/me/projects', { method: 'POST', body: JSON.stringify({ contractor_id: contractorId, title }) }),
    onSuccess: onStarted,
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })
  return (
    <section className="panel p-5">
      <h2 className="font-semibold">{t('rebuild.startTitle')}</h2>
      <p className="mt-1 text-sm text-ink-soft">{t('rebuild.startBody')}</p>
      <label className="mt-4 block text-sm">
        <span className="text-ink-soft">{t('rebuild.projectTitle')}</span>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2"
        />
      </label>
      <ul className="mt-4 space-y-2">
        {contractors.data?.map((c) => (
          <li
            key={c.id}
            className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-line px-4 py-3"
          >
            <ContractorLine c={c} />
            <button
              onClick={() => start.mutate(c.id)}
              disabled={start.isPending || title.trim().length < 3}
              className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
            >
              {t('rebuild.invite')}
            </button>
          </li>
        ))}
      </ul>
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </section>
  )
}

function MilestoneCard({ m, onChanged }: { m: Milestone; onChanged: () => void }) {
  const { t, i18n } = useTranslation()
  const [disputing, setDisputing] = useState(false)
  const [reason, setReason] = useState('')
  const [error, setError] = useState<string | null>(null)
  const act = useMutation({
    mutationFn: (action: 'approve' | 'dispute') =>
      api<Milestone>(`/milestones/${m.id}/${action}`, {
        method: 'POST',
        body: action === 'dispute' ? JSON.stringify({ reason }) : undefined,
      }),
    onSuccess: () => {
      setDisputing(false)
      setError(null)
      onChanged()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })

  return (
    <li className="panel p-4">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="font-medium">
            {m.seq}. {m.title} · {money(m.amount)}
            {m.is_deposit && <span className="ml-2 text-xs text-ink-faint">{t('rebuild.deposit')}</span>}
          </div>
          <div className="text-xs text-ink-faint">{dateRange(m, i18n.resolvedLanguage)}</div>
        </div>
        <MilestoneStatusPill status={m.status} />
      </div>
      {m.done_looks_like && (
        <p className="mt-2 text-sm text-ink-soft">
          <span className="font-medium text-ink">{t('rebuild.doneLooksLike')}:</span> {m.done_looks_like}
        </p>
      )}
      {(m.photo_urls.length > 0 || m.site_check) && m.status !== 'pending' && (
        <div className="mt-3 space-y-3">
          <PhotoStrip urls={m.photo_urls} />
          {m.site_check && !m.is_deposit && <SiteCheckView check={m.site_check} />}
        </div>
      )}

      {m.status === 'submitted' && (
        <div className="mt-3 space-y-2">
          <p className="text-sm text-ink-soft">
            {m.needs_human_review ? t('rebuild.willReview') : t('rebuild.willPay', { amount: money(m.amount) })}
          </p>
          <div className="flex flex-wrap gap-2">
            <button
              onClick={() => act.mutate('approve')}
              disabled={act.isPending}
              className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
            >
              {m.needs_human_review ? t('rebuild.approveToReview') : t('rebuild.approveAndPay')}
            </button>
            <button
              onClick={() => setDisputing((d) => !d)}
              className="rounded-lg border border-line px-3 py-1.5 text-sm text-ink-soft hover:bg-sunken"
            >
              {t('rebuild.dispute')}
            </button>
          </div>
          {disputing && (
            <div className="space-y-2">
              <div className="flex gap-2">
                <textarea
                  value={reason}
                  onChange={(e) => setReason(e.target.value)}
                  rows={2}
                  placeholder={t('rebuild.disputePlaceholder')}
                  className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
                />
                <VoiceButton onText={(text) => setReason(text)} />
              </div>
              <button
                onClick={() => act.mutate('dispute')}
                disabled={reason.trim().length < 10 || act.isPending}
                className="rounded-lg bg-danger px-3 py-1.5 text-sm font-medium text-white disabled:opacity-40"
              >
                {t('rebuild.sendDispute')}
              </button>
            </div>
          )}
        </div>
      )}
      {m.status === 'pending' && <p className="mt-2 text-xs text-ink-faint">{t('rebuild.explain.pending')}</p>}
      {m.status === 'under_review' && <p className="mt-2 text-sm text-ink-soft">{t('rebuild.explain.under_review')}</p>}
      {m.status === 'disputed' && <p className="mt-2 text-sm text-ink-soft">{t('rebuild.explain.disputed')}</p>}
      {m.status === 'refunded' && <p className="mt-2 text-sm text-ink-soft">{t('rebuild.explain.refunded')}</p>}
      {m.status === 'paid' && (
        <p className="mt-2 text-xs text-ink-faint">
          {t('rebuild.paidOn', {
            date: m.paid_at ? new Date(m.paid_at).toLocaleDateString(i18n.resolvedLanguage) : '',
          })}
          {m.paypal_ref && ` · ${t('purchases.paypalRef', { ref: m.paypal_ref })}`}
        </p>
      )}
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </li>
  )
}

function HouseholdProject({ p, onChanged }: { p: Project; onChanged: () => void }) {
  const { t } = useTranslation()
  const [error, setError] = useState<string | null>(null)
  const accept = useMutation({
    mutationFn: () => api<Project>(`/projects/${p.id}/accept`, { method: 'POST' }),
    onSuccess: onChanged,
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })

  return (
    <section className="space-y-4">
      <div className="panel p-5">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">{p.title}</h2>
            <p className="mt-0.5 text-sm">
              <ContractorLine c={p.contractor} />
            </p>
          </div>
          <span className="rounded-full bg-sunken px-2.5 py-0.5 text-sm font-medium">
            {t(`rebuild.projectStatus.${p.status}`)}
          </span>
        </div>
        {p.milestones.length > 0 && (
          <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Stat label={t('rebuild.price')} value={money(p.total_price)} />
            <Stat label={t('rebuild.inEscrow')} value={money(p.escrow_balance)} hint={t('rebuild.escrowHint')} />
            <Stat label={t('rebuild.paidOut')} value={money(paidOut(p))} />
            <MoveInStat p={p} />
          </div>
        )}
        {p.status === 'active' && p.changes.length > 0 && (
          <div className="mt-4">
            <ScheduleNotice p={p} />
          </div>
        )}
        {p.status === 'awaiting_plan' && (
          <p className="mt-4 text-sm text-ink-soft">
            {t('rebuild.awaitingPlan', { name: p.contractor.business_name })}
          </p>
        )}
        {p.status === 'plan_submitted' && (
          <div className="mt-4 space-y-2 rounded-lg bg-amber-soft p-4">
            <p className="font-medium">{t('rebuild.reviewPlan', { name: p.contractor.business_name })}</p>
            <p className="text-sm text-ink-soft">{t('rebuild.acceptExplain', { cap: money(p.deposit_cap) })}</p>
            <button
              onClick={() => accept.mutate()}
              disabled={accept.isPending}
              className="rounded-lg bg-ember px-4 py-2 text-sm font-medium text-on-ember disabled:opacity-40"
            >
              {t('rebuild.accept', { amount: money(p.total_price) })}
            </button>
            {error && <p className="text-sm text-danger">{error}</p>}
          </div>
        )}
      </div>
      <GanttSlot project={p} editable={false} />
      <ul className="grid items-start gap-3 lg:grid-cols-2">
        {p.milestones.map((m) => (
          <MilestoneCard key={m.id} m={m} onChanged={onChanged} />
        ))}
      </ul>
    </section>
  )
}

export default function Rebuild() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const projects = useQuery({ queryKey: ['my-projects'], queryFn: () => api<Project[]>('/households/me/projects') })
  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['my-projects'] })
    void queryClient.invalidateQueries({ queryKey: ['ledger'] })
  }, [queryClient])

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-4xl leading-tight tracking-tight text-balance">{t('rebuild.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('rebuild.subtitle')}</p>
      </div>
      {projects.isError && <p className="rounded-lg bg-danger-soft px-4 py-3 text-danger">{t('errors.generic')}</p>}
      {projects.isPending && <div className="h-64 animate-pulse rounded-xl bg-sunken" />}
      {projects.data?.length === 0 && <StartProject onStarted={refresh} />}
      {projects.data?.map((p) => (
        <HouseholdProject key={p.id} p={p} onChanged={refresh} />
      ))}
    </div>
  )
}
