import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'

// The browser's speech recognition (Chrome, Edge, Safari). Firefox has none; the button hides itself.
type Recognition = {
  lang: string
  interimResults: boolean
  continuous: boolean
  start(): void
  stop(): void
  onresult: ((e: { results: ArrayLike<ArrayLike<{ transcript: string }> & { isFinal: boolean }> }) => void) | null
  onend: (() => void) | null
  onerror: ((e: { error: string }) => void) | null
}
declare global {
  interface Window {
    SpeechRecognition?: new () => Recognition
    webkitSpeechRecognition?: new () => Recognition
  }
}

// Speech recognition wants a full locale, not just a language.
const SPEECH_LOCALE: Record<string, string> = { en: 'en-US', es: 'es-US', zh: 'zh-CN', tl: 'fil-PH', vi: 'vi-VN' }

type Props = {
  /** Called with the words heard so far (`final` is false while the person is still talking). */
  onText: (text: string, final: boolean) => void
  className?: string
}

/** Speak instead of typing, in the language the app is set to. */
export function VoiceButton({ onText, className = '' }: Props) {
  const { t, i18n } = useTranslation()
  const [listening, setListening] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const recognition = useRef<Recognition | null>(null)
  const Ctor = typeof window === 'undefined' ? undefined : (window.SpeechRecognition ?? window.webkitSpeechRecognition)

  useEffect(() => () => recognition.current?.stop(), [])
  if (!Ctor) return null

  const toggle = () => {
    if (listening) {
      recognition.current?.stop()
      return
    }
    const r = new Ctor()
    r.lang = SPEECH_LOCALE[i18n.resolvedLanguage ?? 'en'] ?? 'en-US'
    r.interimResults = true
    r.continuous = false
    r.onresult = (e) => {
      const results = Array.from(e.results)
      onText(results.map((res) => res[0].transcript).join(' ').trim(), results.every((res) => res.isFinal))
    }
    r.onerror = (e) => setError(e.error === 'not-allowed' ? t('voice.blocked') : t('voice.failed'))
    r.onend = () => setListening(false)
    recognition.current = r
    setError(null)
    setListening(true)
    r.start()
  }

  return (
    <>
      <button
        type="button"
        onClick={toggle}
        aria-pressed={listening}
        aria-label={listening ? t('voice.stop') : t('voice.start')}
        title={listening ? t('voice.stop') : t('voice.start')}
        className={`grid size-9 shrink-0 place-items-center rounded-lg border ${listening ? 'animate-pulse border-ember bg-ember-soft text-ember' : 'border-line text-ink-soft hover:bg-sunken hover:text-ink'} ${className}`}
      >
        <svg viewBox="0 0 24 24" className="size-4" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
          <rect x="9" y="3" width="6" height="11" rx="3" />
          <path d="M5 11a7 7 0 0 0 14 0M12 18v3" strokeLinecap="round" />
        </svg>
      </button>
      {error && <span className="text-xs text-danger">{error}</span>}
    </>
  )
}
