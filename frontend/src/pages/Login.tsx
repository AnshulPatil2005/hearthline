import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router'
import { api, ApiError, type Role, type User } from '../api'
import { useAuth } from '../auth'
import { DemoTour } from '../components/DemoTour'
import { Footer } from '../components/Footer'
import { LanguageSelect, Logo } from '../components/Shell'
import { homePathFor } from '../paths'

const ROLE_TINT: Record<Role, string> = {
  household: 'bg-ember-soft text-ember',
  donor: 'bg-sage-soft text-sage',
  contractor: 'bg-amber-soft text-amber',
  reviewer: 'bg-sunken text-ink',
  supervisor: 'bg-sunken text-ink',
  org_admin: 'bg-sage-soft text-sage',
  business: 'bg-amber-soft text-amber',
}

const initials = (name: string) =>
  name
    .split(' ')
    .map((part) => part[0])
    .join('')
    .slice(0, 2)

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

  return (
    <div className="min-h-svh px-4 py-10">
      <div className="mx-auto max-w-5xl">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2 text-lg font-semibold">
            <Logo className="size-8" />
            Hearthline
          </div>
          <LanguageSelect />
        </div>

        <div className="mt-12 max-w-2xl">
          <p className="text-sm font-medium tracking-wide text-ember uppercase">
            {(['prepare', 'respond', 'rebuild', 'reopen'] as const).map((s) => t(`app.stages.${s}`)).join(' · ')}
          </p>
          <h1 className="mt-3 text-4xl font-semibold tracking-tight text-balance">{t('app.tagline')}</h1>
          <h2 className="mt-8 text-xl font-semibold">{t('login.title')}</h2>
          <p className="mt-2 text-ink-soft">{t('login.subtitle')}</p>
        </div>

        {(error || personas.isError) && (
          <p role="alert" className="mt-6 rounded-lg bg-danger-soft px-4 py-3 text-danger">
            {t('login.error')}
          </p>
        )}

        <ul className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {personas.isPending &&
            Array.from({ length: 8 }, (_, i) => <li key={i} className="h-44 animate-pulse rounded-xl bg-sunken" />)}
          {personas.data?.map((p) => (
            <li key={p.id}>
              <button
                onClick={() => void choose(p)}
                disabled={pending !== null}
                className="flex h-full w-full flex-col rounded-xl border border-line bg-surface p-4 text-left shadow-sm transition hover:-translate-y-0.5 hover:border-ember hover:shadow-md disabled:opacity-60"
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`grid size-10 place-items-center rounded-full text-sm font-semibold ${ROLE_TINT[p.role]}`}
                  >
                    {initials(p.name)}
                  </span>
                  <div>
                    <div className="font-semibold">{p.name}</div>
                    <div className="text-xs text-ink-faint">{t(`roles.${p.role}`)}</div>
                  </div>
                </div>
                <p className="mt-3 flex-1 text-sm text-ink-soft first-letter:uppercase">
                  {t(`login.persona.${p.email.split('@')[0].replace('.', '_')}`, {
                    defaultValue: p.title?.split(' · ')[1] ?? p.title,
                  })}
                </p>
                <span className="mt-4 text-sm font-medium text-ember">
                  {pending === p.id ? '…' : t('login.signIn', { name: p.name.split(' ')[0] })} →
                </span>
              </button>
            </li>
          ))}
        </ul>

        <DemoTour />
        <ResetDemo />
      </div>
      <div className="mt-10">
        <Footer />
      </div>
    </div>
  )
}
