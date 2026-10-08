import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useParams } from 'react-router'
import { api, type Registry, type RegistryItem } from '../api'
import DonatePanel from '../components/DonatePanel'
import { Progress } from '../components/PublicFrame'
import { LanguageSelect, Logo } from '../components/Shell'
import { money } from '../format'

function ItemCard({ item, onFund }: { item: RegistryItem; onFund: () => void }) {
  const { t } = useTranslation()
  const funded = item.status !== 'open'
  return (
    <li className="flex flex-col rounded-xl border border-line bg-surface p-4 shadow-sm">
      <div className="flex items-start justify-between gap-2">
        <h3 className="font-semibold">
          {item.name}
          {item.quantity > 1 && <span className="ml-1 font-normal text-ink-faint">× {item.quantity}</span>}
        </h3>
        {funded && (
          <span className="shrink-0 rounded-full bg-sage-soft px-2 py-0.5 text-xs font-medium text-sage">
            {t(`registry.status.${item.status}`)}
          </span>
        )}
      </div>
      {item.note && <p className="mt-1 text-sm text-ink-soft">{item.note}</p>}
      <div className="mt-auto pt-4">
        <Progress funded={Number(item.funded_amount)} target={Number(item.target_amount)} />
        <div className="mt-2 flex items-center justify-between text-sm">
          <span className="text-ink-soft">
            {t('registry.raisedOf', { raised: money(item.funded_amount), target: money(item.target_amount) })}
          </span>
          {!funded && (
            <button
              onClick={onFund}
              className="rounded-lg bg-ember px-3 py-1.5 font-medium text-on-ember hover:opacity-90"
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
    <div className="min-h-svh">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-4 py-3">
          <span className="flex items-center gap-2 font-semibold">
            <Logo />
            Hearthline
          </span>
          <LanguageSelect />
        </div>
      </header>

      <main className="mx-auto max-w-5xl px-4 py-8">
        {registry.isError && (
          <p className="rounded-lg bg-danger-soft px-4 py-3 text-danger">{t('registry.notFound')}</p>
        )}
        {!reg && !registry.isError && <div className="h-64 animate-pulse rounded-xl bg-sunken" />}
        {reg && (
          <div className="grid gap-8 lg:grid-cols-[minmax(0,1fr)_20rem]">
            <div className="space-y-6">
              <div>
                <p className="text-sm text-ink-faint">
                  {reg.household_name} · {reg.city}, {reg.state}
                  {reg.disaster_name && ` · ${t('registry.affectedBy', { disaster: reg.disaster_name })}`}
                </p>
                <h1 className="mt-2 text-4xl font-semibold tracking-tight text-balance">{reg.title}</h1>
                <p className="mt-4 leading-relaxed whitespace-pre-line text-ink-soft">{reg.story}</p>
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
                <h2 className="text-lg font-semibold">{t('registry.needs')}</h2>
                <ul className="mt-3 grid gap-4 sm:grid-cols-2">
                  {reg.items.map((item) => (
                    <ItemCard
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
              <section className="rounded-xl border border-line bg-surface p-5 shadow-sm">
                <p className="text-3xl font-semibold tabular-nums">{money(reg.total_funded)}</p>
                <p className="text-sm text-ink-soft">
                  {t('registry.raisedOfTotal', { target: money(reg.total_target) })}
                </p>
                <div className="mt-3">
                  <Progress funded={Number(reg.total_funded)} target={Number(reg.total_target)} />
                </div>
                <p className="mt-2 text-sm text-ink-faint">{t('registry.donors', { count: reg.donor_count })}</p>
                <button
                  onClick={() => setGiving('general')}
                  className="mt-4 w-full rounded-lg border border-line px-3 py-2 text-sm font-medium hover:bg-sunken"
                >
                  {t('registry.giveGeneral')}
                </button>
              </section>

              <section className="rounded-xl bg-sunken p-4 text-sm text-ink-soft">
                <h2 className="font-semibold text-ink">{t('registry.howTitle')}</h2>
                <p className="mt-1">{t('registry.howBody')}</p>
              </section>

              {reg.recent_donations.length > 0 && (
                <section className="rounded-xl border border-line bg-surface p-4">
                  <h2 className="text-sm font-semibold">{t('registry.recent')}</h2>
                  <ul className="mt-2 space-y-3 text-sm">
                    {reg.recent_donations.map((d) => (
                      <li key={d.id}>
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
      </main>
      <footer className="border-t border-line px-4 py-3 text-center text-xs text-ink-faint">
        {t('app.demoNotice')}
      </footer>
    </div>
  )
}
