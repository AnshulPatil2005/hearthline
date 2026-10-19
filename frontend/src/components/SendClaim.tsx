import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, ApiError, type ClaimStatus } from '../api'
import { money, parseTime } from '../format'

/**
 * The household sends their insurer a contents claim built from the pre-disaster inventory and the policy's limits;
 * the adjuster reviews it and pays with PayPal, and the money goes on to the family's own PayPal account.
 */
export function SendClaim({ insurer }: { insurer: string }) {
  const { t, i18n } = useTranslation()
  const queryClient = useQueryClient()
  const claim = useQuery({ queryKey: ['claim'], queryFn: () => api<ClaimStatus | null>('/households/me/claim') })
  const [copied, setCopied] = useState(false)
  const prepare = useMutation({
    mutationFn: () => api<ClaimStatus>('/households/me/claim', { method: 'POST' }),
    onSuccess: (c) => queryClient.setQueryData(['claim'], c),
  })
  const c = claim.data
  const when = (iso: string) => parseTime(iso).toLocaleDateString(i18n.resolvedLanguage, { dateStyle: 'medium' })
  const copy = async (link: string) => {
    try {
      await navigator.clipboard.writeText(link)
      setCopied(true)
    } catch {
      setCopied(false)
    }
  }

  return (
    <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <h2 className="font-semibold">{t('claim.title', { insurer: c?.insurer ?? insurer })}</h2>
      {c?.status === 'paid' ? (
        <div className="mt-2 space-y-1 text-sm">
          <p className="text-lg font-semibold text-sage">
            {t('claim.paid', {
              insurer: c.insurer,
              amount: money(c.approved_amount, { cents: true }),
              date: c.paid_at ? when(c.paid_at) : '',
            })}
          </p>
          <p className="text-ink-soft">
            {c.payout_status === 'sent' ? (
              t('claim.sentTo', { account: c.payout_to })
            ) : (
              <>
                {t('claim.held')}{' '}
                <Link to="/aid" className="text-ember hover:underline">
                  {t('claim.connect')}
                </Link>
              </>
            )}
          </p>
          {c.adjuster_name && (
            <p className="text-xs text-ink-faint">{t('claim.adjuster', { name: c.adjuster_name })}</p>
          )}
        </div>
      ) : (
        <div className="mt-2 space-y-3 text-sm">
          <p className="text-ink-soft">{t('claim.body')}</p>
          {c && (
            <>
              <dl className="flex flex-wrap gap-x-6 gap-y-1">
                <div>
                  <dt className="text-ink-faint">{t('claim.items', { count: c.items })}</dt>
                  <dd className="font-semibold tabular-nums">{money(c.inventory_value)}</dd>
                </div>
                <div>
                  <dt className="text-ink-faint">{t('claim.estimate')}</dt>
                  <dd className="font-semibold tabular-nums">{money(c.estimate)}</dd>
                </div>
              </dl>
              <div>
                <p className="font-medium">{t('claim.sendLink')}</p>
                <div className="mt-1 flex flex-wrap gap-2">
                  <input
                    readOnly
                    value={c.link}
                    aria-label={t('claim.sendLink')}
                    onFocus={(e) => e.currentTarget.select()}
                    className="min-w-0 flex-1 rounded-lg border border-line bg-sunken px-3 py-2 font-mono text-xs"
                  />
                  <button
                    onClick={() => void copy(c.link)}
                    className="rounded-lg border border-line px-3 py-2 hover:bg-sunken"
                  >
                    {copied ? t('claim.copied') : t('claim.copy')}
                  </button>
                  <a
                    href={c.link}
                    target="_blank"
                    rel="noreferrer"
                    className="rounded-lg border border-line px-3 py-2 hover:bg-sunken"
                  >
                    {t('claim.preview')} ↗
                  </a>
                </div>
              </div>
            </>
          )}
          <button
            onClick={() => prepare.mutate()}
            disabled={prepare.isPending || claim.isPending}
            className={
              c
                ? 'text-sm text-ink-soft underline-offset-2 hover:underline disabled:opacity-40'
                : 'rounded-lg bg-ember px-4 py-2 font-medium text-on-ember disabled:opacity-40'
            }
          >
            {prepare.isPending ? t('claim.preparing') : c ? t('claim.update') : t('claim.prepare')}
          </button>
          {prepare.error && (
            <p className="text-danger">
              {prepare.error instanceof ApiError ? prepare.error.message : t('errors.generic')}
            </p>
          )}
        </div>
      )}
    </section>
  )
}
