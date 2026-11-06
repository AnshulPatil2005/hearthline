import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useRef, useState } from 'react'
import { useTranslation } from 'react-i18next'
import { useNavigate, useSearchParams } from 'react-router'
import { api, ApiError, type Role, type User } from '../api'
import { useAuth } from '../auth'
import { DemoTour } from '../components/DemoTour'
import { Footer } from '../components/Footer'
import { FeatureIndex, QuickFacts, SponsorShowcase, WhyItMatters } from '../components/Showcase'
import { LanguageSelect, Wordmark } from '../components/Shell'
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
    <div id="reset" className="mt-8 scroll-mt-6 text-center text-sm text-ink-soft" aria-live="polite">
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
  const people = GROUPS.flatMap((g) => (personas.data ?? []).filter((p) => g.roles.includes(p.role)))

  return (
    <div className="flex min-h-svh flex-col">
      <header className="border-b border-line bg-surface">
        <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3">
          <Wordmark />
          <nav className="flex items-center gap-5 text-sm">
            <a href="#features" className="hidden text-ink-soft hover:text-ink sm:inline">
              {t('showcase.navFeatures')}
            </a>
            <a href="#sponsors" className="hidden text-ink-soft hover:text-ink sm:inline">
              {t('showcase.navSponsors')}
            </a>
            <a href="#tour" className="hidden text-ink-soft hover:text-ink sm:inline">
              {t('showcase.navTour')}
            </a>
            <LanguageSelect />
          </nav>
        </div>
      </header>

      <main className="mx-auto w-full max-w-6xl flex-1 space-y-14 px-4 py-10">
        <section className="space-y-6">
          <div className="max-w-3xl">
            <p className="text-sm font-medium text-ember">{STAGES.map((s) => t(`app.stages.${s}`)).join(' · ')}</p>
            <h1 className="mt-2 text-4xl leading-tight tracking-tight text-balance sm:text-5xl">{t('app.tagline')}</h1>
            <p className="mt-4 text-lg text-ink-soft">{t('login.lede')}</p>
            <div className="mt-6 flex flex-wrap gap-3">
              <a href="#tour" className="rounded-lg bg-ember px-4 py-2.5 font-medium text-on-ember hover:opacity-90">
                {t('showcase.ctaTour')}
              </a>
              <a
                href="#features"
                className="rounded-lg border border-line bg-surface px-4 py-2.5 font-medium hover:bg-sunken"
              >
                {t('showcase.ctaFeatures')}
              </a>
              <a
                href="#sponsors"
                className="rounded-lg border border-line bg-surface px-4 py-2.5 font-medium hover:bg-sunken"
              >
                {t('showcase.ctaSponsors')}
              </a>
            </div>
          </div>
          <QuickFacts />
        </section>

        <WhyItMatters />

        <section aria-labelledby="cast-title">
          <div className="flex flex-wrap items-end justify-between gap-x-8 gap-y-1">
            <h2 id="cast-title" className="text-2xl">
              {t('login.title')}
            </h2>
            <p className="max-w-xl text-sm text-ink-soft">{t('login.subtitle')}</p>
          </div>
          {(error || personas.isError) && (
            <p role="alert" className="mt-4 rounded-lg bg-danger-soft px-4 py-3 text-danger">
              {t('login.error')}
            </p>
          )}
          <ul className="mt-4 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {personas.isPending &&
              Array.from({ length: 9 }, (_, i) => <li key={i} className="h-24 animate-pulse rounded-xl bg-sunken" />)}
            {people.map((p) => (
              <li key={p.id}>
                <button
                  onClick={() => void choose(p)}
                  disabled={pending !== null}
                  className="panel flex h-full w-full flex-col p-4 text-left hover:border-ember disabled:opacity-60"
                >
                  <span className="min-w-0">
                    <span className="block font-semibold">{p.name}</span>
                    <span className="block text-xs text-ink-faint">{t(`roles.${p.role}`)}</span>
                    <span className="mt-1 block text-sm text-ink-soft first-letter:uppercase">{persona(p)}</span>
                  </span>
                  <span className="mt-auto pt-3 text-sm font-medium text-ember">
                    {pending === p.id ? '…' : t('login.signIn', { name: p.name.split(' ')[0] })} →
                  </span>
                </button>
              </li>
            ))}
          </ul>
        </section>

        <FeatureIndex />
        <SponsorShowcase />
        <div id="tour" className="scroll-mt-6">
          <DemoTour />
        </div>
        <ResetDemo />
      </main>
      <Footer />
    </div>
  )
}
