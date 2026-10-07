import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, type RegistryItem } from '../api'
import { money } from '../format'
import { getPayPalSdk, type PaymentSession, type SessionCallbacks } from '../paypal'

type Method = 'paypal' | 'venmo' | 'paylater'
type Props = { slug: string; item: RegistryItem | null; onDone: () => void; onClose: () => void }

export default function DonatePanel({ slug, item, onDone, onClose }: Props) {
  const { t, i18n } = useTranslation()
  const remaining = item ? Number(item.remaining) : null
  const presets = item
    ? [...new Set([remaining!, Math.ceil(remaining! / 2), 25].filter((v) => v > 0 && v <= remaining!))]
    : [25, 50, 100]
  const [amount, setAmount] = useState<number>(presets[0])
  const [name, setName] = useState('')
  const [message, setMessage] = useState('')
  const [status, setStatus] = useState<'idle' | 'paying' | 'done' | 'error'>('idle')
  const [error, setError] = useState<string | null>(null)
  const [eligible, setEligible] = useState<Record<Method, boolean> | null>(null)
  const sessions = useRef<Partial<Record<Method, PaymentSession>>>({})
  const donationId = useRef<number | null>(null)
  const payLaterButton = useRef<HTMLElement & { productCode?: string; countryCode?: string }>(null)

  useEffect(() => {
    let cancelled = false
    const callbacks: SessionCallbacks = {
      async onApprove() {
        try {
          await api(`/donations/${donationId.current}/capture`, { method: 'POST' })
          setStatus('done')
          onDone()
        } catch (e) {
          setStatus('error')
          setError(e instanceof Error ? e.message : t('errors.generic'))
        }
      },
      onCancel: () => setStatus('idle'),
      onError: (e) => {
        setStatus('error')
        setError(e?.message ?? t('errors.generic'))
      },
    }
    getPayPalSdk(i18n.resolvedLanguage === 'es' ? 'es-US' : 'en-US')
      .then(async (sdk) => {
        const methods = await sdk.findEligibleMethods({ currencyCode: 'USD' })
        if (cancelled) return
        const flags = {
          paypal: methods.isEligible('paypal'),
          venmo: methods.isEligible('venmo'),
          paylater: methods.isEligible('paylater'),
        }
        if (flags.paypal) sessions.current.paypal = sdk.createPayPalOneTimePaymentSession(callbacks)
        if (flags.venmo) sessions.current.venmo = sdk.createVenmoOneTimePaymentSession(callbacks)
        if (flags.paylater) {
          sessions.current.paylater = sdk.createPayLaterOneTimePaymentSession(callbacks)
          const details = methods.getDetails('paylater')
          if (payLaterButton.current) Object.assign(payLaterButton.current, details)
        }
        setEligible(flags)
      })
      .catch(() => !cancelled && setError(t('registry.paypalUnavailable')))
    return () => {
      cancelled = true
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function pay(method: Method) {
    const session = sessions.current[method]
    if (!session) return
    setStatus('paying')
    setError(null)
    // Start the order request without awaiting it: PayPal needs start() inside the click handler.
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
    session.start({ presentationMode: 'auto' }, order).catch((e: Error) => {
      setStatus('error')
      setError(e.message)
    })
  }

  if (status === 'done') {
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

      <div className={`mt-5 grid gap-2 ${valid && status !== 'paying' ? '' : 'pointer-events-none opacity-50'}`}>
        {!eligible && !error && <div className="h-11 animate-pulse rounded-lg bg-sunken" />}
        {eligible?.paypal && <paypal-button type="donate" onClick={() => pay('paypal')} />}
        {eligible?.venmo && <venmo-button onClick={() => pay('venmo')} />}
        <paypal-pay-later-button ref={payLaterButton} hidden={!eligible?.paylater} onClick={() => pay('paylater')} />
      </div>
      <p className="mt-3 text-xs text-ink-faint">{t('registry.paymentNote')}</p>
      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}
    </div>
  )
}
