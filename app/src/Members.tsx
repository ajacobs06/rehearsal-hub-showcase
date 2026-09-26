import { useEffect, useState, type FormEvent } from 'react'
import { ApiError, PARTS, api, canManage, type Member, type Part, type Role } from './api'

const ROLE_LABEL: Record<Role, string> = { member: 'Member', admin: 'Admin', owner: 'Owner' }

export default function Members({ me }: { me: Member }) {
  const [members, setMembers] = useState<Member[] | null>(null)
  const [loadError, setLoadError] = useState(false)

  useEffect(() => {
    api
      .listMembers()
      .then(setMembers)
      .catch(() => setLoadError(true))
  }, [])

  const replace = (m: Member) => setMembers((list) => list?.map((x) => (x.id === m.id ? m : x)) ?? null)
  const remove = (id: string) => setMembers((list) => list?.filter((x) => x.id !== id) ?? null)
  const add = (m: Member) => setMembers((list) => [...(list ?? []), m])

  if (loadError) return <p className="error">Couldn't load members. Refresh the page to try again.</p>

  const active = members?.filter((m) => m.status === 'active') ?? []
  const invited = members?.filter((m) => m.status === 'invited') ?? []
  const groups = [
    ...PARTS.map((p) => ({ title: p.label, items: active.filter((m) => m.part === p.value) })),
    { title: 'No part yet', items: active.filter((m) => m.part === null) },
    { title: 'Invited', items: invited },
  ].filter((g) => g.items.length > 0)

  return (
    <>
      <h1>Members</h1>
      {members && (
        <p className="muted">
          {active.length} active, {invited.length} invited
        </p>
      )}

      <InviteForm me={me} onInvited={add} />

      {members === null ? (
        <div className="panel">
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line short" />
        </div>
      ) : (
        groups.map((g) => (
          <section key={g.title} className="group">
            <h2>
              {g.title} <span className="count">{g.items.length}</span>
            </h2>
            <ul className="member-list">
              {g.items.map((m) => (
                <MemberRow key={m.id} me={me} member={m} onChange={replace} onRemove={remove} />
              ))}
            </ul>
          </section>
        ))
      )}
    </>
  )
}

function InviteForm({ me, onInvited }: { me: Member; onInvited: (m: Member) => void }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [part, setPart] = useState<Part | ''>('')
  const [role, setRole] = useState<Role>('member')
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const roles = (['member', 'admin', 'owner'] as Role[]).filter((r) => canManage(me, r))

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      const res = await api.invite({ name, email, part: part || null, role })
      onInvited(res.member)
      setMessage(
        res.emailed
          ? { kind: 'ok', text: `Invite emailed to ${res.member.email}.` }
          : {
              kind: 'ok',
              text: `${res.member.email} can now sign in. The email didn't send, so share the site link with them yourself.`,
            },
      )
      setName('')
      setEmail('')
      setPart('')
      setRole('member')
    } catch (err) {
      const text =
        err instanceof ApiError && err.reason === 'already_exists'
          ? 'That email is already a member or has been invited.'
          : err instanceof ApiError && err.status === 422
            ? 'Check the name and email address.'
            : "Couldn't send the invite. Try again."
      setMessage({ kind: 'error', text })
    } finally {
      setBusy(false)
    }
  }

  return (
    <form className="panel invite" onSubmit={submit}>
      <h2>Invite a member</h2>
      <div className="fields">
        <label>
          Name
          <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={100} autoComplete="off" />
        </label>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
            autoComplete="off"
          />
          <span className="hint">The Google account they'll sign in with.</span>
        </label>
        <label>
          Part
          <select value={part} onChange={(e) => setPart(e.target.value as Part | '')}>
            <option value="">Let them choose</option>
            {PARTS.map((p) => (
              <option key={p.value} value={p.value}>
                {p.label}
              </option>
            ))}
          </select>
        </label>
        {roles.length > 1 && (
          <label>
            Role
            <select value={role} onChange={(e) => setRole(e.target.value as Role)}>
              {roles.map((r) => (
                <option key={r} value={r}>
                  {ROLE_LABEL[r]}
                </option>
              ))}
            </select>
          </label>
        )}
      </div>
      <button className="button" type="submit" disabled={busy}>
        {busy ? 'Sending' : 'Send invite'}
      </button>
      {message && (
        <p className={message.kind === 'error' ? 'error' : 'success'} role="status">
          {message.text}
        </p>
      )}
    </form>
  )
}

function MemberRow({
  me,
  member,
  onChange,
  onRemove,
}: {
  me: Member
  member: Member
  onChange: (m: Member) => void
  onRemove: (id: string) => void
}) {
  const [confirming, setConfirming] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isMe = member.id === me.id
  const editable = !isMe && canManage(me, member.role)
  const roles = (['member', 'admin', 'owner'] as Role[]).filter((r) => canManage(me, r))

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch {
      setError("Couldn't save that change.")
    } finally {
      setBusy(false)
    }
  }

  return (
    <li className="member">
      <div className="member-main">
        <p className="member-name">
          {member.name}
          {isMe && <span className="muted"> (you)</span>}
        </p>
        <p className="muted small member-email">{member.email}</p>
        <div className="badges">
          {member.role !== 'member' && <span className={`badge ${member.role}`}>{ROLE_LABEL[member.role]}</span>}
          {member.status === 'invited' && <span className="badge invited">Invited</span>}
        </div>
      </div>

      {editable && (
        <div className="member-actions">
          <label className="compact">
            <span className="visually-hidden">Part for {member.name}</span>
            <select
              value={member.part ?? ''}
              disabled={busy}
              onChange={(e) =>
                run(async () =>
                  onChange(await api.updateMember(member.id, { part: (e.target.value || null) as Part | null })),
                )
              }
            >
              <option value="">No part</option>
              {PARTS.map((p) => (
                <option key={p.value} value={p.value}>
                  {p.label}
                </option>
              ))}
            </select>
          </label>
          {roles.length > 1 && (
            <label className="compact">
              <span className="visually-hidden">Role for {member.name}</span>
              <select
                value={member.role}
                disabled={busy}
                onChange={(e) =>
                  run(async () => onChange(await api.updateMember(member.id, { role: e.target.value as Role })))
                }
              >
                {roles.map((r) => (
                  <option key={r} value={r}>
                    {ROLE_LABEL[r]}
                  </option>
                ))}
              </select>
            </label>
          )}
          {confirming ? (
            <span className="confirm">
              <button
                className="button danger small"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await api.deleteMember(member.id)
                    onRemove(member.id)
                  })
                }
              >
                Remove
              </button>
              <button className="button secondary small" disabled={busy} onClick={() => setConfirming(false)}>
                Keep
              </button>
            </span>
          ) : (
            <button className="button secondary small" onClick={() => setConfirming(true)}>
              Remove
            </button>
          )}
        </div>
      )}
      {error && <p className="error small">{error}</p>}
    </li>
  )
}
