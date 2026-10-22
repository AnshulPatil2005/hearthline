import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { api, type Purchase } from '../api'
import { money } from '../format'

const TONE: Record<Purchase['status'], string> = {
  proposed: 'bg-sunken text-ink-soft',
  awaiting_approval: 'bg-amber-soft text-amber',
  approved: 'bg-sunken text-ink',
  paid: 'bg-sage-soft text-sage',
  shipped: 'bg-sage-soft text-sage',
  delivered: 'bg-sage-soft text-sage',
  blocked: 'bg-danger-soft text-danger',
  rejected: 'bg-sunken text-ink-faint',
  failed: 'bg-danger-soft text-danger',
}

function PurchaseCard({ p, onChanged }: { p: Purchase; onChanged: () => void }) {
  const { t } = useTranslation()
  const act = useMutation({
    mutationFn: (action: 'approve' | 'reject' | 'simulate-shipping') =>
      api(`/purchases/${p.id}/${action}`, { method: 'POST' }),
    onSuccess: onChanged,
  })
  return (
    <li className="rounded-xl border border-line bg-surface p-4 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="font-medium">{p.title}</div>
          <div className="text-sm text-ink-soft">
            {p.local_business_id && (
              <span className="mr-1.5 rounded-full bg-sage-soft px-2 py-0.5 text-xs font-medium text-sage">
                {t('purchases.local')}
              </span>
            )}
            {p.retailer && `${p.retailer} · `}
            {p.quantity > 1 && `${p.quantity} × ${money(p.unit_price, { cents: true })} · `}
            <span className="font-medium text-ink">{money(p.total, { cents: true })}</span>
          </div>
        </div>
        <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${TONE[p.status]}`}>
          {t(`purchases.status.${p.status}`)}
        </span>
      </div>

      {p.ai_reasoning && (
        <p className="mt-3 rounded-lg bg-sunken p-3 text-sm text-ink-soft">
          <span className="font-medium text-ink">{t('purchases.agentSays')}</span> {p.ai_reasoning}
          {p.ai_confidence !== null && (
            <span className="ml-1 text-ink-faint">
              ({t('purchases.confidence', { pct: Math.round(p.ai_confidence * 100) })})
            </span>
          )}
        </p>
      )}

      {p.negotiation && p.negotiation.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-ink-soft">{t('purchases.negotiation')}</summary>
          <ol className="mt-2 space-y-2">
            {p.negotiation.map((m, i) => {
              const shopper = m.from === "Hearthline's Shopper"
              return (
                <li key={i} className={`flex ${shopper ? 'justify-start' : 'justify-end'}`}>
                  <div
                    className={`max-w-[85%] rounded-lg px-3 py-2 ${shopper ? 'bg-sunken' : 'border border-line bg-surface'}`}
                  >
                    <p className="text-xs font-medium text-ink-faint">
                      {shopper ? t('purchases.shopperName') : m.from}
                      {m.unit_price && (
                        <span className="ml-2 tabular-nums">{money(m.unit_price, { cents: true })}</span>
                      )}
                    </p>
                    <p>{m.text}</p>
                  </div>
                </li>
              )
            })}
          </ol>
        </details>
      )}

      {p.refused_offers.length > 0 && (
        <ul className="mt-3 space-y-1 rounded-lg border border-danger/30 bg-danger-soft p-3 text-sm">
          {p.refused_offers.map((r) => (
            <li key={`${r.retailer}-${r.title}`}>
              <span className="font-medium text-danger">{t('purchases.refused', { retailer: r.retailer })}</span>{' '}
              {t('purchases.refusedWhy', {
                price: money(r.price, { cents: true }),
                markup: Math.round(r.markup_percent),
                baseline: money(r.baseline, { cents: true }),
              })}
            </li>
          ))}
        </ul>
      )}

      {p.policy_checks.length > 0 && (
        <details className="mt-3 text-sm">
          <summary className="cursor-pointer text-ink-soft">
            {t('purchases.checks', {
              passed: p.policy_checks.filter((c) => c.passed).length,
              total: p.policy_checks.length,
            })}
          </summary>
          <ul className="mt-2 space-y-1">
            {p.policy_checks.map((c) => (
              <li key={c.rule} className="flex gap-2">
                <span className={c.passed ? 'text-sage' : 'text-danger'} aria-hidden="true">
                  {c.passed ? '✓' : '✗'}
                </span>
                <span>
                  <span className="font-medium">{t(`purchases.rule.${c.rule}`, { defaultValue: c.rule })}</span>
                  <span className="text-ink-faint"> · {c.detail}</span>
                </span>
              </li>
            ))}
          </ul>
        </details>
      )}

      {p.error && <p className="mt-2 text-sm text-danger">{p.error}</p>}
      {p.tracking_number && (
        <p className="mt-2 text-sm text-ink-soft">
          {t('purchases.tracking', { carrier: p.carrier, number: p.tracking_number })}
        </p>
      )}
      {p.paypal_ref && <p className="mt-1 text-xs text-ink-faint">{t('purchases.paypalRef', { ref: p.paypal_ref })}</p>}

      <div className="mt-3 flex flex-wrap gap-2">
        {p.status === 'awaiting_approval' && (
          <>
            <button
              onClick={() => act.mutate('approve')}
              disabled={act.isPending}
              className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
            >
              {t('purchases.approve', { amount: money(p.total, { cents: true }) })}
            </button>
            <button
              onClick={() => act.mutate('reject')}
              disabled={act.isPending}
              className="rounded-lg border border-line px-3 py-1.5 text-sm hover:bg-sunken"
            >
              {t('purchases.reject')}
            </button>
          </>
        )}
        {p.local_business_id && p.status === 'paid' && (
          <span className="text-xs text-ink-faint">{t('purchases.localDelivers', { store: p.retailer })}</span>
        )}
        {!p.local_business_id && (p.status === 'paid' || p.status === 'shipped') && (
          <button
            onClick={() => act.mutate('simulate-shipping')}
            disabled={act.isPending}
            className="rounded-md border border-dashed border-line px-3 py-1 text-xs text-ink-faint hover:border-ember hover:text-ember"
          >
            {p.status === 'paid' ? t('purchases.simulateShip') : t('purchases.simulateDeliver')}
          </button>
        )}
      </div>
    </li>
  )
}

export default function PurchaseList() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const purchases = useQuery({
    queryKey: ['purchases'],
    queryFn: () => api<Purchase[]>('/households/me/purchases'),
    refetchInterval: 5000, // the Shopper runs in the background after an item is funded
  })
  const refresh = () => {
    for (const key of ['purchases', 'my-registry', 'fund']) void queryClient.invalidateQueries({ queryKey: [key] })
  }
  if (!purchases.data?.length) return null
  return (
    <section>
      <h2 className="text-lg font-semibold">{t('purchases.title')}</h2>
      <p className="text-sm text-ink-soft">{t('purchases.subtitle')}</p>
      <ul className="mt-3 grid gap-3 lg:grid-cols-2">
        {purchases.data.map((p) => (
          <PurchaseCard key={p.id} p={p} onChanged={refresh} />
        ))}
      </ul>
    </section>
  )
}
