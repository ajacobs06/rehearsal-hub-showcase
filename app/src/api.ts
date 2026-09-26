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

export const signInUrl = '/.auth/login/google?post_login_redirect_uri=/'
export const signOutUrl = '/.auth/logout?post_logout_redirect_uri=/'
