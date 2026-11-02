import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router'
import { api, ApiError, type Role, type User } from '../api'
import { useAuth } from '../auth'
import { DemoTour } from '../components/DemoTour'
import { Footer } from '../components/Footer'
import { Dateline, Wordmark } from '../components/Shell'
import { homePathFor } from '../paths'

// The cast, in the order a visitor meets them: the people helped, the people rebuilding, the people deciding
const GROUPS: { key: string; roles: Role[] }[] = [
  { key: 'people', roles: ['household', 'donor'] },
  { key: 'build', roles: ['contractor', 'business'] },
  { key: 'relief', roles: ['org_admin', 'reviewer', 'supervisor'] },
]
const STAGES = ['prepare', 'respond', 'rebuild', 'reopen'] as const

type ResetStatus = { running: boolean; available_in_seconds: number; error: string | null }

/** Judges change shared demo state; anyone can put it back (at most every ten minutes). */
function ResetDemo() {
  const { t } = useTranslation()
  const queryClient = useQueryClient()
  const [confirming, setConfirming] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const status = useQuery({
    queryKey: ['demo-reset'],
    queryFn: () => api<ResetStatus>('/demo/reset'),
    refetchInterval: (q) => (q.state.data?.running ? 3000 : false),
  })
  const running = status.data?.running ?? false
  const wasRunning = useRef(false)
  useEffect(() => {
    if (wasRunning.current && !running) {
      setMessage(status.data?.error ? t('login.reset.failed') : t('login.reset.done'))
      void queryClient.invalidateQueries({ queryKey: ['personas'] })
    }
    wasRunning.current = running
  }, [running, status.data?.error, queryClient, t])
  const reset = useMutation({
    mutationFn: () => api<ResetStatus>('/demo/reset', { method: 'POST' }),
    onSuccess: (r) => {
      setConfirming(false)
      setMessage(null)
      queryClient.setQueryData(['demo-reset'], r)
    },
    onError: (e) => {
      setConfirming(false)
      setMessage(e instanceof ApiError ? e.message : t('errors.generic'))
    },
  })

  return (
    <div className="mt-8 text-center text-sm text-ink-soft" aria-live="polite">
      {running ? (
        <p>{t('login.reset.running')}</p>
      ) : confirming ? (
        <p className="flex flex-wrap items-center justify-center gap-2">
          {t('login.reset.confirm')}
          <button
            onClick={() => reset.mutate()}
            disabled={reset.isPending}
            className="rounded-md bg-ember px-2.5 py-1 font-medium text-on-ember disabled:opacity-40"
          >
            {t('login.reset.yes')}
          </button>
          <button onClick={() => setConfirming(false)} className="underline">
            {t('login.reset.cancel')}
          </button>
        </p>
      ) : (
        <p>
          {message && <span className="mr-2">{message}</span>}
          <button onClick={() => setConfirming(true)} className="text-ember underline-offset-2 hover:underline">
            {t('login.reset.ask')}
          </button>
        </p>
      )}
    </div>
  )
}

export default function Login() {
  const { t } = useTranslation()
  const { signInAsPersona } = useAuth()
  const navigate = useNavigate()
  const [pending, setPending] = useState<number | null>(null)
  const [error, setError] = useState(false)
  const personas = useQuery({ queryKey: ['personas'], queryFn: () => api<User[]>('/auth/personas') })
  const [params] = useSearchParams()
  const autoTried = useRef(false)

  // Deep links for judges and the README: /login?as=elena.rivera&next=/inventory or /login?as=reviewer
  useEffect(() => {
    const wanted = params.get('as')?.toLowerCase()
    if (!wanted || !personas.data || autoTried.current) return
    autoTried.current = true
    const match = personas.data.find((p) => p.email.startsWith(`${wanted}@`) || p.role === wanted)
    if (match) void choose(match)
  })

  async function choose(user: User) {
    setPending(user.id)
    setError(false)
    try {
      const signedIn = await signInAsPersona(user.id)
      const next = params.get('next')
      navigate(next?.startsWith('/') && !next.startsWith('//') ? next : homePathFor(signedIn.role))
    } catch {
      setError(true)
    } finally {
      setPending(null)
    }
  }

  const persona = (p: User) =>
    t(`login.persona.${p.email.split('@')[0].replace('.', '_')}`, {
      defaultValue: p.title?.split(' · ')[1] ?? p.title,
    })

  return (
    <div className="flex min-h-svh flex-col">
      <Dateline />
      <div className="mx-auto w-full max-w-6xl flex-1 px-4">
        <header className="flex items-end justify-between gap-4 border-b-4 border-ink pt-8 pb-4">
          <Wordmark size="lg" />
        </header>

        <section className="grid gap-x-12 gap-y-8 border-b border-ink py-10 lg:grid-cols-[minmax(0,1.35fr)_minmax(0,1fr)]">
          <div>
            <p className="kicker text-ember">{STAGES.map((s) => t(`app.stages.${s}`)).join(' · ')}</p>
            <h1 className="mt-4 text-5xl leading-[1.02] tracking-tight text-balance sm:text-6xl">{t('app.tagline')}</h1>
            <p className="mt-6 max-w-xl text-lg leading-relaxed text-ink-soft">{t('login.lede')}</p>
          </div>
          <ol className="divide-y divide-line self-end border-t border-ink lg:border-t-0">
            {STAGES.map((stage, i) => (
              <li key={stage} className="grid grid-cols-[2.5rem_minmax(0,1fr)] gap-2 py-3">
                <span className="font-mono text-sm text-ember">{String(i + 1).padStart(2, '0')}</span>
                <div>
                  <p className="font-serif text-xl font-semibold">{t(`app.stages.${stage}`)}</p>
                  <p className="text-sm text-ink-soft">{t(`login.stageLines.${stage}`)}</p>
                </div>
              </li>
            ))}
          </ol>
        </section>

        <section aria-labelledby="cast-title" className="py-10">
          <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-2">
            <h2 id="cast-title" className="text-3xl">
              {t('login.title')}
            </h2>
            <p className="max-w-xl text-ink-soft">{t('login.subtitle')}</p>
          </div>

          {(error || personas.isError) && (
            <p role="alert" className="mt-6 border-l-2 border-danger bg-danger-soft px-4 py-3 text-danger">
              {t('login.error')}
            </p>
          )}

          {personas.isPending && <div className="mt-8 h-96 animate-pulse bg-sunken" />}
          <div className="mt-6 grid gap-x-10 gap-y-8 lg:grid-cols-3">
            {personas.data &&
              GROUPS.map((g) => (
                <div key={g.key}>
                  <h3 className="kicker border-b border-ink pb-2 text-ink">{t(`login.groups.${g.key}`)}</h3>
                  <ul className="divide-y divide-line">
                    {personas.data
                      .filter((p) => g.roles.includes(p.role))
                      .map((p) => (
                        <li key={p.id}>
                          <button
                            onClick={() => void choose(p)}
                            disabled={pending !== null}
                            className="group grid w-full grid-cols-[minmax(0,1fr)_auto] items-start gap-3 py-4 text-left disabled:opacity-60"
                          >
                            <span className="min-w-0">
                              <span className="block font-serif text-xl font-semibold group-hover:text-ember">
                                {p.name}
                              </span>
                              <span className="kicker block text-ink-faint">{t(`roles.${p.role}`)}</span>
                              <span className="mt-1 block text-sm text-ink-soft first-letter:uppercase">
                                {persona(p)}
                              </span>
                            </span>
                            <span
                              aria-hidden
                              className="mt-0.5 text-2xl leading-none text-ember transition-transform group-hover:translate-x-1"
                            >
                              {pending === p.id ? '…' : '→'}
                            </span>
                            <span className="sr-only">{t('login.signIn', { name: p.name.split(' ')[0] })}</span>
                          </button>
                        </li>
                      ))}
                  </ul>
                </div>
              ))}
          </div>
        </section>

        <DemoTour />
        <ResetDemo />
      </div>
      <div className="mt-10">
        <Footer />
      </div>
    </div>
  )
}
