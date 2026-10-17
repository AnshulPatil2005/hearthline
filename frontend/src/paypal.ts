/** PayPal JS SDK v6: loads the core script once and creates one SDK instance for the page. */
import { api } from './api'

type OrderPromise = Promise<{ orderId: string }>

export type PaymentSession = {
  start(options: { presentationMode: 'auto' | 'popup' | 'modal' | 'redirect' }, order: OrderPromise): Promise<void>
}

export type SessionCallbacks = {
  onApprove(data: { orderId: string }): Promise<void> | void
  onCancel?(data: { orderId?: string }): void
  onError?(error: Error): void
}

export type PayPalSdk = {
  findEligibleMethods(options: { currencyCode: string }): Promise<{
    isEligible(method: 'paypal' | 'venmo' | 'paylater' | 'credit'): boolean
    getDetails(method: string): { productCode?: string; countryCode?: string }
  }>
  createPayPalOneTimePaymentSession(callbacks: SessionCallbacks): PaymentSession
  createVenmoOneTimePaymentSession(callbacks: SessionCallbacks): PaymentSession
  createPayLaterOneTimePaymentSession(callbacks: SessionCallbacks): PaymentSession
}

declare global {
  interface Window {
    paypal?: { createInstance(options: Record<string, unknown>): Promise<PayPalSdk> }
  }
}

const SCRIPT_URL = {
  sandbox: 'https://www.sandbox.paypal.com/web-sdk/v6/core',
  live: 'https://www.paypal.com/web-sdk/v6/core',
}

let instance: Promise<PayPalSdk> | null = null

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    if (window.paypal) return resolve()
    const script = document.createElement('script')
    script.src = src
    script.async = true
    script.onload = () => resolve()
    script.onerror = () => reject(new Error('Could not load PayPal'))
    document.head.appendChild(script)
  })
}

export function getPayPalSdk(locale: string): Promise<PayPalSdk> {
  instance ??= (async () => {
    const { client_id, environment } = await api<{ client_id: string; environment: 'sandbox' | 'live' }>('/paypal/client-id')
    await loadScript(SCRIPT_URL[environment])
    return window.paypal!.createInstance({
      clientId: client_id,
      components: ['paypal-payments', 'venmo-payments'],
      pageType: 'checkout',
      locale,
      // Sandbox only: pretend the buyer is in the US so Venmo and Pay Later can be tested.
      ...(environment === 'sandbox' ? { testBuyerCountry: 'US' } : {}),
    })
  })().catch((e) => {
    instance = null // allow a retry
    throw e
  })
  return instance
}
