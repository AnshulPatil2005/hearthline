import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link, useSearchParams } from 'react-router'
import { api, ApiError, type PayPalConnection } from '../api'
import { useAuth } from '../auth'
import { homePathFor } from '../paths'

/** PayPal sends the person back here after Log in with PayPal; the code becomes their connected account. */
export default function ConnectPayPalReturn() {
  const { t } = useTranslation()
  const { user } = useAuth()
  const queryClient = useQueryClient()
  const [params] = useSearchParams()
  const code = params.get('code')
  const state = params.get('state')
  const cancelled = !!params.get('error') || !code || !state
  const finish = useQuery({
    queryKey: ['paypal-connect-finish', code],
    queryFn: async () => {
      const r = await api<PayPalConnection>('/paypal/connect/finish', {
        method: 'POST',
        body: JSON.stringify({ code, state }),
      })
      queryClient.setQueryData(['paypal-connect'], r)
      return r
    },
    enabled: !cancelled && !!user,
    retry: false,
    staleTime: Infinity, // a code works once
  })
  const back = user ? homePathFor(user.role) : '/login'

  return (
    <div className="mx-auto max-w-lg space-y-4 panel p-6 text-center">
      <h1 className="text-2xl font-semibold">{t('connectPayPal.title')}</h1>
      {cancelled ? (
        <p className="text-ink-soft">{t('connectPayPal.cancelled')}</p>
      ) : finish.isPending ? (
        <p className="text-ink-soft">{t('connectPayPal.finishing')}</p>
      ) : finish.isError ? (
        <p className="text-danger">{finish.error instanceof ApiError ? finish.error.message : t('errors.generic')}</p>
      ) : (
        finish.data && (
          <div className="space-y-2">
            <p className="text-lg font-semibold text-sage">{t('connectPayPal.done')}</p>
            <p className="text-sm">
              {t('connectPayPal.connected', {
                name: finish.data.name || finish.data.email,
                email: finish.data.email,
                what: finish.data.receives.map((r) => t(`connectPayPal.what.${r.what}`)).join(', '),
              })}
            </p>
            {!finish.data.verified_account && (
              <p className="text-sm text-amber">{t('connectPayPal.notVerifiedNote')}</p>
            )}
          </div>
        )
      )}
      <Link to={back} className="inline-block rounded-lg bg-ember px-4 py-2 text-sm font-medium text-on-ember">
        {t('connectPayPal.back')}
      </Link>
    </div>
  )
}
