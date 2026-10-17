import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

export function Footer() {
  const { t } = useTranslation()
  return (
    <footer className="flex flex-wrap items-center justify-center gap-x-3 gap-y-1 border-t border-line px-4 py-3 text-center text-xs text-ink-faint">
      <span>{t('app.demoNotice')}</span>
      <span aria-hidden>·</span>
      <Link to="/privacy" className="hover:text-ink">
        {t('legal.privacy.title')}
      </Link>
      <Link to="/terms" className="hover:text-ink">
        {t('legal.terms.title')}
      </Link>
    </footer>
  )
}
