import { useCallback, useEffect, useRef, useState } from 'react'
import { songsApi, type FileKind } from './api'

const ARTWORK: MediaImage[] = [
  { src: '/icon-192.png', sizes: '192x192', type: 'image/png' },
  { src: '/bss-logo.png', sizes: '500x500', type: 'image/png' },
]
const SKIP_SECONDS = 10

// The lock screen and notification controls drive one track: the one that last started playing.
let lockScreenOwner: HTMLAudioElement | null = null

function seek(el: HTMLAudioElement, to: number) {
  el.currentTime = Math.max(0, Number.isFinite(el.duration) ? Math.min(to, el.duration) : to)
}

function claimLockScreen(el: HTMLAudioElement, title: string, label: string) {
  if (!('mediaSession' in navigator)) return
  const session = navigator.mediaSession
  lockScreenOwner = el
  session.metadata = new MediaMetadata({ title, artist: label, album: 'Rehearsal Hub', artwork: ARTWORK })
  const handlers: [MediaSessionAction, MediaSessionActionHandler][] = [
    ['play', () => void el.play().catch(() => undefined)],
    ['pause', () => el.pause()],
    ['seekbackward', (d) => seek(el, el.currentTime - (d.seekOffset ?? SKIP_SECONDS))],
    ['seekforward', (d) => seek(el, el.currentTime + (d.seekOffset ?? SKIP_SECONDS))],
    ['seekto', (d) => d.seekTime !== undefined && seek(el, d.seekTime)],
  ]
  for (const [action, handler] of handlers) {
    try {
      session.setActionHandler(action, handler)
    } catch {
      // This browser doesn't offer that control.
    }
  }
}

function releaseLockScreen(el: HTMLAudioElement) {
  if (lockScreenOwner !== el || !('mediaSession' in navigator)) return
  lockScreenOwner = null
  const session = navigator.mediaSession
  session.metadata = null
  session.playbackState = 'none'
  for (const action of ['play', 'pause', 'seekbackward', 'seekforward', 'seekto'] as const) {
    try {
      session.setActionHandler(action, null)
    } catch {
      // Never set, so nothing to clear.
    }
  }
}

/** Keeps the lock screen's progress bar in step with this track, when it owns the lock screen. */
function syncLockScreen(el: HTMLAudioElement) {
  if (lockScreenOwner !== el) return
  const session = navigator.mediaSession
  session.playbackState = el.paused ? 'paused' : 'playing'
  if (!Number.isFinite(el.duration)) return
  try {
    session.setPositionState({
      duration: el.duration,
      position: Math.min(el.currentTime, el.duration),
      playbackRate: el.playbackRate,
    })
  } catch {
    // Not supported, or mid-way through loading a refreshed link (the next event sets it).
  }
}

/**
 * Streams one track straight from Blob Storage. Links expire after 15 minutes, so when one is
 * about to expire (or playback fails because it has), fetch a fresh link and resume in place.
 * While playing it also shows on the phone's lock screen, which keeps working across a refresh
 * because the refresh swaps the source of the same audio element.
 */
export default function Player({
  songId,
  title,
  kind,
  label,
}: {
  songId: string
  title: string
  kind: FileKind
  label: string
}) {
  const audio = useRef<HTMLAudioElement>(null)
  const expiresAt = useRef(0)
  const retries = useRef(0)
  const [failed, setFailed] = useState(false)

  const fail = useCallback(() => {
    if (audio.current) releaseLockScreen(audio.current)
    setFailed(true)
  }, [])

  const attach = useCallback(
    async (resumeAt = 0, play = false) => {
      const link = await songsApi.fileLink(songId, kind)
      const el = audio.current
      if (!el) return
      expiresAt.current = Date.parse(link.expiresAt)
      el.src = link.url
      if (resumeAt > 0) {
        el.addEventListener('loadedmetadata', () => (el.currentTime = resumeAt), { once: true })
      }
      if (play) el.play().catch(() => undefined)
    },
    [songId, kind],
  )

  useEffect(() => {
    attach().catch(fail)
  }, [attach, fail])

  useEffect(() => {
    const el = audio.current
    return () => {
      if (el) releaseLockScreen(el)
    }
  }, [])

  function refreshInPlace() {
    const el = audio.current
    if (!el) return
    attach(el.currentTime, true).catch(fail)
  }

  function onPlay() {
    const el = audio.current
    if (el) claimLockScreen(el, title, label)
    if (expiresAt.current - Date.now() < 60_000) refreshInPlace()
  }

  function onSync() {
    if (audio.current) syncLockScreen(audio.current)
  }

  function onError() {
    if (retries.current >= 2) return fail()
    retries.current += 1
    refreshInPlace()
  }

  if (failed) return <p className="error small">Couldn't load the {label} track. Refresh the page to try again.</p>

  return (
    <audio
      ref={audio}
      className="player"
      controls
      preload="metadata"
      aria-label={`${label} track`}
      onPlay={onPlay}
      onError={onError}
      onPlaying={() => {
        retries.current = 0
        onSync()
      }}
      onPause={onSync}
      onSeeked={onSync}
      onRateChange={onSync}
      onLoadedMetadata={onSync}
      onDurationChange={onSync}
    />
  )
}
