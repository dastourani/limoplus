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

/**
 * Returns the first genuinely readable node ID in the book (an unlocked chapter overview,
 * or the first unlocked section inside any chapter), even when earlier chapters are locked.
 */
export function firstReadableNodeId(book: Pick<BookDetail, 'chapters'>): number | null {
  for (const chapter of book.chapters) {
    if (!chapter.is_locked && chapter.has_overview) {
      return chapter.id;
    }
    const openSection = chapter.sections.find((s) => !s.is_locked);
    if (openSection) {
      return openSection.id;
    }
  }
  return null;
}

export type BookCtaModel =
  | { kind: 'preparing' }
  | {
      kind: 'full';
      targetNodeId: number | null;
      buttonLabel: 'ادامه بده' | 'شروع';
    }
  | {
      kind: 'guest';
      lastTitle: string | null;
      targetNodeId: number | null;
      buttonLabel: 'ادامهٔ مطالعه' | 'شروع مطالعهٔ رایگان' | null;
      showUnlock: boolean;
    };

/**
 * Resolves the hero CTA state for a book screen.
 * Guests on both partially-free and completely-free books get the streamlined
 * «شروع مطالعهٔ رایگان» -> «آخرین مطالعه: «...»» + «ادامهٔ مطالعه» flow,
 * while signed-in or entitled users keep the full progress-lemon card.
 */
export function resolveBookCta(
  book: Pick<BookDetail, 'owned' | 'product_status' | 'chapters'>,
  options: { isAuthenticated: boolean; lastSection: { id: number; title: string } | null },
): BookCtaModel {
  const state = book.product_status.state;
  if (state === 'coming_soon' || state === 'preparing') {
    return { kind: 'preparing' };
  }
  const firstOpenNodeId = firstReadableNodeId(book);
  const fullAccess = book.owned || (options.isAuthenticated && state === 'free');
  if (fullAccess) {
    return {
      kind: 'full',
      targetNodeId: options.lastSection ? options.lastSection.id : firstOpenNodeId,
      buttonLabel: options.lastSection ? 'ادامه بده' : 'شروع',
    };
  }
  const canStartFree = state === 'free' || book.product_status.preview === 'sample';
  const firstFreeNodeId = canStartFree ? firstOpenNodeId : null;
  const targetNodeId = options.lastSection ? options.lastSection.id : firstFreeNodeId;
  const buttonLabel = options.lastSection
    ? 'ادامهٔ مطالعه'
    : firstFreeNodeId != null
      ? 'شروع مطالعهٔ رایگان'
      : null;
  return {
    kind: 'guest',
    lastTitle: options.lastSection?.title ?? null,
    targetNodeId,
    buttonLabel,
    showUnlock: state === 'paid',
  };
}
