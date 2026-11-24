import type { BookDetail } from '../api/endpoints';

/**
 * Checks whether a locally remembered section/chapter ID is still present and unlocked
 * in the book's current access state (prevents stale guest/expired history from surfacing locked chapters).
 */
export function isSectionAccessibleInBook(book: Pick<BookDetail, 'chapters'>, nodeId: number): boolean {
  for (const chapter of book.chapters) {
    if (chapter.id === nodeId) {
      return Boolean(chapter.has_overview && !chapter.is_locked);
    }
    const sec = chapter.sections.find((s) => s.id === nodeId);
    if (sec) {
      return !sec.is_locked;
    }
  }
  return false;
}
