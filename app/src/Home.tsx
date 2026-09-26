import { useEffect, useState } from 'react'
import { PARTS, api, rehearsalsApi, type Member, type Part, type Rehearsal } from './api'
import { RehearsalCard, internalLink } from './Rehearsals'
import Songs from './Songs'

export default function Home({
  member,
  navigate,
  onChange,
}: {
  member: Member
  navigate: (to: string) => void
  onChange: (m: Member) => void
}) {
  const [editing, setEditing] = useState(member.part === null)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const firstName = member.name.split(' ')[0]
  const partLabel = PARTS.find((p) => p.value === member.part)?.label

  async function choose(part: Part) {
    setSaving(true)
    setError(null)
    try {
      onChange(await api.updateMe({ part }))
      setEditing(false)
    } catch {
      setError("Couldn't save your part. Try again.")
    } finally {
      setSaving(false)
    }
  }

  return (
    <>
      <h1>Hi {firstName}</h1>

      <NextRehearsal navigate={navigate} />

      <section className="panel">
        {editing ? (
          <>
            <h2>Which part do you sing?</h2>
            <div className="segmented" role="group" aria-label="Voice part">
              {PARTS.map((p) => (
                <button
                  key={p.value}
                  className={p.value === member.part ? 'selected' : undefined}
                  aria-pressed={p.value === member.part}
                  disabled={saving}
                  onClick={() => choose(p.value)}
                >
                  {p.label}
                </button>
              ))}
            </div>
            {error && <p className="error">{error}</p>}
          </>
        ) : (
          <div className="row">
            <div>
              <p className="muted small">Your usual part</p>
              <p className="part-name">{partLabel}</p>
              <p className="muted small">You can learn a different part on any song's page.</p>
            </div>
            <button className="button secondary" onClick={() => setEditing(true)}>
              Change
            </button>
          </div>
        )}
      </section>

      <Songs navigate={navigate} />
    </>
  )
}

function NextRehearsal({ navigate }: { navigate: (to: string) => void }) {
  const [next, setNext] = useState<Rehearsal | null | undefined>(undefined)

  useEffect(() => {
    rehearsalsApi
      .list('upcoming')
      .then((list) => setNext(list[0] ?? null))
      .catch(() => setNext(null))
  }, [])

  if (next === undefined)
    return (
      <div className="panel">
        <div className="skeleton skeleton-line" />
        <div className="skeleton skeleton-line short" />
      </div>
    )

  return (
    <section className="stack">
      <div className="row">
        <h2>Next rehearsal</h2>
        <a className="small" {...internalLink('/schedule', navigate)}>
          Full schedule
        </a>
      </div>
      {next ? (
        <RehearsalCard r={next} navigate={navigate} onChange={setNext} showSongs />
      ) : (
        <p className="muted">Nothing scheduled yet.</p>
      )}
    </section>
  )
}
