import type { usePayPalCheckout, Method } from '../usePayPalCheckout'

type Props = {
  checkout: ReturnType<typeof usePayPalCheckout>
  disabled: boolean
  type?: 'pay' | 'donate' | 'buynow' | 'checkout'
  onPay: (method: Method) => void
  only?: Method[] // e.g. a gift in another currency: PayPal only (Venmo and Pay Later take dollars)
}

/** The PayPal, Venmo and Pay Later buttons that are eligible for this buyer, plus any error. */
export function PayButtons({ checkout, disabled, type = 'pay', onPay, only }: Props) {
  const { error, paying, payLaterButton } = checkout
  const eligible = checkout.eligible && {
    paypal: checkout.eligible.paypal && (!only || only.includes('paypal')),
    venmo: checkout.eligible.venmo && (!only || only.includes('venmo')),
    paylater: checkout.eligible.paylater && (!only || only.includes('paylater')),
  }
  return (
    <>
      <div className={`mt-5 grid gap-2 ${!disabled && !paying ? '' : 'pointer-events-none opacity-50'}`}>
        {!eligible && !error && <div className="h-11 animate-pulse rounded-lg bg-sunken" />}
        {eligible?.paypal && <paypal-button type={type} onClick={() => onPay('paypal')} />}
        {eligible?.venmo && <venmo-button onClick={() => onPay('venmo')} />}
        <paypal-pay-later-button ref={payLaterButton} hidden={!eligible?.paylater} onClick={() => onPay('paylater')} />
      </div>
      {error && (
        <p role="alert" className="mt-3 text-sm text-danger">
          {error}
        </p>
      )}
    </>
  )
}
