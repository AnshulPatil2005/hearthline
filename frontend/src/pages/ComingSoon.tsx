import { useTranslation } from 'react-i18next'
import { useAuth } from '../auth'

export default function ComingSoon() {
  const { t } = useTranslation()
  const { user } = useAuth()
  if (!user) return null
  const features = t(`comingSoon.features.${user.role}`, { returnObjects: true }) as string[]

  return (
    <div className="max-w-2xl">
      <h1 className="text-4xl leading-tight tracking-tight text-balance">
        {t('comingSoon.title', { role: t(`roles.${user.role}`) })}
      </h1>
      <p className="mt-2 text-ink-soft">{user.title}</p>
      <section className="mt-8 panel p-5">
        <p className="text-ink-soft">{t('comingSoon.body', { name: user.name.split(' ')[0] })}</p>
        <ul className="mt-4 space-y-2">
          {features.map((f) => (
            <li key={f} className="flex gap-2">
              <span className="text-ember" aria-hidden="true">
                ✓
              </span>
              {f}
            </li>
          ))}
        </ul>
      </section>
    </div>
  )
}
