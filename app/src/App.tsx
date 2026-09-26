import { useEffect, useState } from 'react'

type Health = { status: string; time: string }

export default function App() {
  const [health, setHealth] = useState<Health | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    fetch('/api/health')
      .then((res) => {
        if (!res.ok) throw new Error(`HTTP ${res.status}`)
        return res.json() as Promise<Health>
      })
      .then(setHealth)
      .catch((err: Error) => setError(err.message))
  }, [])

  return (
    <main style={{ padding: '2rem 1rem', maxWidth: '40rem', margin: '0 auto' }}>
      <h1>Rehearsal Hub</h1>
      <p>
        API:{' '}
        {error ? `unreachable (${error})` : health ? `${health.status} at ${health.time}` : 'checking…'}
      </p>
    </main>
  )
}
