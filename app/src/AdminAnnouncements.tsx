import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, announcementsApi, formatDay, type Announcement, type AnnouncementInput, type Group, type Member } from './api'
import { AnnouncementBody, byline } from './Announcements'
import { GroupCheckboxes, groupNames, useGroups } from './groups'
import { internalLink } from './Rehearsals'

type Navigate = (to: string) => void

/** A post whose only group was deleted is kept for admins only (the server never widens it). */
function audience(ids: string[], groups: Group[] | null): { text: string; hidden: boolean } {
  if (ids.length === 0) return { text: 'Everyone', hidden: false }
  const names = groupNames(ids, groups)
  if (groups && !names) return { text: 'Its group was deleted, so only admins can see it', hidden: true }
  return { text: `For: ${names}`, hidden: false }
}

function Audience({ ids }: { ids: string[] }) {
  const groups = useGroups()
  const { text, hidden } = audience(ids, groups)
  return <p className={`small ${hidden ? 'error' : 'for-groups'}`}>{text}</p>
}

/** Admin: every announcement, newest first, and "Post an announcement". */
export function AdminAnnouncementList({ me, navigate }: { me: Member; navigate: Navigate }) {
  const [list, setList] = useState<Announcement[] | null>(null)
  const [adding, setAdding] = useState(false)
  const [error, setError] = useState(false)

  useEffect(() => {
    announcementsApi
      .list('all')
      .then(setList)
      .catch(() => setError(true))
  }, [])

  if (error) return <p className="error">Couldn't load announcements. Refresh the page to try again.</p>

  return (
    <>
      {adding ? (
        <>
          <h3>Post an announcement</h3>
          <AnnouncementForm
            me={me}
            submitLabel="Post announcement"
            onCancel={() => setAdding(false)}
            onSubmit={async (body) => navigate(`/admin/announcements/${(await announcementsApi.create(body)).id}`)}
          />
        </>
      ) : (
        <div>
          <button className="button" onClick={() => setAdding(true)}>
            Post an announcement
          </button>
        </div>
      )}

      <section className="stack">
        <h3>Posted</h3>
        {list === null ? (
          <div className="panel">
            <div className="skeleton skeleton-line" />
          </div>
        ) : list.length === 0 ? (
          <p className="muted">Nothing posted yet.</p>
        ) : (
          <ul className="song-list">
            {list.map((a) => (
              <li key={a.id}>
                <a {...internalLink(`/admin/announcements/${a.id}`, navigate)}>
                  <span className="song-title">{a.title}</span>
                  <span className="muted small">{formatDay(a.createdAt)}</span>
                  <Audience ids={a.groups} />
                </a>
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  )
}

/** Admin: one announcement as members see it, with edit and delete. */
export function AdminAnnouncementDetail({ id, me, navigate }: { id: string; me: Member; navigate: Navigate }) {
  const [a, setA] = useState<Announcement | null>(null)
  const [missing, setMissing] = useState(false)
  const [editing, setEditing] = useState(false)

  useEffect(() => {
    announcementsApi
      .get(id)
      .then(setA)
      .catch(() => setMissing(true))
  }, [id])

  const back = (
    <div className="row">
      <a className="back" {...internalLink('/admin/announcements', navigate)}>
        All announcements
      </a>
      {a && (
        <a className="manage-link small" {...internalLink(`/announcements/${id}`, navigate)}>
          View as member
        </a>
      )}
    </div>
  )

  if (missing)
    return (
      <>
        {back}
        <p className="muted">That announcement doesn't exist any more.</p>
      </>
    )
  if (!a)
    return (
      <>
        {back}
        <div className="skeleton skeleton-title" />
      </>
    )

  return (
    <>
      {back}
      {editing ? (
        <AnnouncementForm
          me={me}
          initial={a}
          submitLabel="Save changes"
          onCancel={() => setEditing(false)}
          onSubmit={async (body) => {
            setA(await announcementsApi.update(a.id, body))
            setEditing(false)
          }}
        />
      ) : (
        <>
          <article className="post">
            <h2 className="detail-title">{a.title}</h2>
            <div>
              <p className="muted small">{byline(a)}</p>
              <Audience ids={a.groups} />
            </div>
            <AnnouncementBody text={a.body} />
          </article>
          <div>
            <button className="button secondary" onClick={() => setEditing(true)}>
              Edit announcement
            </button>
          </div>
        </>
      )}
      <DeleteAnnouncement a={a} onDeleted={() => navigate('/admin/announcements')} />
    </>
  )
}

function AnnouncementForm({
  me,
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  me: Member
  initial?: Announcement
  submitLabel: string
  onSubmit: (body: AnnouncementInput) => Promise<void>
  onCancel: () => void
}) {
  const [title, setTitle] = useState(initial?.title ?? '')
  const [body, setBody] = useState(initial?.body ?? '')
  const [forGroups, setForGroups] = useState<string[]>(initial?.groups ?? [])
  const groups = useGroups()
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  // Ticked groups that still exist: a deleted one can't be saved, and has no checkbox.
  const known = groups ? forGroups.filter((g) => groups.some((x) => x.id === g)) : forGroups
  const lostAudience = !!initial && initial.groups.length > 0 && !!groups && audience(initial.groups, groups).hidden

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setBusy(true)
    try {
      await onSubmit({ title, body, groups: known })
    } catch (err) {
      setError(
        err instanceof ApiError && err.reason === 'unknown_group'
          ? 'One of those groups no longer exists. Reload and try again.'
          : "Couldn't save the announcement. Check the details and try again.",
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <div className="fields">
        <label className="wide">
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={120} />
        </label>
        <label className="wide">
          Announcement
          <textarea value={body} onChange={(e) => setBody(e.target.value)} required maxLength={5000} rows={8} />
          <span className="hint">
            Plain text. Leave a blank line between paragraphs. Links starting with https:// become clickable.
          </span>
        </label>
        {lostAudience && (
          <p className="group-warning small">
            This was only for a group that has since been deleted, so only admins can see it. Tick who should see it,
            or leave all unticked for everyone.
          </p>
        )}
        <GroupCheckboxes
          groups={groups}
          value={known}
          onChange={setForGroups}
          me={me}
          legend="Who is it for?"
          hint="Leave all unticked for everyone. Only people in the ticked groups will see it."
          adminGroupsLocked={false}
        />
      </div>
      <div className="actions">
        <button className="button" type="submit" disabled={busy}>
          {busy ? 'Saving' : submitLabel}
        </button>
        <button className="button secondary" type="button" onClick={onCancel}>
          Cancel
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  )
}

function DeleteAnnouncement({ a, onDeleted }: { a: Announcement; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState(false)
  return (
    <div className="danger-zone">
      {confirming ? (
        <>
          <p>Delete this announcement for everyone? This can't be undone.</p>
          <div className="actions">
            <button
              className="button danger"
              onClick={() =>
                announcementsApi
                  .remove(a.id)
                  .then(onDeleted)
                  .catch(() => setError(true))
              }
            >
              Delete announcement
            </button>
            <button className="button secondary" onClick={() => setConfirming(false)}>
              Keep
            </button>
          </div>
        </>
      ) : (
        <button className="button secondary" onClick={() => setConfirming(true)}>
          Delete announcement
        </button>
      )}
      {error && <p className="error">Couldn't delete the announcement. Try again.</p>}
    </div>
  )
}
