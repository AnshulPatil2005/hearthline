import { useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type RegistryItem } from '../api'
import { money } from '../format'
import { usePayPalCheckout, type Method } from '../usePayPalCheckout'
import { PayButtons } from './PayButtons'

type Props = { slug: string; item: RegistryItem | null; onDone: () => void; onClose: () => void }

export default function DonatePanel({ slug, item, onDone, onClose }: Props) {
  const { t } = useTranslation()
  const remaining = item ? Number(item.remaining) : null
  const presets = item
    ? [...new Set([remaining!, Math.ceil(remaining! / 2), 25].filter((v) => v > 0 && v <= remaining!))]
    : [25, 50, 100]
  const [amount, setAmount] = useState<number>(presets[0])
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
        <p className="text-lg font-semibold text-sage">{t('registry.thanks', { amount: money(amount) })}</p>
        <p className="mt-1 text-sm text-ink-soft">{t('registry.thanksBody')}</p>
        <button onClick={onClose} className="mt-3 text-sm font-medium text-ember hover:underline">
          {t('registry.close')}
        </button>
      </div>
    )
  }

  const valid = amount >= 1 && (remaining === null || amount <= remaining)
  return (
    <div className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <h3 className="font-semibold">
          {item ? t('registry.fundItem', { name: item.name }) : t('registry.fundGeneral')}
        </h3>
        <button onClick={onClose} aria-label={t('registry.close')} className="text-ink-faint hover:text-ink">
          ✕
        </button>
      </div>

      <fieldset className="mt-4">
        <legend className="text-sm text-ink-soft">{t('registry.amount')}</legend>
        <div className="mt-2 flex flex-wrap gap-2">
          {presets.map((p) => (
            <button
              key={p}
              onClick={() => setAmount(p)}
              className={`rounded-lg border px-3 py-1.5 text-sm font-medium ${amount === p ? 'border-ember bg-ember-soft text-ember' : 'border-line hover:bg-sunken'}`}
            >
              {money(p)}
              {item && p === remaining && (
                <span className="ml-1 font-normal text-ink-faint">· {t('registry.fullItem')}</span>
              )}
            </button>
          ))}
          <label className="flex items-center gap-1 rounded-lg border border-line px-2 text-sm">
            $
            <input
              type="number"
              min={1}
              max={remaining ?? 10000}
              value={amount}
              onChange={(e) => setAmount(Number(e.target.value))}
              className="w-20 bg-transparent py-1.5 outline-none"
              aria-label={t('registry.customAmount')}
            />
          </label>
        </div>
      </fieldset>

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

      <PayButtons checkout={checkout} disabled={!valid} type="donate" onPay={pay} />
      <p className="mt-3 text-xs text-ink-faint">{t('registry.paymentNote')}</p>
    </div>
  )
}
