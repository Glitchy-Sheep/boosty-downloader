/** Native play does not bubble, including media rendered inside saved post HTML. */
export function attachPlaybackExclusivity(root: Document): () => void {
  const onPlay = (event: Event): void => {
    if (!(event.target instanceof HTMLMediaElement)) return
    for (const element of root.querySelectorAll<HTMLMediaElement>('video, audio')) {
      if (element !== event.target && !element.paused) element.pause()
    }
  }
  root.addEventListener('play', onPlay, true)
  return () => root.removeEventListener('play', onPlay, true)
}
