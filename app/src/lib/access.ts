import { toPersianDigits } from '../theme';

type AccessKind = 'purchase' | 'gift' | 'subscription' | 'staff' | null;

/** The one label a book's open access shows, on the shelf and on the book page alike. */
export function accessLabel(book: { owned: boolean; access?: AccessKind }): string | null {
  if (!book.owned) return null;
  if (book.access === 'subscription') return 'با اشتراک';
  if (book.access === 'staff') return 'دسترسی مدیر';
  if (book.access === 'gift') return 'هدیه';
  return 'خریداری شده';
}

export type ShelfLabel = { text: string; kind: 'soon' | 'access' | 'free' | 'locked' };

/**
 * Exactly one label per book on the shelf, from the book's real state. The first that applies wins:
 * coming soon, the reader's own access, the whole book free, n free chapters, some free sections, or a lock.
 */
export function shelfLabel(book: {
  owned: boolean;
  access?: AccessKind;
  is_coming_soon: boolean;
  free_chapter: number | null;
  free_chapters?: number;
  all_free?: boolean;
  has_free_part: boolean;
}): ShelfLabel {
  if (book.is_coming_soon) return { text: 'به‌زودی', kind: 'soon' };
  const access = accessLabel(book);
  if (access) return { text: access, kind: 'access' };
  if (book.all_free) return { text: 'کل کتاب رایگان', kind: 'free' };
  const n = book.free_chapters ?? (book.free_chapter ? 1 : 0);
  if (n === 1 && book.free_chapter) return { text: `فصل ${toPersianDigits(book.free_chapter)} رایگان`, kind: 'free' };
  if (n > 1) return { text: `${toPersianDigits(n)} فصل رایگان`, kind: 'free' };
  if (book.has_free_part) return { text: 'بخشی رایگان', kind: 'free' };
  return { text: 'نسخه‌ی کامل', kind: 'locked' };
}
