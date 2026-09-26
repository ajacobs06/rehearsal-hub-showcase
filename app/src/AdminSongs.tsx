import { useCallback, useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
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

const AUDIO_FILES: FileKind[] = ['tenor', 'lead', 'bari', 'bass', 'full']
const ALL_FILES: FileKind[] = ['score', ...AUDIO_FILES]
const GROUPS: SongStatus[] = ['learning', 'performing', 'retired']

/** Admin: every song (retired too), how complete its files are, and "Add a song". */
export function AdminSongList({ navigate }: { navigate: Navigate }) {
  const [songs, setSongs] = useState<Song[] | null>(null)
  const [error, setError] = useState(false)

  const load = useCallback(() => {
    songsApi
      .list('all')
      .then(setSongs)
      .catch(() => setError(true))
  }, [])
  useEffect(load, [load])

  const [shown, filters] = useSongFilter(songs)

  if (error) return <p className="error">Couldn't load songs. Refresh the page to try again.</p>

  return (
    <>
      <div className="actions">
        <AddSong onCreated={(s) => navigate(`/admin/songs/${s.id}`)} />
      </div>
      <BulkScoreUpload songs={songs ?? []} onDone={load} />
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
                  const tracks = AUDIO_FILES.filter((k) => s.files[k]).length
                  return (
                    <li key={s.id}>
                      <a {...internalLink(`/admin/songs/${s.id}`, navigate)}>
                        <span className="song-title">{s.title}</span>
                        {songTagLine(s) && <span className="muted small">{songTagLine(s)}</span>}
                        <span className={`small ${s.files.score ? 'ready' : 'muted'}`}>
                          {s.files.score ? 'Score uploaded' : 'No score'}, {tracks} of {AUDIO_FILES.length} tracks
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

// ---------- Bulk score upload ----------

const MAX_PDF_BYTES = 25 * 1024 * 1024

type Row = {
  key: string
  file: File
  title: string
  include: boolean
  status: 'waiting' | 'uploading' | 'done' | 'error'
  progress: number
  message?: string
}

/** "Lida_Rose - SATB.pdf" -> "Lida Rose - SATB" */
function titleFromFile(name: string): string {
  return name.replace(/\.pdf$/i, '').replace(/_+/g, ' ').replace(/\s+/g, ' ').trim().slice(0, 120)
}

const keyOf = (title: string) => title.trim().toLowerCase()

function problemWith(row: Row): string | null {
  if (!/\.pdf$/i.test(row.file.name) && row.file.type !== 'application/pdf') return 'Not a PDF'
  if (row.file.size > MAX_PDF_BYTES) return 'Over 25 MB'
  if (!row.title.trim()) return 'Needs a title'
  return null
}

/**
 * Upload many score PDFs at once (e.g. a folder downloaded from Google Drive). Each file becomes a
 * new song titled from its filename, or replaces the score of an existing song with that title.
 * Files go one at a time through the same checks as a single upload.
 */
function BulkScoreUpload({ songs, onDone }: { songs: Song[]; onDone: () => void }) {
  const [open, setOpen] = useState(false)
  const [rows, setRows] = useState<Row[]>([])
  const [running, setRunning] = useState(false)
  const existing = new Map(songs.map((s) => [keyOf(s.title), s]))

  const update = (key: string, patch: Partial<Row>) => setRows((rs) => rs.map((r) => (r.key === key ? { ...r, ...patch } : r)))

  function pick(e: ChangeEvent<HTMLInputElement>) {
    const files = [...(e.target.files ?? [])]
    e.target.value = ''
    const seen = new Set<string>()
    setRows(
      files.map((file, i) => {
        const title = titleFromFile(file.name)
        const row: Row = { key: `${i}-${file.name}`, file, title, include: true, status: 'waiting', progress: 0 }
        // Untick problems and repeated titles, so one file doesn't overwrite another.
        row.include = !problemWith(row) && !seen.has(keyOf(title))
        seen.add(keyOf(title))
        return row
      }),
    )
  }

  const included = rows.filter((r) => r.include && !problemWith(r))
  // Titles shared by more than one usable file (shown on each), and whether two ticked ones clash.
  const usable = rows.filter((r) => !problemWith(r)).map((r) => keyOf(r.title))
  const shared = new Set(usable.filter((k, i) => usable.indexOf(k) !== i))
  const ticked = included.map((r) => keyOf(r.title))
  const clash = ticked.some((k, i) => ticked.indexOf(k) !== i)

  async function run() {
    setRunning(true)
    const created = new Map<string, string>() // title -> id, for songs made during this run
    for (const row of included) {
      update(row.key, { status: 'uploading', progress: 0, message: undefined })
      const k = keyOf(row.title)
      let newId: string | null = null
      try {
        let id = existing.get(k)?.id ?? created.get(k)
        if (!id) {
          id = newId = (await songsApi.create({ title: row.title.trim() })).id
          created.set(k, id)
        }
        await songsApi.uploadFile(id, 'score', row.file, (f) => update(row.key, { progress: f }))
        update(row.key, { status: 'done', progress: 1 })
      } catch (err) {
        // Don't leave behind a new song with no score.
        if (newId) {
          created.delete(k)
          await songsApi.remove(newId).catch(() => undefined)
        }
        const reason = err instanceof ApiError ? err.reason : undefined
        update(row.key, { status: 'error', message: UPLOAD_ERROR[reason ?? ''] ?? "Couldn't upload this file." })
      }
    }
    setRunning(false)
    onDone()
  }

  if (!open)
    return (
      <div>
        <button className="button secondary" onClick={() => setOpen(true)}>
          Upload scores
        </button>
      </div>
    )

  const done = rows.filter((r) => r.status === 'done').length
  const failed = rows.filter((r) => r.status === 'error').length
  const finished = !running && done + failed > 0

  return (
    <section className="panel bulk-upload">
      <h3>Upload scores</h3>
      <p className="muted small">
        Pick several PDFs, for example a folder downloaded from Google Drive. Each becomes a song named after its file, or
        replaces the score of a song with the same title.
      </p>
      <div>
        <input id="bulk-pdfs" className="visually-hidden" type="file" multiple accept="application/pdf,.pdf" onChange={pick} disabled={running} />
        <label htmlFor="bulk-pdfs" className="button secondary" aria-disabled={running}>
          {rows.length ? 'Choose different PDFs' : 'Choose PDFs'}
        </label>
      </div>

      {rows.length > 0 && (
        <ul className="bulk-rows">
          {rows.map((r) => {
            const problem = problemWith(r)
            const match = existing.get(keyOf(r.title))
            const note =
              r.status === 'done'
                ? 'Uploaded'
                : r.status === 'error'
                  ? r.message
                  : problem ??
                    (shared.has(keyOf(r.title))
                      ? 'Same title as another file'
                      : match
                        ? `Replaces the score of "${match.title}"`
                        : 'New song')
            return (
              <li key={r.key} className={`bulk-row status-${r.status}`}>
                <label className="check">
                  <input
                    type="checkbox"
                    checked={r.include && !problem}
                    disabled={Boolean(problem) || running || r.status === 'done'}
                    onChange={(e) => update(r.key, { include: e.target.checked })}
                  />
                  <span className="visually-hidden">Include {r.file.name}</span>
                </label>
                <div className="bulk-main">
                  <label>
                    <span className="visually-hidden">Song title for {r.file.name}</span>
                    <input
                      value={r.title}
                      maxLength={120}
                      disabled={running || r.status === 'done'}
                      onChange={(e) => update(r.key, { title: e.target.value })}
                    />
                  </label>
                  <p className={`small ${r.status === 'error' || problem ? 'error' : r.status === 'done' ? 'ready' : 'muted'}`}>
                    {note} <span className="muted">({r.file.name})</span>
                  </p>
                  {r.status === 'uploading' && (
                    <progress value={r.progress} max={1} aria-label={`Uploading ${r.file.name}`} />
                  )}
                </div>
              </li>
            )
          })}
        </ul>
      )}

      <div className="actions">
        {rows.length > 0 && !finished && (
          <button className="button" onClick={run} disabled={running || included.length === 0 || clash}>
            {running ? 'Uploading' : `Upload ${included.length} ${included.length === 1 ? 'score' : 'scores'}`}
          </button>
        )}
        <button
          className="button secondary"
          disabled={running}
          onClick={() => {
            setRows([])
            setOpen(false)
          }}
        >
          {finished ? 'Done' : 'Cancel'}
        </button>
      </div>
      {clash && !running && (
        <p className="error small">Two ticked files have the same title. Rename or untick one.</p>
      )}
      {finished && (
        <p className={failed ? 'error' : 'success'} role="status">
          {done} uploaded{failed ? `, ${failed} failed. Fix those and try again.` : '.'}
        </p>
      )}
    </section>
  )
}
