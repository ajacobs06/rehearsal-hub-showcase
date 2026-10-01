import { useEffect, useState } from 'react'
import { PARTS, RSVP_OPTIONS, formatWhen, rehearsalsApi, type Member, type Rehearsal, type RsvpResponse } from './api'
import { ForGroups, RehearsalForm, internalLink } from './Rehearsals'

type Navigate = (to: string) => void

const PART_COLUMNS: { key: string; label: string }[] = [
  ...PARTS.map((p) => ({ key: p.value, label: p.label })),
  { key: 'none', label: 'No part' },
]

/** Reply totals; the API only sends them to admins. */
function countsLine(r: Rehearsal): string {
  const c = r.counts
  if (!c) return ''
  const parts = [`${c.yes} going`]
  if (c.maybe) parts.push(`${c.maybe} maybe`)
  if (c.no) parts.push(`${c.no} can't go`)
  parts.push(`${c.noReply} no reply`)
  return parts.join(', ')
}

/** Admin: every rehearsal (all groups, upcoming and past) and "Add a rehearsal". */
export function AdminRehearsalList({ me, navigate }: { me: Member; navigate: Navigate }) {
  const [upcoming, setUpcoming] = useState<Rehearsal[] | null>(null)
  const [past, setPast] = useState<Rehearsal[]>([])
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    rehearsalsApi
      .list('upcoming', 'all')
      .then(setUpcoming)
      .catch(() => setError(true))
    rehearsalsApi
      .list('past', 'all')
      .then(setPast)
      .catch(() => setPast([]))
  }, [])

  if (error) return <p className="error">Couldn't load rehearsals. Refresh the page to try again.</p>

  const row = (r: Rehearsal) => (
    <li key={r.id}>
      <a {...internalLink(`/admin/rehearsals/${r.id}`, navigate)}>
        <span className="song-title">{formatWhen(r.start, r.end)}</span>
        <span className="muted small">{r.venue}</span>
        <ForGroups ids={r.groups} />
        <span className="small">{countsLine(r)}</span>
      </a>
    </li>
  )

  return (
    <>
      {adding ? (
        <>
          <h3>Add a rehearsal</h3>
          <RehearsalForm
            me={me}
            submitLabel="Add rehearsal"
            onCancel={() => setAdding(false)}
            onSubmit={async (body) => navigate(`/admin/rehearsals/${(await rehearsalsApi.create(body)).id}`)}
          />
        </>
      ) : (
        <div>
          <button className="button" onClick={() => setAdding(true)}>
            Add a rehearsal
          </button>
        </div>
      )}

      <section className="stack">
        <h3>Coming up</h3>
        {upcoming === null ? (
          <div className="panel">
            <div className="skeleton skeleton-line" />
          </div>
        ) : upcoming.length === 0 ? (
          <p className="muted">Nothing scheduled.</p>
        ) : (
          <ul className="song-list">{upcoming.map(row)}</ul>
        )}
      </section>

      {past.length > 0 && (
        <section className="stack">
          <h3>Past</h3>
          <ul className="song-list">{past.map(row)}</ul>
        </section>
      )}
    </>
  )
}

/** Admin: one rehearsal's numbers, replies, edit and delete. */
export function AdminRehearsalDetail({ id, me, navigate }: { id: string; me: Member; navigate: Navigate }) {
  const [r, setR] = useState<Rehearsal | null>(null)
  const [missing, setMissing] = useState(false)
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    rehearsalsApi
      .get(id)
      .then(setR)
      .catch(() => setMissing(true))
  }, [id])

  const back = (
    <div className="row">
      <a className="back" {...internalLink('/admin/rehearsals', navigate)}>
        All rehearsals
      </a>
      {r && (
        <a className="manage-link small" {...internalLink(`/rehearsals/${id}`, navigate)}>
          View as member
        </a>
      )}
    </div>
  )

  if (missing)
    return (
      <>
        {back}
        <p className="muted">That rehearsal doesn't exist any more.</p>
      </>
    )
  if (!r)
    return (
      <>
        {back}
        <div className="skeleton skeleton-title" />
      </>
    )

  return (
    <>
      {back}
      <div>
        <h2 className="detail-title">{formatWhen(r.start, r.end)}</h2>
        <p className="muted">{r.venue}</p>
        <ForGroups ids={r.groups} />
        <p className="small">{countsLine(r)}</p>
      </div>
      {r.songParts && r.songParts.length > 0 && <PartNumbers r={r} />}
      {r.attendees && <Replies r={r} />}
      {editing ? (
        <RehearsalForm
          me={me}
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
      <DeleteRehearsal r={r} onDeleted={() => navigate('/admin/rehearsals')} />
    </>
  )
}

/** Per song on the plan: how many in each part are coming (by the part they sing on that song). */
export function PartNumbers({ r }: { r: Rehearsal }) {
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

export function Replies({ r }: { r: Rehearsal }) {
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

export function DeleteRehearsal({ r, onDeleted }: { r: Rehearsal; onDeleted: () => void }) {
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
