import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import { api, ApiError, type ReadinessMine } from '../api'
import { money } from '../format'

/** PayPal sends the giver here after they approve the subscription: record it, and any payment PayPal already took. */
export default function GivingReadinessReturn() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [params] = useSearchParams()
  const id = params.get('id')
  const cancelled = !!params.get('cancelled') || !id
  const finished = useQuery({
    queryKey: ['readiness-finish', id],
    queryFn: async () => {
      const r = await api<ReadinessMine>(`/donors/me/readiness/${id}/finish`, { method: 'POST' })
      queryClient.setQueryData(['readiness'], r)
      return r
    },
    enabled: !cancelled,
    retry: false,
    staleTime: Infinity,
  })
  const mine = finished.data?.mine
  return (
    <div className="mx-auto max-w-lg space-y-4 rounded-xl border border-line bg-surface p-6 text-center shadow-sm">
      <h1 className="text-2xl font-semibold">{t('readiness.title')}</h1>
      <div aria-live="polite" className="space-y-2">
        {cancelled ? (
          <p className="text-ink-soft">{t('readiness.returnCancelled')}</p>
        ) : finished.isPending ? (
          <p className="text-ink-soft">{t('readiness.returnSaving')}</p>
        ) : finished.isError ? (
          <p className="text-danger">
            {finished.error instanceof ApiError ? finished.error.message : t('errors.generic')}
          </p>
        ) : mine?.status === 'active' ? (
          <>
            <p className="text-lg font-semibold text-sage">
              {t('readiness.returnActive', { amount: money(mine.monthly) })}
            </p>
            <p className="text-sm text-ink-soft">
              {mine.payments > 0
                ? t('readiness.returnFirst', { amount: money(mine.given, { cents: true }) })
                : t('readiness.returnSoon')}
            </p>
          </>
        ) : (
          <p className="text-ink-soft">{t('readiness.returnPending')}</p>
        )}
      </div>
      <Link to="/giving" className="inline-block rounded-lg bg-ember px-4 py-2 text-sm font-medium text-on-ember">
        {t('readiness.back')}
      </Link>
    </div>
  )
}
