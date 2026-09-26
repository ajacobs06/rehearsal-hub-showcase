import { useEffect, useState, type ChangeEvent, type FormEvent } from 'react'
import {
  ApiError,
  FILE_LABEL,
  PARTS,
  STATES,
  STATUS_LABEL,
  UPLOAD_ERROR,
  songsApi,
  type FileKind,
  type LearnState,
  type Member,
  type Part,
  type Song,
  type SongStatus,
} from './api'
import Player from './Player'

const AUDIO: FileKind[] = ['tenor', 'lead', 'bari', 'bass', 'full']
const ALL_FILES: FileKind[] = [...AUDIO, 'score']

export default function SongPage({ id, me, navigate }: { id: string; me: Member; navigate: (to: string) => void }) {
  const [song, setSong] = useState<Song | null>(null)
  const [missing, setMissing] = useState(false)
  const isAdmin = me.role !== 'member'

  useEffect(() => {
    songsApi
      .get(id)
      .then(setSong)
      .catch(() => setMissing(true))
  }, [id])

  const back = (
    <a
      className="back"
      href="/"
      onClick={(e) => {
        e.preventDefault()
        navigate('/')
      }}
    >
      All songs
    </a>
  )

  if (missing)
    return (
      <>
        {back}
        <h1>Song not found</h1>
        <p className="muted">It may have been removed or retired.</p>
      </>
    )

  if (!song)
    return (
      <>
        {back}
        <div className="skeleton skeleton-title" />
        <div className="skeleton skeleton-line" />
      </>
    )

  const mine = song.myPart && song.files[song.myPart] ? song.myPart : null
  const others = AUDIO.filter((k) => k !== mine && song.files[k])
  const meta = [song.arranger, song.key && `Key of ${song.key}`].filter(Boolean).join(' · ')

  return (
    <>
      {back}
      <div>
        <h1>{song.title}</h1>
        {meta && <p className="muted">{meta}</p>}
        <span className={`badge status-${song.status}`}>{STATUS_LABEL[song.status]}</span>
      </div>

      <PartPanel song={song} usual={me.part} onChange={setSong} />
      <ProgressPanel song={song} onChange={setSong} />

      {others.length > 0 && (
        <section>
          <h2>{song.myPart ? 'Other tracks' : 'Tracks'}</h2>
          <ul className="track-list">
            {others.map((k) => (
              <TrackRow key={k} songId={song.id} kind={k} />
            ))}
          </ul>
        </section>
      )}

      {song.files.score && (
        <section className="panel row">
          <div>
            <h2>Score</h2>
            <p className="muted small">PDF, opens in a new tab</p>
          </div>
          <OpenScoreButton songId={song.id} />
        </section>
      )}

      {!mine && others.length === 0 && !song.files.score && !isAdmin && (
        <p className="muted">No tracks or score yet. Check back after the committee uploads them.</p>
      )}

      {isAdmin && <AdminSong song={song} onChange={setSong} onDeleted={() => navigate('/')} />}
    </>
  )
}

/** The part this member is learning for this song, with the option to learn a different one. */
function PartPanel({ song, usual, onChange }: { song: Song; usual: Part | null; onChange: (s: Song) => void }) {
  const part = song.myPart
  const [picking, setPicking] = useState(part === null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)
  const track = part && song.files[part] ? part : null

  async function choose(p: Part | null) {
    setBusy(true)
    setError(false)
    try {
      onChange(await songsApi.setMyPart(song.id, p))
      setPicking(false)
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <div className="row part-head">
        <h2>
          {part
            ? `Your part${song.partOverride ? ' for this song' : ''}: ${FILE_LABEL[part]}`
            : 'Which part are you learning?'}
        </h2>
        {part && !picking && (
          <div className="actions">
            <button className="button secondary small" onClick={() => setPicking(true)} disabled={busy}>
              {song.partOverride ? 'Change' : 'Learn a different part'}
            </button>
            {song.partOverride && usual && (
              <button className="button secondary small" onClick={() => choose(null)} disabled={busy}>
                Back to {FILE_LABEL[usual]}
              </button>
            )}
          </div>
        )}
      </div>

      {picking ? (
        <>
          <div className="segmented" role="group" aria-label="Part for this song">
            {PARTS.map((p) => (
              <button
                key={p.value}
                className={p.value === part ? 'selected' : undefined}
                aria-pressed={p.value === part}
                disabled={busy}
                onClick={() => choose(p.value)}
              >
                {p.label}
              </button>
            ))}
          </div>
          {part && (
            <button className="button secondary small cancel" onClick={() => setPicking(false)}>
              Cancel
            </button>
          )}
        </>
      ) : track ? (
        <>
          <Player key={track} songId={song.id} kind={track} label={FILE_LABEL[track]} />
          <DownloadButton songId={song.id} kind={track} />
        </>
      ) : (
        part && <p className="muted">No {FILE_LABEL[part]} track yet.</p>
      )}
      {error && <p className="error small">Couldn't change your part. Try again.</p>}
    </section>
  )
}

function ProgressPanel({ song, onChange }: { song: Song; onChange: (s: Song) => void }) {
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState(false)

  async function choose(state: LearnState) {
    setBusy(true)
    setError(false)
    try {
      onChange(await songsApi.setMyState(song.id, state))
    } catch {
      setError(true)
    } finally {
      setBusy(false)
    }
  }

  return (
    <section className="panel">
      <h2>Your progress</h2>
      <div className="segmented states" role="group" aria-label="Your progress on this song">
        {STATES.map((s) => (
          <button
            key={s.value}
            className={s.value === song.myState ? 'selected' : undefined}
            aria-pressed={s.value === song.myState}
            disabled={busy}
            onClick={() => choose(s.value)}
          >
            {s.label}
          </button>
        ))}
      </div>
      <p className="muted small hint-below">Ready means you could perform it tomorrow.</p>
      {error && <p className="error small">Couldn't save your progress. Try again.</p>}
    </section>
  )
}

function TrackRow({ songId, kind }: { songId: string; kind: FileKind }) {
  const [open, setOpen] = useState(false)
  return (
    <li className="track">
      <div className="row">
        <span className="track-name">{FILE_LABEL[kind]}</span>
        <button className="button secondary small" aria-expanded={open} onClick={() => setOpen(!open)}>
          {open ? 'Hide' : 'Play'}
        </button>
      </div>
      {open && (
        <>
          <Player songId={songId} kind={kind} label={FILE_LABEL[kind]} />
          <DownloadButton songId={songId} kind={kind} />
        </>
      )}
    </li>
  )
}

function DownloadButton({ songId, kind }: { songId: string; kind: FileKind }) {
  const [busy, setBusy] = useState(false)
  async function download() {
    setBusy(true)
    try {
      // The link carries Content-Disposition: attachment, so this downloads and stays on the page.
      window.location.href = (await songsApi.fileLink(songId, kind, true)).url
    } finally {
      setBusy(false)
    }
  }
  return (
    <button className="button secondary small download" onClick={download} disabled={busy}>
      Download
    </button>
  )
}

function OpenScoreButton({ songId }: { songId: string }) {
  async function open() {
    // Open the tab during the tap so mobile browsers don't block it, then point it at the PDF.
    const tab = window.open('about:blank', '_blank')
    try {
      const { url } = await songsApi.fileLink(songId, 'score')
      if (tab) {
        tab.opener = null
        tab.location.href = url
      } else {
        window.location.href = url
      }
    } catch {
      tab?.close()
    }
  }
  return (
    <button className="button" onClick={open}>
      Open score
    </button>
  )
}

// ---------- Admin ----------

function AdminSong({
  song,
  onChange,
  onDeleted,
}: {
  song: Song
  onChange: (s: Song) => void
  onDeleted: () => void
}) {
  return (
    <section className="admin-section">
      <h2>Manage this song</h2>
      <DetailsForm song={song} onChange={onChange} />
      <div className="panel">
        <h3>Files</h3>
        <ul className="file-slots">
          {ALL_FILES.map((k) => (
            <FileSlot key={k} song={song} kind={k} onChange={onChange} />
          ))}
        </ul>
      </div>
      <DeleteSong song={song} onDeleted={onDeleted} />
    </section>
  )
}

function DetailsForm({ song, onChange }: { song: Song; onChange: (s: Song) => void }) {
  const [title, setTitle] = useState(song.title)
  const [arranger, setArranger] = useState(song.arranger ?? '')
  const [key, setKey] = useState(song.key ?? '')
  const [status, setStatus] = useState<SongStatus>(song.status)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      onChange(await songsApi.update(song.id, { title, arranger: arranger || null, key: key || null, status }))
      setMessage({ kind: 'ok', text: 'Saved.' })
    } catch {
      setMessage({ kind: 'error', text: "Couldn't save. Check the title and try again." })
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

function FileSlot({ song, kind, onChange }: { song: Song; kind: FileKind; onChange: (s: Song) => void }) {
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

function DeleteSong({ song, onDeleted }: { song: Song; onDeleted: () => void }) {
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
