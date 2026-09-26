import { useState, type FormEvent } from 'react'
import { ApiError, feedbackApi } from './api'

/** "Send feedback": the page it was opened from is recorded to help the committee find the problem. */
export default function FeedbackPage({ from, back }: { from: string | null; back: React.ReactNode }) {
  const [message, setMessage] = useState('')
  const [busy, setBusy] = useState(false)
  const [sent, setSent] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await feedbackApi.send(message, from)
      setSent(true)
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 429
          ? "You've sent a lot of feedback today. Please try again tomorrow."
          : "Couldn't send your feedback. Try again.",
      )
    } finally {
      setBusy(false)
    }
  }

  return (
    <>
      {back}
      <h1>Send feedback</h1>
      {sent ? (
        <p className="success" role="status">
          Thanks, the committee will see it.
        </p>
      ) : (
        <form className="panel" onSubmit={submit}>
          <div className="fields">
            <label className="wide">
              What's working, what isn't, or what would help?
              <textarea value={message} onChange={(e) => setMessage(e.target.value)} required maxLength={2000} rows={6} />
              <span className="hint">
                {from ? `We'll note you sent this from ${from}. ` : ''}The committee sees your name with it.
              </span>
            </label>
          </div>
          <button className="button" type="submit" disabled={busy || !message.trim()}>
            {busy ? 'Sending' : 'Send feedback'}
          </button>
          {error && <p className="error">{error}</p>}
        </form>
      )}
    </>
  )
}
