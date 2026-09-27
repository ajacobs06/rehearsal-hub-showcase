import { useState } from 'react'
import { ApiError, PARTS, accountApi, signOutUrl, type Member } from './api'
import { groupNames, useGroups } from './groups'

/** "Your data": see what's stored, download it, or delete the account (UK GDPR access and erasure). */
export default function Account({ me, back }: { me: Member; back: React.ReactNode }) {
  const groups = useGroups()
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const part = PARTS.find((p) => p.value === me.part)?.label ?? 'Not set'

  async function download() {
    setError(null)
    try {
      const data = await accountApi.exportData()
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }))
      const a = document.createElement('a')
      a.href = url
      a.download = 'rehearsal-hub-my-data.json'
      a.click()
      URL.revokeObjectURL(url)
    } catch {
      setError("Couldn't prepare your download. Try again.")
    }
  }

  async function remove() {
    setBusy(true)
    setError(null)
    try {
      await accountApi.deleteAccount()
      window.location.href = signOutUrl
    } catch (err) {
      setError(
        err instanceof ApiError && err.reason === 'owner_must_hand_over'
          ? 'You own the site. Make someone else an owner (Admin, Members, Groups button), then ask them to remove you.'
          : err instanceof ApiError && err.reason === 'sign_in_account_not_deleted'
            ? "Couldn't delete your email sign-in account, so nothing was deleted. Try again."
            : "Couldn't delete your account. Try again.",
      )
      setBusy(false)
    }
  }

  return (
    <>
      {back}
      <h1>Your data</h1>
      <section className="panel">
        <h2>What we store about you</h2>
        <dl className="facts">
          <dt>Name</dt>
          <dd>{me.name}</dd>
          <dt>Email</dt>
          <dd>{me.email}</dd>
          <dt>Usual part</dt>
          <dd>{part}</dd>
          <dt>Groups</dt>
          <dd>{groupNames(me.groups, groups) || 'None'}</dd>
        </dl>
        <p className="muted small">
          Plus your progress and part for each song, your rehearsal replies and any feedback you've sent. The download has all of
          it.
        </p>
        <button className="button secondary" onClick={download}>
          Download my data
        </button>
      </section>

      <section className="panel">
        <h2>Delete my account</h2>
        <p className="muted small">
          This removes your account, progress, part choices, rehearsal replies and feedback straight away, and your email sign-in
          account if you use one. You'd need a new invite to come back.
        </p>
        {confirming ? (
          <div className="actions">
            <button className="button danger" onClick={remove} disabled={busy}>
              {busy ? 'Deleting' : 'Delete everything'}
            </button>
            <button className="button secondary" onClick={() => setConfirming(false)}>
              Keep my account
            </button>
          </div>
        ) : (
          <button className="button secondary" onClick={() => setConfirming(true)}>
            Delete my account
          </button>
        )}
      </section>
      {error && <p className="error">{error}</p>}
    </>
  )
}
