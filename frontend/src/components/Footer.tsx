import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'

export function Footer() {
  const { t } = useTranslation()
  return (
    <footer className="border-t border-line">
      <div className="mx-auto flex max-w-6xl flex-wrap items-center justify-between gap-x-6 gap-y-1 px-4 py-4 text-xs text-ink-faint">
        <span>{t('app.demoNotice')}</span>
        <span className="flex gap-4">
          <Link to="/features" className="hover:text-ink">
            {t('nav.features')}
          </Link>
          <Link to="/privacy" className="hover:text-ink">
            {t('legal.privacy.title')}
          </Link>
          <Link to="/terms" className="hover:text-ink">
            {t('legal.terms.title')}
          </Link>
        </span>
      </div>
    </footer>
  )
}
