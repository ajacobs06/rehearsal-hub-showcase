import { useState } from 'react'
import { PARTS, api, type Member, type Part } from './api'
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

      <Songs me={member} navigate={navigate} />
    </>
  )
}
