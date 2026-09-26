import { useMemo, useState } from 'react'
import { DIFFICULTIES, type Difficulty, type Song } from './api'

/**
 * Search and filter for a song list. Text matches title, arranger and tags. Difficulties
 * combine with OR (easy or medium); tags combine with AND (christmas and upbeat).
 */
export function useSongFilter(songs: Song[] | null): [Song[] | null, React.ReactNode] {
  const [query, setQuery] = useState('')
  const [levels, setLevels] = useState<Difficulty[]>([])
  const [tags, setTags] = useState<string[]>([])

  const allTags = useMemo(() => [...new Set((songs ?? []).flatMap((s) => s.tags))].sort(), [songs])
  const hasLevels = (songs ?? []).some((s) => s.difficulty)

  const filtered = useMemo(() => {
    if (!songs) return null
    const q = query.trim().toLowerCase()
    return songs.filter(
      (s) =>
        (!q || [s.title, s.arranger ?? '', ...s.tags].some((t) => t.toLowerCase().includes(q))) &&
        (levels.length === 0 || (s.difficulty !== null && levels.includes(s.difficulty))) &&
        tags.every((t) => s.tags.includes(t)),
    )
  }, [songs, query, levels, tags])

  const toggle = <T,>(list: T[], item: T) => (list.includes(item) ? list.filter((x) => x !== item) : [...list, item])
  const active = query.trim() !== '' || levels.length > 0 || tags.length > 0

  if (!songs || songs.length === 0) return [filtered, null]

  const ui = (
    <div className="song-filters">
      <label>
        Search songs
        <input type="search" value={query} onChange={(e) => setQuery(e.target.value)} autoComplete="off" />
        <span className="hint">Title, arranger or tag</span>
      </label>
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
        <div className="chips" role="group" aria-label="Filter by tag">
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
