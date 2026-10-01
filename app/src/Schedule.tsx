import { useEffect, useState } from 'react'
import { formatWhen, rehearsalsApi, type Rehearsal } from './api'
import { RehearsalCard, internalLink } from './Rehearsals'

export default function Schedule({ navigate }: { navigate: (to: string) => void }) {
  const [upcoming, setUpcoming] = useState<Rehearsal[] | null>(null)
  const [past, setPast] = useState<Rehearsal[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    rehearsalsApi
      .list('upcoming')
      .then(setUpcoming)
      .catch(() => setError(true))
    rehearsalsApi
      .list('past')
      .then(setPast)
      .catch(() => setPast([]))
  }, [])

  const replace = (r: Rehearsal) => setUpcoming((list) => list?.map((x) => (x.id === r.id ? r : x)) ?? null)

  if (error) return <p className="error">Couldn't load the schedule. Refresh the page to try again.</p>

  return (
    <>
      <h1>Schedule</h1>


      <section className="stack">
        <h2>Coming up</h2>
        {upcoming === null ? (
          <div className="panel">
            <div className="skeleton skeleton-line" />
            <div className="skeleton skeleton-line short" />
          </div>
        ) : upcoming.length === 0 ? (
          <p className="muted">
            Nothing scheduled yet. Check back soon.
          </p>
        ) : (
          upcoming.map((r) => <RehearsalCard key={r.id} r={r} navigate={navigate} onChange={replace} />)
        )}
      </section>

      {past && past.length > 0 && (
        <section>
          <h2>Past rehearsals</h2>
          <ul className="song-list">
            {past.map((r) => (
              <li key={r.id}>
                <a {...internalLink(`/rehearsals/${r.id}`, navigate)}>
                  <span className="song-title">{formatWhen(r.start, r.end)}</span>
                  <span className="muted small">{r.venue}</span>
                </a>
              </li>
            ))}
          </ul>
        </section>
      )}
    </>
  )
}
