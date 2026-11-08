import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import { api, ApiError, type GiftCardInfo, type RegularInfo } from '../api'
import { GiftCardQr } from '../components/GiftCardQr'
import { PublicFrame } from '../components/PublicFrame'
import { money } from '../format'

type DonationDone = { amount?: string; remaining?: string; name?: string }

/**
 * Where PayPal sends someone after approving a payment that was prepared through the public API or an AI
 * agent. Capturing here is what actually takes the money; the PayPal webhook is the backup if this tab closes.
 */
export default function PaymentReturn() {
  const { t } = useTranslation()
  const [params] = useSearchParams()
  const kind = params.get('kind')
  const id = params.get('id')
  const token = encodeURIComponent(params.get('t') ?? '') // a gift card's or regular's proof of purchase
  const cancelled = params.get('cancelled') === '1'
  const capture = useQuery<GiftCardInfo | DonationDone | RegularInfo>({
    queryKey: ['paid', kind, id],
    enabled: !cancelled && !!id && (kind === 'donation' || kind === 'gift_card' || kind === 'regular'),
    retry: false,
    staleTime: Infinity, // capture once per visit
    queryFn: () =>
      kind === 'gift_card'
        ? api<GiftCardInfo>(`/gift-cards/${id}/capture?token=${token}`, { method: 'POST' })
        : kind === 'regular'
          ? api<RegularInfo>(`/regulars/${id}/sync?token=${token}`, { method: 'POST' })
          : api<DonationDone>(`/donations/${id}/capture`, { method: 'POST' }),
  })
  const card =
    kind === 'gift_card'
      ? (capture.data as GiftCardInfo | undefined)
      : kind === 'regular'
        ? (capture.data as RegularInfo | undefined)?.card
        : undefined

  return (
    <PublicFrame>
      <div className="mx-auto max-w-lg rounded-2xl border border-line bg-surface p-6 text-center shadow-sm">
        {cancelled && <p className="text-lg">{t('paid.cancelled')}</p>}
        {capture.isPending && !cancelled && <p className="text-ink-soft">{t('paid.finishing')}</p>}
        {capture.isError && (
          <p className="text-danger">
            {capture.error instanceof ApiError ? capture.error.message : t('errors.generic')}
          </p>
        )}
        {capture.data !== undefined && kind === 'donation' && (
          <>
            <p className="text-2xl font-semibold text-sage">{t('paid.thanks')}</p>
            <p className="mt-2 text-ink-soft">{t('paid.donationBody')}</p>
          </>
        )}
        {card && (
          <>
            <p className="text-2xl font-semibold text-sage">
              {kind === 'regular' ? t('paid.regularReady') : t('paid.cardReady')}
            </p>
            <div className="mt-4 flex justify-center">
              <GiftCardQr code={card.code} />
            </div>
            <p className="mt-2 font-mono text-lg">{card.code}</p>
            <p className="text-sm text-ink-soft">
              {t('reopen.card.worth')} {money(card.face_value, { cents: true })}
            </p>
            <Link
              to={`/card/${card.code}`}
              className="mt-3 inline-block text-sm font-medium text-ember hover:underline"
            >
              {t('reopen.buy.keep')}
            </Link>
          </>
        )}
      </div>
    </PublicFrame>
  )
}
