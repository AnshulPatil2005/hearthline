import { useMutation } from '@tanstack/react-query'
import type { GridApi, GridState } from 'ag-grid-community'
import { useState } from 'react'
import { useTranslation } from 'react-i18next'
import { api, ApiError } from '../api'
import { VoiceButton } from './VoiceButton'

type Answer = { explanation: string; state: Partial<GridState>; matching: number }

type Props<T> = {
  grid: () => GridApi<T> | null
  /** The grid's state when the page opened: used for anything the answer doesn't set. */
  initial: () => GridState | null
}

/**
 * "Ask the grid": AG Grid's AI Toolkit describes the grid's possible state as a JSON schema; the server
 * asks a model to fill it in from the question, checks the answer, and the grid applies it.
 */
export function AskGrid<T>({ grid, initial }: Props<T>) {
  const { t, i18n } = useTranslation()
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState<Answer | null>(null)
  const [error, setError] = useState<string | null>(null)

  const ask = useMutation({
    mutationFn: (q: string) => {
      const gridApi = grid()
      if (!gridApi) throw new Error('grid not ready')
      const schema = gridApi.getStructuredSchema({ exclude: ['columnSizing', 'pivot'] })
      return api<Answer>('/command/ask', { method: 'POST', body: JSON.stringify({ question: q, grid_schema: schema }) })
    },
    onSuccess: (a) => {
      const gridApi = grid()
      const start = initial()
      if (!gridApi || !start) return
      // Show every column the answer filters on, so each filter is visible in a header.
      const filtered = Object.keys(a.state.filter?.filterModel ?? {})
      const visibility = a.state.columnVisibility ?? start.columnVisibility
      gridApi.setState({
        ...gridApi.getState(),
        filter: a.state.filter ?? { filterModel: {} },
        sort: a.state.sort,
        rowGroup: a.state.rowGroup ?? { groupColIds: [] },
        aggregation: a.state.aggregation ?? start.aggregation,
        columnVisibility: visibility && {
          hiddenColIds: visibility.hiddenColIds.filter((id) => !filtered.includes(id)),
        },
      })
      setAnswer(a)
      setError(null)
    },
    onError: (e) => setError(e instanceof ApiError ? e.message : t('errors.generic')),
  })

  const reset = () => {
    const gridApi = grid()
    const start = initial()
    if (gridApi && start) gridApi.setState({ ...gridApi.getState(), ...start, sideBar: gridApi.getState().sideBar })
    setAnswer(null)
    setQuestion('')
  }

  const examples = [t('command.ask.example1'), t('command.ask.example2'), t('command.ask.example3')]
  return (
    <section className="panel p-4">
      <form
        className="flex flex-wrap items-center gap-2"
        onSubmit={(e) => {
          e.preventDefault()
          if (question.trim().length >= 3) ask.mutate(question.trim())
        }}
      >
        <label htmlFor="ask-grid" className="text-sm font-semibold">
          {t('command.ask.label')}
        </label>
        <input
          id="ask-grid"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder={t('command.ask.placeholder')}
          className="min-w-64 flex-1 rounded-lg border border-line bg-surface px-3 py-2 text-sm"
        />
        <VoiceButton
          onText={(text, final) => {
            setQuestion(text)
            if (final && text.trim().length >= 3) ask.mutate(text.trim()) // asking out loud runs it
          }}
        />
        <button
          type="submit"
          disabled={ask.isPending || question.trim().length < 3}
          className="rounded-lg bg-ember px-3 py-2 text-sm font-medium text-on-ember disabled:opacity-40"
        >
          {ask.isPending ? t('command.ask.thinking') : t('command.ask.go')}
        </button>
        {answer && (
          <button type="button" onClick={reset} className="rounded-lg px-2 py-2 text-sm text-ink-soft hover:text-ink">
            {t('command.ask.reset')}
          </button>
        )}
      </form>
      {!answer && (
        <div className="mt-2 flex flex-wrap gap-2">
          {examples.map((ex) => (
            <button
              key={ex}
              onClick={() => {
                setQuestion(ex)
                ask.mutate(ex)
              }}
              disabled={ask.isPending}
              className="rounded-full bg-sunken px-3 py-1 text-xs text-ink-soft hover:text-ink"
            >
              {ex}
            </button>
          ))}
        </div>
      )}
      {answer && (
        <p className="mt-2 text-sm" aria-live="polite">
          <span className="mr-2 rounded bg-ember-soft px-1.5 py-0.5 text-xs font-medium text-ember">AI</span>
          {answer.explanation}{' '}
          <span className="text-ink-soft">
            ·{' '}
            {t('command.matching', {
              count: answer.matching,
              n: answer.matching.toLocaleString(i18n.resolvedLanguage),
            })}
          </span>
          <span className="block text-xs text-ink-faint">{t('command.ask.check')}</span>
        </p>
      )}
      {error && <p className="mt-2 text-sm text-danger">{error}</p>}
    </section>
  )
}
