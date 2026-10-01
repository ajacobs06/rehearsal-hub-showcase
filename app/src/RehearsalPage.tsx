import { useEffect, useState } from 'react'
import { formatWhen, rehearsalsApi, type Member, type Rehearsal } from './api'
import { ForGroups, RsvpButtons, SongsToPrepare, internalLink } from './Rehearsals'


export default function RehearsalPage({ id, me, navigate }: { id: string; me: Member; navigate: (to: string) => void }) {
  const [r, setR] = useState<Rehearsal | null>(null)
  const [missing, setMissing] = useState(false)
  const isAdmin = me.role !== 'member'

  useEffect(() => {
    rehearsalsApi
      .get(id)
      .then(setR)
      .catch(() => setMissing(true))
  }, [id])

  const back = (
    <a className="back" {...internalLink('/schedule', navigate)}>
      Schedule
    </a>
  )

  if (missing)
    return (
      <>
        {back}
        <h1>Rehearsal not found</h1>
        <p className="muted">It may have been cancelled.</p>
      </>
    )

  if (!r)
    return (
      <>
        {back}
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-line" />
      </>
    )

  return (
    <>
      <div className="row">
        {back}
        {isAdmin && (
          <a className="manage-link small" {...internalLink(`/admin/rehearsals/${r.id}`, navigate)}>
            Manage rehearsal
          </a>
        )}
      </div>
      <div>
        <h1>{formatWhen(r.start, r.end)}</h1>
        <p className="muted">{r.venue}</p>
        <ForGroups ids={r.groups} />
      </div>

      {r.notes && <p className="notes">{r.notes}</p>}

      <section className="panel">
        <h2>Are you coming?</h2>
        <RsvpButtons r={r} onChange={setR} />
      </section>

      <section>
        <h2>Songs to prepare</h2>
        <SongsToPrepare r={r} navigate={navigate} />
      </section>

    </>
  )
}

