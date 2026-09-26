import { useCallback, useEffect, useRef, useState } from 'react'
import { songsApi, type FileKind } from './api'

/**
 * Streams one track straight from Blob Storage. Links expire after 15 minutes, so when one is
 * about to expire (or playback fails because it has), fetch a fresh link and resume in place.
 */
export default function Player({ songId, kind, label }: { songId: string; kind: FileKind; label: string }) {
  const audio = useRef<HTMLAudioElement>(null)
  const expiresAt = useRef(0)
  const retries = useRef(0)
  const [failed, setFailed] = useState(false)

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
    attach().catch(() => setFailed(true))
  }, [attach])

  function refreshInPlace() {
    const el = audio.current
    if (!el) return
    attach(el.currentTime, true).catch(() => setFailed(true))
  }

  function onPlay() {
    if (expiresAt.current - Date.now() < 60_000) refreshInPlace()
  }

  function onError() {
    if (retries.current >= 2) return setFailed(true)
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
      onPlaying={() => (retries.current = 0)}
      onError={onError}
    />
  )
}
