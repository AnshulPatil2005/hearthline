import { useMutation } from '@tanstack/react-query'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError, type PayPalAgentAnswer } from '../api'
import { VoiceButton } from './VoiceButton'

const EXAMPLES = ['ex1', 'ex2', 'ex3'] as const

/**
 * "Ask PayPal": the Funds agent answers with PayPal's own MCP tools (read-only, checked on the server) and
 * Hearthline's records, and shows each call it made.
 */
export function AskPayPal() {
  const { t } = useTranslation()
  const [question, setQuestion] = useState('')
  const [error, setError] = useState<string | null>(null)
  const ask = useMutation({
    mutationFn: (q: string) =>
      api<PayPalAgentAnswer>('/command/paypal/ask', { method: 'POST', body: JSON.stringify({ question: q }) }),
    onSuccess: () => setError(null),
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })
  const run = (q: string) => {
    setQuestion(q)
    if (q.trim().length >= 3) ask.mutate(q.trim())
  }
  const answer = ask.data

  return (
    <section id="ask-paypal" aria-labelledby="ask-paypal-title" className="space-y-3 rounded-xl border border-line bg-surface p-5 shadow-sm">
      <div>
        <h2 id="ask-paypal-title" className="text-lg font-semibold">
          {t('disputes.ask.title')}
        </h2>
        <p className="mt-1 text-sm text-ink-soft">{t('disputes.ask.subtitle')}</p>
      </div>
      <form
        onSubmit={(e) => {
          e.preventDefault()
          run(question)
        }}
        className="flex flex-wrap gap-2"
      >
        <input
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={t('disputes.ask.placeholder')}
          aria-label={t('disputes.ask.title')}
          maxLength={500}
          className="min-w-64 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
        />
        <VoiceButton
          onText={(text, final) => {
            setQuestion(text)
            if (final) run(text)
          }}
        />
        <button
          type="submit"
          disabled={ask.isPending || question.trim().length < 3}
          className="rounded-lg bg-ember px-3 py-2 text-sm font-medium text-on-ember disabled:opacity-40"
        >
          {ask.isPending ? t('disputes.ask.asking') : t('disputes.ask.ask')}
        </button>
      </form>
      <div className="flex flex-wrap gap-2">
        {EXAMPLES.map((k) => (
          <button
            key={k}
            onClick={() => run(t(`disputes.ask.${k}`))}
            disabled={ask.isPending}
            className="rounded-full border border-line px-3 py-1 text-xs text-ink-soft hover:bg-sunken disabled:opacity-40"
          >
            {t(`disputes.ask.${k}`)}
          </button>
        ))}
      </div>
      {error && <p className="text-sm text-danger">{error}</p>}
      {answer && !ask.isPending && (
        <div className="space-y-3">
          <p className="whitespace-pre-line rounded-lg bg-sunken px-4 py-3 text-sm leading-relaxed">{answer.answer}</p>
          {answer.steps.length > 0 && (
            <details open className="text-sm">
              <summary className="cursor-pointer text-ink-soft">{t('disputes.ask.steps', { count: answer.steps.length })}</summary>
              <ol className="mt-2 space-y-1.5">
                {answer.steps.map((s, i) => (
                  <li key={i} className="flex flex-wrap items-baseline gap-2">
                    <span
                      className={`rounded-full px-2 py-0.5 text-xs font-medium ${
                        s.source === 'paypal' ? 'bg-ember-soft text-ember' : 'bg-sage-soft text-sage'
                      }`}
                    >
                      {s.source === 'paypal' ? t('disputes.ask.paypal') : t('disputes.ask.hearthline')}
                    </span>
                    <code className="font-mono text-xs">
                      {s.tool}({Object.keys(s.args).length ? JSON.stringify(s.args) : ''})
                    </code>
                    <span className={`text-xs ${s.ok ? 'text-ink-faint' : 'text-danger'}`}>
                      {s.ok ? s.summary.slice(0, 120) : s.summary}
                    </span>
                  </li>
                ))}
              </ol>
            </details>
          )}
        </div>
      )}
    </section>
  )
}
