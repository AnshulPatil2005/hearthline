import { useMutation, useQuery } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type Project, type ScheduleChange, type ScheduleMove, type WhatIf } from '../api'
import { money, parseTime } from '../format'
import { Stat } from './Milestones'
import type { GanttPreview } from './ProjectGantt'

const DAY_CHOICES = [3, 7, 14]

function useDay() {
  const { i18n } = useTranslation()
  return (iso: string | Date) =>
    (typeof iso === 'string' ? parseTime(iso) : iso).toLocaleDateString(i18n.resolvedLanguage, {
      month: 'short',
      day: 'numeric',
    })
}

/** The steps a delay moves, with the escrow payment each one releases when it's done. */
function Moves({ moved }: { moved: ScheduleMove[] }) {
  const { t } = useTranslation()
  const day = useDay()
  if (moved.length === 0) return null
  return (
    <div>
      <p className="text-sm font-medium">{t('rebuild.whatIf.paymentsMove')}</p>
      <ul className="mt-1 space-y-1 text-sm">
        {moved.map((m) => (
          <li key={m.milestone_id} className="flex flex-wrap justify-between gap-x-3">
            <span>
              {m.seq}. {m.title} <span className="text-ink-soft">({money(m.amount)})</span>
            </span>
            <span className="tabular-nums text-ink-soft">
              {t('rebuild.whatIf.doneBy', { from: day(m.end_before), to: day(m.end_after) })}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/** The contractor tries a delay on the chart (Bryntum's engine moves every step that waits for it), sees what moves
 * and which payments, then tells the homeowner why. The server works out the same schedule and saves it. */
export function WhatIfPanel({ p, gantt, onSaved }: { p: Project; gantt: GanttPreview | null; onSaved: () => void }) {
  const { t } = useTranslation()
  const day = useDay()
  const pending = p.milestones.filter((m) => m.status === 'pending')
  const [open, setOpen] = useState(false)
  const [milestoneId, setMilestoneId] = useState(pending[0]?.id ?? 0)
  const [days, setDays] = useState(7)
  const [reason, setReason] = useState('')
  const [engineMoveIn, setEngineMoveIn] = useState<Date | null>(null)
  const valid = open && milestoneId > 0 && days >= 1 && days <= 120

  const preview = useQuery({
    queryKey: ['what-if', p.id, milestoneId, days],
    queryFn: () =>
      api<WhatIf>(`/projects/${p.id}/what-if`, {
        method: 'POST',
        body: JSON.stringify({ milestone_id: milestoneId, days }),
      }),
    enabled: valid,
  })
  useEffect(() => {
    if (!valid || !gantt) return
    let current = true
    void gantt.preview(milestoneId, days).then((d) => current && setEngineMoveIn(d))
    return () => {
      current = false
    }
  }, [valid, gantt, milestoneId, days])
  useEffect(() => () => gantt?.clear(), [gantt]) // leaving the page puts the chart back

  const save = useMutation({
    mutationFn: () =>
      api<ScheduleChange>(`/projects/${p.id}/delays`, {
        method: 'POST',
        body: JSON.stringify({ milestone_id: milestoneId, days, reason }),
      }),
    onSuccess: () => {
      gantt?.clear()
      setOpen(false)
      setReason('')
      onSaved()
    },
  })
  const close = () => {
    gantt?.clear()
    setOpen(false)
  }

  if (pending.length === 0 || p.status !== 'active') return null
  if (!open)
    return (
      <button
        onClick={() => setOpen(true)}
        className="rounded-lg border border-line px-3 py-2 text-sm font-medium hover:bg-sunken"
      >
        {t('rebuild.whatIf.open')}
      </button>
    )

  const w = preview.data
  const step = p.milestones.find((m) => m.id === milestoneId)
  const agrees = w && engineMoveIn && Math.abs(engineMoveIn.getTime() - parseTime(w.move_in_after).getTime()) < 60_000
  const error = save.error ?? preview.error
  return (
    <section
      aria-labelledby="what-if-title"
      className="space-y-3 rounded-xl border border-line bg-surface p-4 shadow-sm"
    >
      <div>
        <h3 id="what-if-title" className="font-semibold">
          {t('rebuild.whatIf.title')}
        </h3>
        <p className="text-sm text-ink-soft">{t('rebuild.whatIf.intro')}</p>
      </div>
      <div className="flex flex-wrap items-end gap-3">
        <label className="text-sm">
          <span className="mb-1 block text-ink-soft">{t('rebuild.whatIf.step')}</span>
          <select
            value={milestoneId}
            onChange={(e) => setMilestoneId(Number(e.target.value))}
            className="rounded-lg border border-line bg-surface px-3 py-2"
          >
            {pending.map((m) => (
              <option key={m.id} value={m.id}>
                {m.seq}. {m.title}
              </option>
            ))}
          </select>
        </label>
        <label className="text-sm">
          <span className="mb-1 block text-ink-soft">{t('rebuild.whatIf.daysLate')}</span>
          <input
            type="number"
            min={1}
            max={120}
            value={days}
            onChange={(e) => setDays(Number(e.target.value))}
            className="w-24 rounded-lg border border-line bg-surface px-3 py-2"
          />
        </label>
        <div className="flex gap-1">
          {DAY_CHOICES.map((d) => (
            <button
              key={d}
              onClick={() => setDays(d)}
              aria-pressed={days === d}
              className={`rounded-full px-3 py-1.5 text-xs ${days === d ? 'bg-ink text-surface' : 'bg-sunken'}`}
            >
              {t('rebuild.whatIf.days', { count: d })}
            </button>
          ))}
        </div>
      </div>

      <div aria-live="polite" className="space-y-3 rounded-lg bg-sunken p-3">
        {w && step && (
          <>
            <p className="font-medium">
              {w.move_in_days > 0
                ? t('rebuild.whatIf.moves', {
                    from: day(w.move_in_before),
                    to: day(w.move_in_after),
                    count: w.move_in_days,
                  })
                : t('rebuild.whatIf.absorbed', { date: day(w.move_in_before), step: step.title, count: w.slack_days })}
            </p>
            {w.move_in_days > 0 && w.slack_days > 0 && (
              <p className="text-sm text-ink-soft">
                {t('rebuild.whatIf.partlyAbsorbed', { step: step.title, count: w.slack_days })}
              </p>
            )}
            <Moves moved={w.moved} />
            {engineMoveIn && (
              <p className="text-xs text-ink-faint">
                {agrees
                  ? t('rebuild.whatIf.engineAgrees')
                  : t('rebuild.whatIf.engineSays', { date: day(engineMoveIn) })}
              </p>
            )}
          </>
        )}
        {!w && preview.isFetching && <p className="text-sm text-ink-soft">…</p>}
      </div>

      <form
        className="flex flex-col gap-2 sm:flex-row sm:items-start"
        onSubmit={(e) => {
          e.preventDefault()
          save.mutate()
        }}
      >
        <label htmlFor="delay-reason" className="sr-only">
          {t('rebuild.whatIf.reasonLabel')}
        </label>
        <input
          id="delay-reason"
          value={reason}
          maxLength={300}
          onChange={(e) => setReason(e.target.value)}
          placeholder={t('rebuild.whatIf.reasonPlaceholder')}
          className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
        />
        <button
          type="submit"
          disabled={!valid || reason.trim().length < 3 || save.isPending}
          className="rounded-lg bg-ember px-3 py-2 text-sm font-medium text-on-ember disabled:opacity-40"
        >
          {t('rebuild.whatIf.tell', { name: p.household_name })}
        </button>
        <button type="button" onClick={close} className="rounded-lg px-3 py-2 text-sm text-ink-soft hover:bg-surface">
          {t('rebuild.whatIf.cancel')}
        </button>
      </form>
      {error && (
        <p className="text-sm text-danger">{error instanceof ApiError ? error.message : t('errors.generic')}</p>
      )}
    </section>
  )
}

/** What the homeowner sees after the contractor records a delay: the new move-in day, why, and what moves. */
export function ScheduleNotice({ p }: { p: Project }) {
  const { t } = useTranslation()
  const day = useDay()
  const c = p.changes[0]
  if (!c) return null
  const later = parseTime(c.move_in_after) > parseTime(c.move_in_before)
  const daysLater = Math.round((parseTime(c.move_in_after).getTime() - parseTime(c.move_in_before).getTime()) / 864e5)
  return (
    <div className="space-y-2 rounded-lg bg-amber-soft p-4">
      <p className="font-medium">
        {later
          ? t('rebuild.whatIf.noticeMoved', {
              name: p.contractor.business_name,
              date: day(c.move_in_after),
              count: daysLater,
            })
          : t('rebuild.whatIf.noticeSame', { name: p.contractor.business_name, date: day(c.move_in_after) })}
      </p>
      <p className="text-sm">
        {t('rebuild.whatIf.noticeWhy', { step: c.milestone_title, count: c.days })} <q className="italic">{c.reason}</q>
      </p>
      <Moves moved={c.moved} />
    </div>
  )
}

/** Move-in day, with the date in the plan the homeowner accepted when it has changed. */
export function MoveInStat({ p }: { p: Project }) {
  const { t } = useTranslation()
  const day = useDay()
  if (!p.move_in) return null
  const moved = p.planned_move_in !== null && day(p.planned_move_in) !== day(p.move_in)
  return (
    <Stat
      label={t('rebuild.whatIf.moveIn')}
      value={day(p.move_in)}
      hint={moved && p.planned_move_in ? t('rebuild.whatIf.planned', { date: day(p.planned_move_in) }) : undefined}
    />
  )
}
