import type { ProductStatus } from '../api/endpoints';
import { toPersianDigits, toPersianOrdinal } from '../theme';

type AccessKind = 'purchase' | 'gift' | 'subscription' | 'staff' | 'editor' | null;

/** The one label a book's open access shows, on the shelf and on the book page alike. */
export function accessLabel(book: { owned: boolean; access?: AccessKind; is_published?: boolean }): string | null {
  if (!book.owned && book.access !== 'editor') return null;
  if (book.access === 'editor') return 'دوره اختصاصی';
  if (book.access === 'subscription') return 'با اشتراک';
  if (book.access === 'staff') return 'دسترسی مدیر';
  if (book.access === 'gift') return 'دوره اختصاصی';
  return 'خریداری شده';
}

export type ShelfLabel = { text: string; kind: 'soon' | 'access' | 'free' | 'planning' | 'locked' };

/**
 * Exactly one cover label from the API's explicit product state. A free preview never changes the whole-book state.
 */
export function shelfLabel(book: {
  owned: boolean;
  access?: AccessKind;
  product_status: ProductStatus;
  free_chapter: number | null;
  free_chapters?: number;
  partial_free_chapter?: number | null;
}): ShelfLabel {
  const status = book.product_status;
  if (status.state === 'coming_soon') return { text: 'به‌زودی', kind: 'soon' };
  const access = accessLabel(book);
  if (access) return { text: access, kind: 'access' };
  if (status.state === 'free') return { text: 'کل کتاب رایگان', kind: 'free' };
  if (status.preview === 'sample') {
    const n = book.free_chapters ?? (book.free_chapter ? 1 : 0);
    if (n === 1 && book.free_chapter) return { text: `فصل ${toPersianOrdinal(book.free_chapter)} رایگان`, kind: 'free' };
    if (n > 1) return { text: `${toPersianDigits(n)} فصل رایگان`, kind: 'free' };
    if (book.partial_free_chapter) return { text: `بخشی از فصل ${toPersianDigits(book.partial_free_chapter)} رایگان`, kind: 'free' };
    return { text: 'بخشی رایگان', kind: 'free' };
  }
  if (status.state === 'preparing') return { text: 'در حال برنامه‌ریزی', kind: 'planning' };
  if (status.state === 'unpriced') return { text: 'قیمت تعیین نشده', kind: 'locked' };
  if (status.state === 'unavailable') return { text: 'در دسترس نیست', kind: 'locked' };
  return { text: 'نسخه‌ی کامل', kind: 'locked' };
}
