import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import {
  ApiError,
  FILE_LABEL,
  DIFFICULTIES,
  KINDS,
  STATUS_LABEL,
  UPLOAD_ERROR,
  normaliseTag,
  songTagLine,
  songsApi,
  type Difficulty,
  type FileKind,
  type SongKind,
  type Song,
  type SongStatus,
} from './api'
import { internalLink } from './Rehearsals'
import { useSongFilter } from './SongFilter'

type Navigate = (to: string) => void

const ALL_FILES: FileKind[] = ['tenor', 'lead', 'bari', 'bass', 'full', 'score']
const GROUPS: SongStatus[] = ['learning', 'performing', 'retired']

/** Admin: every song (retired too), how complete its files are, and "Add a song". */
export function AdminSongList({ navigate }: { navigate: Navigate }) {
  const [songs, setSongs] = useState<Song[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    songsApi
      .list('all')
      .then(setSongs)
      .catch(() => setError(true))
  }, [])

  const [shown, filters] = useSongFilter(songs)

  if (error) return <p className="error">Couldn't load songs. Refresh the page to try again.</p>

  return (
    <>
      <AddSong onCreated={(s) => navigate(`/admin/songs/${s.id}`)} />
      {filters}
      {songs === null ? (
        <div className="panel">
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line short" />
        </div>
      ) : songs.length === 0 ? (
        <p className="muted">No songs yet. Add the first one above.</p>
      ) : shown && shown.length === 0 ? (
        <p className="muted">No songs match. Try another search or clear the filters.</p>
      ) : (
        GROUPS.map((status) => {
          const items = (shown ?? songs).filter((s) => s.status === status)
          if (items.length === 0) return null
          return (
            <div key={status} className="group">
              <h3>
                {STATUS_LABEL[status]} <span className="count">{items.length}</span>
              </h3>
              <ul className="song-list">
                {items.map((s) => {
                  const have = ALL_FILES.filter((k) => s.files[k]).length
                  return (
                    <li key={s.id}>
                      <a {...internalLink(`/admin/songs/${s.id}`, navigate)}>
                        <span className="song-title">{s.title}</span>
                        {songTagLine(s) && <span className="muted small">{songTagLine(s)}</span>}
                        <span className={`small ${have === ALL_FILES.length ? 'ready' : 'muted'}`}>
                          {have} of {ALL_FILES.length} files
                          {have < ALL_FILES.length &&
                            `. Missing: ${ALL_FILES.filter((k) => !s.files[k])
                              .map((k) => FILE_LABEL[k])
                              .join(', ')}`}
                        </span>
                      </a>
                    </li>
                  )
                })}
              </ul>
            </div>
          )
        })
      )}
    </>
  )
}

/** Admin: one song's details, files and deletion. */
export function AdminSongDetail({ id, navigate }: { id: string; navigate: Navigate }) {
  const [song, setSong] = useState<Song | null>(null)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    songsApi
      .get(id)
      .then(setSong)
      .catch(() => setMissing(true))
  }, [id])

  const back = (
    <div className="row">
      <a className="back" {...internalLink('/admin/songs', navigate)}>
        All songs
      </a>
      {song && song.status !== 'retired' && (
        <a className="manage-link small" {...internalLink(`/songs/${id}`, navigate)}>
          View as member
        </a>
      )}
    </div>
  )

  if (missing)
    return (
      <>
        {back}
        <p className="muted">That song doesn't exist any more.</p>
      </>
    )
  if (!song)
    return (
      <>
        {back}
        <div className="skeleton skeleton-title" />
      </>
    )

  return (
    <>
      {back}
      <h2 className="detail-title">{song.title}</h2>
      <DetailsForm song={song} onChange={setSong} />
      <div className="panel">
        <h3>Files</h3>
        <ul className="file-slots">
          {ALL_FILES.map((k) => (
            <FileSlot key={k} song={song} kind={k} onChange={setSong} />
          ))}
        </ul>
      </div>
      <DeleteSong song={song} onDeleted={() => navigate('/admin/songs')} />
    </>
  )
}

export function AddSong({ onCreated }: { onCreated: (s: Song) => void }) {
  const [open, setOpen] = useState(false)
  const [title, setTitle] = useState('')
  const [arranger, setArranger] = useState('')
  const [key, setKey] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      onCreated(await songsApi.create({ title, arranger: arranger || null, key: key || null }))
    } catch {
      setError("Couldn't add the song. Check the title and try again.")
      setBusy(false)
    }
  }

  if (!open)
    return (
      <div>
        <button className="button" onClick={() => setOpen(true)}>
          Add a song
        </button>
      </div>
    )

  return (
    <form className="panel" onSubmit={submit}>
      <h2>Add a song</h2>
      <div className="fields">
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={120} autoFocus />
        </label>
        <label>
          Arranger
          <input value={arranger} onChange={(e) => setArranger(e.target.value)} maxLength={120} />
        </label>
        <label>
          Key
          <input value={key} onChange={(e) => setKey(e.target.value)} maxLength={20} placeholder="e.g. Bb" />
        </label>
      </div>
      <div className="actions">
        <button className="button" type="submit" disabled={busy}>
          {busy ? 'Adding' : 'Add song'}
        </button>
        <button className="button secondary" type="button" onClick={() => setOpen(false)}>
          Cancel
        </button>
      </div>
      {error && <p className="error">{error}</p>}
    </form>
  )
}

export function DetailsForm({ song, onChange }: { song: Song; onChange: (s: Song) => void }) {
  const [title, setTitle] = useState(song.title)
  const [arranger, setArranger] = useState(song.arranger ?? '')
  const [key, setKey] = useState(song.key ?? '')
  const [status, setStatus] = useState<SongStatus>(song.status)
  const [kind, setKind] = useState<SongKind>(song.kind)
  const [difficulty, setDifficulty] = useState<Difficulty | ''>(song.difficulty ?? '')
  const [tags, setTags] = useState<string[]>(song.tags)
  const knownTags = useKnownTags()
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      onChange(
        await songsApi.update(song.id, {
          title,
          arranger: arranger || null,
          key: key || null,
          status,
          kind,
          difficulty: difficulty || null,
          tags,
        }),
      )
      setMessage({ kind: 'ok', text: 'Saved.' })
    } catch {
      setMessage({ kind: 'error', text: "Couldn't save. Check the title and labels and try again." })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="panel" onSubmit={submit}>
      <h3>Details</h3>
      <div className="fields">
        <label>
          Title
          <input value={title} onChange={(e) => setTitle(e.target.value)} required maxLength={120} />
        </label>
        <label>
          Arranger
          <input value={arranger} onChange={(e) => setArranger(e.target.value)} maxLength={120} />
        </label>
        <label>
          Key
          <input value={key} onChange={(e) => setKey(e.target.value)} maxLength={20} />
        </label>
        <label>
          Status
          <select value={status} onChange={(e) => setStatus(e.target.value as SongStatus)}>
            <option value="learning">Learning</option>
            <option value="performing">Performing</option>
            <option value="retired">Retired (hidden from members)</option>
          </select>
        </label>
        <label>
          Type
          <select value={kind} onChange={(e) => setKind(e.target.value as SongKind)}>
            {KINDS.map((k) => (
              <option key={k.value} value={k.value}>
                {k.label}
              </option>
            ))}
          </select>
        </label>
        <label>
          Difficulty
          <select value={difficulty} onChange={(e) => setDifficulty(e.target.value as Difficulty | '')}>
            <option value="">Not set</option>
            {DIFFICULTIES.map((d) => (
              <option key={d.value} value={d.value}>
                {d.label}
              </option>
            ))}
          </select>
        </label>
        <TagEditor tags={tags} onChange={setTags} suggestions={knownTags} />
      </div>
      <button className="button" type="submit" disabled={busy}>
        {busy ? 'Saving' : 'Save details'}
      </button>
      {message && (
        <p className={message.kind === 'error' ? 'error' : 'success'} role="status">
          {message.text}
        </p>
      )}
    </form>
  )
}

export function FileSlot({ song, kind, onChange }: { song: Song; kind: FileKind; onChange: (s: Song) => void }) {
  const [progress, setProgress] = useState<number | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [confirming, setConfirming] = useState(false)
  const file = song.files[kind]
  const inputId = `file-${kind}`

  async function onPick(e: ChangeEvent<HTMLInputElement>) {
    const picked = e.target.files?.[0]
    e.target.value = ''
    if (!picked) return
    setError(null)
    setProgress(0)
    try {
      onChange(await songsApi.uploadFile(song.id, kind, picked, setProgress))
    } catch (err) {
      const reason = err instanceof ApiError ? err.reason : undefined
      setError(UPLOAD_ERROR[reason ?? ''] ?? "Couldn't upload that file. Try again.")
      // A rejected upload also clears the old file on the server, so reload the song.
      songsApi.get(song.id).then(onChange).catch(() => undefined)
    } finally {
      setProgress(null)
    }
  }

  async function remove() {
    setError(null)
    try {
      onChange(await songsApi.removeFile(song.id, kind))
    } catch {
      setError("Couldn't remove that file.")
    }
    setConfirming(false)
  }

  return (
    <li className="file-slot">
      <div className="row">
        <div>
          <p className="track-name">{FILE_LABEL[kind]}</p>
          <p className="muted small">
            {file
              ? `${(file.size / 1024 / 1024).toFixed(1)} MB, uploaded ${new Date(file.uploadedAt).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' })}`
              : 'Not uploaded'}
          </p>
        </div>
        <div className="slot-actions">
          <input
            id={inputId}
            className="visually-hidden"
            type="file"
            accept={kind === 'score' ? 'application/pdf,.pdf' : 'audio/mpeg,.mp3'}
            onChange={onPick}
            disabled={progress !== null}
          />
          <label htmlFor={inputId} className="button secondary small" aria-disabled={progress !== null}>
            {file ? 'Replace' : 'Upload'}
          </label>
          {file &&
            (confirming ? (
              <>
                <button className="button danger small" onClick={remove}>
                  Remove
                </button>
                <button className="button secondary small" onClick={() => setConfirming(false)}>
                  Keep
                </button>
              </>
            ) : (
              <button className="button secondary small" onClick={() => setConfirming(true)}>
                Remove
              </button>
            ))}
        </div>
      </div>
      {progress !== null && (
        <progress value={progress} max={1} aria-label={`Uploading ${FILE_LABEL[kind]}`}>
          {Math.round(progress * 100)}%
        </progress>
      )}
      {error && <p className="error small">{error}</p>}
    </li>
  )
}

export function DeleteSong({ song, onDeleted }: { song: Song; onDeleted: () => void }) {
  const [confirming, setConfirming] = useState(false)
  const [error, setError] = useState(false)

  async function remove() {
    try {
      await songsApi.remove(song.id)
      onDeleted()
    } catch {
      setError(true)
    }
  }

  return (
    <div className="danger-zone">
      {confirming ? (
        <>
          <p>Delete "{song.title}" and all its tracks? Members lose access straight away.</p>
          <div className="actions">
            <button className="button danger" onClick={remove}>
              Delete song
            </button>
            <button className="button secondary" onClick={() => setConfirming(false)}>
              Keep
            </button>
          </div>
        </>
      ) : (
        <button className="button secondary" onClick={() => setConfirming(true)}>
          Delete song
        </button>
      )}
      {error && <p className="error">Couldn't delete the song. Try again.</p>}
    </div>
  )
}

/** Every tag already used on a song, for suggestions (so tags stay consistent). */
function useKnownTags(): string[] {
  const [tags, setTags] = useState<string[]>([])
  useEffect(() => {
    songsApi
      .list('all')
      .then((all) => setTags([...new Set(all.flatMap((s) => s.tags))].sort()))
      .catch(() => setTags([]))
  }, [])
  return tags
}

const MAX_TAGS = 10
const TAG_OK = /^[a-z0-9][a-z0-9 &'-]{0,29}$/

/** Genre and mood labels (stored as `tags`; unrelated to barbershop tags, which are the song Type). */
function TagEditor({ tags, onChange, suggestions }: { tags: string[]; onChange: (t: string[]) => void; suggestions: string[] }) {
  const [draft, setDraft] = useState('')
  const [error, setError] = useState<string | null>(null)

  function add() {
    const tag = normaliseTag(draft)
    if (!tag) return
    if (!TAG_OK.test(tag)) return setError("Use letters, numbers, spaces and & ' - (up to 30 characters).")
    if (tags.includes(tag)) return setDraft('')
    if (tags.length >= MAX_TAGS) return setError(`A song can have up to ${MAX_TAGS} genre and mood labels.`)
    onChange([...tags, tag])
    setDraft('')
    setError(null)
  }

  return (
    <div className="wide tag-editor">
      <label htmlFor="tag-input">Genre and mood</label>
      <span className="tag-input">
        <input
          id="tag-input"
          value={draft}
          list="known-tags"
          aria-describedby="tag-hint"
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === 'Enter' || e.key === ',') {
              e.preventDefault()
              add()
            }
          }}
          maxLength={30}
          autoComplete="off"
        />
        <button type="button" className="button secondary" onClick={add}>
          Add
        </button>
      </span>
      <span className="hint" id="tag-hint">
        e.g. christmas, upbeat, ballad. Press Enter or Add.
      </span>
      <datalist id="known-tags">
        {suggestions
          .filter((t) => !tags.includes(t))
          .map((t) => (
            <option key={t} value={t} />
          ))}
      </datalist>
      {tags.length > 0 && (
        <ul className="chips tag-list" aria-label="Genre and mood on this song">
          {tags.map((t) => (
            <li key={t}>
              <button
                type="button"
                className="chip"
                aria-label={`Remove ${t}`}
                onClick={() => onChange(tags.filter((x) => x !== t))}
              >
                {t} <span aria-hidden="true">×</span>
              </button>
            </li>
          ))}
        </ul>
      )}
      {error && <p className="error small">{error}</p>}
    </div>
  )
}
