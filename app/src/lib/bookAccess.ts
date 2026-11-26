import type { BookDetail, PriceDiscount, ProductStatus } from '../api/endpoints';

export type LockedBookInfo = {
  title?: string;
  price: number | null;
  regular_price?: number | null;
  discount?: PriceDiscount | null;
  product_status: ProductStatus;
  slug?: string;
  single_sale_only?: boolean;
};

export type SectionForbiddenResolution =
  | { kind: 'locked'; book: LockedBookInfo }
  | { kind: 'restricted'; message: string };

export function productStateNote(state?: ProductStatus['state']): string | null {
  if (state === 'coming_soon') return 'این کتاب به‌زودی منتشر می‌شود.';
  if (state === 'preparing') return 'محتوای کتاب هنوز برای مطالعه آماده نشده است.';
  if (state === 'unpriced') return 'قیمت نسخه‌ی کامل هنوز تعیین نشده است؛ خرید مستقیم فعلاً ممکن نیست.';
  if (state === 'unavailable') return 'این کتاب فعلاً برای مطالعه در دسترس نیست.';
  return null;
}

export function lockedCtaLabel(singleSaleOnly?: boolean): 'خرید کتاب' | 'خرید یا اشتراک' {
  return singleSaleOnly ? 'خرید کتاب' : 'خرید یا اشتراک';
}

/**
 * Checks whether `nodeId` belongs to `book` and is currently locked for the viewer.
 * Returns `false` if `nodeId` is unlocked (e.g. buyer or free preview) or absent from `book`.
 */
export function isNodeLockedInBook(book: Pick<BookDetail, 'chapters'>, nodeId: number): boolean {
  for (const chapter of book.chapters) {
    if (chapter.id === nodeId) {
      return Boolean(chapter.is_locked);
    }
    const sec = chapter.sections.find((s) => s.id === nodeId);
    if (sec) {
      return Boolean(sec.is_locked);
    }
  }
  return false;
}

export function lockedPayloadFromBook(
  book: Pick<BookDetail, 'slug' | 'title' | 'price' | 'regular_price' | 'discount' | 'product_status' | 'single_sale_only'>,
): LockedBookInfo {
  return {
    slug: book.slug,
    title: book.title,
    price: book.price,
    regular_price: book.regular_price ?? null,
    discount: book.discount ?? null,
    product_status: book.product_status,
    single_sale_only: book.single_sale_only,
  };
}

/**
 * True only for a 403 whose payload carries no specific server error code (e.g. proxy-stripped
 * HTML/empty 403 where ApiError falls back to `code === 'error'`). Specific server reasons such
 * as `user_inactive` or `device_limit` must never be treated as a locked-book gate.
 */
export function isAmbiguous403(err: { status: number; code: string; data?: Record<string, unknown> }): boolean {
  if (err.status !== 403) return false;
  const serverCode = typeof err.data?.code === 'string' ? err.data.code.trim() : '';
  const effectiveCode = serverCode || err.code.trim();
  return !effectiveCode || effectiveCode === 'error';
}

/**
 * Resolves a 403 error on direct `/section/[id]` entry without ever guessing status or price:
 * - Explicit `code === 'locked'` with server-supplied `book` metadata shows the lock/purchase UI.
 * - An ambiguous 403 (no specific server error code) only shows the lock/purchase UI when fetched
 *   `book` metadata confirms that `nodeId` belongs to `book` and is currently locked for this user.
 * - A 403 with a specific non-locked server code, an unlocked section, an unknown node, or missing
 *   book metadata returns `restricted` with the server's message and Back + Retry instead of a purchase prompt.
 */
export function resolveSectionForbidden(
  err: { status: number; code: string; message?: string; data?: Record<string, unknown> },
  options: { nodeId: number; book?: BookDetail | null },
): SectionForbiddenResolution {
  if (err.code === 'locked') {
    const bookData = err.data?.book as Partial<LockedBookInfo> | undefined;
    if (bookData && bookData.product_status) {
      return {
        kind: 'locked',
        book: {
          title: bookData.title,
          slug: bookData.slug,
          price: bookData.price ?? null,
          regular_price: bookData.regular_price ?? null,
          discount: bookData.discount ?? null,
          product_status: bookData.product_status,
          single_sale_only: bookData.single_sale_only,
        },
      };
    }
    return {
      kind: 'restricted',
      message: err.message || 'اجازه‌ی این کار را ندارید.',
    };
  }

  if (isAmbiguous403(err) && options.book && isNodeLockedInBook(options.book, options.nodeId)) {
    return {
      kind: 'locked',
      book: lockedPayloadFromBook(options.book),
    };
  }

  return {
    kind: 'restricted',
    message: err.message || 'اجازه‌ی این کار را ندارید.',
  };
}

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
