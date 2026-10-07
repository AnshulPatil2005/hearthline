import { useEffect, useState } from 'react'
import { API_URL } from './api'

type Health = { status: string; integrations: Record<string, boolean> }

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch(`${API_URL}/health`)
      .then((r) => (r.ok ? r.json() : Promise.reject(new Error(`HTTP ${r.status}`))))
      .then(setHealth)
      .catch((e: Error) => setError(e.message))
  }, [])

  return (
    <main style={{ maxWidth: 720, margin: '0 auto', padding: '48px 16px' }}>
      <h1>Hearthline</h1>
      <p style={{ color: 'var(--muted)', marginTop: 8 }}>
        Prepare · Respond · Rebuild · Reopen
      </p>

      <section
        style={{
          marginTop: 32,
          padding: 20,
          background: 'var(--surface)',
          border: '1px solid var(--border)',
          borderRadius: 12,
        }}
      >
        <h2 style={{ fontSize: 18 }}>System status</h2>
        {error && <p style={{ color: 'var(--warn)' }}>API unreachable at <code>{API_URL}</code> ({error})</p>}
        {!error && !health && <p>Checking API…</p>}
        {health && (
          <ul style={{ listStyle: 'none', padding: 0, margin: '12px 0 0' }}>
            {Object.entries(health.integrations).map(([name, ok]) => (
              <li key={name} style={{ display: 'flex', justifyContent: 'space-between', padding: '6px 0' }}>
                <span>{name}</span>
                <span style={{ color: ok ? 'var(--ok)' : 'var(--muted)' }}>{ok ? 'configured' : 'not configured'}</span>
              </li>
            ))}
          </ul>
        )}
      </section>
    </main>
  )
}
