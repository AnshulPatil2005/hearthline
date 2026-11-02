import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState, type FormEvent } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, ApiError, type GivingMandate, type MandateGift, type MandateOptions, type MandateRound } from '../api'
import { money } from '../format'

const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback)

const STATUS_TONE: Record<GivingMandate['status'], string> = {
  pending: 'bg-sunken text-ink-soft',
  saving: 'bg-amber-soft text-amber',
  active: 'bg-sage-soft text-sage',
  paused: 'bg-amber-soft text-amber',
  revoked: 'bg-sunken text-ink-soft',
}

const GIFT_TONE: Record<MandateGift['status'], string> = {
  claimed: 'bg-sunken text-ink-soft',
  checking: 'bg-amber-soft text-amber',
  given: 'bg-sage-soft text-sage',
  failed: 'bg-danger-soft text-danger',
}

/** The donor sets limits, then saves their PayPal account at PayPal (Vault); PayPal sends them to /giving/mandate. */
function MandateForm() {
  const { t } = useTranslation()
  const options = useQuery({
    queryKey: ['mandate-options'],
    queryFn: () => api<MandateOptions>('/donors/me/mandates/options'),
  })
  const [states, setStates] = useState<string[]>([])
  const [categories, setCategories] = useState<string[]>([])
  const [perGift, setPerGift] = useState('50')
  const [monthly, setMonthly] = useState('150')
  const [note, setNote] = useState('')
  const start = useMutation({
    mutationFn: () =>
      api<{ approve_url: string }>('/donors/me/mandates', {
        method: 'POST',
        body: JSON.stringify({ states, categories, per_gift_max: perGift, monthly_max: monthly, note }),
      }),
    onSuccess: (r) => window.location.assign(r.approve_url),
  })
  const toggle = (list: string[], value: string) =>
    list.includes(value) ? list.filter((v) => v !== value) : [...list, value]
  const submit = (e: FormEvent) => {
    e.preventDefault()
    start.mutate()
  }
  const o = options.data
  return (
    <form onSubmit={submit} className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <label className="block text-sm">
          <span className="font-medium">{t('mandate.perGift')}</span>
          <input
            id="mandate-per-gift"
            type="number"
            min={1}
            max={o ? Number(o.max_per_gift) : undefined}
            step="1"
            value={perGift}
            onChange={(e) => setPerGift(e.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2"
          />
        </label>
        <label className="block text-sm">
          <span className="font-medium">{t('mandate.monthly')}</span>
          <input
            id="mandate-monthly"
            type="number"
            min={1}
            max={o ? Number(o.max_monthly) : undefined}
            step="1"
            value={monthly}
            onChange={(e) => setMonthly(e.target.value)}
            className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2"
          />
        </label>
      </div>
      <fieldset className="text-sm">
        <legend className="font-medium">{t('mandate.where')}</legend>
        <p className="text-ink-faint">{states.length ? t('mandate.whereSome') : t('mandate.whereAnywhere')}</p>
        <div className="mt-2 flex flex-wrap items-center gap-2">
          {states.map((s) => (
            <button
              key={s}
              type="button"
              onClick={() => setStates(toggle(states, s))}
              aria-label={t('mandate.removeState', { state: s })}
              className="rounded-full bg-ember-soft px-2.5 py-1 text-xs font-medium text-ember"
            >
              {s} ×
            </button>
          ))}
          <select
            id="mandate-state"
            value=""
            onChange={(e) => e.target.value && setStates(toggle(states, e.target.value))}
            aria-label={t('mandate.addState')}
            className="rounded-lg border border-line bg-surface px-2 py-1 text-sm"
          >
            <option value="">{t('mandate.addState')}</option>
            {o?.states
              .filter((s) => !states.includes(s))
              .map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
          </select>
        </div>
      </fieldset>
      <fieldset className="text-sm">
        <legend className="font-medium">{t('mandate.what')}</legend>
        <p className="text-ink-faint">{categories.length ? t('mandate.whatSome') : t('mandate.whatAny')}</p>
        <div className="mt-2 flex flex-wrap gap-2">
          {o?.categories.map((c) => (
            <button
              key={c}
              type="button"
              aria-pressed={categories.includes(c)}
              onClick={() => setCategories(toggle(categories, c))}
              className={`rounded-full border px-2.5 py-1 text-xs font-medium ${categories.includes(c) ? 'border-ember bg-ember-soft text-ember' : 'border-line hover:bg-sunken'}`}
            >
              {t(`localShop.category.${c}`, { defaultValue: c })}
            </button>
          ))}
        </div>
      </fieldset>
      <label className="block text-sm">
        <span className="font-medium">{t('mandate.note')}</span>
        <textarea
          id="mandate-note"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          maxLength={280}
          rows={2}
          placeholder={t('mandate.notePlaceholder')}
          className="mt-1 w-full rounded-lg border border-line bg-surface px-3 py-2"
        />
      </label>
      <div className="flex flex-wrap items-center gap-3">
        <button
          type="submit"
          disabled={start.isPending || !(Number(perGift) > 0) || !(Number(monthly) >= Number(perGift))}
          className="rounded-lg bg-ember px-4 py-2 text-sm font-medium text-on-ember disabled:opacity-40"
        >
          {start.isPending ? t('mandate.opening') : t('mandate.save')}
        </button>
        <span className="text-xs text-ink-faint">{t('mandate.saveHint')}</span>
      </div>
      {start.isError && <p className="text-sm text-danger">{errorText(start.error, t('errors.generic'))}</p>}
    </form>
  )
}

function GiftRow({ gift }: { gift: MandateGift }) {
  const { t } = useTranslation()
  return (
    <li className="space-y-1 py-3">
      <div className="flex flex-wrap items-center justify-between gap-2 text-sm">
        <span className="font-medium">
          {gift.item} · {money(gift.amount, { cents: true })}
        </span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${GIFT_TONE[gift.status]}`}>
          {t(`mandate.giftStatus.${gift.status}`)}
        </span>
      </div>
      <Link to={`/r/${gift.registry_slug}`} className="text-sm text-ember hover:underline">
        {gift.family}
      </Link>
      {gift.reason && (
        <p className="text-sm text-ink-soft">
          {gift.by_ai && (
            <span className="mr-1.5 rounded bg-ember-soft px-1.5 py-0.5 text-xs font-medium text-ember">AI</span>
          )}
          {gift.reason}
        </p>
      )}
      {gift.error && <p className="text-xs text-danger">{gift.error}</p>}
    </li>
  )
}

function MandateCard({ m }: { m: GivingMandate }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [summary, setSummary] = useState<string | null>(null)
  const save = (next: GivingMandate) =>
    queryClient.setQueryData<GivingMandate[]>(['mandates'], (all) => all?.map((x) => (x.id === next.id ? next : x)))
  const act = useMutation({
    mutationFn: (action: 'pause' | 'resume' | 'revoke') =>
      api<GivingMandate>(`/donors/me/mandates/${m.id}/${action}`, { method: 'POST' }),
    onSuccess: (r) => {
      save(r)
      setConfirming(false)
    },
  })
  const run = useMutation({
    mutationFn: () => api<MandateRound>(`/donors/me/mandates/${m.id}/run`, { method: 'POST' }),
    onSuccess: (r) => {
      save(r.mandate)
      setSummary(r.summary)
      void queryClient.invalidateQueries({ queryKey: ['giving'] })
    },
  })
  const used = Number(m.monthly_max) ? Math.min(100, (Number(m.given_this_month) / Number(m.monthly_max)) * 100) : 0
  const busy = act.isPending || run.isPending
  const error = act.error ?? run.error
  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <dl className="grid gap-1 text-sm">
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-ink-faint">{t('mandate.from')}</dt>
            <dd className="font-medium">{m.paypal_email ?? '…'}</dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-ink-faint">{t('mandate.limits')}</dt>
            <dd>{t('mandate.limitsValue', { gift: money(m.per_gift_max), month: money(m.monthly_max) })}</dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-ink-faint">{t('mandate.where')}</dt>
            <dd>{m.states.length ? m.states.join(', ') : t('mandate.anywhere')}</dd>
          </div>
          <div className="flex flex-wrap gap-x-2">
            <dt className="text-ink-faint">{t('mandate.what')}</dt>
            <dd>
              {m.categories.length
                ? m.categories.map((c) => t(`localShop.category.${c}`, { defaultValue: c })).join(', ')
                : t('mandate.anyNeed')}
            </dd>
          </div>
          {m.note && (
            <div className="flex flex-wrap gap-x-2">
              <dt className="text-ink-faint">{t('mandate.yourWords')}</dt>
              <dd>“{m.note}”</dd>
            </div>
          )}
        </dl>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_TONE[m.status]}`}>
          {t(`mandate.status.${m.status}`)}
        </span>
      </div>
      <div>
        <div className="flex justify-between text-sm">
          <span>{t('mandate.thisMonth')}</span>
          <span className="tabular-nums">
            {money(m.given_this_month, { cents: true })} / {money(m.monthly_max)}
          </span>
        </div>
        <div
          className="mt-1 h-2 rounded-full bg-sunken"
          role="progressbar"
          aria-label={t('mandate.thisMonth')}
          aria-valuemin={0}
          aria-valuemax={100}
          aria-valuenow={Math.round(used)}
        >
          <div className="h-2 rounded-full bg-sage" style={{ width: `${used}%` }} />
        </div>
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {m.status === 'active' && (
          <button
            onClick={() => run.mutate()}
            disabled={busy}
            className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
          >
            {run.isPending ? t('mandate.giving') : t('mandate.giveNow')}
          </button>
        )}
        {m.status === 'active' && (
          <button
            onClick={() => act.mutate('pause')}
            disabled={busy}
            className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken"
          >
            {t('mandate.pause')}
          </button>
        )}
        {m.status === 'paused' && (
          <button
            onClick={() => act.mutate('resume')}
            disabled={busy}
            className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken"
          >
            {t('mandate.resume')}
          </button>
        )}
        {confirming ? (
          <span className="flex flex-wrap items-center gap-2 text-sm">
            {t('mandate.revokeConfirm')}
            <button
              onClick={() => act.mutate('revoke')}
              disabled={busy}
              className="rounded-lg bg-danger px-3 py-1.5 font-medium text-white disabled:opacity-40"
            >
              {t('mandate.revokeYes')}
            </button>
            <button onClick={() => setConfirming(false)} className="underline">
              {t('mandate.cancel')}
            </button>
          </span>
        ) : (
          <button onClick={() => setConfirming(true)} disabled={busy} className="text-sm text-danger hover:underline">
            {t('mandate.revoke')}
          </button>
        )}
      </div>
      <div aria-live="polite">
        {summary && <p className="rounded-lg bg-sunken px-3 py-2 text-sm">{summary}</p>}
        {error && <p className="text-sm text-danger">{errorText(error, t('errors.generic'))}</p>}
        {m.error && <p className="text-sm text-amber">{m.error}</p>}
      </div>
      {m.gifts.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold">{t('mandate.gifts')}</h3>
          <ul className="divide-y divide-line">
            {m.gifts.map((g) => (
              <GiftRow key={g.id} gift={g} />
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}

/** Giving mandates on the donor's Giving page: set one up, or see and control the one that's giving. */
export function GivingMandates() {
  const { t } = useTranslation()
  const mandates = useQuery({ queryKey: ['mandates'], queryFn: () => api<GivingMandate[]>('/donors/me/mandates') })
  const current = mandates.data?.find((m) => ['active', 'paused', 'saving'].includes(m.status))
  if (mandates.isPending) return null
  return (
    <section aria-labelledby="mandate-title" className="panel p-5">
      <h2 id="mandate-title" className="text-lg font-semibold">
        {t('mandate.title')}
      </h2>
      <p className="mt-1 mb-4 max-w-3xl text-sm text-ink-soft">
        {current ? t('mandate.activeIntro') : t('mandate.intro')}
      </p>
      {current ? <MandateCard m={current} /> : <MandateForm />}
    </section>
  )
}
