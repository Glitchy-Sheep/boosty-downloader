import { cn } from 'cn'
import { useState, type ReactNode } from 'react'

type AuthorArtworkProps = {
  src: string | null
  className: string
  fallback?: ReactNode
}

/** Decorative artwork keeps its placeholder until the current image loads. */
export function AuthorArtwork({ src, className, fallback = null }: AuthorArtworkProps) {
  if (!src) return fallback
  return <LoadedArtwork key={src} src={src} className={className} fallback={fallback} />
}

function LoadedArtwork({ src, className, fallback }: AuthorArtworkProps & { src: string }) {
  const [loaded, setLoaded] = useState(false)
  const [failed, setFailed] = useState(false)
  if (failed) return fallback

  return (
    <>
      {!loaded && fallback}
      <img
        src={src}
        alt=""
        className={cn(className, !loaded && 'invisible')}
        onLoad={() => setLoaded(true)}
        onError={() => setFailed(true)}
      />
    </>
  )
}
