import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { Link } from 'react-router'
import { api, ApiError, type NavigatorAnswer, type NavigatorNote, type NavigatorPlan, type NavigatorStep } from '../api'
import { VoiceButton } from './VoiceButton'

const SPEECH_LOCALE: Record<string, string> = { en: 'en-US', es: 'es-US', zh: 'zh-CN', tl: 'fil-PH', vi: 'vi-VN' }
const errorText = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback)
const canSpeak = typeof window !== 'undefined' && 'speechSynthesis' in window

function speak(text: string, lang: string) {
  window.speechSynthesis.cancel()
  const words = new SpeechSynthesisUtterance(text)
  words.lang = SPEECH_LOCALE[lang] ?? 'en-US'
  window.speechSynthesis.speak(words)
}

function Listen({ text }: { text: string }) {
  const { t, i18n } = useTranslation()
  if (!canSpeak) return null
  return (
    <button
      onClick={() => speak(text, i18n.resolvedLanguage ?? 'en')}
      className="rounded-lg border border-line px-2.5 py-1 text-xs text-ink-soft hover:bg-sunken"
    >
      {t('navigator.listen')}
    </button>
  )
}

function Due({ step }: { step: NavigatorStep }) {
  const { t, i18n } = useTranslation()
  if (!step.due || step.days_left === null) return null
  const due = new Date(`${step.due}T12:00:00`)
  const days = step.days_left
  const date = due.toLocaleDateString(i18n.resolvedLanguage, { month: 'short', day: 'numeric' })
  const tone =
    step.done || step.kind === 'event'
      ? 'bg-sunken text-ink-soft'
      : days < 0
        ? 'bg-danger-soft text-danger'
        : days <= 7
          ? 'bg-amber-soft text-ink'
          : 'bg-sunken text-ink-soft'
  const label =
    days < 0 && !step.done
      ? t('navigator.overdue', { date })
      : days === 0
        ? t('navigator.today')
        : days > 0 && days <= 30
          ? t('navigator.inDays', { count: days, date })
          : date
  return <span className={`shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${tone}`}>{label}</span>
}

function StepRow({ step, onMark }: { step: NavigatorStep; onMark: (s: NavigatorStep) => void }) {
  const { t } = useTranslation()
  const external = step.link.startsWith('http')
  const open = t(`navigator.step.${step.key}.go`)
  return (
    <li className={`flex flex-wrap items-start gap-3 py-3 ${step.done ? 'opacity-80' : ''}`}>
      {step.manual ? (
        <input
          type="checkbox"
          checked={step.done}
          onChange={() => onMark(step)}
          aria-label={t('navigator.markDone', { what: t(`navigator.step.${step.key}.title`, step.params) })}
          className="mt-1 h-4 w-4 accent-[var(--sage)]"
        />
      ) : (
        <span
          aria-hidden
          className={`mt-1.5 h-2.5 w-2.5 shrink-0 rounded-full ${step.kind === 'event' ? 'bg-ink-faint' : 'bg-ember'}`}
        />
      )}
      <div className="min-w-0 flex-1">
        <p className={`font-medium ${step.done ? 'line-through' : ''}`}>
          {t(`navigator.step.${step.key}.title`, step.params)}
        </p>
        <p className="text-sm text-ink-soft">{t(`navigator.step.${step.key}.detail`, step.params)}</p>
      </div>
      <Due step={step} />
      {!step.done &&
        (external ? (
          <a
            href={step.link}
            target="_blank"
            rel="noopener noreferrer"
            className="shrink-0 rounded-lg border border-line px-2.5 py-1 text-sm hover:bg-sunken"
          >
            {open}
          </a>
        ) : (
          <Link to={step.link} className="shrink-0 rounded-lg border border-line px-2.5 py-1 text-sm hover:bg-sunken">
            {open}
          </Link>
        ))}
    </li>
  )
}

/** The family's next steps, soonest first, explained by the navigator in their language; they can ask, by voice too. */
export function RecoveryNavigator() {
  const { t, i18n } = useTranslation()
  const lang = i18n.resolvedLanguage ?? 'en'
  const queryClient = useQueryClient()
  const key = ['navigator', lang]
  const plan = useQuery({ queryKey: key, queryFn: () => api<NavigatorPlan>(`/households/me/navigator?lang=${lang}`) })
  const [question, setQuestion] = useState('')
  const explain = useMutation({
    mutationFn: () =>
      api<NavigatorNote>('/households/me/navigator/explain', { method: 'POST', body: JSON.stringify({ lang }) }),
    onSuccess: (note) => queryClient.setQueryData<NavigatorPlan>(key, (p) => (p ? { ...p, note } : p)),
  })
  const ask = useMutation({
    mutationFn: (q: string) =>
      api<NavigatorAnswer>('/households/me/navigator/ask', {
        method: 'POST',
        body: JSON.stringify({ lang, question: q }),
      }),
  })
  const mark = useMutation({
    mutationFn: (s: NavigatorStep) =>
      api<NavigatorPlan>(`/households/me/navigator/steps/${encodeURIComponent(s.id)}?lang=${lang}`, {
        method: 'POST',
        body: JSON.stringify({ done: !s.done }),
      }),
    onSuccess: (p) => queryClient.setQueryData(key, p),
  })
  const p = plan.data
  if (!p) return null
  const open = p.steps.filter((s) => !s.done)
  const done = p.steps.filter((s) => s.done)
  return (
    <section aria-labelledby="navigator-title" className="rounded-xl border border-line bg-surface p-5 shadow-sm">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h2 id="navigator-title" className="text-lg font-semibold">
          {t('navigator.title')}
        </h2>
        <p className="text-sm text-ink-soft">{t('navigator.count', { count: open.length })}</p>
      </div>

      <div className="mt-3 rounded-lg bg-sunken px-4 py-3" aria-live="polite">
        {p.note ? (
          <>
            <p className="text-sm">{p.note.text}</p>
            <div className="mt-2 flex flex-wrap items-center gap-2">
              <Listen text={p.note.text} />
              <span className="text-xs text-ink-faint">{t('navigator.byAi')}</span>
            </div>
          </>
        ) : (
          <div className="flex flex-wrap items-center gap-3">
            <p className="text-sm text-ink-soft">{t('navigator.explainHint')}</p>
            <button
              onClick={() => explain.mutate()}
              disabled={explain.isPending || open.length === 0}
              className="rounded-lg bg-ember px-3 py-1.5 text-sm font-medium text-on-ember disabled:opacity-40"
            >
              {explain.isPending ? t('navigator.explaining') : t('navigator.explain')}
            </button>
          </div>
        )}
        {explain.isError && <p className="mt-2 text-sm text-danger">{errorText(explain.error, t('errors.generic'))}</p>}
      </div>

      {open.length === 0 ? (
        <p className="mt-3 text-sm text-ink-soft">{t('navigator.allDone')}</p>
      ) : (
        <ul className="mt-2 divide-y divide-line">
          {open.map((s) => (
            <StepRow key={s.id} step={s} onMark={(x) => mark.mutate(x)} />
          ))}
        </ul>
      )}
      {done.length > 0 && (
        <details className="mt-2 text-sm">
          <summary className="cursor-pointer text-ink-soft">{t('navigator.doneCount', { count: done.length })}</summary>
          <ul className="divide-y divide-line">
            {done.map((s) => (
              <StepRow key={s.id} step={s} onMark={(x) => mark.mutate(x)} />
            ))}
          </ul>
        </details>
      )}

      <form
        className="mt-4 flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (question.trim().length >= 3) ask.mutate(question.trim())
        }}
      >
        <label htmlFor="navigator-ask" className="sr-only">
          {t('navigator.ask')}
        </label>
        <input
          id="navigator-ask"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={t('navigator.askPlaceholder')}
          className="min-w-0 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
        />
        <VoiceButton
          onText={(text, final) => {
            setQuestion(text)
            if (final && text.trim().length >= 3) ask.mutate(text.trim())
          }}
        />
        <button
          type="submit"
          disabled={ask.isPending || question.trim().length < 3}
          className="rounded-lg border border-line px-3 py-2 text-sm hover:bg-sunken disabled:opacity-40"
        >
          {ask.isPending ? t('navigator.asking') : t('navigator.ask')}
        </button>
      </form>
      <div aria-live="polite">
        {ask.data && (
          <div className="mt-3 rounded-lg border border-line px-4 py-3">
            <p className="text-sm">{ask.data.answer}</p>
            <div className="mt-2 flex items-center gap-2">
              <Listen text={ask.data.answer} />
              <span className="text-xs text-ink-faint">{t('navigator.notAdvice')}</span>
            </div>
          </div>
        )}
        {ask.isError && <p className="mt-2 text-sm text-danger">{errorText(ask.error, t('errors.generic'))}</p>}
      </div>
    </section>
  )
}
