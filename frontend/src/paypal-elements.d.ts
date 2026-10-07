// PayPal JS SDK v6 web components, so TSX accepts them.
import type { DetailedHTMLProps, HTMLAttributes } from 'react'

type PayPalButtonProps = DetailedHTMLProps<HTMLAttributes<HTMLElement>, HTMLElement> & {
  type?: 'pay' | 'checkout' | 'donate' | 'buynow'
  hidden?: boolean
}

declare module 'react' {
  // eslint-disable-next-line @typescript-eslint/no-namespace
  namespace JSX {
    interface IntrinsicElements {
      'paypal-button': PayPalButtonProps
      'venmo-button': PayPalButtonProps
      'paypal-pay-later-button': PayPalButtonProps
    }
  }
}
