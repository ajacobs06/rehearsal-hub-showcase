import { useMemo, useState } from 'react'
import { DIFFICULTIES, KINDS, type Difficulty, type Song, type SongKind } from './api'

/**
 * Search and filter for a song list. Text matches title, arranger and genre/mood labels. Type and
 * difficulty combine with OR (easy or medium); genre/mood labels combine with AND (christmas and upbeat).
 */
export function useSongFilter(songs: Song[] | null): [Song[] | null, React.ReactNode] {
  const [query, setQuery] = useState('')
  const [kinds, setKinds] = useState<SongKind[]>([])
  const [levels, setLevels] = useState<Difficulty[]>([])
  const [tags, setTags] = useState<string[]>([])

  const allTags = useMemo(() => [...new Set((songs ?? []).flatMap((s) => s.tags))].sort(), [songs])
  const hasLevels = (songs ?? []).some((s) => s.difficulty)
  const hasTagKind = (songs ?? []).some((s) => s.kind === 'tag')

  const filtered = useMemo(() => {
    if (!songs) return null
    const q = query.trim().toLowerCase()
    return songs.filter(
      (s) =>
        (!q || [s.title, s.arranger ?? '', ...s.tags].some((t) => t.toLowerCase().includes(q))) &&
        (kinds.length === 0 || kinds.includes(s.kind)) &&
        (levels.length === 0 || (s.difficulty !== null && levels.includes(s.difficulty))) &&
        tags.every((t) => s.tags.includes(t)),
    )
  }, [songs, query, kinds, levels, tags])

  const toggle = <T,>(list: T[], item: T) => (list.includes(item) ? list.filter((x) => x !== item) : [...list, item])
  const active = query.trim() !== '' || kinds.length > 0 || levels.length > 0 || tags.length > 0

  if (!songs || songs.length === 0) return [filtered, null]

  const ui = (
    <div className="song-filters">
      <label>
        Search songs
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} autoComplete="off" />
        <span className="hint">Title, arranger, genre or mood</span>
      </label>
      {hasTagKind && (
        <div className="chips" role="group" aria-label="Filter by type">
          {KINDS.map((k) => (
            <button key={k.value} className="chip" aria-pressed={kinds.includes(k.value)} onClick={() => setKinds((l) => toggle(l, k.value))}>
              {k.plural}
            </button>
          ))}
        </div>
      )}
      {hasLevels && (
        <div className="chips" role="group" aria-label="Filter by difficulty">
          {DIFFICULTIES.map((d) => (
            <button
              key={d.value}
              className="chip"
              aria-pressed={levels.includes(d.value)}
              onClick={() => setLevels((l) => toggle(l, d.value))}
            >
              {d.label}
            </button>
          ))}
        </div>
      )}
      {allTags.length > 0 && (
        <div className="chips" role="group" aria-label="Filter by genre or mood">
          {allTags.map((t) => (
            <button key={t} className="chip" aria-pressed={tags.includes(t)} onClick={() => setTags((l) => toggle(l, t))}>
              {t}
            </button>
          ))}
        </div>
      )}
      {active && filtered && (
        <div className="row filter-summary">
          <p className="muted small" role="status">
            Showing {filtered.length} of {songs.length} songs
          </p>
          <button
            className="button secondary small"
            onClick={() => {
              setQuery('')
              setKinds([])
              setLevels([])
              setTags([])
            }}
          >
            Clear
          </button>
        </div>
      )}
    </div>
  )
  return [filtered, ui]
}
