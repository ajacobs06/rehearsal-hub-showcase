import { useCallback, useEffect, useState } from 'react'
import { ApiError, api, signInUrl, signOutUrl, type Member } from './api'

// The BSS badge, used as-is: never recoloured, stretched or cropped.
const LOGO = '/bss-logo.png'
import Home from './Home'
import { internalLink } from './Rehearsals'
import Account from './Account'
import Admin from './Admin'
import FeedbackPage from './FeedbackPage'
import Privacy from './Privacy'
import RehearsalPage from './RehearsalPage'
import Schedule from './Schedule'
import SongPage from './SongPage'

type Session =
  | { kind: 'loading' }
  | { kind: 'signed-out' }
  | { kind: 'not-invited'; email: string }
  | { kind: 'error' }
  | { kind: 'member'; member: Member }

function usePath(): [string, (to: string) => void] {
  const [path, setPath] = useState(window.location.pathname + window.location.search)
  useEffect(() => {
    const onPop = () => setPath(window.location.pathname + window.location.search)
    window.addEventListener('popstate', onPop)
    return () => window.removeEventListener('popstate', onPop)
  }, [])
  const navigate = useCallback((to: string) => {
    window.history.pushState(null, '', to)
    setPath(to)
    window.scrollTo(0, 0)
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

  const [pathname, query = ''] = path.split('?')

  // The privacy notice is public: signed-out visitors get it on its own.
  if (pathname === '/privacy' && session.kind !== 'member') {
    return (
      <main className="page">
        <Privacy
          back={
            <a className="back" {...internalLink('/', navigate)}>
              Back
            </a>
          }
        />
      </main>
    )
  }

  if (session.kind === 'signed-out') {
    return (
      <main className="page gate welcome">
        <img className="gate-logo" src={LOGO} alt="Barbershop Singing Society" width={144} height={144} />
        <div className="gate-copy">
          <h1>Rehearsal Hub</h1>
          <p className="lede">
            Learning tracks, progress and the rehearsal schedule for members of the University of Birmingham Barbershop
            Singing Society.
          </p>
        </div>
        <div className="gate-action">
          <a className="button" href={signInUrl}>
            Sign in with Google
          </a>
          <p className="muted small">Not on the list yet? Ask the committee to invite the Google account you'll use.</p>
          <a className="small text-link" {...internalLink('/privacy', navigate)}>
            Privacy notice
          </a>
        </div>
      </main>
    )
  }

  if (session.kind === 'not-invited') {
    return (
      <main className="page gate">
        <img className="gate-logo small" src={LOGO} alt="Barbershop Singing Society" width={96} height={96} />
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
        <img className="gate-logo small" src={LOGO} alt="Barbershop Singing Society" width={96} height={96} />
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
  const songId = pathname.match(/^\/songs\/([A-Za-z0-9]+)$/)?.[1]
  const rehearsalId = pathname.match(/^\/rehearsals\/([A-Za-z0-9]+)$/)?.[1]
  // Old bookmarks from before the admin page existed.
  const adminPath = pathname === '/members' ? '/admin/members' : pathname === '/tracker' ? '/admin/tracker' : pathname
  const view = isAdmin && adminPath.startsWith('/admin')
    ? 'admin'
    : pathname === '/schedule'
      ? 'schedule'
      : pathname === '/privacy'
        ? 'privacy'
        : pathname === '/feedback'
          ? 'feedback'
          : pathname === '/account'
            ? 'account'
            : rehearsalId
              ? 'rehearsal'
              : songId
                ? 'song'
                : 'home'
  const backHome = (
    <a className="back" {...internalLink('/', navigate)}>
      Home
    </a>
  )

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
        <a
          className="wordmark"
          href="/"
          onClick={(e) => {
            e.preventDefault()
            navigate('/')
          }}
        >
          <img src={LOGO} alt="" width={32} height={32} />
          Rehearsal Hub
        </a>
        {/* Top bar on wider screens, bottom tab bar on phones (see index.css). */}
        <nav className="primary" aria-label="Main">
          {link('/', 'Home', view === 'home')}
          {link('/schedule', 'Schedule', view === 'schedule' || view === 'rehearsal')}
          {isAdmin && link('/admin', 'Admin', view === 'admin')}
        </nav>
        <a className="signout" href={signOutUrl}>
          Sign out
        </a>
      </header>
      <main className="page">
        {view === 'admin' ? (
          <Admin path={adminPath} me={member} navigate={navigate} />
        ) : view === 'schedule' ? (
          <Schedule navigate={navigate} />
        ) : view === 'rehearsal' && rehearsalId ? (
          <RehearsalPage key={rehearsalId} id={rehearsalId} me={member} navigate={navigate} />
        ) : view === 'song' && songId ? (
          <SongPage key={songId} id={songId} me={member} navigate={navigate} />
        ) : view === 'privacy' ? (
          <Privacy back={backHome} />
        ) : view === 'feedback' ? (
          <FeedbackPage from={new URLSearchParams(query).get('from')} back={backHome} />
        ) : view === 'account' ? (
          <Account me={member} back={backHome} />
        ) : (
          <Home member={member} navigate={navigate} onChange={(m) => setSession({ kind: 'member', member: m })} />
        )}
        <footer className="site-footer">
          <a className="text-link" {...internalLink('/privacy', navigate)}>
            Privacy
          </a>
          <a className="text-link" {...internalLink('/account', navigate)}>
            Your data
          </a>
          <a className="text-link" {...internalLink(`/feedback?from=${encodeURIComponent(pathname)}`, navigate)}>
            Send feedback
          </a>
        </footer>
      </main>
    </>
  )
}
