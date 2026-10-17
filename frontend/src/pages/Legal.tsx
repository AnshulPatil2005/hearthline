import { useTranslation } from 'react-i18next'
import { PublicFrame } from '../components/PublicFrame'

type Section = { h: string; p: string }

/** Privacy and terms, in plain words (PayPal's Log in with PayPal settings link to both). */
export default function Legal({ doc }: { doc: 'privacy' | 'terms' }) {
  const { t } = useTranslation()
  const sections = t(`legal.${doc}.sections`, { returnObjects: true }) as Section[]
  return (
    <PublicFrame>
      <article className="mx-auto max-w-2xl space-y-6">
        <header className="space-y-2">
          <h1 className="text-3xl font-semibold tracking-tight">{t(`legal.${doc}.title`)}</h1>
          <p className="text-ink-soft">{t(`legal.${doc}.intro`)}</p>
        </header>
        {sections.map((s) => (
          <section key={s.h} className="space-y-1">
            <h2 className="text-lg font-semibold">{s.h}</h2>
            <p className="leading-relaxed text-ink-soft">{s.p}</p>
          </section>
        ))}
        <p className="text-sm text-ink-faint">
          {t('legal.questions')}{' '}
          <a href="https://github.com/AnshulPatil2005/hearthline/issues" className="text-ember hover:underline">
            GitHub
          </a>
        </p>
      </article>
    </PublicFrame>
  )
}
