import { useQuery } from '@tanstack/react-query'
import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type FxRates, type RegistryItem } from '../api'
import { money } from '../format'
import { usePayPalCheckout, type Method } from '../usePayPalCheckout'
import { PayButtons } from './PayButtons'

type Props = { slug: string; item: RegistryItem | null; onDone: () => void; onClose: () => void }

// A first guess at the giver's currency, from the browser's locale (they can change it)
const REGION_CURRENCY: Record<string, string> = { MX: 'MXN', PH: 'PHP', CA: 'CAD', GB: 'GBP' }
const EURO = new Set(['AT', 'BE', 'DE', 'ES', 'FI', 'FR', 'GR', 'IE', 'IT', 'NL', 'PT'])
function guessCurrency(): string {
  const region = (navigator.language.split('-')[1] ?? '').toUpperCase()
  return REGION_CURRENCY[region] ?? (EURO.has(region) ? 'EUR' : 'USD')
}

export default function DonatePanel({ slug, item, onDone, onClose }: Props) {
  const { t, i18n } = useTranslation()
  const fx = useQuery({ queryKey: ['fx'], queryFn: () => api<FxRates>('/fx'), staleTime: 60 * 60_000 })
  const [currency, setCurrency] = useState(guessCurrency)
  const foreign = currency !== 'USD' && !!fx.data?.per_usd[currency]
  const rate = foreign ? Number(fx.data!.per_usd[currency]) * Number(fx.data!.spread) : 1
  const toGiver = (usd: number) => (foreign ? Math.ceil(usd * rate) : usd) // what they pay for the family to get usd
  const toFamily = (given: number) => (foreign ? given / rate : given) // about what the family gets
  const remaining = item ? Number(item.remaining) : null
  const usdPresets = item
    ? [...new Set([remaining!, Math.ceil(remaining! / 2), 25].filter((v) => v > 0 && v <= remaining!))]
    : [25, 50, 100]
  const presets = usdPresets.map(toGiver)
  const [picked, setAmount] = useState<number | null>(null)
  const amount = picked ?? presets[0]
  const names = new Intl.DisplayNames([i18n.resolvedLanguage ?? 'en'], { type: 'currency' })
  const shown = (v: number) => money(v, { currency: foreign ? currency : 'USD' })
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  const [done, setDone] = useState(false)
  const donationId = useRef<number | null>(null)
  const checkout = usePayPalCheckout(async () => {
    await api(`/donations/${donationId.current}/capture`, { method: 'POST' })
    setDone(true)
    onDone()
  })

  function pay(method: Method) {
    const order = api<{ donation_id: number; order_id: string }>(`/registries/${slug}/donations`, {
      method: 'POST',
      body: JSON.stringify({
        item_id: item?.id ?? null,
        amount,
        currency: foreign ? currency : 'USD',
        donor_name: name || null,
        message,
        payment_method: method,
      }),
    }).then((r) => {
      donationId.current = r.donation_id
      return { orderId: r.order_id }
    })
    checkout.start(method, order)
  }

  if (done) {
    return (
      <div className="rounded-xl border border-sage/40 bg-sage-soft p-5" role="status">
        <p className="text-lg font-semibold text-sage">{t('registry.thanks', { amount: shown(amount) })}</p>
        <p className="mt-1 text-sm text-ink-soft">{t('registry.thanksBody')}</p>
        <button onClick={onClose} className="mt-3 text-sm font-medium text-ember hover:underline">
          {t('registry.close')}
        </button>
      </div>
    )
  }

  const valid = amount >= 1 && (remaining === null || toFamily(amount) <= remaining * (foreign ? 1.02 : 1))
  return (
    <div className="panel p-5">
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-semibold">
          {item ? t('registry.fundItem', { name: item.name }) : t('registry.fundGeneral')}
        </h3>
        <button onClick={onClose} aria-label={t('registry.close')} className="text-ink-faint hover:text-ink">
          ✕
        </button>
      </div>

      <label className="mt-4 flex flex-wrap items-center gap-2 text-sm">
        <span className="text-ink-soft">{t('registry.giveIn')}</span>
        <select
          name="currency"
          value={foreign ? currency : 'USD'}
          onChange={(e) => {
            setCurrency(e.target.value)
            setAmount(null)
          }}
          className="rounded-lg border border-line bg-surface px-2 py-1.5"
        >
          {['USD', ...Object.keys(fx.data?.names ?? {})].map((c) => (
            <option key={c} value={c}>
              {c} · {names.of(c)}
            </option>
          ))}
        </select>
      </label>

      <fieldset className="mt-4">
        <legend className="text-sm text-ink-soft">{t('registry.amount')}</legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {presets.map((p) => (
            <button
              key={p}
              onClick={() => setAmount(p)}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${amount === p ? 'border-ember bg-ember-soft text-ember' : 'border-line hover:bg-sunken'}`}
            >
              {shown(p)}
              {item && p === presets[0] && usdPresets[0] === remaining && (
                <span className="ml-1 font-normal text-ink-faint">· {t('registry.fullItem')}</span>
              )}
            </button>
          ))}
          <label className="flex items-center gap-1 rounded-lg border border-line px-2 text-sm">
            {foreign ? currency : '$'}
            <input
              type="number"
              min={1}
              max={remaining === null ? undefined : toGiver(remaining)}
              value={amount}
              onChange={(e) => setAmount(Number(e.target.value))}
              className="w-20 bg-transparent py-1.5 outline-none"
              aria-label={t('registry.customAmount')}
            />
          </label>
        </div>
      </fieldset>
      {foreign && (
        <p className="mt-2 text-sm text-ink-soft" aria-live="polite">
          {t('registry.fxEstimate', { usd: money(toFamily(amount)), given: shown(amount) })}
        </p>
      )}

      <div className="mt-4 grid gap-3 sm:grid-cols-2">
        <input
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder={t('registry.yourName')}
          maxLength={80}
          className="rounded-lg border border-line bg-surface px-3 py-2 text-sm"
        />
        <input
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          placeholder={t('registry.message')}
          maxLength={280}
          className="rounded-lg border border-line bg-surface px-3 py-2 text-sm"
        />
      </div>

      <PayButtons
        checkout={checkout}
        disabled={!valid}
        type="donate"
        onPay={pay}
        only={foreign ? ['paypal'] : undefined}
      />
      <p className="mt-3 text-xs text-ink-faint">{t('registry.paymentNote')}</p>
    </div>
  )
}
