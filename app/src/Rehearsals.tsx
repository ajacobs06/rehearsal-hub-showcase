import { useEffect, useState, type FormEvent } from 'react'
import {
  ApiError,
  FILE_LABEL,
  RSVP_OPTIONS,
  STATE_LABEL,
  formatWhen,
  rehearsalsApi,
  songsApi,
  type Rehearsal,
  type RehearsalInput,
  type Member,
  type RsvpResponse,
  type Song,
} from './api'
import { GroupCheckboxes, groupNames, useGroups } from './groups'

type Navigate = (to: string) => void

export function internalLink(to: string, navigate: Navigate) {
  return {
    href: to,
    onClick: (e: React.MouseEvent) => {
      e.preventDefault()
      navigate(to)
    },
  }
}

export function countsLine(r: Rehearsal): string {
  const parts = [`${r.counts.yes} going`]
  if (r.counts.maybe) parts.push(`${r.counts.maybe} maybe`)
  if (r.counts.no) parts.push(`${r.counts.no} can't go`)
  return parts.join(', ')
}

export function RsvpButtons({ r, onChange }: { r: Rehearsal; onChange: (r: Rehearsal) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)

  if (!r.rsvpOpen) return <p className="muted small">RSVPs have closed.</p>

  async function choose(response: RsvpResponse) {
    setBusy(true)
    setError(false)
    try {
      // Tapping your current answer again withdraws it.
      onChange(await rehearsalsApi.rsvp(r.id, response === r.myRsvp ? null : response))
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <div>
      <div className="segmented rsvp" role="group" aria-label="Are you coming?">
        {RSVP_OPTIONS.map((o) => (
          <button
            key={o.value}
            className={o.value === r.myRsvp ? 'selected' : undefined}
            aria-pressed={o.value === r.myRsvp}
            disabled={busy}
            onClick={() => choose(o.value)}
          >
            {o.label}
          </button>
        ))}
      </div>
      {error && <p className="error small">Couldn't save your reply. Try again.</p>}
    </div>
  )
}

export function SongsToPrepare({ r, navigate }: { r: Rehearsal; navigate: Navigate }) {
  if (r.songs.length === 0) return <p className="muted small">No songs planned yet.</p>
  return (
    <ul className="prep-list">
      {r.songs.map((s) => (
        <li key={s.id}>
          <a {...internalLink(`/songs/${s.id}`, navigate)}>
            <span className="song-head">
              <span className="song-title">{s.title}</span>
              {s.myState !== 'not_started' && (
                <span className={`badge state-${s.myState}`}>{STATE_LABEL[s.myState]}</span>
              )}
            </span>
            {s.myPart && (
              <span className={`small ${s.hasMyTrack ? 'ready' : 'muted'}`}>
                {s.hasMyTrack ? `${FILE_LABEL[s.myPart]} track ready` : `No ${FILE_LABEL[s.myPart]} track yet`}
              </span>
            )}
          </a>
        </li>
      ))}
    </ul>
  )
}

export function RehearsalCard({
  r,
  navigate,
  onChange,
  showSongs = false,
}: {
  r: Rehearsal
  navigate: Navigate
  onChange: (r: Rehearsal) => void
  showSongs?: boolean
}) {
  return (
    <article className="panel rehearsal-card">
      <div className="row">
        <div>
          <h3 className="when">{formatWhen(r.start, r.end)}</h3>
          <p className="muted">{r.venue}</p>
          <ForGroups ids={r.groups} />
        </div>
        <a className="button secondary small" {...internalLink(`/rehearsals/${r.id}`, navigate)}>
          Details
        </a>
      </div>
      {showSongs ? (
        <>
          <h4>Songs to prepare</h4>
          <SongsToPrepare r={r} navigate={navigate} />
        </>
      ) : (
        r.songs.length > 0 && <p className="small">{r.songs.map((s) => s.title).join(', ')}</p>
      )}
      <p className="muted small">{countsLine(r)}</p>
      <RsvpButtons r={r} onChange={onChange} />
    </article>
  )
}

/** "For: Open chorus" when a rehearsal is limited to groups. */
export function ForGroups({ ids }: { ids: string[] }) {
  const groups = useGroups()
  const names = groupNames(ids, groups)
  return names ? <p className="small for-groups">For: {names}</p> : null
}

// ---------- Admin form (create and edit) ----------

const pad = (n: number) => String(n).padStart(2, '0')

/** ISO timestamp -> value for <input type="datetime-local"> in the browser's time zone. */
function toLocalInput(iso: string): string {
  const d = new Date(iso)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`
}

function toTimeInput(iso: string): string {
  const d = new Date(iso)
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`
}

export function RehearsalForm({
  me,
  initial,
  submitLabel,
  onSubmit,
  onCancel,
}: {
  me: Member
  initial?: Rehearsal
  submitLabel: string
  onSubmit: (body: RehearsalInput) => Promise<void>
  onCancel?: () => void
}) {
  const [start, setStart] = useState(initial ? toLocalInput(initial.start) : '')
  const [endTime, setEndTime] = useState(initial?.end ? toTimeInput(initial.end) : '')
  const [venue, setVenue] = useState(initial?.venue ?? '')
  const [notes, setNotes] = useState(initial?.notes ?? '')
  const [songIds, setSongIds] = useState<string[]>(initial?.songs.map((s) => s.id) ?? [])
  const [forGroups, setForGroups] = useState<string[]>(initial?.groups ?? [])
  const groups = useGroups()
  const [songs, setSongs] = useState<Song[] | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    songsApi
      .list('all')
      .then((all) => setSongs(all.filter((s) => s.status !== 'retired' || songIds.includes(s.id))))
      .catch(() => setSongs([]))
    // Only on mount: the song list doesn't need to follow ticks.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  async function submit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const startDate = new Date(start)
    let end: string | null = null
    if (endTime) {
      const endDate = new Date(`${start.slice(0, 10)}T${endTime}`)
      if (endDate <= startDate) return setError('The finish time must be after the start time.')
      end = endDate.toISOString()
    }
    setBusy(true)
    try {
      await onSubmit({ start: startDate.toISOString(), end, venue, notes: notes.trim() || null, songIds, groups: forGroups })
    } catch (err) {
      setError(
        err instanceof ApiError && err.reason === 'unknown_song'
          ? 'One of those songs no longer exists. Reload and try again.'
          : err instanceof ApiError && err.reason === 'unknown_group'
            ? 'One of those groups no longer exists. Reload and try again.'
          : "Couldn't save the rehearsal. Check the details and try again.",
      )
    } finally {
      setBusy(false)
    }
  }

  const toggle = (id: string) => setSongIds((ids) => (ids.includes(id) ? ids.filter((x) => x !== id) : [...ids, id]))

  return (
    <form className="panel" onSubmit={submit}>
      <div className="fields">
        <label>
          Date and start time
          <input type="datetime-local" value={start} onChange={(e) => setStart(e.target.value)} required />
        </label>
        <label>
          Finish time
          <input type="time" value={endTime} onChange={(e) => setEndTime(e.target.value)} />
          <span className="hint">Optional. Same day as the start.</span>
        </label>
        <label className="wide">
          Venue
          <input value={venue} onChange={(e) => setVenue(e.target.value)} required maxLength={120} />
        </label>
        <fieldset className="wide song-picks">
          <legend>Songs to cover</legend>
          {songs === null ? (
            <div className="skeleton skeleton-line" />
          ) : songs.length === 0 ? (
            <p className="muted small">No songs yet. Add songs from Home first.</p>
          ) : (
            songs.map((s) => (
              <label key={s.id} className="check">
                <input type="checkbox" checked={songIds.includes(s.id)} onChange={() => toggle(s.id)} />
                {s.title}
              </label>
            ))
          )}
        </fieldset>
        <GroupCheckboxes
          groups={groups}
          value={forGroups}
          onChange={setForGroups}
          me={me}
          legend="Who is it for?"
          hint="Leave all unticked for everyone. Only people in the ticked groups will see it."
          adminGroupsLocked={false}
        />
        <label className="wide">
          Notes
          <textarea value={notes} onChange={(e) => setNotes(e.target.value)} maxLength={2000} rows={3} />
          <span className="hint">Optional, e.g. "Bring the new scores" or "Sectionals first hour".</span>
        </label>
      </div>
      <div className="actions">
        <button className="button" type="submit" disabled={busy}>
          {busy ? 'Saving' : submitLabel}
        </button>
        {onCancel && (
          <button className="button secondary" type="button" onClick={onCancel}>
            Cancel
          </button>
        )}
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  )
}
