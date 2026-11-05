import { useTranslation } from 'react-i18next'
import { PublicFrame } from '../components/PublicFrame'
import { FeatureIndex, QuickFacts, SponsorShowcase } from '../components/Showcase'

/** Everything Hearthline does, for a judge: every feature one click away, and how each sponsor's tool is used. */
export default function Features() {
  const { t } = useTranslation()
  return (
    <PublicFrame wide>
      <div className="space-y-12">
        <div className="max-w-3xl">
          <h1 className="text-4xl leading-tight tracking-tight text-balance">{t('showcase.pageTitle')}</h1>
          <p className="mt-2 text-lg text-ink-soft">{t('login.lede')}</p>
        </div>
        <QuickFacts />
        <FeatureIndex />
        <SponsorShowcase />
      </div>
    </PublicFrame>
  )
}
