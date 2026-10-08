import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { getPayPalSdk, type PaymentSession, type SessionCallbacks } from './paypal'

export type Method = 'paypal' | 'venmo' | 'paylater'
type PayLaterButton = HTMLElement & { productCode?: string; countryCode?: string }

/**
 * PayPal, Venmo and Pay Later one-time payments with the JS SDK v6.
 * `start(method, order)` must be called from the button's click handler; `order` is the server call that
 * creates the PayPal order. `onApprove` runs after the buyer approves (capture it on the server there).
 */
export function usePayPalCheckout(onApprove: () => Promise<void>) {
  const { t, i18n } = useTranslation()
  const [eligible, setEligible] = useState<Record<Method, boolean> | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [paying, setPaying] = useState(false)
  const sessions = useRef<Partial<Record<Method, PaymentSession>>>({})
  const payLaterButton = useRef<PayLaterButton>(null)
  const approve = useRef(onApprove)
  useEffect(() => {
    approve.current = onApprove
  })

  useEffect(() => {
    let cancelled = false
    const callbacks: SessionCallbacks = {
      async onApprove() {
        try {
          await approve.current()
        } catch (e) {
          setError(e instanceof Error ? e.message : t('errors.generic'))
        } finally {
          setPaying(false)
        }
      },
      onCancel: () => setPaying(false),
      onError: (e) => {
        setPaying(false)
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
          if (payLaterButton.current) Object.assign(payLaterButton.current, methods.getDetails('paylater'))
        }
        setEligible(flags)
      })
      .catch(() => !cancelled && setError(t('registry.paypalUnavailable')))
    return () => {
      cancelled = true
    }
  }, []) // eslint-disable-line react-hooks/exhaustive-deps

  function start(method: Method, order: Promise<{ orderId: string }>) {
    const session = sessions.current[method]
    if (!session) return
    setPaying(true)
    setError(null)
    // PayPal needs start() inside the click handler, so the order request isn't awaited first.
    session.start({ presentationMode: 'auto' }, order).catch((e: Error) => {
      setPaying(false)
      setError(e.message)
    })
  }

  return { eligible, error, paying, payLaterButton, start }
}
