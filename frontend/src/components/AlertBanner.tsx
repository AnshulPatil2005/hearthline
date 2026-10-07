import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, type InventorySummary } from '../api'
import { money } from '../format'

export type HazardAlert = {
  id: number
  source: 'nws' | 'simulated'
  event: string
  headline: string
  severity: string
  description: string
  instruction: string
  expires: string | null
}

const TONE: Record<string, string> = {
  Extreme: 'border-danger/40 bg-danger-soft',
  Severe: 'border-danger/40 bg-danger-soft',
  Moderate: 'border-amber/40 bg-amber-soft',
}

// Alerts where people may have to leave home get the go-bag checklist; others (heat, frost) don't.
const MAY_EVACUATE = /evacuat|fire|flood|hurricane|tropical storm|storm surge|tsunami|tornado|extreme wind|earthquake/i

function useAlerts() {
  return useQuery({ queryKey: ['alerts'], queryFn: () => api<HazardAlert[]>('/households/me/alerts') })
}

export default function AlertBanner({ summary }: { summary: InventorySummary }) {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const alerts = useAlerts()
  const dismiss = useMutation({
    mutationFn: (id: number) => api(`/alerts/${id}/dismiss`, { method: 'POST' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['alerts'] }),
  })
  const checklist = t('alerts.checklist', { returnObjects: true }) as string[]

  if (!alerts.data?.length) return null
  return (
    <div className="space-y-3">
      {alerts.data.map((a) => (
        <section
          key={a.id}
          role="alert"
          className={`rounded-xl border p-5 ${TONE[a.severity] ?? 'border-line bg-surface'}`}
        >
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="text-lg font-semibold">{a.event}</h2>
                <span className="rounded-full bg-surface/70 px-2 py-0.5 text-xs text-ink-soft">
                  {a.source === 'nws' ? t('alerts.sourceNws') : t('alerts.sourceSimulated')}
                </span>
              </div>
              <p className="mt-1 text-sm text-ink-soft">{a.headline}</p>
            </div>
            <button
              onClick={() => dismiss.mutate(a.id)}
              className="rounded-md px-2 py-1 text-sm text-ink-soft hover:bg-surface/60 hover:text-ink"
            >
              {t('alerts.dismiss')}
            </button>
          </div>
          {a.instruction && <p className="mt-3 font-medium">{a.instruction}</p>}
          {MAY_EVACUATE.test(a.event) && (
            <div className="mt-4 grid gap-4 md:grid-cols-2">
              <div>
                <h3 className="text-sm font-semibold">{t('alerts.grabTitle')}</h3>
                <ul className="mt-2 space-y-1 text-sm">
                  {checklist.map((c) => (
                    <li key={c} className="flex gap-2">
                      <span aria-hidden="true">□</span>
                      {c}
                    </li>
                  ))}
                </ul>
              </div>
              <div className="rounded-lg bg-surface/70 p-3 text-sm">
                <h3 className="font-semibold">{t('alerts.savedTitle')}</h3>
                <p className="mt-1 text-ink-soft">
                  {t('alerts.savedBody', { count: summary.item_count, value: money(summary.total_value) })}
                </p>
                <Link to="/inventory" className="mt-2 inline-block font-medium text-ember hover:underline">
                  {t('actions.openInventory')} →
                </Link>
              </div>
            </div>
          )}
        </section>
      ))}
    </div>
  )
}

export function SimulateAlertButton() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const simulate = useMutation({
    mutationFn: () => api('/households/me/alerts/simulate', { method: 'POST' }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['alerts'] })
      window.scrollTo({ top: 0, behavior: 'smooth' })
    },
  })
  return (
    <button
      onClick={() => simulate.mutate()}
      disabled={simulate.isPending}
      className="rounded-md border border-dashed border-line px-3 py-1.5 text-xs text-ink-faint hover:border-ember hover:text-ember"
    >
      {t('alerts.simulate')}
    </button>
  )
}
