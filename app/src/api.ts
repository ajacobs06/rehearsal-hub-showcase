export type Part = 'tenor' | 'lead' | 'bari' | 'bass'
export type Role = 'member' | 'admin' | 'owner'

export interface Member {
  id: string
  email: string
  name: string
  part: Part | null
  role: Role
  status: 'invited' | 'active'
  groups: string[]
  createdAt: string
}

export interface Group {
  id: string
  name: string
  /** Members of this group are admins. */
  admin: boolean
  memberCount: number
}

export interface InviteRequest {
  email: string
  name: string
  part: Part | null
  groups: string[]
}

export const PARTS: { value: Part; label: string }[] = [
  { value: 'tenor', label: 'Tenor' },
  { value: 'lead', label: 'Lead' },
  { value: 'bari', label: 'Bari' },
  { value: 'bass', label: 'Bass' },
]

export const ROLE_RANK: Record<Role, number> = { member: 0, admin: 1, owner: 2 }

/** Mirrors the API rule: owners manage everyone, otherwise only roles below your own. */
export function canManage(actor: Member, role: Role): boolean {
  return actor.role === 'owner' || ROLE_RANK[actor.role] > ROLE_RANK[role]
}

export class ApiError extends Error {
  status: number
  reason?: string
  email?: string

  constructor(status: number, detail: unknown) {
    const d = detail && typeof detail === 'object' && !Array.isArray(detail) ? (detail as Record<string, string>) : {}
    super(d.reason ?? `HTTP ${status}`)
    this.status = status
    this.reason = d.reason
    this.email = d.email
  }
}

async function request<T>(path: string, init?: { method?: string; body?: unknown }): Promise<T> {
  const res = await fetch(path, {
    method: init?.method ?? 'GET',
    headers: init?.body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: init?.body !== undefined ? JSON.stringify(init.body) : undefined,
  })
  if (!res.ok) {
    let detail: unknown
    try {
      detail = ((await res.json()) as { detail?: unknown }).detail
    } catch {
      detail = undefined
    }
    throw new ApiError(res.status, detail)
  }
  return (res.status === 204 ? undefined : await res.json()) as T
}

export const api = {
  me: () => request<Member>('/api/me'),
  updateMe: (body: { name?: string; part?: Part | null }) => request<Member>('/api/me', { method: 'PATCH', body }),
  listMembers: () => request<Member[]>('/api/members'),
  invite: (body: InviteRequest) =>
    request<{ member: Member; emailed: boolean }>('/api/members', { method: 'POST', body }),
  updateMember: (id: string, body: { name?: string; part?: Part | null; groups?: string[]; owner?: boolean }) =>
    request<Member>(`/api/members/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  deleteMember: (id: string) => request<void>(`/api/members/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

// ---------- Songs ----------

export type SongStatus = 'learning' | 'performing' | 'retired'
export type LearnState = 'not_started' | 'learning' | 'learned' | 'ready'

export const STATES: { value: LearnState; label: string }[] = [
  { value: 'not_started', label: 'Not started' },
  { value: 'learning', label: 'Learning' },
  { value: 'learned', label: 'Learned' },
  { value: 'ready', label: 'Ready' },
]

export const STATE_LABEL: Record<LearnState, string> = {
  not_started: 'Not started',
  learning: 'Learning',
  learned: 'Learned',
  ready: 'Ready',
}

/** Learned counts include performance-ready. */
export const isLearned = (s: LearnState) => s === 'learned' || s === 'ready'
export type FileKind = Part | 'full' | 'score'

export interface Song {
  id: string
  title: string
  arranger: string | null
  key: string | null
  status: SongStatus
  kind: SongKind
  difficulty: Difficulty | null
  tags: string[]
  files: Partial<Record<FileKind, { size: number; uploadedAt: string }>>
  createdAt: string
  /** The part the signed-in member is learning for this song: their per-song choice, else their usual part. */
  myPart: Part | null
  partOverride: boolean
  myState: LearnState
}

export interface Tracker {
  songs: { id: string; title: string; status: SongStatus }[]
  members: { id: string; name: string; part: Part | null }[]
  entries: { songId: string; memberId: string; part: Part | null; state: LearnState }[]
}

export const trackerApi = {
  get: () => request<Tracker>('/api/tracker'),
}

export interface SongInput {
  title?: string
  arranger?: string | null
  key?: string | null
  status?: SongStatus
  kind?: SongKind
  difficulty?: Difficulty | null
  tags?: string[]
}

export type Difficulty = 'easy' | 'medium' | 'hard'

/** A full song, or a barbershop tag (the short ringing phrase). Not related to genre/mood labels. */
export type SongKind = 'song' | 'tag'

export const KINDS: { value: SongKind; label: string; plural: string }[] = [
  { value: 'song', label: 'Full song', plural: 'Full songs' },
  { value: 'tag', label: 'Tag', plural: 'Tags' },
]

export const DIFFICULTIES: { value: Difficulty; label: string }[] = [
  { value: 'easy', label: 'Easy' },
  { value: 'medium', label: 'Medium' },
  { value: 'hard', label: 'Hard' },
]

/**
 * Full songs: "Medium · christmas, upbeat". Barbershop tags: "Tag · Medium, christmas, upbeat"
 * (one middle dot per line either way).
 */
export function songTagLine(song: { kind: SongKind; difficulty: Difficulty | null; tags: string[] }): string {
  const level = DIFFICULTIES.find((d) => d.value === song.difficulty)?.label
  if (song.kind === 'tag') return ['Tag', [level, ...song.tags].filter(Boolean).join(', ')].filter(Boolean).join(' · ')
  return [level, song.tags.join(', ')].filter(Boolean).join(' · ')
}

/** Mirrors the server: lowercase, trim, collapse spaces. */
export const normaliseTag = (tag: string) => tag.trim().replace(/\s+/g, ' ').toLowerCase()

export interface FileLink {
  url: string
  expiresAt: string
}

export const STATUS_LABEL: Record<SongStatus, string> = {
  learning: 'Learning',
  performing: 'Performing',
  retired: 'Retired',
}

export const FILE_LABEL: Record<FileKind, string> = {
  tenor: 'Tenor',
  lead: 'Lead',
  bari: 'Bari',
  bass: 'Bass',
  full: 'Full mix',
  score: 'Score',
}

export const UPLOAD_ERROR: Record<string, string> = {
  wrong_type: "That file isn't the right type. Tracks must be MP3s and scores must be PDFs.",
  too_large: 'That file is too big. Tracks can be up to 50 MB and scores up to 25 MB.',
  empty: 'That file is empty.',
  upload_missing: "The upload didn't reach storage. Try again.",
}

export const songsApi = {
  list: (scope: 'mine' | 'all' = 'mine') => request<Song[]>(`/api/songs?scope=${scope}`),
  get: (id: string) => request<Song>(`/api/songs/${encodeURIComponent(id)}`),
  create: (body: SongInput) => request<Song>('/api/songs', { method: 'POST', body }),
  update: (id: string, body: SongInput) =>
    request<Song>(`/api/songs/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/api/songs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  fileLink: (id: string, kind: FileKind, download = false) =>
    request<FileLink>(`/api/songs/${encodeURIComponent(id)}/files/${kind}${download ? '?download=true' : ''}`),
  setMyPart: (id: string, part: Part | null) =>
    request<Song>(`/api/songs/${encodeURIComponent(id)}/my-part`, { method: 'PUT', body: { part } }),
  setMyState: (id: string, state: LearnState) =>
    request<Song>(`/api/songs/${encodeURIComponent(id)}/my-state`, { method: 'PUT', body: { state } }),
  removeFile: (id: string, kind: FileKind) =>
    request<Song>(`/api/songs/${encodeURIComponent(id)}/files/${kind}`, { method: 'DELETE' }),

  /** Upload straight to Blob Storage with a short-lived link, then ask the API to check the file. */
  async uploadFile(id: string, kind: FileKind, file: File, onProgress: (fraction: number) => void): Promise<Song> {
    const base = `/api/songs/${encodeURIComponent(id)}/files/${kind}`
    const ticket = await request<{ url: string; contentType: string; maxBytes: number }>(`${base}/upload`, {
      method: 'POST',
    })
    if (file.size > ticket.maxBytes) throw new ApiError(400, { reason: 'too_large' })
    await new Promise<void>((resolve, reject) => {
      const xhr = new XMLHttpRequest()
      xhr.open('PUT', ticket.url)
      xhr.setRequestHeader('x-ms-blob-type', 'BlockBlob')
      xhr.setRequestHeader('x-ms-blob-content-type', ticket.contentType)
      xhr.upload.onprogress = (e) => e.lengthComputable && onProgress(e.loaded / e.total)
      xhr.onload = () => (xhr.status < 300 ? resolve() : reject(new ApiError(xhr.status, { reason: 'upload_failed' })))
      xhr.onerror = () => reject(new ApiError(0, { reason: 'upload_failed' }))
      xhr.send(file)
    })
    return request<Song>(`${base}/complete`, { method: 'POST' })
  },
}

// ---------- Rehearsals ----------

export type RsvpResponse = 'yes' | 'maybe' | 'no'

export const RSVP_OPTIONS: { value: RsvpResponse; label: string }[] = [
  { value: 'yes', label: 'Going' },
  { value: 'maybe', label: 'Maybe' },
  { value: 'no', label: "Can't go" },
]

export interface Rehearsal {
  id: string
  start: string
  end: string | null
  venue: string
  notes: string | null
  groups: string[]
  songs: {
    id: string
    title: string
    status: SongStatus
    myPart: Part | null
    myState: LearnState
    hasMyTrack: boolean
  }[]
  myRsvp: RsvpResponse | null
  rsvpOpen: boolean
  counts: { yes: number; maybe: number; no: number; noReply: number }
  attendees: { memberId: string; name: string; part: Part | null; response: RsvpResponse | null }[] | null
  songParts: { songId: string; title: string; parts: Record<string, { yes: number; maybe: number }> }[] | null
}

export interface RehearsalInput {
  start?: string
  end?: string | null
  venue?: string
  notes?: string | null
  songIds?: string[]
  groups?: string[]
}

export const rehearsalsApi = {
  list: (when: 'upcoming' | 'past' = 'upcoming', scope: 'mine' | 'all' = 'mine') =>
    request<Rehearsal[]>(`/api/rehearsals?when=${when}&scope=${scope}`),
  get: (id: string) => request<Rehearsal>(`/api/rehearsals/${encodeURIComponent(id)}`),
  create: (body: RehearsalInput) => request<Rehearsal>('/api/rehearsals', { method: 'POST', body }),
  update: (id: string, body: RehearsalInput) =>
    request<Rehearsal>(`/api/rehearsals/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/api/rehearsals/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  rsvp: (id: string, response: RsvpResponse | null) =>
    request<Rehearsal>(`/api/rehearsals/${encodeURIComponent(id)}/rsvp`, { method: 'PUT', body: { response } }),
}

const UK = 'Europe/London'

/** "Tue 30 Sep, 7:00 pm to 9:00 pm" in UK time. */
export function formatWhen(start: string, end: string | null): string {
  const day = new Date(start).toLocaleDateString('en-GB', { weekday: 'short', day: 'numeric', month: 'short', timeZone: UK })
  const time = (iso: string) =>
    new Date(iso).toLocaleTimeString('en-GB', { hour: 'numeric', minute: '2-digit', hour12: true, timeZone: UK })
  return end ? `${day}, ${time(start)} to ${time(end)}` : `${day}, ${time(start)}`
}

export const groupsApi = {
  list: () => request<Group[]>('/api/groups'),
  create: (name: string, admin = false) => request<Group>('/api/groups', { method: 'POST', body: { name, admin } }),
  update: (id: string, body: { name?: string; admin?: boolean }) =>
    request<Group>(`/api/groups/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/api/groups/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  setMembers: (id: string, memberIds: string[]) =>
    request<Group>(`/api/groups/${encodeURIComponent(id)}/members`, { method: 'PUT', body: { memberIds } }),
}

// ---------- Feedback and your data ----------

export interface FeedbackItem {
  id: string
  memberId: string
  name: string
  email: string
  message: string
  page: string | null
  status: 'new' | 'done'
  createdAt: string
}

export const feedbackApi = {
  send: (message: string, page: string | null) =>
    request<FeedbackItem>('/api/feedback', { method: 'POST', body: { message, page } }),
  list: () => request<FeedbackItem[]>('/api/feedback'),
  setStatus: (id: string, status: 'new' | 'done') =>
    request<FeedbackItem>(`/api/feedback/${encodeURIComponent(id)}`, { method: 'PATCH', body: { status } }),
  remove: (id: string) => request<void>(`/api/feedback/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

export const accountApi = {
  exportData: () => request<Record<string, unknown>>('/api/me/export'),
  deleteAccount: () => request<void>('/api/me', { method: 'DELETE' }),
}

export const PRIVACY_CONTACT = 'barbershopsingingsociety@gmail.com'

export const signInUrl = '/.auth/login/google?post_login_redirect_uri=/'
export const signOutUrl = '/.auth/logout?post_logout_redirect_uri=/'
