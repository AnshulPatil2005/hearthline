import { lazy, Suspense, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'
import { mediaUrl, type Contractor, type MilestoneStatus, type Project, type SiteCheck } from '../api'

// Bryntum Gantt is large; load it only when a project has a schedule to show.
export const ProjectGantt = lazy(() => import('./ProjectGantt'))

const STATUS_TONE: Record<MilestoneStatus, string> = {
  pending: 'bg-sunken text-ink-soft',
  submitted: 'bg-amber-soft text-amber',
  under_review: 'bg-amber-soft text-amber',
  paid: 'bg-sage-soft text-sage',
  disputed: 'bg-danger-soft text-danger',
  refunded: 'bg-danger-soft text-danger',
}

const VERDICT_TONE: Record<SiteCheck['verdict'], string> = {
  matches: 'bg-sage-soft text-sage',
  partial: 'bg-amber-soft text-amber',
  does_not_match: 'bg-danger-soft text-danger',
  unchecked: 'bg-sunken text-ink-soft',
}

export function MilestoneStatusPill({ status }: { status: MilestoneStatus }) {
  const { t } = useTranslation()
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STATUS_TONE[status]}`}>
      {t(`rebuild.status.${status}`)}
    </span>
  )
}

export function PhotoStrip({ urls }: { urls: string[] }) {
  const { t } = useTranslation()
  if (urls.length === 0) return null
  return (
    <ul className="grid grid-cols-3 gap-2 sm:grid-cols-4">
      {urls.map((u, i) => (
        <li key={u}>
          <a href={mediaUrl(u) ?? undefined} target="_blank" rel="noreferrer" aria-label={t('a11y.openPhoto', { n: i + 1 })}>
            <img src={mediaUrl(u) ?? ''} alt="" className="aspect-[4/3] w-full rounded-lg object-cover" />
          </a>
        </li>
      ))}
    </ul>
  )
}

/** What the Site agent saw in the contractor's photos. It informs the people who decide; it never pays. */
export function SiteCheckView({ check }: { check: SiteCheck }) {
  const { t } = useTranslation()
  const concerns = [...check.concerns, ...(check.metadata_concerns ?? [])]
  return (
    <div className="rounded-lg border border-line bg-paper p-3 text-sm">
      <div className="flex flex-wrap items-center gap-2">
        <span className="font-semibold">{t('rebuild.siteCheck.title')}</span>
        <span className={`rounded-full px-2 py-0.5 text-xs font-medium ${VERDICT_TONE[check.verdict]}`}>
          {t(`rebuild.siteCheck.verdict.${check.verdict}`)}
        </span>
        {check.verdict !== 'unchecked' && (
          <span className="text-xs text-ink-faint">
            {t('rebuild.siteCheck.confidence', { value: Math.round(check.confidence * 100) })}
          </span>
        )}
      </div>
      {check.observations.length > 0 && (
        <ul className="mt-2 list-disc space-y-0.5 pl-5 text-ink-soft">
          {check.observations.map((o) => (
            <li key={o}>{o}</li>
          ))}
        </ul>
      )}
      {concerns.length > 0 && (
        <>
          <p className="mt-2 font-medium text-amber">{t('rebuild.siteCheck.concerns')}</p>
          <ul className="list-disc space-y-0.5 pl-5 text-ink-soft">
            {concerns.map((c) => (
              <li key={c}>{c}</li>
            ))}
          </ul>
        </>
      )}
    </div>
  )
}

export function Stat({ label, value, hint }: { label: string; value: ReactNode; hint?: string }) {
  return (
    <div className="rounded-lg bg-sunken px-4 py-3">
      <div className="text-xs text-ink-faint">{label}</div>
      <div className="mt-0.5 text-xl font-semibold">{value}</div>
      {hint && <div className="mt-0.5 text-xs text-ink-faint">{hint}</div>}
    </div>
  )
}

export function ContractorLine({ c }: { c: Contractor }) {
  const { t } = useTranslation()
  return (
    <span className="text-ink-soft">
      {c.business_name} · {t('rebuild.license', { state: c.license_state, number: c.license_number })}
      {c.license_verified && <span className="ml-1 text-sage">✓ {t('rebuild.verified')}</span>}
    </span>
  )
}

export function GanttSlot({ project, editable, onSynced }: { project: Project; editable: boolean; onSynced?: () => void }) {
  if (project.milestones.length === 0) return null
  // Remount when statuses change so bar colours and progress match the cards below.
  const key = project.milestones.map((m) => m.status).join()
  return (
    <Suspense fallback={<div className="h-[22rem] animate-pulse rounded-xl bg-sunken" />}>
      <ProjectGantt
        key={key}
        base={`/bryntum/gantt/${project.id}`}
        rows={project.milestones.length}
        editable={editable}
        onSynced={onSynced}
      />
    </Suspense>
  )
}
