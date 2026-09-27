import { Fragment, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { announcementsApi, formatDay, type Announcement } from './api'
import { ForGroups, internalLink } from './Rehearsals'

type Navigate = (to: string) => void

// Only http(s) links become clickable; trailing punctuation stays text ("see https://x.org.").
const URL_RE = /(https?:\/\/[^\s<]+[^\s<.,:;!?)\]'"])/g

function Linked({ text }: { text: string }) {
  return (
    <>
      {text.split(URL_RE).map((part, i) =>
        i % 2 === 1 ? (
          <a key={i} href={part} target="_blank" rel="noreferrer">
            {part}
          </a>
        ) : (
          <Fragment key={i}>{part}</Fragment>
        ),
      )}
    </>
  )
}

function Paragraphs({ text }: { text: string }) {
  return (
    <>
      {text
        .split(/\n\s*\n/)
        .filter((p) => p.trim())
        .map((p, i) => (
          <p key={i}>
            {p.split('\n').map((line, j) => (
              <Fragment key={j}>
                {j > 0 && <br />}
                <Linked text={line} />
              </Fragment>
            ))}
          </p>
        ))}
    </>
  )
}

/** Plain text: blank lines make paragraphs, single line breaks are kept. */
export function AnnouncementBody({ text }: { text: string }) {
  return (
    <div className="post-body">
      <Paragraphs text={text} />
    </div>
  )
}

/** Home: the post cut to 10 lines with an ellipsis; `more` shows only when something was cut. */
function AnnouncementPreview({ text, more }: { text: string; more: ReactNode }) {
  const ref = useRef<HTMLDivElement>(null)
  const [cut, setCut] = useState(false)

  useLayoutEffect(() => {
    const el = ref.current
    if (!el) return
    const check = () => setCut(el.scrollHeight > el.clientHeight + 1)
    check()
    const observer = new ResizeObserver(check)
    observer.observe(el)
    return () => observer.disconnect()
  }, [text])

  return (
    <>
      <div ref={ref} className="post-body clamp">
        <Paragraphs text={text} />
      </div>
      {cut && more}
    </>
  )
}

export function byline(a: Announcement): string {
  return `${formatDay(a.createdAt)} by ${a.authorName ?? 'Committee'}${a.updatedAt ? ' (edited)' : ''}`
}

function Post({ a, navigate, titleLink = true }: { a: Announcement; navigate: Navigate; titleLink?: boolean }) {
  return (
    <article className="post">
      <h2>{titleLink ? <a {...internalLink(`/announcements/${a.id}`, navigate)}>{a.title}</a> : a.title}</h2>
      <div>
        <p className="muted small">{byline(a)}</p>
        <ForGroups ids={a.groups} />
      </div>
      <AnnouncementBody text={a.body} />
    </article>
  )
}

/** Every announcement you can see, newest first, in full. */
export function AnnouncementsPage({ navigate }: { navigate: Navigate }) {
  const [list, setList] = useState<Announcement[] | null>(null)
  const [error, setError] = useState(false)

  useEffect(() => {
    announcementsApi
      .list()
      .then(setList)
      .catch(() => setError(true))
  }, [])

  return (
    <>
      <h1>Announcements</h1>
      {error ? (
        <p className="error">Couldn't load announcements. Refresh the page to try again.</p>
      ) : list === null ? (
        <div className="panel">
          <div className="skeleton skeleton-line" />
          <div className="skeleton skeleton-line short" />
        </div>
      ) : list.length === 0 ? (
        <p className="muted">No announcements yet. News from the committee will appear here.</p>
      ) : (
        <div className="posts">
          {list.map((a) => (
            <Post key={a.id} a={a} navigate={navigate} />
          ))}
        </div>
      )}
    </>
  )
}

/** One announcement, for links from Home. */
export function AnnouncementPage({ id, navigate }: { id: string; navigate: Navigate }) {
  const [a, setA] = useState<Announcement | null>(null)
  const [missing, setMissing] = useState(false)

  useEffect(() => {
    announcementsApi
      .get(id)
      .then(setA)
      .catch(() => setMissing(true))
  }, [id])

  return (
    <>
      <a className="back" {...internalLink('/announcements', navigate)}>
        All announcements
      </a>
      {missing ? (
        <p className="muted">That announcement doesn't exist any more.</p>
      ) : a === null ? (
        <div className="skeleton skeleton-title" />
      ) : (
        <div className="posts">
          <Post a={a} navigate={navigate} titleLink={false} />
        </div>
      )}
    </>
  )
}

/** Home: the newest announcement, if there is one. */
export function LatestAnnouncement({ navigate }: { navigate: Navigate }) {
  const [latest, setLatest] = useState<Announcement | null | undefined>(undefined)

  useEffect(() => {
    announcementsApi
      .list('mine', 1)
      .then((list) => setLatest(list[0] ?? null))
      .catch(() => setLatest(null))
  }, [])

  if (latest === undefined)
    return (
      <div className="panel">
        <div className="skeleton skeleton-line" />
        <div className="skeleton skeleton-line short" />
      </div>
    )
  // Nothing posted yet: Home stays short rather than showing an empty box.
  if (latest === null) return null

  return (
    <section className="stack">
      <div className="row">
        <h2>Latest news</h2>
        <a className="small text-link" {...internalLink('/announcements', navigate)}>
          All announcements
        </a>
      </div>
      <article className="panel post-card">
        <h3>
          <a {...internalLink(`/announcements/${latest.id}`, navigate)}>{latest.title}</a>
        </h3>
        <p className="muted small">{byline(latest)}</p>
        <AnnouncementPreview
          text={latest.body}
          more={
            <a className="small text-link" {...internalLink(`/announcements/${latest.id}`, navigate)}>
              Read more
            </a>
          }
        />
      </article>
    </section>
  )
}
