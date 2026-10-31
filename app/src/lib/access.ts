/** The one label a book's open access shows, on the shelf and on the book page alike. */
export function accessLabel(book: { owned: boolean; access?: 'purchase' | 'subscription' | 'staff' | null }): string | null {
  if (!book.owned) return null;
  if (book.access === 'subscription') return 'با اشتراک';
  if (book.access === 'staff') return 'دسترسی مدیر';
  return 'خریداری شده';
}
