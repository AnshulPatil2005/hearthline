import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type BatchAid } from '../api'
import { money, parseTime } from '../format'

const KNOWN = ['PENDING', 'SUCCESS', 'UNCLAIMED', 'RETURNED']

/** Cash aid paid straight to the household's PayPal account in a batch, such as first-72-hours aid. */
export function BatchAidList() {
  const { t, i18n } = useTranslation()
  const aid = useQuery({ queryKey: ['batch-aid'], queryFn: () => api<BatchAid[]>('/households/me/batch-aid') })
  if (!aid.data?.length) return null
  return (
    <section aria-labelledby="batch-aid-title" className="panel p-5">
      <h2 id="batch-aid-title" className="text-lg font-semibold">
        {t('aid.batchAid.title')}
      </h2>
      <ul className="mt-2 divide-y divide-line">
        {aid.data.map((a) => (
          <li key={a.id} className="py-3">
            <div className="flex flex-wrap items-baseline justify-between gap-2">
              <p className="font-medium">
                {money(a.amount)} · {a.first_72_hours ? t('rapid.title') : a.title}
              </p>
              {a.sent_at && (
                <span className="text-xs text-ink-faint">
                  {parseTime(a.sent_at).toLocaleString(i18n.resolvedLanguage, {
                    dateStyle: 'medium',
                    timeStyle: 'short',
                  })}
                </span>
              )}
            </div>
            {a.first_72_hours && <p className="mt-1 text-sm text-ink-soft">{t('aid.batchAid.rapid')}</p>}
            <p className="mt-1 text-sm">
              {KNOWN.includes(a.status)
                ? t(`aid.batchAid.status.${a.status}`, { email: a.receiver })
                : t('aid.batchAid.status.other', { status: a.status })}
              <span className="ml-2 text-xs text-ink-faint">{t('aid.batchAid.to', { email: a.receiver })}</span>
            </p>
          </li>
        ))}
      </ul>
    </section>
  )
}
