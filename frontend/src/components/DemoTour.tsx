import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

// The PayPal sandbox's test buyer, as in the README. Sandbox only: no real money moves.
const BUYER = { email: 'sb-m9476w53417949@personal.example.com', password: 'S-Ca7>oD' }

const STEPS = [
  { key: 'give', to: '/r/rivera-family' },
  { key: 'shopper', to: '/login?as=elena.rivera&next=/registry' },
  { key: 'store', to: '/login?as=rosa.delgado&next=/business' },
  { key: 'review', to: '/login?as=priya.nair&next=/review' },
  { key: 'mandate', to: '/login?as=marcus.chen&next=/giving' },
  { key: 'command', to: '/login?as=sam.whitfield&next=/command' },
] as const

function CopyButton({ value, what }: { value: string; what: string }) {
  const { t } = useTranslation()
  const [copied, setCopied] = useState(false)
  return (
    <button
      type="button"
      onClick={() =>
        void navigator.clipboard.writeText(value).then(() => {
          setCopied(true)
          setTimeout(() => setCopied(false), 1500)
        })
      }
      aria-label={t('tour.copy', { what })}
      className="rounded-md border border-line px-2 py-0.5 text-xs hover:bg-surface"
    >
      {copied ? t('tour.copied') : t('tour.copyShort')}
    </button>
  )
}

/** A five-minute path through the demo for someone who hasn't read the README: one link per step. */
export function DemoTour() {
  const { t } = useTranslation()
  return (
    <section aria-labelledby="tour-title" className="mt-10 rounded-xl border border-line bg-surface p-5 shadow-sm">
      <h2 id="tour-title" className="text-lg font-semibold">
        {t('tour.title')}
      </h2>
      <p className="mt-1 text-sm text-ink-soft">{t('tour.subtitle')}</p>
      <ol className="mt-4 space-y-4">
        {STEPS.map((s, i) => (
          <li key={s.key} className="flex gap-3">
            <span className="grid size-7 shrink-0 place-items-center rounded-full bg-ember-soft text-sm font-semibold text-ember">
              {i + 1}
            </span>
            <div className="min-w-0 flex-1 text-sm">
              <p className="font-medium">{t(`tour.${s.key}.title`)}</p>
              <p className="text-ink-soft">{t(`tour.${s.key}.body`)}</p>
              {s.key === 'give' && (
                <div className="mt-2 rounded-lg bg-sunken px-3 py-2 text-xs">
                  <p className="font-medium text-ink-soft">{t('tour.buyer')}</p>
                  <dl className="mt-1 space-y-1">
                    {(
                      [
                        ['buyerEmail', BUYER.email],
                        ['buyerPassword', BUYER.password],
                      ] as const
                    ).map(([label, value]) => (
                      <div key={label} className="flex flex-wrap items-center gap-2">
                        <dt className="text-ink-faint">{t(`tour.${label}`)}</dt>
                        <dd className="flex min-w-0 flex-wrap items-center gap-2">
                          <span className="font-mono break-all">{value}</span>
                          <CopyButton value={value} what={t(`tour.${label}`)} />
                        </dd>
                      </div>
                    ))}
                  </dl>
                </div>
              )}
            </div>
            <Link to={s.to} className="shrink-0 self-start text-sm font-medium text-ember hover:underline">
              {t('tour.open')} →
            </Link>
          </li>
        ))}
      </ol>
    </section>
  )
}
