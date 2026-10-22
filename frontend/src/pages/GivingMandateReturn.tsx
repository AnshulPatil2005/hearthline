import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import { api, ApiError, type GivingMandate, type MandateRound } from '../api'
import { money } from '../format'

/** PayPal sends the donor here after "Save and Continue": save the account, then give the first round right away. */
export default function GivingMandateReturn() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [params] = useSearchParams()
  const setupId = params.get('approval_token_id')
  const cancelled = !!params.get('cancelled') || !setupId
  const started = useQuery({
    queryKey: ['mandate-finish', setupId],
    queryFn: async () => {
      const mandate = await api<GivingMandate>('/donors/me/mandates/finish', {
        method: 'POST',
        body: JSON.stringify({ setup_id: setupId }),
      })
      let round: MandateRound | null = null
      if (mandate.status === 'active') {
        round = await api<MandateRound>(`/donors/me/mandates/${mandate.id}/run`, { method: 'POST' }).catch(() => null)
      }
      void queryClient.invalidateQueries({ queryKey: ['mandates'] })
      void queryClient.invalidateQueries({ queryKey: ['giving'] })
      return { mandate: round?.mandate ?? mandate, round }
    },
    enabled: !cancelled,
    retry: false,
    staleTime: Infinity, // saving happens once
  })
  const data = started.data
  return (
    <div className="mx-auto max-w-lg space-y-4 rounded-xl border border-line bg-surface p-6 text-center shadow-sm">
      <h1 className="text-2xl font-semibold">{t('mandate.title')}</h1>
      <div aria-live="polite" className="space-y-2">
        {cancelled ? (
          <p className="text-ink-soft">{t('mandate.returnCancelled')}</p>
        ) : started.isPending ? (
          <p className="text-ink-soft">{t('mandate.returnSaving')}</p>
        ) : started.isError ? (
          <p className="text-danger">
            {started.error instanceof ApiError ? started.error.message : t('errors.generic')}
          </p>
        ) : (
          data && (
            <>
              <p className="text-lg font-semibold text-sage">{t('mandate.returnActive')}</p>
              <p className="text-sm">{t('mandate.returnFrom', { email: data.mandate.paypal_email ?? '' })}</p>
              {data.round && (
                <p className="text-sm text-ink-soft">
                  {data.round.given > 0
                    ? t('mandate.returnGave', {
                        count: data.round.given,
                        amount: money(data.mandate.given_this_month, { cents: true }),
                      })
                    : data.round.summary}
                </p>
              )}
            </>
          )
        )}
      </div>
      <Link to="/giving" className="inline-block rounded-lg bg-ember px-4 py-2 text-sm font-medium text-on-ember">
        {t('mandate.back')}
      </Link>
    </div>
  )
}
