import { useEffect, useState, useSyncExternalStore } from 'react'
import { useTranslation } from 'react-i18next'
import { serverWaking } from '../api'

/** Says the demo server is waking up when a request after a quiet spell takes more than a few seconds. */
export function WakingNotice() {
  const { t } = useTranslation()
  const waking = useSyncExternalStore(serverWaking.subscribe, serverWaking.get)
  const [show, setShow] = useState(false)
  useEffect(() => {
    if (!waking) {
      setShow(false)
      return
    }
    const timer = setTimeout(() => setShow(true), 4000)
    return () => clearTimeout(timer)
  }, [waking])
  if (!show) return null
  return (
    <p
      role="status"
      className="fixed inset-x-4 bottom-4 z-50 mx-auto max-w-md rounded-xl border border-line bg-surface px-4 py-3 text-center text-sm text-ink-soft shadow-lg"
    >
      {t('app.waking')}
    </p>
  )
}
