import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, signInUrl, signOutUrl, type Member } from './api'
import Home from './Home'
import Members from './Members'

type Session =
  | { kind: 'loading' }
  | { kind: 'signed-out' }
  | { kind: 'not-invited'; email: string }
  | { kind: 'error' }
  | { kind: 'member'; member: Member }

function usePath(): [string, (to: string) => void] {
  const [path, setPath] = useState(window.location.pathname)
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const navigate = useCallback((to: string) => {
    window.history.pushState(null, '', to)
    setPath(to)
  }, [])
  return [path, navigate]
}

export default function App() {
  const [session, setSession] = useState<Session>({ kind: 'loading' })
  const [path, navigate] = usePath()

  const load = useCallback(() => {
    api
      .me()
      .then((member) => setSession({ kind: 'member', member }))
      .catch((err: unknown) => {
        if (err instanceof ApiError && err.status === 401) setSession({ kind: 'signed-out' })
        else if (err instanceof ApiError && err.reason === 'not_invited')
          setSession({ kind: 'not-invited', email: err.email ?? '' })
        else setSession({ kind: 'error' })
      })
  }, [])

  useEffect(load, [load])

  if (session.kind === 'loading') {
    return (
      <main className="page" aria-busy="true">
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-line" />
        <div className="skeleton skeleton-line short" />
      </main>
    )
  }

  if (session.kind === 'signed-out') {
    return (
      <main className="page gate">
        <h1>Rehearsal Hub</h1>
        <p className="lede">Learning tracks and rehearsal plans for the UoB Barbershop Singing Society.</p>
        <a className="button" href={signInUrl}>
          Sign in with Google
        </a>
        <p className="muted small">Use the email address the committee invited.</p>
      </main>
    )
  }

  if (session.kind === 'not-invited') {
    return (
      <main className="page gate">
        <h1>You're not on the list yet</h1>
        <p className="lede">
          You're signed in as <strong>{session.email}</strong>, but that address hasn't been invited.
        </p>
        <p>Ask a committee member to invite this address, or sign out and try a different Google account.</p>
        <a className="button secondary" href={signOutUrl}>
          Sign out
        </a>
      </main>
    )
  }

  if (session.kind === 'error') {
    return (
      <main className="page gate">
        <h1>Something went wrong</h1>
        <p className="lede">We couldn't reach Rehearsal Hub. Check your connection and try again.</p>
        <button className="button" onClick={load}>
          Try again
        </button>
      </main>
    )
  }

  const { member } = session
  const isAdmin = member.role !== 'member'
  const view = isAdmin && path === '/members' ? 'members' : 'home'

  const link = (to: string, label: string, active: boolean) => (
    <a
      href={to}
      aria-current={active ? 'page' : undefined}
      onClick={(e) => {
        e.preventDefault()
        navigate(to)
      }}
    >
      {label}
    </a>
  )

  return (
    <>
      <header className="topbar">
        <span className="wordmark">Rehearsal Hub</span>
        <nav>
          {isAdmin && link('/', 'Home', view === 'home')}
          {isAdmin && link('/members', 'Members', view === 'members')}
          <a href={signOutUrl}>Sign out</a>
        </nav>
      </header>
      <main className="page">
        {view === 'members' ? (
          <Members me={member} />
        ) : (
          <Home member={member} onChange={(m) => setSession({ kind: 'member', member: m })} />
        )}
      </main>
    </>
  )
}
