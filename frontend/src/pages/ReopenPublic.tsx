import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Suspense, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import { api, type GiftCardInfo, type PublicCampaign, type Tranche } from '../api'
import { GiftCardQr } from '../components/GiftCardQr'
import { ProjectGantt } from '../components/Milestones'
import { PayButtons } from '../components/PayButtons'
import { Progress, PublicFrame } from '../components/PublicFrame'
import { money } from '../format'
import { usePayPalCheckout, type Method } from '../usePayPalCheckout'

const TRANCHE_TONE: Record<Tranche['status'], string> = {
  pending: 'bg-sunken text-ink-soft',
  requested: 'bg-amber-soft text-amber',
  released: 'bg-sage-soft text-sage',
  rejected: 'bg-sunken text-ink-soft',
}

function BuyCard({ campaign, onBought }: { campaign: PublicCampaign; onBought: () => void }) {
  const { t, i18n } = useTranslation()
  const c = campaign.campaign!
  const left = Number(c.goal_amount) - Number(c.raised)
  const [amount, setAmount] = useState(50)
  const [name, setName] = useState('')
  const [card, setCard] = useState<GiftCardInfo | null>(null)
  const cardId = useRef<number | null>(null)
  const checkout = usePayPalCheckout(async () => {
    setCard(await api<GiftCardInfo>(`/gift-cards/${cardId.current}/capture`, { method: 'POST' }))
    onBought()
  })

  function pay(method: Method) {
    const order = api<{ card_id: number; order_id: string }>(`/reopen/${campaign.slug}/cards`, {
      method: 'POST',
      body: JSON.stringify({ amount, buyer_name: name || null, payment_method: method }),
    }).then((r) => {
      cardId.current = r.card_id
      return { orderId: r.order_id }
    })
    checkout.start(method, order)
  }

  if (card) {
    return (
      <section className="rounded-xl border border-sage/40 bg-sage-soft p-5" role="status">
        <p className="text-lg font-semibold text-sage">{t('reopen.buy.thanks', { name: campaign.name })}</p>
        <div className="mt-4 flex flex-wrap items-center gap-5">
          <GiftCardQr code={card.code} />
          <div>
            <p className="text-sm text-ink-soft">{t('reopen.card.worth')}</p>
            <p className="text-3xl font-semibold">{money(card.face_value, { cents: true })}</p>
            <p className="mt-2 font-mono text-lg tracking-wider">{card.code}</p>
            <Link to={`/card/${card.code}`} className="mt-2 inline-block text-sm font-medium text-ember hover:underline">
              {t('reopen.buy.keep')}
            </Link>
          </div>
        </div>
      </section>
    )
  }

  const worth = (amount * (100 + c.bonus_percent)) / 100
  const valid = amount >= 10 && amount <= Math.min(500, left)
  return (
    <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <h2 className="text-lg font-semibold">{t('reopen.buy.title')}</h2>
      <div className="mt-3 flex flex-wrap gap-2">
        {[25, 50, 100].map((v) => (
          <button
            key={v}
            onClick={() => setAmount(v)}
            className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${amount === v ? 'border-ember bg-ember-soft text-ember' : 'border-line hover:bg-sunken'}`}
          >
            {money(v)}
          </button>
        ))}
        <label className="flex items-center gap-1 rounded-lg border border-line px-2 text-sm">
          $
          <input
            type="number"
            min={10}
            max={500}
            value={amount}
            onChange={(e) => setAmount(Number(e.target.value))}
            className="w-20 bg-transparent py-1.5 outline-none"
            aria-label={t('reopen.buy.custom')}
          />
        </label>
      </div>
      <p className="mt-3 text-sm">
        {c.bonus_percent > 0
          ? t('reopen.buy.worthBonus', { pay: money(amount), worth: money(worth, { cents: true }), bonus: c.bonus_percent })
          : t('reopen.buy.worth', { pay: money(amount) })}
      </p>
      <input
        value={name}
        onChange={(e) => setName(e.target.value)}
        placeholder={t('reopen.buy.name')}
        maxLength={80}
        className="mt-3 w-full rounded-lg border border-line bg-surface px-3 py-2 text-sm"
      />
      <PayButtons checkout={checkout} disabled={!valid} type="buynow" onPay={pay} />
      <p className="mt-3 text-xs text-ink-faint">
        {t('reopen.buy.promise', {
          name: campaign.name,
          date: new Date(c.reopen_by).toLocaleDateString(i18n.resolvedLanguage, { month: 'long', day: 'numeric' }),
        })}
      </p>
    </section>
  )
}

/** Monthly pre-payment (PayPal Subscriptions): the person approves on PayPal, then comes back to /paid. */
function BecomeRegular({ campaign }: { campaign: PublicCampaign }) {
  const { t } = useTranslation()
  const c = campaign.campaign!
  const [name, setName] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [going, setGoing] = useState(false)
  const monthlyWorth = (Number(c.regular_monthly) * (100 + c.bonus_percent)) / 100
  const start = async () => {
    setGoing(true)
    setError(null)
    try {
      const r = await api<{ regular_id: number; approval_url: string | null }>(`/reopen/${campaign.slug}/regulars`, {
        method: 'POST',
        body: JSON.stringify({ buyer_name: name || null }),
      })
      if (r.approval_url) window.location.assign(r.approval_url)
    } catch (e) {
      setError(e instanceof Error ? e.message : t('errors.generic'))
      setGoing(false)
    }
  }
  return (
    <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <h2 className="text-lg font-semibold">{t('reopen.regular.title')}</h2>
      <p className="mt-1 text-sm text-ink-soft">
        {t('reopen.regular.body', {
          monthly: money(c.regular_monthly),
          months: c.regular_months,
          worth: money(monthlyWorth, { cents: true }),
          name: campaign.name,
        })}
      </p>
      {c.regulars > 0 && <p className="mt-1 text-xs text-ink-faint">{t('reopen.regular.count', { count: c.regulars })}</p>}
      <div className="mt-3 flex flex-wrap gap-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('reopen.buy.name')}
          maxLength={80}
          className="min-w-48 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
        />
        <button
          onClick={() => void start()}
          disabled={going}
          className="rounded-lg bg-ember px-3 py-2 text-sm font-medium text-on-ember disabled:opacity-40"
        >
          {going ? t('reopen.regular.going') : t('reopen.regular.start')}
        </button>
      </div>
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </section>
  )
}

export default function ReopenPublic() {
  const { slug = '' } = useParams()
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const page = useQuery({ queryKey: ['reopen', slug], queryFn: () => api<PublicCampaign>(`/reopen/${slug}`) })
  const b = page.data
  const c = b?.campaign

  return (
    <PublicFrame>
      {page.isError && <p className="text-ink-soft">{t('reopen.notFound')}</p>}
      {page.isPending && <div className="h-64 animate-pulse rounded-xl bg-sunken" />}
      {b && c && (
        <div className="space-y-8">
          <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_24rem]">
            <div>
              <p className="text-sm font-medium text-ember">{t('reopen.badge')}</p>
              <h1 className="mt-1 text-4xl font-semibold tracking-tight">{b.name}</h1>
              <p className="mt-1 text-ink-soft">
                {t(`reopen.kind.${b.kind}`, { defaultValue: b.kind })} · {b.city}, {b.state} ·{' '}
                <span className="text-sage">✓ {t('reopen.verified')}</span>
              </p>
              <p className="mt-4 leading-relaxed">{b.story}</p>
              {c.status === 'reopened' && (
                <p className="mt-4 rounded-lg bg-sage-soft px-4 py-3 font-medium text-sage">{t('reopen.isOpen')}</p>
              )}
              {c.status === 'refunded' && (
                <p className="mt-4 rounded-lg bg-sunken px-4 py-3 text-ink-soft">{t('reopen.wasRefunded')}</p>
              )}
              <div className="mt-6 rounded-xl border border-line bg-surface p-5 shadow-sm">
                <Progress funded={Number(c.raised)} target={Number(c.goal_amount)} />
                <p className="mt-2 text-sm">
                  <span className="text-lg font-semibold">{money(c.raised)}</span>{' '}
                  <span className="text-ink-soft">
                    {t('reopen.ofGoal', { goal: money(c.goal_amount) })} · {t('reopen.cardsSold', { count: c.cards_sold })}
                  </span>
                </p>
                <p className="mt-1 text-sm text-ink-soft">
                  {t('reopen.reopensBy', {
                    date: new Date(c.reopen_by).toLocaleDateString(i18n.resolvedLanguage, {
                      month: 'long',
                      day: 'numeric',
                      year: 'numeric',
                    }),
                  })}
                  {c.bonus_percent > 0 && ` · ${t('reopen.bonus', { bonus: c.bonus_percent })}`}
                </p>
                {b.supporters.length > 0 && (
                  <p className="mt-3 text-sm text-ink-soft">
                    {t('reopen.supporters', { names: b.supporters.join(', ') })}
                  </p>
                )}
              </div>
            </div>
            {c.status === 'live' && (
              <div className="space-y-4">
                <BuyCard campaign={b} onBought={() => void queryClient.invalidateQueries({ queryKey: ['reopen', slug] })} />
                <BecomeRegular campaign={b} />
              </div>
            )}
          </div>

          <section className="space-y-3">
            <h2 className="text-xl font-semibold">{t('reopen.plan.title')}</h2>
            <p className="text-sm text-ink-soft">{t('reopen.plan.body')}</p>
            <ul className="grid gap-2 md:grid-cols-3">
              {c.tranches.map((tr) => (
                <li key={tr.id} className="rounded-xl border border-line bg-surface p-4 shadow-sm">
                  <div className="flex items-start justify-between gap-2">
                    <span className="font-medium">{tr.title}</span>
                    <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${TRANCHE_TONE[tr.status]}`}>
                      {t(`reopen.tranche.${tr.status}`)}
                    </span>
                  </div>
                  <p className="mt-1 text-sm text-ink-soft">{money(tr.amount)}</p>
                </li>
              ))}
            </ul>
            <Suspense fallback={<div className="h-64 animate-pulse rounded-xl bg-sunken" />}>
              <ProjectGantt
                base={`/bryntum/reopen/${slug}`}
                rows={c.tranches.length + 1}
                editable={false}
                compact
                label={t('reopen.plan.step')}
                hint={t('reopen.plan.hint')}
              />
            </Suspense>
          </section>
        </div>
      )}
    </PublicFrame>
  )
}
