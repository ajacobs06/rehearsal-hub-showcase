import { useEffect, useState } from 'react'
import { PARTS, RSVP_OPTIONS, formatWhen, rehearsalsApi, type Member, type Rehearsal, type RsvpResponse } from './api'
import { RehearsalForm, RsvpButtons, SongsToPrepare, countsLine, internalLink } from './Rehearsals'

const PART_COLUMNS: { key: string; label: string }[] = [...PARTS.map((p) => ({ key: p.value, label: p.label })), { key: 'none', label: 'No part' }]

export default function RehearsalPage({ id, me, navigate }: { id: string; me: Member; navigate: (to: string) => void }) {
  const [r, setR] = useState<Rehearsal | null>(null)
  const [missing, setMissing] = useState(false)
  const [editing, setEditing] = useState(false)
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
      {back}
      <div>
        <h1>{formatWhen(r.start, r.end)}</h1>
        <p className="muted">{r.venue}</p>
      </div>

      {r.notes && <p className="notes">{r.notes}</p>}

      <section className="panel">
        <h2>Are you coming?</h2>
        <RsvpButtons r={r} onChange={setR} />
        <p className="muted small hint-below">{countsLine(r)}</p>
      </section>

      <section>
        <h2>Songs to prepare</h2>
        <SongsToPrepare r={r} navigate={navigate} />
      </section>

      {isAdmin && (
        <section className="admin">
          <h2>Manage this rehearsal</h2>
          {r.songParts && r.songParts.length > 0 && <PartNumbers r={r} />}
          {r.attendees && <Replies r={r} />}
          {editing ? (
            <RehearsalForm
              initial={r}
              submitLabel="Save changes"
              onCancel={() => setEditing(false)}
              onSubmit={async (body) => {
                setR(await rehearsalsApi.update(r.id, body))
                setEditing(false)
              }}
            />
          ) : (
            <div>
              <button className="button secondary" onClick={() => setEditing(true)}>
                Edit rehearsal
              </button>
            </div>
          )}
          <DeleteRehearsal r={r} onDeleted={() => navigate('/schedule')} />
        </section>
      )}
    </>
  )
}

/** Per song on the plan: how many in each part are coming (by the part they sing on that song). */
function PartNumbers({ r }: { r: Rehearsal }) {
  const used = PART_COLUMNS.filter((c) => r.songParts!.some((sp) => sp.parts[c.key]))
  return (
    <div className="panel">
      <h3>Who's coming, by part</h3>
      <p className="muted small">Going, plus maybes in brackets. Uses the part each person sings on that song.</p>
      <div className="table-wrap flat">
        <table className="grid">
          <thead>
            <tr>
              <th scope="col">Song</th>
              {used.map((c) => (
                <th key={c.key} scope="col">
                  {c.label}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {r.songParts!.map((sp) => (
              <tr key={sp.songId}>
                <th scope="row">{sp.title}</th>
                {used.map((c) => {
                  const n = sp.parts[c.key]
                  return (
                    <td key={c.key} className={!n || n.yes === 0 ? 'short' : undefined}>
                      {n ? `${n.yes}${n.maybe ? ` (+${n.maybe})` : ''}` : '0'}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

function Replies({ r }: { r: Rehearsal }) {
  const groups: { key: RsvpResponse | null; label: string }[] = [
    ...RSVP_OPTIONS.map((o) => ({ key: o.value, label: o.label })),
    { key: null, label: 'No reply yet' },
  ]
  const partLabel = (p: string | null) => PARTS.find((x) => x.value === p)?.label ?? 'No part'
  return (
    <div className="panel">
      <h3>Replies</h3>
      <div className="replies">
        {groups.map((g) => {
          const people = r.attendees!.filter((a) => a.response === g.key)
          if (people.length === 0) return null
          return (
            <div key={g.label}>
              <h4>
                {g.label} <span className="count">{people.length}</span>
              </h4>
              <ul className="who">
                {people.map((a) => (
                  <li key={a.memberId}>
                    <span>{a.name}</span>
                    <span className="muted small">{partLabel(a.part)}</span>
                  </li>
                ))}
              </ul>
            </div>
          )
        })}
      </div>
    </div>
  )
}

function DeleteRehearsal({ r, onDeleted }: { r: Rehearsal; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState(false)
  return (
    <div className="danger-zone">
      {confirming ? (
        <>
          <p>Delete this rehearsal and everyone's replies? This can't be undone.</p>
          <div className="actions">
            <button
              className="button danger"
              onClick={() =>
                rehearsalsApi
                  .remove(r.id)
                  .then(onDeleted)
                  .catch(() => setError(true))
              }
            >
              Delete rehearsal
            </button>
            <button className="button secondary" onClick={() => setConfirming(false)}>
              Keep
            </button>
          </div>
        </>
      ) : (
        <button className="button secondary" onClick={() => setConfirming(true)}>
          Delete rehearsal
        </button>
      )}
      {error && <p className="error">Couldn't delete the rehearsal. Try again.</p>}
    </div>
  )
}
