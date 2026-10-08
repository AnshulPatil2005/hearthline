import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useParams } from 'react-router'
import { api, type GiftCardInfo } from '../api'
import { GiftCardQr } from '../components/GiftCardQr'
import { PublicFrame } from '../components/PublicFrame'
import { money } from '../format'

/** The buyer's gift card: a QR code to show at the counter and what's left on it. */
export default function GiftCardView() {
  const { code = '' } = useParams()
  const { t, i18n } = useTranslation()
  const card = useQuery({ queryKey: ['card', code], queryFn: () => api<GiftCardInfo>(`/gift-cards/${code}`) })
  const c = card.data
  const date = (d: string) => new Date(d).toLocaleDateString(i18n.resolvedLanguage, { month: 'long', day: 'numeric' })

  return (
    <PublicFrame>
      {card.isError && <p className="text-ink-soft">{t('reopen.card.notFound')}</p>}
      {card.isPending && <div className="mx-auto h-96 max-w-md animate-pulse rounded-2xl bg-sunken" />}
      {c && (
        <div className="mx-auto max-w-md rounded-2xl border border-line bg-surface p-6 text-center shadow-sm">
          <p className="text-sm font-medium text-ember">{t('reopen.card.title')}</p>
          <h1 className="mt-1 text-2xl font-semibold">{c.business_name}</h1>
          <div className="mt-5 flex justify-center">
            <GiftCardQr code={c.code} size={220} />
          </div>
          <p className="mt-3 font-mono text-lg tracking-wider">{c.code}</p>
          {c.status === 'refunded' ? (
            <p className="mt-4 rounded-lg bg-sunken px-4 py-3 text-sm text-ink-soft">
              {t('reopen.card.refunded', { amount: money(c.refunded_amount, { cents: true }) })}
            </p>
          ) : (
            <>
              <p className="mt-4 text-sm text-ink-soft">{t('reopen.card.balance')}</p>
              <p className="text-4xl font-semibold">{money(c.balance, { cents: true })}</p>
              <p className="text-xs text-ink-faint">
                {t('reopen.card.paid', { paid: money(c.amount_paid), worth: money(c.face_value, { cents: true }) })}
              </p>
              <p className="mt-4 rounded-lg bg-sunken px-4 py-3 text-sm">
                {c.campaign_status === 'reopened'
                  ? t('reopen.card.useNow')
                  : t('reopen.card.useLater', { name: c.business_name, date: date(c.reopen_by) })}
              </p>
            </>
          )}
          <Link to={`/reopen/${c.business_slug}`} className="mt-4 inline-block text-sm font-medium text-ember hover:underline">
            {t('reopen.card.seeFund')}
          </Link>
        </div>
      )}
    </PublicFrame>
  )
}
