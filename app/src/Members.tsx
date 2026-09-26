import { useCallback, useEffect, useState, type FormEvent } from 'react'
import { ApiError, COMMITTEE, PARTS, api, canManage, groupsApi, type Group, type Member, type Part } from './api'
import { GroupCheckboxes, groupNames, refreshGroups, useGroups } from './groups'

export default function Members({ me }: { me: Member }) {
  const [members, setMembers] = useState<Member[] | null>(null)
  const [loadError, setLoadError] = useState(false)
  const [tab, setTab] = useState<'people' | 'groups'>('people')
  const groups = useGroups()

  const load = useCallback(() => {
    api
      .listMembers()
      .then(setMembers)
      .catch(() => setLoadError(true))
  }, [])
  useEffect(load, [load])

  const replace = (m: Member) => {
    setMembers((list) => list?.map((x) => (x.id === m.id ? m : x)) ?? null)
    refreshGroups()
  }
  const remove = (id: string) => {
    setMembers((list) => list?.filter((x) => x.id !== id) ?? null)
    refreshGroups()
  }
  const add = (m: Member) => {
    setMembers((list) => [...(list ?? []), m])
    refreshGroups()
  }

  if (loadError) return <p className="error">Couldn't load members. Refresh the page to try again.</p>

  const active = members?.filter((m) => m.status === 'active') ?? []
  const invited = members?.filter((m) => m.status === 'invited') ?? []
  const byPart = [
    ...PARTS.map((p) => ({ title: p.label, items: active.filter((m) => m.part === p.value) })),
    { title: 'No part yet', items: active.filter((m) => m.part === null) },
    { title: 'Invited', items: invited },
  ].filter((g) => g.items.length > 0)

  return (
    <>
      <h1>Members</h1>
      <div className="segmented tabs" role="group" aria-label="Members view">
        <button className={tab === 'people' ? 'selected' : undefined} aria-pressed={tab === 'people'} onClick={() => setTab('people')}>
          People
        </button>
        <button className={tab === 'groups' ? 'selected' : undefined} aria-pressed={tab === 'groups'} onClick={() => setTab('groups')}>
          Groups
        </button>
      </div>

      {members === null ? (
        <div className="panel">
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line short" />
        </div>
      ) : tab === 'people' ? (
        <>
          <p className="muted">
            {active.length} active, {invited.length} invited
          </p>
          <InviteForm me={me} groups={groups} onInvited={add} />
          {byPart.map((g) => (
            <section key={g.title} className="group">
              <h2>
                {g.title} <span className="count">{g.items.length}</span>
              </h2>
              <ul className="member-list">
                {g.items.map((m) => (
                  <MemberRow key={m.id} me={me} member={m} groups={groups} onChange={replace} onRemove={remove} />
                ))}
              </ul>
            </section>
          ))}
        </>
      ) : (
        <GroupsTab me={me} members={members} groups={groups} onMembersChanged={load} />
      )}
    </>
  )
}

function InviteForm({ me, groups, onInvited }: { me: Member; groups: Group[] | null; onInvited: (m: Member) => void }) {
  const [name, setName] = useState('')
  const [email, setEmail] = useState('')
  const [part, setPart] = useState<Part | ''>('')
  const [chosen, setChosen] = useState<string[]>([])
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)

  async function submit(e: FormEvent) {
    e.preventDefault()
    setBusy(true)
    setMessage(null)
    try {
      const res = await api.invite({ name, email, part: part || null, groups: chosen })
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
      setChosen([])
    } catch (err) {
      const text =
        err instanceof ApiError && err.reason === 'already_exists'
          ? 'That email is already a member or has been invited.'
          : err instanceof ApiError && err.reason === 'owner_only_committee'
            ? 'Only owners can add people to the committee.'
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
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required autoComplete="off" />
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
        <GroupCheckboxes
          groups={groups}
          value={chosen}
          onChange={setChosen}
          me={me}
          legend="Groups"
          hint="Committee members are admins."
        />
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
  groups,
  onChange,
  onRemove,
}: {
  me: Member
  member: Member
  groups: Group[] | null
  onChange: (m: Member) => void
  onRemove: (id: string) => void
}) {
  const [confirming, setConfirming] = useState(false)
  const [editingGroups, setEditingGroups] = useState(false)
  const [draft, setDraft] = useState<string[]>(member.groups)
  const [owner, setOwner] = useState(member.role === 'owner')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const isMe = member.id === me.id
  const editable = !isMe && canManage(me, member.role)

  async function run(action: () => Promise<void>) {
    setBusy(true)
    setError(null)
    try {
      await action()
    } catch (err) {
      setError(
        err instanceof ApiError && err.reason === 'owner_only_committee'
          ? 'Only owners can change the committee.'
          : "Couldn't save that change.",
      )
    } finally {
      setBusy(false)
    }
  }

  function saveGroups() {
    run(async () => {
      const body: { groups: string[]; owner?: boolean } = { groups: draft }
      if (me.role === 'owner' && !isMe && owner !== (member.role === 'owner')) body.owner = owner
      onChange(await api.updateMember(member.id, body))
      setEditingGroups(false)
    })
  }

  const names = groupNames(member.groups, groups)

  return (
    <li className="member">
      <div className="member-main">
        <p className="member-name">
          {member.name}
          {isMe && <span className="muted"> (you)</span>}
        </p>
        <p className="muted small member-email">{member.email}</p>
        {names && <p className="small member-groups">{names}</p>}
        <div className="badges">
          {member.role === 'owner' && <span className="badge owner">Owner</span>}
          {member.role === 'admin' && <span className="badge admin">Admin</span>}
          {member.status === 'invited' && <span className="badge invited">Invited</span>}
        </div>
      </div>

      <div className="member-actions">
        {editable && (
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
        )}
        <button
          className="button secondary small"
          aria-expanded={editingGroups}
          onClick={() => {
            setDraft(member.groups)
            setOwner(member.role === 'owner')
            setEditingGroups(!editingGroups)
          }}
        >
          Groups
        </button>
        {editable &&
          (confirming ? (
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
          ))}
      </div>

      {editingGroups && (
        <div className="group-editor">
          <GroupCheckboxes groups={groups} value={draft} onChange={setDraft} me={me} legend={`Groups for ${member.name}`} />
          {me.role === 'owner' && !isMe && (
            <label className="check">
              <input type="checkbox" checked={owner} onChange={(e) => setOwner(e.target.checked)} />
              Owner (full control, for handing over)
            </label>
          )}
          <div className="actions">
            <button className="button small" onClick={saveGroups} disabled={busy}>
              Save groups
            </button>
            <button className="button secondary small" onClick={() => setEditingGroups(false)}>
              Cancel
            </button>
          </div>
        </div>
      )}
      {error && <p className="error small">{error}</p>}
    </li>
  )
}

// ---------- Groups tab ----------

function GroupsTab({
  me,
  members,
  groups,
  onMembersChanged,
}: {
  me: Member
  members: Member[]
  groups: Group[] | null
  onMembersChanged: () => void
}) {
  const [newName, setNewName] = useState('')
  const [openId, setOpenId] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function addQuartet(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      const g = await groupsApi.create(newName)
      setNewName('')
      refreshGroups()
      setOpenId(g.id)
    } catch {
      setError("Couldn't add the quartet. Check the name and try again.")
    }
  }

  if (groups === null)
    return (
      <div className="panel">
        <div className="skeleton skeleton-line" />
      </div>
    )

  const fixed = groups.filter((g) => g.kind === 'fixed')
  const quartets = groups.filter((g) => g.kind === 'quartet')

  return (
    <>
      <p className="muted">
        Rehearsals can be for one or more groups; everyone else won't see them. Songs are always visible to everyone.
      </p>
      <section className="stack">
        <h2>Chorus and committee</h2>
        <ul className="member-list">
          {fixed.map((g) => (
            <GroupRow key={g.id} me={me} group={g} members={members} open={openId === g.id} onToggle={() => setOpenId(openId === g.id ? null : g.id)} onSaved={onMembersChanged} />
          ))}
        </ul>
      </section>

      <section className="stack">
        <h2>Quartets</h2>
        {quartets.length > 0 ? (
          <ul className="member-list">
            {quartets.map((g) => (
              <GroupRow key={g.id} me={me} group={g} members={members} open={openId === g.id} onToggle={() => setOpenId(openId === g.id ? null : g.id)} onSaved={onMembersChanged} />
            ))}
          </ul>
        ) : (
          <p className="muted">No quartets yet.</p>
        )}
        <form className="panel" onSubmit={addQuartet}>
          <div className="fields">
            <label className="wide">
              Add a quartet
              <input value={newName} onChange={(e) => setNewName(e.target.value)} required maxLength={60} placeholder="Quartet name" />
            </label>
          </div>
          <button className="button" type="submit">
            Add quartet
          </button>
          {error && <p className="error">{error}</p>}
        </form>
      </section>
    </>
  )
}

function GroupRow({
  me,
  group,
  members,
  open,
  onToggle,
  onSaved,
}: {
  me: Member
  group: Group
  members: Member[]
  open: boolean
  onToggle: () => void
  onSaved: () => void
}) {
  const current = members.filter((m) => m.groups.includes(group.id)).map((m) => m.id)
  const [picked, setPicked] = useState<string[]>(current)
  const [name, setName] = useState(group.name)
  const [renaming, setRenaming] = useState(false)
  const [confirmDelete, setConfirmDelete] = useState(false)
  const [busy, setBusy] = useState(false)
  const [message, setMessage] = useState<{ kind: 'ok' | 'error'; text: string } | null>(null)
  const readOnly = group.id === COMMITTEE && me.role !== 'owner'

  async function run(action: () => Promise<void>, done?: string) {
    setBusy(true)
    setMessage(null)
    try {
      await action()
      refreshGroups()
      if (done) setMessage({ kind: 'ok', text: done })
    } catch (err) {
      setMessage({
        kind: 'error',
        text:
          err instanceof ApiError && err.reason === 'owner_only_committee'
            ? 'Only owners can change the committee.'
            : "Couldn't save that change.",
      })
    } finally {
      setBusy(false)
    }
  }

  const toggle = (id: string) => setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : [...p, id]))

  return (
    <li className="member">
      <div className="member-main">
        <p className="member-name">{group.name}</p>
        <p className="muted small">
          {group.memberCount} {group.memberCount === 1 ? 'person' : 'people'}
          {group.id === COMMITTEE && '. Committee members are admins.'}
        </p>
      </div>
      <div className="member-actions">
        <button
          className="button secondary small"
          aria-expanded={open}
          onClick={() => {
            setPicked(current)
            setMessage(null)
            onToggle()
          }}
        >
          Members
        </button>
        {group.kind === 'quartet' && (
          <>
            <button className="button secondary small" onClick={() => setRenaming(!renaming)}>
              Rename
            </button>
            {confirmDelete ? (
              <span className="confirm">
                <button className="button danger small" disabled={busy} onClick={() => run(() => groupsApi.remove(group.id))}>
                  Delete
                </button>
                <button className="button secondary small" onClick={() => setConfirmDelete(false)}>
                  Keep
                </button>
              </span>
            ) : (
              <button className="button secondary small" onClick={() => setConfirmDelete(true)}>
                Delete
              </button>
            )}
          </>
        )}
      </div>

      {renaming && (
        <form
          className="group-editor"
          onSubmit={(e) => {
            e.preventDefault()
            run(async () => {
              await groupsApi.rename(group.id, name)
              setRenaming(false)
            })
          }}
        >
          <label>
            Quartet name
            <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={60} />
          </label>
          <div className="actions">
            <button className="button small" type="submit" disabled={busy}>
              Save name
            </button>
          </div>
        </form>
      )}

      {open && (
        <div className="group-editor">
          <fieldset className="song-picks">
            <legend>Who's in {group.name}</legend>
            {members.map((m) => (
              <label key={m.id} className="check">
                <input type="checkbox" checked={picked.includes(m.id)} disabled={readOnly} onChange={() => toggle(m.id)} />
                {m.name}
                {m.status === 'invited' && <span className="muted small">(invited)</span>}
              </label>
            ))}
            {readOnly && <span className="hint">Only owners can change the committee, because it makes people admins.</span>}
          </fieldset>
          {!readOnly && (
            <div className="actions">
              <button
                className="button small"
                disabled={busy}
                onClick={() =>
                  run(async () => {
                    await groupsApi.setMembers(group.id, picked)
                    onSaved()
                  }, 'Saved.')
                }
              >
                Save members
              </button>
            </div>
          )}
        </div>
      )}
      {message && <p className={`small ${message.kind === 'error' ? 'error' : 'success'}`}>{message.text}</p>}
    </li>
  )
}
