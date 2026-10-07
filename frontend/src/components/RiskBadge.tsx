import { useTranslation } from 'react-i18next'
import type { RiskTier } from '../api'

const TONE: Record<RiskTier | 'low' | 'medium' | 'high', string> = {
  low: 'bg-sage-soft text-sage',
  medium: 'bg-amber-soft text-amber',
  high: 'bg-danger-soft text-danger',
}

export default function RiskBadge({ tier, score }: { tier: RiskTier; score?: number }) {
  const { t } = useTranslation()
  return (
    <span className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium ${TONE[tier]}`}>
      {t(`review.risk.${tier}`)}
      {score !== undefined && <span className="opacity-70">· {score}</span>}
    </span>
  )
}
