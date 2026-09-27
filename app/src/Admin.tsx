import type { Member } from './api'
import { AdminAnnouncementDetail, AdminAnnouncementList } from './AdminAnnouncements'
import { AdminRehearsalDetail, AdminRehearsalList } from './AdminRehearsals'
import AdminFeedback from './AdminFeedback'
import { AdminSongDetail, AdminSongList } from './AdminSongs'
import Members from './Members'
import { internalLink } from './Rehearsals'
import Tracker from './Tracker'

const TABS = [
  { key: 'rehearsals', label: 'Rehearsals' },
  { key: 'announcements', label: 'Announcements' },
  { key: 'songs', label: 'Songs' },
  { key: 'members', label: 'Members' },
  { key: 'groups', label: 'Groups' },
  { key: 'tracker', label: 'Tracker' },
  { key: 'feedback', label: 'Feedback' },
] as const

/** Admins and owners only: everything that manages the society lives here. */
export default function Admin({ path, me, navigate }: { path: string; me: Member; navigate: (to: string) => void }) {
  const [, , section = 'rehearsals', id] = path.split('/')
  const tab = TABS.some((t) => t.key === section) ? section : 'rehearsals'

  return (
    <>
      <h1>Admin</h1>
      <nav className="admin-tabs" aria-label="Admin sections">
        {TABS.map((t) => (
          <a key={t.key} aria-current={tab === t.key ? 'page' : undefined} {...internalLink(`/admin/${t.key}`, navigate)}>
            {t.label}
          </a>
        ))}
      </nav>
      {tab === 'rehearsals' &&
        (id ? <AdminRehearsalDetail key={id} id={id} me={me} navigate={navigate} /> : <AdminRehearsalList me={me} navigate={navigate} />)}
      {tab === 'announcements' &&
        (id ? (
          <AdminAnnouncementDetail key={id} id={id} me={me} navigate={navigate} />
        ) : (
          <AdminAnnouncementList me={me} navigate={navigate} />
        ))}
      {tab === 'songs' && (id ? <AdminSongDetail key={id} id={id} navigate={navigate} /> : <AdminSongList navigate={navigate} />)}
      {tab === 'members' && <Members me={me} view="people" />}
      {tab === 'groups' && <Members me={me} view="groups" />}
      {tab === 'tracker' && <Tracker />}
      {tab === 'feedback' && <AdminFeedback />}
    </>
  )
}
