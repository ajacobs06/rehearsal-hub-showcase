import { useEffect, useState } from 'react'
import { COMMITTEE, groupsApi, type Group, type Member } from './api'

// Group names change rarely: fetch once per page load and share, refreshing after edits.
let cached: Promise<Group[]> | null = null
const listeners = new Set<(g: Group[]) => void>()

export function refreshGroups(): void {
  cached = groupsApi.list()
  cached.then((g) => listeners.forEach((l) => l(g))).catch(() => undefined)
}

export function useGroups(): Group[] | null {
  const [groups, setGroups] = useState<Group[] | null>(null)
  useEffect(() => {
    if (!cached) cached = groupsApi.list()
    cached.then(setGroups).catch(() => setGroups([]))
    listeners.add(setGroups)
    return () => {
      listeners.delete(setGroups)
    }
  }, [])
  return groups
}

export function groupNames(ids: string[], groups: Group[] | null): string {
  if (!groups) return ''
  return ids
    .map((id) => groups.find((g) => g.id === id)?.name)
    .filter(Boolean)
    .join(', ')
}

/** Group checkboxes. Committee makes people admins, so only owners may change it. */
export function GroupCheckboxes({
  groups,
  value,
  onChange,
  me,
  legend,
  hint,
  committeeLocked = true,
}: {
  groups: Group[] | null
  value: string[]
  onChange: (ids: string[]) => void
  me: Member
  legend: string
  hint?: string
  committeeLocked?: boolean
}) {
  const locked = committeeLocked && me.role !== 'owner'
  const toggle = (id: string) => onChange(value.includes(id) ? value.filter((x) => x !== id) : [...value, id])
  return (
    <fieldset className="wide song-picks">
      <legend>{legend}</legend>
      {groups === null ? (
        <div className="skeleton skeleton-line" />
      ) : (
        groups.map((g) => (
          <label key={g.id} className="check">
            <input
              type="checkbox"
              checked={value.includes(g.id)}
              disabled={g.id === COMMITTEE && locked}
              onChange={() => toggle(g.id)}
            />
            {g.name}
          </label>
        ))
      )}
      {locked && groups?.some((g) => g.id === COMMITTEE) && (
        <span className="hint">Only owners can change the committee, because it makes people admins.</span>
      )}
      {hint && <span className="hint">{hint}</span>}
    </fieldset>
  )
}
