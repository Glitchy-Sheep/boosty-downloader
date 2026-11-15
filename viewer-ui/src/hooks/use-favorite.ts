import { usePostMarks } from '@/hooks/use-post-marks'

/** Share the page heart with other views without replacing the retained post detail. */
export function useFavorite(author: string, postId: string) {
  return usePostMarks(author, postId).favorite
}
