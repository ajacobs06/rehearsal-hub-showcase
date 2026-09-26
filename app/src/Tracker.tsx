import { useEffect, useState } from 'react'
import { PARTS, STATE_LABEL, isLearned, trackerApi, type LearnState, type Part, type Tracker as Data } from './api'

type Entry = Data['entries'][number]

const PART_ORDER: (Part | null)[] = ['tenor', 'lead', 'bari', 'bass', null]
const NEED_ORDER: Record<LearnState, number> = { not_started: 0, learning: 1, learned: 2, ready: 3 }
const partLabel = (p: Part | null) => PARTS.find((x) => x.value === p)?.label ?? 'No part'

export default function Tracker() {
  const [data, setData] = useState<Data | null>(null)
  const [error, setError] = useState(false)
  const [view, setView] = useState<'songs' | 'grid'>('songs')

  useEffect(() => {
    trackerApi
      .get()
      .then(setData)
      .catch(() => setError(true))
  }, [])

  if (error) return <p className="error">Couldn't load the tracker. Refresh the page to try again.</p>

  return (
    <>
      <p className="muted">
        Who has learned each current song, grouped by the part they sing on it. Learned includes ready.
      </p>

      {data === null ? (
        <div className="panel">
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line short" />
        </div>
      ) : data.songs.length === 0 ? (
        <p className="muted">No current songs yet. Add one from Home and it will appear here.</p>
      ) : data.members.length === 0 ? (
        <p className="muted">No active members yet. Invited people appear once they sign in.</p>
      ) : (
        <>
          <div className="segmented tabs" role="group" aria-label="Tracker view">
            <button className={view === 'songs' ? 'selected' : undefined} aria-pressed={view === 'songs'} onClick={() => setView('songs')}>
              By song
            </button>
            <button className={view === 'grid' ? 'selected' : undefined} aria-pressed={view === 'grid'} onClick={() => setView('grid')}>
              Grid
            </button>
          </div>
          {view === 'songs' ? <BySong data={data} /> : <Grid data={data} />}
        </>
      )}
    </>
  )
}

function byPart(entries: Entry[]) {
  return PART_ORDER.map((part) => {
    const items = entries.filter((e) => e.part === part)
    return { part, items, learned: items.filter((e) => isLearned(e.state)).length }
  }).filter((g) => g.items.length > 0)
}

function BySong({ data }: { data: Data }) {
  const [open, setOpen] = useState<string | null>(null)
  const names = new Map(data.members.map((m) => [m.id, m.name]))

  return (
    <ul className="tracker-songs">
      {data.songs.map((song) => {
        const groups = byPart(data.entries.filter((e) => e.songId === song.id))
        const expanded = open === song.id
        return (
          <li key={song.id}>
            <button className="tracker-song" aria-expanded={expanded} onClick={() => setOpen(expanded ? null : song.id)}>
              <span className="song-title">{song.title}</span>
              <span className="part-counts">
                {groups.map((g) => (
                  <span key={g.part ?? 'none'} className={g.learned === g.items.length ? 'count-done' : undefined}>
                    {partLabel(g.part)} {g.learned}/{g.items.length}
                  </span>
                ))}
              </span>
            </button>
            {expanded && (
              <div className="song-detail">
                {groups.map((g) => (
                  <div key={g.part ?? 'none'}>
                    <h3>
                      {partLabel(g.part)} <span className="count">{g.learned}/{g.items.length} learned</span>
                    </h3>
                    <ul className="who">
                      {[...g.items]
                        .sort((a, b) => NEED_ORDER[a.state] - NEED_ORDER[b.state])
                        .map((e) => (
                          <li key={e.memberId}>
                            <span>{names.get(e.memberId)}</span>
                            <span className={`badge state-${e.state}`}>{STATE_LABEL[e.state]}</span>
                          </li>
                        ))}
                    </ul>
                  </div>
                ))}
              </div>
            )}
          </li>
        )
      })}
    </ul>
  )
}

function Grid({ data }: { data: Data }) {
  const cell = new Map(data.entries.map((e) => [`${e.memberId}|${e.songId}`, e]))
  const groups = PART_ORDER.map((part) => ({ part, members: data.members.filter((m) => m.part === part) })).filter(
    (g) => g.members.length > 0,
  )

  return (
    <div className="table-wrap">
      <table className="grid">
        <thead>
          <tr>
            <th scope="col">Member</th>
            {data.songs.map((s) => (
              <th key={s.id} scope="col">
                {s.title}
              </th>
            ))}
          </tr>
        </thead>
        {groups.map((g) => (
          <tbody key={g.part ?? 'none'}>
            <tr className="part-row">
              <th scope="colgroup" colSpan={data.songs.length + 1}>
                {partLabel(g.part)}
              </th>
            </tr>
            {g.members.map((m) => (
              <tr key={m.id}>
                <th scope="row">{m.name}</th>
                {data.songs.map((s) => {
                  const e = cell.get(`${m.id}|${s.id}`)
                  if (!e) return <td key={s.id} />
                  return (
                    <td key={s.id}>
                      <span className={`badge state-${e.state}`}>{STATE_LABEL[e.state]}</span>
                      {e.part !== m.part && <span className="muted small as-part">as {partLabel(e.part)}</span>}
                    </td>
                  )
                })}
              </tr>
            ))}
          </tbody>
        ))}
        <tfoot>
          <tr>
            <th scope="row">Learned</th>
            {data.songs.map((s) => {
              const items = data.entries.filter((e) => e.songId === s.id)
              return (
                <td key={s.id}>
                  {items.filter((e) => isLearned(e.state)).length}/{items.length}
                </td>
              )
            })}
          </tr>
        </tfoot>
      </table>
    </div>
  )
}
