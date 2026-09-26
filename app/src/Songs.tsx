import { useEffect, useState, type FormEvent } from 'react'
import { FILE_LABEL, STATE_LABEL, STATUS_LABEL, songsApi, type Member, type Song, type SongStatus } from './api'

const GROUPS: SongStatus[] = ['learning', 'performing', 'retired']

export default function Songs({ me, navigate }: { me: Member; navigate: (to: string) => void }) {
  const [songs, setSongs] = useState<Song[] | null>(null)
  const [loadError, setLoadError] = useState(false)
  const isAdmin = me.role !== 'member'

  useEffect(() => {
    songsApi
      .list()
      .then(setSongs)
      .catch(() => setLoadError(true))
  }, [])

  if (loadError) return <p className="error">Couldn't load songs. Refresh the page to try again.</p>

  return (
    <section className="songs">
      <div className="section-head">
        <h2>Songs</h2>
      </div>

      {isAdmin && <AddSong onCreated={(s) => navigate(`/songs/${s.id}`)} />}

      {songs === null ? (
        <div className="panel">
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line short" />
        </div>
      ) : songs.length === 0 ? (
        <p className="muted">
          {isAdmin ? 'No songs yet. Add the first one above.' : "No songs yet. They'll appear here once the committee adds them."}
        </p>
      ) : (
        GROUPS.map((status) => {
          const items = songs.filter((s) => s.status === status)
          if (items.length === 0) return null
          return (
            <div key={status} className="group">
              <h3>
                {STATUS_LABEL[status]} <span className="count">{items.length}</span>
              </h3>
              <ul className="song-list">
                {items.map((s) => (
                  <li key={s.id}>
                    <a
                      href={`/songs/${s.id}`}
                      onClick={(e) => {
                        e.preventDefault()
                        navigate(`/songs/${s.id}`)
                      }}
                    >
                      <span className="song-head">
                        <span className="song-title">{s.title}</span>
                        {s.myState !== 'not_started' && (
                          <span className={`badge state-${s.myState}`}>{STATE_LABEL[s.myState]}</span>
                        )}
                      </span>
                      {s.arranger && <span className="muted small">{s.arranger}</span>}
                      {s.myPart && (
                        <span className={`small ${s.files[s.myPart] ? 'ready' : 'muted'}`}>
                          {s.files[s.myPart]
                            ? `${FILE_LABEL[s.myPart]} track ready`
                            : `No ${FILE_LABEL[s.myPart]} track yet`}
                          {s.partOverride && ' (this song)'}
                        </span>
                      )}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )
        })
      )}
    </section>
  )
}

function AddSong({ onCreated }: { onCreated: (s: Song) => void }) {
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
      <button className="button secondary" onClick={() => setOpen(true)}>
        Add a song
      </button>
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
