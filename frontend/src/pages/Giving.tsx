import { useQuery } from '@tanstack/react-query'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, type Gift, type Giving as GivingData, type RegistrySummary, type ReopenFundSummary } from '../api'
import { Stat } from '../components/Milestones'
import { money } from '../format'

function GiftCard({ gift }: { gift: Gift }) {
  const { t, i18n } = useTranslation()
  const date = (d: string) => new Date(d).toLocaleDateString(i18n.resolvedLanguage, { month: 'short', day: 'numeric' })
  return (
    <li className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div>
          <div className="font-semibold">
            {gift.item ?? t('giving.householdFund')} · {money(gift.amount, { cents: true })}
          </div>
          <a href={gift.link} className="text-sm text-ember hover:underline">
            {gift.to}
          </a>
        </div>
        <span className="text-xs text-ink-faint">{date(gift.created_at)}</span>
      </div>
      <ol className="mt-4 space-y-2 border-l-2 border-line pl-4">
        {gift.timeline.map((e, i) => (
          <li key={i} className="relative text-sm">
            <span className="absolute -left-[1.4rem] top-1.5 size-2.5 rounded-full bg-ember" aria-hidden="true" />
            {e.event}
            {e.at && <span className="ml-2 text-xs text-ink-faint">{date(e.at)}</span>}
          </li>
        ))}
      </ol>
    </li>
  )
}

/** A donor's gifts and what each one did, with a short note from the Funds agent. */
export default function Giving() {
  const { t, i18n } = useTranslation()
  const giving = useQuery({ queryKey: ['giving'], queryFn: () => api<GivingData>('/donors/me/giving') })
  // The Funds agent's note takes a few seconds; the template shows until it arrives.
  const note = useQuery({
    queryKey: ['giving-note'],
    queryFn: () => api<{ summary: string; by_ai: boolean }>('/donors/me/giving/note'),
    enabled: !!giving.data?.gifts.length,
    staleTime: 5 * 60_000,
  })
  const registries = useQuery({ queryKey: ['v1-registries'], queryFn: () => api<RegistrySummary[]>('/v1/registries?limit=3') })
  const funds = useQuery({ queryKey: ['v1-reopen'], queryFn: () => api<ReopenFundSummary[]>('/v1/reopen-funds') })
  const g = giving.data

  return (
    <div className="space-y-6">
      <div>
        <h1 className="text-3xl font-semibold tracking-tight">{t('giving.title')}</h1>
        <p className="mt-1 text-ink-soft">{t('giving.subtitle')}</p>
      </div>
      {g && (
        <>
          <div className="grid gap-3 sm:grid-cols-4">
            <Stat label={t('giving.stat.given')} value={money(g.total_given)} />
            <Stat label={t('giving.stat.families')} value={g.families_helped.toLocaleString(i18n.resolvedLanguage)} />
            <Stat label={t('giving.stat.businesses')} value={g.businesses_helped.toLocaleString(i18n.resolvedLanguage)} />
            <Stat label={t('giving.stat.delivered')} value={g.items_delivered.toLocaleString(i18n.resolvedLanguage)} />
          </div>
          <p className="rounded-xl border border-line bg-surface p-5 leading-relaxed shadow-sm" aria-live="polite">
            {note.data?.by_ai && (
              <span className="mr-2 rounded bg-ember-soft px-1.5 py-0.5 text-xs font-medium text-ember">AI</span>
            )}
            {note.data?.summary ?? g.summary}
          </p>
          <ul className="grid gap-4 lg:grid-cols-2">
            {g.gifts.map((gift) => (
              <GiftCard key={`${gift.kind}-${gift.id}`} gift={gift} />
            ))}
          </ul>
        </>
      )}
      <section className="space-y-3">
        <h2 className="text-lg font-semibold">{t('giving.helpMore')}</h2>
        <ul className="grid gap-3 md:grid-cols-3">
          {registries.data?.map((r) => (
            <li key={r.slug} className="rounded-xl border border-line bg-surface p-4 shadow-sm">
              <Link to={`/r/${r.slug}`} className="font-medium text-ember hover:underline">
                {r.title}
              </Link>
              <p className="mt-1 text-sm text-ink-soft">
                {t('giving.stillNeeds', { amount: money(r.still_needed), count: r.open_items })}
              </p>
            </li>
          ))}
          {funds.data?.map((f) => (
            <li key={f.slug} className="rounded-xl border border-line bg-surface p-4 shadow-sm">
              <Link to={`/reopen/${f.slug}`} className="font-medium text-ember hover:underline">
                {f.business}
              </Link>
              <p className="mt-1 text-sm text-ink-soft">
                {t('giving.reopenRaised', { raised: money(f.raised), goal: money(f.goal_amount), bonus: f.bonus_percent })}
              </p>
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
