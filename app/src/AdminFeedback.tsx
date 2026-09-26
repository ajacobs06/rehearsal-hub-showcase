import { useEffect, useState } from 'react'
import { feedbackApi, type FeedbackItem } from './api'

/** Admin: pilot feedback, newest first, with new items above done ones. */
export default function AdminFeedback() {
  const [items, setItems] = useState<FeedbackItem[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    feedbackApi
      .list()
      .then(setItems)
      .catch(() => setError(true))
  }, [])

  if (error) return <p className="error">Couldn't load feedback. Refresh the page to try again.</p>
  if (items === null)
    return (
      <div className="panel">
        <div className="skeleton skeleton-line" />
      </div>
    )
  if (items.length === 0) return <p className="muted">No feedback yet. Members send it from the link at the bottom of each page.</p>

  const replace = (f: FeedbackItem) => setItems((list) => list?.map((x) => (x.id === f.id ? f : x)) ?? null)
  const open = items.filter((f) => f.status === 'new').length

  return (
    <>
      <p className="muted">
        {open} new, {items.length - open} done
      </p>
      <ul className="member-list">
        {items.map((f) => (
          <li key={f.id} className="member feedback-item">
            <div className="member-main">
              <p className="feedback-message">{f.message}</p>
              <p className="muted small">
                {f.name}, {new Date(f.createdAt).toLocaleString('en-GB', { day: 'numeric', month: 'short', hour: 'numeric', minute: '2-digit', timeZone: 'Europe/London' })}
                {f.page && `, from ${f.page}`}
              </p>
              {f.status === 'new' && (
                <div className="badges">
                  <span className="badge admin">New</span>
                </div>
              )}
            </div>
            <div className="member-actions">
              <button
                className="button secondary small"
                onClick={() => feedbackApi.setStatus(f.id, f.status === 'new' ? 'done' : 'new').then(replace)}
              >
                {f.status === 'new' ? 'Mark done' : 'Mark new'}
              </button>
              <button
                className="button secondary small"
                onClick={() => feedbackApi.remove(f.id).then(() => setItems((l) => l?.filter((x) => x.id !== f.id) ?? null))}
              >
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>
    </>
  )
}
