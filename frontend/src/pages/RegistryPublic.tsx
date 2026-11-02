import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router'
import { api, type Registry, type RegistryItem } from '../api'
import DonatePanel from '../components/DonatePanel'
import { Progress, PublicFrame } from '../components/PublicFrame'
import { money } from '../format'

function ItemRow({ item, onFund }: { item: RegistryItem; onFund: () => void }) {
  const { t } = useTranslation()
  const funded = item.status !== 'open'
  return (
    <li className="grid gap-x-6 gap-y-3 py-5 sm:grid-cols-[minmax(0,1fr)_13rem]">
      <div className="min-w-0">
        <h3 className="font-serif text-xl font-semibold tracking-tight">
          {item.name}
          {item.quantity > 1 && (
            <span className="ml-1.5 font-sans text-base font-normal text-ink-faint">× {item.quantity}</span>
          )}
        </h3>
        {item.note && <p className="mt-1 text-sm text-ink-soft">{item.note}</p>}
      </div>
      <div className="flex flex-col justify-center gap-2">
        <Progress funded={Number(item.funded_amount)} target={Number(item.target_amount)} />
        <div className="flex items-center justify-between gap-3">
          <span className="font-mono text-xs text-ink-soft">
            {t('registry.raisedOf', { raised: money(item.funded_amount), target: money(item.target_amount) })}
          </span>
          {funded ? (
            <span className="kicker text-sage">✓ {t(`registry.status.${item.status}`)}</span>
          ) : (
            <button
              onClick={onFund}
              className="rounded-md bg-ember px-3 py-1.5 text-sm font-semibold text-on-ember hover:opacity-90"
            >
              {t('registry.fundThis')}
            </button>
          )}
        </div>
      </div>
    </li>
  )
}

export default function RegistryPublic() {
  const { slug } = useParams()
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [giving, setGiving] = useState<RegistryItem | 'general' | null>(null)
  const registry = useQuery({ queryKey: ['registry', slug], queryFn: () => api<Registry>(`/registries/${slug}`) })
  const reg = registry.data

  return (
    <PublicFrame>
      {registry.isError && <p className="rounded-lg bg-danger-soft px-4 py-3 text-danger">{t('registry.notFound')}</p>}
      {!reg && !registry.isError && <div className="h-64 animate-pulse rounded-xl bg-sunken" />}
      {reg && (
        <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
          <div className="space-y-6">
            <div>
              <p className="kicker text-ember">
                {reg.household_name} · {reg.city}, {reg.state}
                {reg.disaster_name && ` · ${t('registry.affectedBy', { disaster: reg.disaster_name })}`}
              </p>
              <h1 className="mt-3 text-5xl leading-[1.05] tracking-tight text-balance">{reg.title}</h1>
              <p className="mt-5 text-lg leading-relaxed whitespace-pre-line text-ink-soft">{reg.story}</p>
            </div>

            {giving && (
              <DonatePanel
                key={giving === 'general' ? 'general' : giving.id}
                slug={reg.slug}
                item={giving === 'general' ? null : giving}
                onDone={() => void queryClient.invalidateQueries({ queryKey: ['registry', slug] })}
                onClose={() => setGiving(null)}
              />
            )}

            <section>
              <h2 className="border-b border-ink pb-2 text-2xl">{t('registry.needs')}</h2>
              <ul className="divide-y divide-line border-b border-line">
                {reg.items.map((item) => (
                  <ItemRow
                    key={item.id}
                    item={item}
                    onFund={() => {
                      setGiving(item)
                      window.scrollTo({ top: 0, behavior: 'smooth' })
                    }}
                  />
                ))}
              </ul>
            </section>
          </div>

          <aside className="space-y-4 lg:sticky lg:top-6 lg:self-start">
            <section className="border-t-4 border-ink bg-surface p-5">
              <p className="kicker text-ink-faint">{t('registry.raisedLabel')}</p>
              <p className="figure mt-1 text-5xl font-semibold">{money(reg.total_funded)}</p>
              <p className="mt-1 text-sm text-ink-soft">
                {t('registry.raisedOfTotal', { target: money(reg.total_target) })}
              </p>
              <div className="mt-3">
                <Progress funded={Number(reg.total_funded)} target={Number(reg.total_target)} />
              </div>
              <p className="mt-2 font-mono text-xs text-ink-faint">
                {t('registry.donors', { count: reg.donor_count })}
              </p>
              <button
                onClick={() => setGiving('general')}
                className="mt-4 w-full rounded-md border border-ink px-3 py-2 text-sm font-semibold hover:bg-ink hover:text-paper"
              >
                {t('registry.giveGeneral')}
              </button>
            </section>

            <section className="border-l-2 border-ember pl-4">
              <h2 className="kicker text-ink">{t('registry.howTitle')}</h2>
              <p className="mt-2 font-serif text-lg leading-snug text-ink">{t('registry.howBody')}</p>
            </section>

            {reg.recent_donations.length > 0 && (
              <section>
                <h2 className="kicker border-b border-ink pb-2">{t('registry.recent')}</h2>
                <ul className="divide-y divide-line text-sm">
                  {reg.recent_donations.map((d) => (
                    <li key={d.id} className="py-3">
                      <span className="font-medium">{d.donor_name ?? t('registry.anonymous')}</span>{' '}
                      <span className="text-ink-soft">
                        {d.item_name
                          ? t('registry.gaveFor', { amount: money(d.amount), item: d.item_name })
                          : t('registry.gave', { amount: money(d.amount) })}
                      </span>
                      {d.message && <p className="text-ink-faint italic">“{d.message}”</p>}
                    </li>
                  ))}
                </ul>
              </section>
            )}
          </aside>
        </div>
      )}
    </PublicFrame>
  )
}
