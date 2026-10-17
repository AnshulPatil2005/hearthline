import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import type { ColDef } from 'ag-grid-community'
import { AgGridReact } from 'ag-grid-react'
import { Suspense, useCallback, useMemo, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, ApiError, type BusinessInfo, type CardRow, type GiftCardInfo, type Tranche } from '../api'
import { QrScanner } from '../components/GiftCardQr'
import { ProjectGantt, Stat } from '../components/Milestones'
import { Progress } from '../components/PublicFrame'
import { money } from '../format'
import { gridTheme } from '../grid'
import { codeFrom } from '../reopen'
import { ConnectPayPal } from '../components/ConnectPayPal'

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback)
const day = (d: Date) => d.toISOString().slice(0, 10)
const inDays = (n: number) => day(new Date(Date.now() + n * 86_400_000))

type Step = { title: string; amount: string; start: string; end: string }

function CampaignSetup({ onCreated }: { onCreated: () => void }) {
  const { t } = useTranslation()
  const [bonus, setBonus] = useState(20)
  const [reopenBy, setReopenBy] = useState(inDays(45))
  const [steps, setSteps] = useState<Step[]>([
    { title: t('business.setup.example1'), amount: '', start: inDays(1), end: inDays(15) },
    { title: t('business.setup.example2'), amount: '', start: inDays(15), end: inDays(40) },
  ])
  const [error, setError] = useState<string | null>(null)
  const goal = steps.reduce((s, x) => s + (Number(x.amount) || 0), 0)
  const save = useMutation({
    mutationFn: () =>
      api('/business/me/campaign', {
        method: 'POST',
        body: JSON.stringify({
          bonus_percent: bonus,
          reopen_by: new Date(`${reopenBy}T17:00`).toISOString(),
          tranches: steps.map((s) => ({
            title: s.title,
            amount: s.amount,
            start_date: new Date(`${s.start}T09:00`).toISOString(),
            end_date: new Date(`${s.end}T17:00`).toISOString(),
          })),
        }),
      }),
    onSuccess: onCreated,
    onError: (e) => setError(errorText(e, t('errors.generic'))),
  })
  const update = (i: number, patch: Partial<Step>) => setSteps((ss) => ss.map((s, j) => (j === i ? { ...s, ...patch } : s)))
  return (
    <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <h2 className="text-lg font-semibold">{t('business.setup.title')}</h2>
      <p className="mt-1 text-sm text-ink-soft">{t('business.setup.body')}</p>
      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <label className="text-sm">
          <span className="text-ink-soft">{t('business.setup.reopenBy')}</span>
          <input
            type="date"
            value={reopenBy}
            onChange={(e) => setReopenBy(e.target.value)}
            className="mt-1 block w-full rounded-lg border border-line bg-surface px-3 py-2"
          />
        </label>
        <label className="text-sm">
          <span className="text-ink-soft">{t('business.setup.bonus', { bonus })}</span>
          <input
            type="range"
            min={0}
            max={25}
            step={5}
            value={bonus}
            onChange={(e) => setBonus(Number(e.target.value))}
            className="mt-3 block w-full accent-[var(--ember)]"
          />
        </label>
      </div>
      <h3 className="mt-5 text-sm font-semibold">{t('business.setup.steps')}</h3>
      <ol className="mt-2 space-y-2">
        {steps.map((s, i) => (
          <li key={i} className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_8rem_9rem_9rem_auto]">
            <input
              value={s.title}
              onChange={(e) => update(i, { title: e.target.value })}
              aria-label={t('business.setup.stepTitle')}
              className="rounded-lg border border-line bg-surface px-3 py-2 text-sm"
            />
            <label className="flex items-center gap-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm">
              $
              <input
                type="number"
                min={1}
                value={s.amount}
                onChange={(e) => update(i, { amount: e.target.value })}
                aria-label={t('business.setup.amount')}
                className="w-full bg-transparent outline-none"
              />
            </label>
            <input type="date" value={s.start} onChange={(e) => update(i, { start: e.target.value })} aria-label={t('rebuild.gantt.start')} className="rounded-lg border border-line bg-surface px-2 py-2 text-sm" />
            <input type="date" value={s.end} onChange={(e) => update(i, { end: e.target.value })} aria-label={t('rebuild.gantt.end')} className="rounded-lg border border-line bg-surface px-2 py-2 text-sm" />
            <button
              onClick={() => setSteps((ss) => ss.filter((_, j) => j !== i))}
              disabled={steps.length === 1}
              aria-label={t('contractor.removeRow')}
              className="rounded-lg px-2 text-ink-faint hover:bg-sunken disabled:opacity-30"
            >
              ✕
            </button>
          </li>
        ))}
      </ol>
      <button
        onClick={() => setSteps((ss) => [...ss, { title: '', amount: '', start: ss.at(-1)?.end ?? inDays(1), end: ss.at(-1)?.end ?? inDays(14) }])}
        className="mt-2 rounded-lg border border-line px-3 py-1.5 text-sm text-ink-soft hover:bg-sunken"
      >
        + {t('business.setup.addStep')}
      </button>
      <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-lg bg-sunken px-4 py-3 text-sm">
        <span>
          {t('business.setup.goal')}: <strong>{money(goal)}</strong>
        </span>
        <button
          onClick={() => save.mutate()}
          disabled={save.isPending || goal <= 0 || steps.some((s) => s.title.trim().length < 2 || !(Number(s.amount) > 0))}
          className="rounded-lg bg-ember px-4 py-2 font-medium text-on-ember disabled:opacity-40"
        >
          {t('business.setup.start')}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </section>
  )
}

function StepCard({ step, onChanged }: { step: Tranche; onChanged: () => void }) {
  const { t, i18n } = useTranslation()
  const [note, setNote] = useState('')
  const [error, setError] = useState<string | null>(null)
  const ask = useMutation({
    mutationFn: () => api(`/business/me/tranches/${step.id}/request`, { method: 'POST', body: JSON.stringify({ note }) }),
    onSuccess: () => {
      setError(null)
      onChanged()
    },
    onError: (e) => setError(errorText(e, t('errors.generic'))),
  })
  return (
    <li className="rounded-xl border border-line bg-surface p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <div>
          <div className="font-medium">
            {step.seq}. {step.title} · {money(step.amount)}
          </div>
          <div className="text-xs text-ink-faint">
            {new Date(step.start_date).toLocaleDateString(i18n.resolvedLanguage, { month: 'short', day: 'numeric' })} –{' '}
            {new Date(step.end_date).toLocaleDateString(i18n.resolvedLanguage, { month: 'short', day: 'numeric' })}
          </div>
        </div>
        <span className="rounded-full bg-sunken px-2.5 py-0.5 text-xs font-medium">{t(`business.step.${step.status}`)}</span>
      </div>
      {step.decision_note && <p className="mt-2 text-sm text-ink-soft">“{step.decision_note}”</p>}
      {(step.status === 'pending' || step.status === 'rejected') && (
        <div className="mt-3 flex flex-wrap gap-2">
          <input
            value={note}
            onChange={(e) => setNote(e.target.value)}
            placeholder={t('business.step.notePlaceholder')}
            className="min-w-48 flex-1 rounded-lg border border-line bg-surface px-3 py-1.5 text-sm"
          />
          <button
            onClick={() => ask.mutate()}
            disabled={ask.isPending}
            className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
          >
            {t('business.step.ask')}
          </button>
        </div>
      )}
      {step.status === 'requested' && <p className="mt-2 text-sm text-ink-soft">{t('business.step.waiting')}</p>}
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </li>
  )
}

function Redeem({ reopened, onRedeemed }: { reopened: boolean; onRedeemed: () => void }) {
  const { t } = useTranslation()
  const [code, setCode] = useState('')
  const [amount, setAmount] = useState('')
  const [card, setCard] = useState<GiftCardInfo | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)
  const lookUp = useCallback(
    (raw: string) => {
      const c = codeFrom(raw)
      setCode(c)
      setMessage(null)
      api<GiftCardInfo>(`/business/me/cards/${encodeURIComponent(c)}`)
        .then((found) => {
          setCard(found)
          setError(null)
        })
        .catch((e) => {
          setCard(null)
          setError(errorText(e, t('errors.generic')))
        })
    },
    [t],
  )
  const redeem = useMutation({
    mutationFn: () => api<GiftCardInfo>('/business/me/redeem', { method: 'POST', body: JSON.stringify({ code, amount }) }),
    onSuccess: (c) => {
      setMessage(t('business.redeem.done', { amount: money(amount, { cents: true }), left: money(c.balance, { cents: true }) }))
      setCard(c)
      setAmount('')
      setError(null)
      onRedeemed()
    },
    onError: (e) => setError(errorText(e, t('errors.generic'))),
  })
  return (
    <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <h2 className="text-lg font-semibold">{t('business.redeem.title')}</h2>
      <p className="mt-1 text-sm text-ink-soft">{reopened ? t('business.redeem.body') : t('business.redeem.notYet')}</p>
      <div className="mt-3 space-y-3">
        <QrScanner onCode={lookUp} />
        <form
          className="flex flex-wrap gap-2"
          onSubmit={(e) => {
            e.preventDefault()
            lookUp(code)
          }}
        >
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            placeholder={t('business.redeem.codePlaceholder')}
            aria-label={t('business.redeem.code')}
            className="min-w-48 flex-1 rounded-lg border border-line bg-surface px-3 py-2 font-mono text-sm uppercase placeholder:normal-case"
          />
          <button type="submit" className="rounded-lg border border-line px-3 py-2 text-sm hover:bg-sunken">
            {t('business.redeem.check')}
          </button>
        </form>
        {card && (
          <div className="flex flex-wrap items-center gap-2 rounded-lg bg-sunken p-3 text-sm">
            <span>
              {t('business.redeem.balance', { balance: money(card.balance, { cents: true }) })}
            </span>
            <label className="flex items-center gap-1 rounded-lg border border-line bg-surface px-2">
              $
              <input
                type="number"
                min={0.01}
                step={0.01}
                value={amount}
                onChange={(e) => setAmount(e.target.value)}
                aria-label={t('business.redeem.amount')}
                className="w-24 bg-transparent py-1.5 outline-none"
              />
            </label>
            <button
              onClick={() => redeem.mutate()}
              disabled={!reopened || redeem.isPending || !(Number(amount) > 0)}
              className="rounded-lg bg-ember px-3 py-1.5 font-medium text-on-ember disabled:opacity-40"
            >
              {t('business.redeem.take')}
            </button>
          </div>
        )}
        {message && <p className="text-sm text-sage">{message}</p>}
        {error && <p className="text-sm text-danger">{error}</p>}
      </div>
    </section>
  )
}

function CardsGrid() {
  const { t, i18n } = useTranslation()
  const cards = useQuery({ queryKey: ['business-cards'], queryFn: () => api<CardRow[]>('/business/me/cards') })
  const columns = useMemo<ColDef<CardRow>[]>(
    () => [
      { field: 'code_end', headerName: t('business.cards.code'), width: 110, valueFormatter: (p) => `…${p.value}` },
      { field: 'buyer', headerName: t('business.cards.buyer'), flex: 1, minWidth: 120 },
      { field: 'amount_paid', headerName: t('business.cards.paid'), width: 110, type: 'rightAligned', valueFormatter: (p) => money(p.value) },
      { field: 'face_value', headerName: t('business.cards.worth'), width: 110, type: 'rightAligned', valueFormatter: (p) => money(p.value, { cents: true }) },
      { field: 'balance', headerName: t('business.cards.balance'), width: 110, type: 'rightAligned', valueFormatter: (p) => money(p.value, { cents: true }) },
      { field: 'payment_method', headerName: t('business.cards.method'), width: 120, filter: 'agSetColumnFilter', valueFormatter: (p) => t(`business.cards.via.${p.value}`, { defaultValue: p.value }) },
      { field: 'status', headerName: t('business.cards.status'), width: 120, filter: 'agSetColumnFilter', valueFormatter: (p) => t(`business.cards.state.${p.value}`, { defaultValue: p.value }) },
      {
        field: 'activated_at',
        headerName: t('business.cards.bought'),
        width: 130,
        sort: 'desc',
        valueFormatter: (p) => (p.value ? new Date(p.value).toLocaleDateString(i18n.resolvedLanguage, { month: 'short', day: 'numeric' }) : ''),
      },
    ],
    [i18n.resolvedLanguage, t],
  )
  if (!cards.data?.length) return null
  return (
    <section className="space-y-2">
      <h2 className="text-lg font-semibold">{t('business.cards.title', { count: cards.data.length })}</h2>
      <div className="h-96">
        <AgGridReact<CardRow>
          theme={gridTheme}
          rowData={cards.data}
          columnDefs={columns}
          getRowId={(p) => String(p.data.id)}
          defaultColDef={{ sortable: true, resizable: true, suppressHeaderMenuButton: true }}
        />
      </div>
    </section>
  )
}

export default function BusinessHome() {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const me = useQuery({ queryKey: ['my-business'], queryFn: () => api<BusinessInfo>('/business/me') })
  const refresh = useCallback(() => {
    void queryClient.invalidateQueries({ queryKey: ['my-business'] })
    void queryClient.invalidateQueries({ queryKey: ['business-cards'] })
  }, [queryClient])
  const [confirming, setConfirming] = useState(false)
  const reopened = useMutation({ mutationFn: () => api('/business/me/reopened', { method: 'POST' }), onSuccess: refresh })

  const b = me.data
  const c = b?.campaign
  const active = c && (c.status === 'live' || c.status === 'reopened')
  return (
    <div className="space-y-6">
      {me.isPending && <div className="h-64 animate-pulse rounded-xl bg-sunken" />}
      {b && (
        <>
          <div className="flex flex-wrap items-end justify-between gap-3">
            <div>
              <h1 className="text-3xl font-semibold tracking-tight">{b.name}</h1>
              <p className="mt-1 text-ink-soft">{t('business.subtitle')}</p>
            </div>
            {b.verification === 'verified' && c && (
              <Link to={`/reopen/${b.slug}`} target="_blank" className="text-sm font-medium text-ember hover:underline">
                {t('business.publicPage')} ↗
              </Link>
            )}
          </div>
          <ConnectPayPal />
          {b.verification !== 'verified' && (
            <p className="rounded-xl border border-line bg-surface px-4 py-3 shadow-sm">
              {t(`business.verification.${b.verification}`)}
              {b.verification_note && <span className="block text-sm text-ink-soft">“{b.verification_note}”</span>}
            </p>
          )}
          {b.verification === 'verified' && !active && <CampaignSetup onCreated={refresh} />}
          {c && active && (
            <>
              <div className="rounded-xl border border-line bg-surface p-5 shadow-sm">
                <Progress funded={Number(c.raised)} target={Number(c.goal_amount)} />
                <div className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
                  <Stat label={t('business.stat.raised')} value={money(c.raised)} hint={t('reopen.ofGoal', { goal: money(c.goal_amount) })} />
                  <Stat label={t('business.stat.escrow')} value={money(c.escrow)} hint={t('business.stat.escrowHint')} />
                  <Stat label={t('business.stat.released')} value={money(c.released)} />
                  <Stat label={t('business.stat.redeemed')} value={money(c.redeemed, { cents: true })} />
                  <Stat label={t('business.stat.cards')} value={c.cards_sold.toLocaleString(i18n.resolvedLanguage)} hint={t('reopen.bonus', { bonus: c.bonus_percent })} />
                </div>
                {c.status === 'live' && (
                  <div className="mt-4 flex flex-wrap items-center gap-3">
                    {confirming ? (
                      <>
                        <span className="text-sm">{t('business.reopen.confirm')}</span>
                        <button onClick={() => reopened.mutate()} className="rounded-lg bg-sage px-3 py-1.5 text-sm font-medium text-white">
                          {t('business.reopen.yes')}
                        </button>
                        <button onClick={() => setConfirming(false)} className="text-sm text-ink-soft">
                          {t('command.batch.cancel')}
                        </button>
                      </>
                    ) : (
                      <button onClick={() => setConfirming(true)} className="rounded-lg border border-sage px-3 py-1.5 text-sm font-medium text-sage hover:bg-sage-soft">
                        {t('business.reopen.button')}
                      </button>
                    )}
                    <span className="text-xs text-ink-faint">
                      {t('business.reopen.deadline', {
                        date: new Date(c.reopen_by).toLocaleDateString(i18n.resolvedLanguage, { month: 'long', day: 'numeric' }),
                      })}
                    </span>
                  </div>
                )}
                {c.status === 'reopened' && <p className="mt-4 font-medium text-sage">{t('business.reopen.done')}</p>}
              </div>

              <section className="space-y-3">
                <h2 className="text-lg font-semibold">{t('business.steps')}</h2>
                <ul className="grid gap-3 lg:grid-cols-3">
                  {c.tranches.map((s) => (
                    <StepCard key={s.id} step={s} onChanged={refresh} />
                  ))}
                </ul>
                <Suspense fallback={<div className="h-64 animate-pulse rounded-xl bg-sunken" />}>
                  <ProjectGantt
                    key={c.tranches.map((s) => s.status).join()}
                    base={`/bryntum/reopen/${b.slug}`}
                    rows={c.tranches.length + 1}
                    editable
                    onSynced={refresh}
                    label={t('reopen.plan.step')}
                    hint={t('business.ganttHint')}
                  />
                </Suspense>
              </section>

              <Redeem reopened={c.status === 'reopened'} onRedeemed={refresh} />
              <CardsGrid />
            </>
          )}
        </>
      )}
    </div>
  )
}
