import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type Milestone, type Project } from '../api'
import { GanttSlot, MilestoneStatusPill, PhotoStrip, SiteCheckView, Stat } from '../components/Milestones'
import { money } from '../format'
import { dateRange, paidOut } from '../rebuild'
import { ConnectPayPal } from '../components/ConnectPayPal'
import type { GanttPreview } from '../components/ProjectGantt'
import { WhatIfPanel } from '../components/WhatIf'

type Row = { title: string; done_looks_like: string; amount: string; start: string; end: string; is_deposit: boolean }

const day = (d: Date) => d.toISOString().slice(0, 10)
const plusDays = (n: number) => day(new Date(Date.now() + n * 86_400_000))

// California: a home-improvement deposit can't exceed 10% of the price or $1,000, whichever is less.
// The server enforces this; the editor shows it as you type.
const depositCap = (total: number) => Math.min(Math.round(total * 10) / 100, 1000)

function startingRows(p: Project, t: (k: string) => string): Row[] {
  if (p.milestones.length > 0)
    return p.milestones.map((m) => ({
      title: m.title,
      done_looks_like: m.done_looks_like,
      amount: String(Number(m.amount)),
      start: m.start_date.slice(0, 10),
      end: m.end_date.slice(0, 10),
      is_deposit: m.is_deposit,
    }))
  return [
    {
      title: t('contractor.template.deposit'),
      done_looks_like: '',
      amount: '',
      start: plusDays(1),
      end: plusDays(3),
      is_deposit: true,
    },
    {
      title: t('contractor.template.demolition'),
      done_looks_like: '',
      amount: '',
      start: plusDays(4),
      end: plusDays(14),
      is_deposit: false,
    },
    {
      title: t('contractor.template.repair'),
      done_looks_like: '',
      amount: '',
      start: plusDays(15),
      end: plusDays(35),
      is_deposit: false,
    },
  ]
}

function PlanEditor({ p, onSaved }: { p: Project; onSaved: () => void }) {
  const { t } = useTranslation()
  const [rows, setRows] = useState<Row[]>(() => startingRows(p, t))
  const [error, setError] = useState<string | null>(null)
  const total = rows.reduce((s, r) => s + (Number(r.amount) || 0), 0)
  const cap = depositCap(total)
  const deposit = rows.find((r) => r.is_deposit)
  const overCap = deposit !== undefined && Number(deposit.amount) > cap
  const update = (i: number, patch: Partial<Row>) =>
    setRows((rs) =>
      rs.map((r, j) => (j === i ? { ...r, ...patch } : patch.is_deposit ? { ...r, is_deposit: false } : r)),
    )

  const save = useMutation({
    mutationFn: () =>
      api<Project>(`/projects/${p.id}/plan`, {
        method: 'PUT',
        body: JSON.stringify({
          milestones: rows.map((r) => ({
            title: r.title,
            done_looks_like: r.done_looks_like,
            amount: r.amount,
            is_deposit: r.is_deposit,
            start_date: new Date(`${r.start}T08:00`).toISOString(),
            end_date: new Date(`${r.end}T17:00`).toISOString(),
          })),
        }),
      }),
    onSuccess: () => {
      setError(null)
      onSaved()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })
  const valid = rows.every(
    (r) => r.title.trim().length >= 2 && Number(r.amount) > 0 && r.start && r.end && r.end >= r.start,
  )

  return (
    <div className="space-y-3">
      <ol className="space-y-3">
        {rows.map((r, i) => (
          <li
            key={i}
            className="grid gap-2 rounded-lg border border-line p-3 sm:grid-cols-[2rem_minmax(0,1fr)_8rem_9rem_9rem_auto]"
          >
            <span className="pt-2 text-sm text-ink-faint">{i + 1}.</span>
            <div className="space-y-2">
              <input
                value={r.title}
                onChange={(e) => update(i, { title: e.target.value })}
                placeholder={t('contractor.milestoneTitle')}
                aria-label={t('contractor.milestoneTitle')}
                className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
              />
              <input
                value={r.done_looks_like}
                onChange={(e) => update(i, { done_looks_like: e.target.value })}
                placeholder={t('contractor.donePlaceholder')}
                aria-label={t('rebuild.doneLooksLike')}
                className="w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
              />
              <label className="flex items-center gap-2 text-xs text-ink-soft">
                <input
                  type="checkbox"
                  checked={r.is_deposit}
                  onChange={(e) => update(i, { is_deposit: e.target.checked })}
                />
                {t('rebuild.deposit')}
              </label>
            </div>
            <label className="flex h-fit items-center gap-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm">
              $
              <input
                type="number"
                min={1}
                value={r.amount}
                onChange={(e) => update(i, { amount: e.target.value })}
                aria-label={t('contractor.amount')}
                className="w-full bg-transparent outline-none"
              />
            </label>
            <input
              type="date"
              value={r.start}
              onChange={(e) => update(i, { start: e.target.value })}
              aria-label={t('rebuild.gantt.start')}
              className="h-fit rounded-lg border border-line bg-surface px-2 py-2 text-sm"
            />
            <input
              type="date"
              value={r.end}
              onChange={(e) => update(i, { end: e.target.value })}
              aria-label={t('rebuild.gantt.end')}
              className="h-fit rounded-lg border border-line bg-surface px-2 py-2 text-sm"
            />
            <button
              onClick={() => setRows((rs) => rs.filter((_, j) => j !== i))}
              disabled={rows.length === 1}
              aria-label={t('contractor.removeRow')}
              className="h-fit rounded-lg px-2 py-2 text-ink-faint hover:bg-sunken hover:text-ink disabled:opacity-30"
            >
              ✕
            </button>
          </li>
        ))}
      </ol>
      <button
        onClick={() =>
          setRows((rs) => [
            ...rs,
            {
              title: '',
              done_looks_like: '',
              amount: '',
              start: rs.at(-1)?.end ?? plusDays(1),
              end: rs.at(-1)?.end ?? plusDays(7),
              is_deposit: false,
            },
          ])
        }
        disabled={rows.length >= 20}
        className="rounded-lg border border-line px-3 py-1.5 text-sm text-ink-soft hover:bg-sunken"
      >
        + {t('contractor.addRow')}
      </button>
      <div className="flex flex-wrap items-center justify-between gap-3 rounded-lg bg-sunken px-4 py-3 text-sm">
        <span>
          {t('contractor.total')}: <strong>{money(total)}</strong>
          <span className={`ml-3 ${overCap ? 'font-medium text-danger' : 'text-ink-soft'}`}>
            {t('contractor.depositCap', { cap: money(cap) })}
          </span>
        </span>
        <button
          onClick={() => save.mutate()}
          disabled={!valid || overCap || save.isPending}
          className="rounded-lg bg-ember px-4 py-2 font-medium text-on-ember disabled:opacity-40"
        >
          {p.status === 'plan_submitted' ? t('contractor.resend') : t('contractor.send')}
        </button>
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
    </div>
  )
}

function MilestoneWork({ m, canSubmit, onChanged }: { m: Milestone; canSubmit: boolean; onChanged: () => void }) {
  const { t, i18n } = useTranslation()
  const [files, setFiles] = useState<File[]>([])
  const [error, setError] = useState<string | null>(null)
  const submit = useMutation({
    mutationFn: () => {
      const form = new FormData()
      files.forEach((f) => form.append('files', f))
      return api<Milestone>(`/milestones/${m.id}/submit`, { method: 'POST', body: form })
    },
    onSuccess: () => {
      setFiles([])
      setError(null)
      onChanged()
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })

  return (
    <li className="rounded-xl border border-line bg-surface p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="font-medium">
            {m.seq}. {m.title} · {money(m.amount)}
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
      {m.status !== 'pending' && (m.photo_urls.length > 0 || m.site_check) && (
        <div className="mt-3 space-y-3">
          <PhotoStrip urls={m.photo_urls} />
          {m.site_check && !m.is_deposit && <SiteCheckView check={m.site_check} />}
        </div>
      )}
      {m.status === 'pending' && canSubmit && (
        <div className="mt-3 space-y-2">
          {!m.is_deposit && (
            <label className="block text-sm">
              <span className="text-ink-soft">{t('contractor.photos')}</span>
              <input
                type="file"
                accept="image/*"
                multiple
                onChange={(e) => setFiles(Array.from(e.target.files ?? []).slice(0, 8))}
                className="mt-1 block w-full text-sm file:mr-3 file:rounded-lg file:border file:border-line file:bg-surface file:px-3 file:py-1.5"
              />
            </label>
          )}
          <button
            onClick={() => submit.mutate()}
            disabled={submit.isPending || (!m.is_deposit && files.length === 0)}
            className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
          >
            {submit.isPending
              ? t('contractor.checking')
              : m.is_deposit
                ? t('contractor.requestDeposit')
                : t('contractor.submitWork')}
          </button>
        </div>
      )}
      {m.status === 'pending' && !canSubmit && (
        <p className="mt-2 text-xs text-ink-faint">{t('contractor.explain.pending')}</p>
      )}
      {m.status === 'submitted' && <p className="mt-2 text-sm text-ink-soft">{t('contractor.explain.submitted')}</p>}
      {m.status === 'under_review' && (
        <p className="mt-2 text-sm text-ink-soft">{t('contractor.explain.under_review')}</p>
      )}
      {m.status === 'disputed' && <p className="mt-2 text-sm text-ink-soft">{t('contractor.explain.disputed')}</p>}
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

const isPlanning = (p: Project) => p.status === 'awaiting_plan' || p.status === 'plan_submitted'

function ContractorProject({ p, onChanged }: { p: Project; onChanged: () => void }) {
  const { t } = useTranslation()
  const planning = isPlanning(p)
  const next = p.milestones.find((m) => m.status === 'pending') // work is submitted in order
  const [preview, setPreview] = useState<GanttPreview | null>(null)
  return (
    <section className="space-y-4">
      <div className="rounded-xl border border-line bg-surface p-5 shadow-sm">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div>
            <h2 className="text-xl font-semibold">{p.title}</h2>
            <p className="mt-0.5 text-sm text-ink-soft">{p.household_name}</p>
          </div>
          <span className="rounded-full bg-sunken px-2.5 py-0.5 text-sm font-medium">
            {t(`contractor.projectStatus.${p.status}`)}
          </span>
        </div>
        {!planning && (
          <div className="mt-4 grid gap-3 sm:grid-cols-3">
            <Stat label={t('rebuild.price')} value={money(p.total_price)} />
            <Stat label={t('contractor.escrowed')} value={money(p.escrow_balance)} hint={t('contractor.escrowHint')} />
            <Stat label={t('contractor.received')} value={money(paidOut(p))} />
          </div>
        )}
        {planning && (
          <div className="mt-4">
            <p className="mb-3 text-sm text-ink-soft">
              {p.status === 'plan_submitted' ? t('contractor.planSent') : t('contractor.planIntro')}
            </p>
            <PlanEditor p={p} onSaved={onChanged} />
          </div>
        )}
      </div>
      {!planning && (
        <>
          <GanttSlot project={p} editable={p.status === 'active'} onSynced={onChanged} onPreviewReady={setPreview} />
          <WhatIfPanel key={p.changes[0]?.id ?? 0} p={p} gantt={preview} onSaved={onChanged} />
          <ul className="grid items-start gap-3 lg:grid-cols-2">
            {p.milestones.map((m) => (
              <MilestoneWork
                key={m.id}
                m={m}
                canSubmit={p.status === 'active' && m.id === next?.id}
                onChanged={onChanged}
              />
            ))}
          </ul>
        </>
      )}
    </section>
  )
}

export default function ContractorPortal() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const projects = useQuery({
    queryKey: ['contractor-projects'],
    queryFn: () => api<Project[]>('/contractors/me/projects'),
  })
  const refresh = useCallback(
    () => void queryClient.invalidateQueries({ queryKey: ['contractor-projects'] }),
    [queryClient],
  )

  return (
    <div className="space-y-8">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t('contractor.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('contractor.subtitle')}</p>
      </div>
      <ConnectPayPal />
      {projects.isError && <p className="rounded-lg bg-danger-soft px-4 py-3 text-danger">{t('errors.generic')}</p>}
      {projects.isPending && <div className="h-64 animate-pulse rounded-xl bg-sunken" />}
      {projects.data?.length === 0 && <p className="text-ink-soft">{t('contractor.empty')}</p>}
      {/* Projects waiting on a plan come first: that's what the contractor needs to do next. */}
      {projects.data
        ?.toSorted((a, b) => Number(isPlanning(b)) - Number(isPlanning(a)))
        .map((p) => (
          <ContractorProject key={p.id} p={p} onChanged={refresh} />
        ))}
    </div>
  )
}
