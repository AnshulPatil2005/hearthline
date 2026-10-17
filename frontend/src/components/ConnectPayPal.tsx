import { useMutation, useQuery } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type PayPalConnection } from '../api'

/**
 * Where this person's money goes: their own PayPal account, connected with Log in with PayPal. Shown to households
 * (cash aid), contractors (milestone payments) and business owners (Reopen Fund releases).
 */
export function ConnectPayPal() {
  const { t, i18n } = useTranslation()
  const status = useQuery({ queryKey: ['paypal-connect'], queryFn: () => api<PayPalConnection>('/paypal/connect') })
  const [error, setError] = useState<string | null>(null)
  const start = useMutation({
    mutationFn: () => api<{ authorize_url: string }>('/paypal/connect/start', { method: 'POST' }),
    onSuccess: (r) => window.location.assign(r.authorize_url),
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })
  const s = status.data
  if (!s || s.receives.length === 0) return null
  const what = s.receives.map((r) => t(`connectPayPal.what.${r.what}`)).join(', ')
  const current = s.receives[0].current

  return (
    <section className="flex flex-wrap items-center justify-between gap-4 rounded-xl border border-line bg-surface p-5 shadow-sm">
      <div className="min-w-0 flex-1 space-y-1">
        <h2 className="text-lg font-semibold">{t('connectPayPal.title')}</h2>
        {s.connected ? (
          <>
            <p className="text-sm">
              {t('connectPayPal.connected', { name: s.name || s.email, email: s.email, what })}
            </p>
            <p className="flex flex-wrap items-center gap-2 text-xs text-ink-soft">
              <span
                className={`rounded-full px-2 py-0.5 font-medium ${
                  s.verified_account ? 'bg-sage-soft text-sage' : 'bg-amber-soft text-amber'
                }`}
              >
                {s.verified_account ? t('connectPayPal.verified') : t('connectPayPal.notVerified')}
              </span>
              {s.connected_at &&
                t('connectPayPal.since', {
                  date: new Date(s.connected_at + (s.connected_at.endsWith('Z') ? '' : 'Z')).toLocaleDateString(
                    i18n.resolvedLanguage,
                    { dateStyle: 'medium' },
                  ),
                })}
            </p>
          </>
        ) : (
          <p className="text-sm text-ink-soft">
            {current ? t('connectPayPal.notConnectedHas', { current, what }) : t('connectPayPal.notConnected', { what })}
          </p>
        )}
        {error && <p className="text-sm text-danger">{error}</p>}
      </div>
      <button
        onClick={() => start.mutate()}
        disabled={start.isPending || !s.available}
        title={s.available ? undefined : t('connectPayPal.unavailable')}
        className={
          s.connected
            ? 'rounded-lg border border-line px-3 py-2 text-sm hover:bg-sunken disabled:opacity-40'
            : 'rounded-lg bg-[#0070e0] px-4 py-2 text-sm font-semibold text-white hover:bg-[#005ea6] disabled:opacity-40'
        }
      >
        {start.isPending ? t('connectPayPal.opening') : s.connected ? t('connectPayPal.change') : t('connectPayPal.connect')}
      </button>
    </section>
  )
}
