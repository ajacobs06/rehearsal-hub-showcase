export type Part = 'tenor' | 'lead' | 'bari' | 'bass'
export type Role = 'member' | 'admin' | 'owner'

export interface Member {
  id: string
  email: string
  name: string
  part: Part | null
  role: Role
  status: 'invited' | 'active'
  createdAt: string
}

export interface InviteRequest {
  email: string
  name: string
  part: Part | null
  role: Role
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
  updateMember: (id: string, body: { name?: string; part?: Part | null; role?: Role }) =>
    request<Member>(`/api/members/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  deleteMember: (id: string) => request<void>(`/api/members/${encodeURIComponent(id)}`, { method: 'DELETE' }),
}

// ---------- Songs ----------

export type SongStatus = 'learning' | 'performing' | 'retired'
export type FileKind = Part | 'full' | 'score'

export interface Song {
  id: string
  title: string
  arranger: string | null
  key: string | null
  status: SongStatus
  files: Partial<Record<FileKind, { size: number; uploadedAt: string }>>
  createdAt: string
}

export interface SongInput {
  title?: string
  arranger?: string | null
  key?: string | null
  status?: SongStatus
}

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
  list: () => request<Song[]>('/api/songs'),
  get: (id: string) => request<Song>(`/api/songs/${encodeURIComponent(id)}`),
  create: (body: SongInput) => request<Song>('/api/songs', { method: 'POST', body }),
  update: (id: string, body: SongInput) =>
    request<Song>(`/api/songs/${encodeURIComponent(id)}`, { method: 'PATCH', body }),
  remove: (id: string) => request<void>(`/api/songs/${encodeURIComponent(id)}`, { method: 'DELETE' }),
  fileLink: (id: string, kind: FileKind, download = false) =>
    request<FileLink>(`/api/songs/${encodeURIComponent(id)}/files/${kind}${download ? '?download=true' : ''}`),
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

export const signInUrl = '/.auth/login/google?post_login_redirect_uri=/'
export const signOutUrl = '/.auth/logout?post_logout_redirect_uri=/'
