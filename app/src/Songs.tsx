import { useEffect, useState } from 'react'
import { STATE_LABEL, STATUS_LABEL, readiness, songTagLine, songsApi, type Song, type SongStatus } from './api'
import { useSongFilter } from './SongFilter'

const GROUPS: SongStatus[] = ['learning', 'performing']

export default function Songs({ navigate }: { navigate: (to: string) => void }) {
  const [songs, setSongs] = useState<Song[] | null>(null)
  const [loadError, setLoadError] = useState(false)

  useEffect(() => {
    songsApi
      .list()
      .then(setSongs)
      .catch(() => setLoadError(true))
  }, [])

  const [shown, filters] = useSongFilter(songs)

  if (loadError) return <p className="error">Couldn't load songs. Refresh the page to try again.</p>

  return (
    <section className="songs">
      <h1>Songs</h1>
      {filters}

      {songs === null ? (
        <div className="panel">
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line short" />
        </div>
      ) : songs.length === 0 ? (
        <p className="muted">
          {"No songs yet. They'll appear here once the committee adds them."}
        </p>
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
                      {songTagLine(s) && <span className="muted small">{songTagLine(s)}</span>}
                      {(() => {
                        const hasTrack = Boolean(s.myPart && s.files[s.myPart])
                        const r = readiness(Boolean(s.files.score), s.myPart, hasTrack)
                        return (
                          <span className={`small ${r.ready ? 'ready' : 'muted'}`}>
                            {r.text}
                            {hasTrack && s.partOverride && ' (this song)'}
                          </span>
                        )
                      })()}
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
