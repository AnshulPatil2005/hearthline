import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { FEATURE_COUNT, FEATURE_GROUPS, featureHref, SPONSORS, WHY, type Feature } from '../showcase'

const FIRST_NAME: Record<NonNullable<Feature['as']>, string> = {
  'elena.rivera': 'Elena',
  'marcus.chen': 'Marcus',
  'dana.okafor': 'Dana',
  'priya.nair': 'Priya',
  'sam.whitfield': 'Sam',
  'luis.moreno': 'Luis',
  'rosa.delgado': 'Rosa',
}

/** Internal links stay in the app; the API docs and GitHub open in a new tab. */
function Go({ href, className, children }: { href: string; className?: string; children: React.ReactNode }) {
  return href.startsWith('http') ? (
    <a href={href} target="_blank" rel="noopener noreferrer" className={className}>
      {children}
    </a>
  ) : (
    <Link to={href} className={className}>
      {children}
    </Link>
  )
}

/** Every feature in the demo, grouped by stage, each one click away (signed in as the right person). */
export function FeatureIndex() {
  const { t } = useTranslation()
  return (
    <section id="features" aria-labelledby="features-title" className="scroll-mt-6">
      <h2 id="features-title" className="text-2xl">
        {t('showcase.featuresTitle', { count: FEATURE_COUNT })}
      </h2>
      <p className="mt-1 max-w-3xl text-ink-soft">{t('showcase.featuresIntro')}</p>
      {FEATURE_GROUPS.map((g) => (
        <div key={g.key} className="mt-8">
          <h3 className="kicker text-ink-faint">{t(`showcase.groups.${g.key}`)}</h3>
          <ul className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {g.features.map((f) => (
              <li key={f.key} className="panel flex flex-col p-4">
                <h4 className="font-semibold">{t(`showcase.f.${f.key}.title`)}</h4>
                <p className="mt-1 text-sm text-ink-soft">{t(`showcase.f.${f.key}.body`)}</p>
                <div className="mt-3 flex flex-wrap gap-1.5">
                  {f.tags.map((tag) => (
                    <span key={tag} className="rounded-md bg-sunken px-1.5 py-0.5 text-xs text-ink-soft">
                      {tag}
                    </span>
                  ))}
                </div>
                <Go href={featureHref(f)} className="mt-auto pt-3 text-sm font-medium text-ember hover:underline">
                  {f.as ? t('showcase.openAs', { name: FIRST_NAME[f.as] }) : t('showcase.open')} →
                </Go>
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  )
}

/** How each sponsor's tool is used, how deeply, and where to see each use. */
export function SponsorShowcase() {
  const { t } = useTranslation()
  return (
    <section id="sponsors" aria-labelledby="sponsors-title" className="scroll-mt-6">
      <h2 id="sponsors-title" className="text-2xl">
        {t('showcase.sponsorsTitle')}
      </h2>
      <p className="mt-1 max-w-3xl text-ink-soft">{t('showcase.sponsorsIntro')}</p>
      <div className="mt-6 grid gap-4 lg:grid-cols-2">
        {SPONSORS.map((s) => (
          <article
            key={s.key}
            aria-labelledby={`sponsor-${s.key}`}
            className={`panel p-5 ${s.key === 'paypal' ? 'lg:col-span-2' : ''}`}
          >
            <h3 id={`sponsor-${s.key}`} className="text-lg font-semibold">
              {s.name}
            </h3>
            <p className="mt-1 text-sm text-ink-soft">{t(`showcase.sponsor.${s.key}.headline`)}</p>
            <dl className="mt-4 flex flex-wrap gap-x-8 gap-y-3">
              {s.facts.map((n, i) => (
                <div key={i} className="flex flex-col-reverse">
                  <dt className="text-xs text-ink-faint">{t(`showcase.sponsor.${s.key}.facts.${i}`)}</dt>
                  <dd className="figure text-2xl font-semibold">{n}</dd>
                </div>
              ))}
            </dl>
            <ul
              className={`mt-4 border-t border-line ${s.key === 'paypal' ? 'grid gap-x-8 sm:grid-cols-2' : 'divide-y divide-line'}`}
            >
              {s.uses.map((u) => (
                <li key={u.key} className={s.key === 'paypal' ? 'border-b border-line' : ''}>
                  <Go href={u.href} className="flex items-start justify-between gap-3 py-2.5 text-sm hover:text-ember">
                    <span>{t(`showcase.sponsor.${s.key}.uses.${u.key}`)}</span>
                    <span aria-hidden className="text-ember">
                      →
                    </span>
                  </Go>
                </li>
              ))}
            </ul>
          </article>
        ))}
      </div>
    </section>
  )
}

/** A caption under a sponsor's widget: which tool it is, and which of its features are at work. */
export function BuiltWith({ name, what }: { name: string; what: string }) {
  const { t } = useTranslation()
  return (
    <p className="mt-2 text-xs text-ink-faint">
      <span className="font-medium text-ink-soft">{t('showcase.builtWith', { name })}</span> · {what}
    </p>
  )
}

/** The headline numbers a judge sees first. */
/** The problem, in sourced numbers, and what Hearthline does about each part of it. */
export function WhyItMatters() {
  const { t } = useTranslation()
  return (
    <section id="why" aria-labelledby="why-title" className="scroll-mt-6">
      <h2 id="why-title" className="text-2xl">
        {t('showcase.why.title')}
      </h2>
      <p className="mt-1 max-w-3xl text-ink-soft">
        {t('showcase.why.lead')}{' '}
        <a href={WHY.lead.href} target="_blank" rel="noreferrer" className="text-sm text-ink-faint underline">
          {WHY.lead.source}
        </a>
      </p>
      <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {WHY.items.map((item) => (
          <li key={item.key} className="panel flex flex-col p-4">
            <p className="kicker text-ink-faint">{t(`showcase.groups.${item.key}`)}</p>
            <p className="figure mt-1 text-3xl font-semibold">{t(`showcase.why.${item.key}.figure`)}</p>
            <p className="mt-1 text-sm">{t(`showcase.why.${item.key}.text`)}</p>
            <a
              href={item.href}
              target="_blank"
              rel="noreferrer"
              className="mt-1 text-xs text-ink-faint underline hover:text-ink-soft"
            >
              {item.source}
            </a>
            <p className="mt-3 border-t border-line pt-3 text-sm text-ink-soft">
              {t(`showcase.why.${item.key}.answer`)}
            </p>
            <Link
              to={featureHref({ key: item.key, tags: [], ...item.feature })}
              className="mt-auto pt-3 text-sm font-medium text-ember hover:underline"
            >
              {t('showcase.why.see')} →
            </Link>
          </li>
        ))}
      </ul>
    </section>
  )
}

export function QuickFacts() {
  const { t } = useTranslation()
  const facts: [string, string][] = [
    ['11', 'paypal'],
    ['11', 'agents'],
    [String(FEATURE_COUNT), 'features'],
    ['5', 'sponsors'],
    ['5', 'languages'],
  ]
  return (
    <dl className="grid grid-cols-2 gap-3 sm:grid-cols-5">
      {facts.map(([n, key]) => (
        <div key={key} className="flex flex-col-reverse rounded-lg border border-line bg-surface px-4 py-3">
          <dt className="text-xs text-ink-faint">{t(`showcase.facts.${key}`)}</dt>
          <dd className="figure text-2xl font-semibold">{n}</dd>
        </div>
      ))}
    </dl>
  )
}
