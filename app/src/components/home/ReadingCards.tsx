/** «ادامه‌ی خواندن»: one card per book being read, all the same size, side by side. A finished section opens the next
 * one; at the end of a chapter the card says so and starts the next chapter (or, if it is locked, opens the book). */
import { router } from 'expo-router';
import { Pressable, StyleSheet, View, useWindowDimensions } from 'react-native';

import type { BookListItem } from '../../api/endpoints';
import { colors, rtl, toPersianDigits } from '../../theme';
import { BookCover } from '../BookCover';
import { useAppearance } from '../../lib/coverTheme';
import { LemonProgress } from '../LemonProgress';
import { WIDE } from '../../lib/layout';
import { GlideText } from '../GlideText';
import { LemonSlice } from '../LemonSlice';
import { Text } from '../Text';
import { HRow } from './HRow';

export type ReadingNext = {
  id: number;
  title: string;
  locked: boolean;
  new_chapter: boolean;
  chapter_title: string;
  chapter_number: number | null;
  finished_chapter_number: number | null;
};
export type ReadingItem = {
  slug: string;
  bookTitle: string;
  id: number;
  title: string;
  book?: BookListItem;
  next?: ReadingNext | null;
  chapter?: { number: number | null; title: string } | null;
};

/** One wedge per section of the book, as everywhere else (LemonProgress groups them past 24). */
function wedges(progress: number | null | undefined, sections: number) {
  const n = Math.max(1, sections || 1);
  const done = Math.round((progress ?? 0) * n);
  return Array.from({ length: n }, (_, i) => (i < done ? ('done' as const) : ('empty' as const)));
}

export function ReadingCards({ items }: { items: ReadingItem[] }) {
  const { width } = useWindowDimensions();
  // One book on a computer: the card fills the row (up to a comfortable width) instead of half of it.
  if (items.length === 1 && width >= WIDE) {
    return (
      <View style={{ paddingHorizontal: 16 }}>
        <Card r={items[0]} width={undefined} />
      </View>
    );
  }
  const cardW = items.length > 1 ? Math.min(Math.round(Math.min(width, 760) * 0.82), 420) : Math.min(width, 760) - 32;
  return <HRow data={items} keyOf={(r) => r.slug} render={(r) => <Card r={r} width={cardW} />} initial={2} />;
}

function Card({ r, width }: { r: ReadingItem; width: number | undefined }) {
  const light = useAppearance() === 'light';
  const fa = (n: number | null | undefined) => (n ? toPersianDigits(n) : '');
  const next = r.next;
  let label = ''; // the section's own title already says «ادامه‌ی خواندن»
  let sub = r.title;
  let button = 'ادامه بده';
  let open = () => router.push({ pathname: '/section/[id]', params: { id: String(r.id), resume: '1' } });
  if (next?.new_chapter) {
    label = `فصل ${fa(next.finished_chapter_number)} تمام شد`.replace('  ', ' ');
    if (next.locked) {
      sub = `فصل بعد، «${next.chapter_title}»، در نسخه‌ی کامل است`;
      button = 'باز کردن کتاب';
      open = () => router.push(`/book/${r.slug}`);
    } else {
      sub = `شروع فصل ${fa(next.chapter_number)} «${next.chapter_title}»`;
      button = 'شروع فصل بعد';
      open = () => router.push({ pathname: '/section/[id]', params: { id: String(next.id) } });
    }
  } else if (next && !next.locked) {
    sub = next.title;
    open = () => router.push({ pathname: '/section/[id]', params: { id: String(next.id) } });
  }
  // «فصل ۳: مشتق» above the section's name (not at a chapter's end, which says so itself).
  const chapter = !next?.new_chapter && r.chapter ? `فصل ${fa(r.chapter.number)}: ${r.chapter.title}`.replace('فصل : ', '') : '';
  const parts = r.book?.progress != null ? wedges(r.book.progress, r.book.section_count) : null;
  return (
    <Pressable onPress={open} style={[styles.card, light && styles.cardLight, width ? { width } : { maxWidth: 1100 }]} accessibilityRole="button" accessibilityLabel={`${r.bookTitle}، ${sub}`}>
      {r.book ? (
        <BookCover book={r.book} major={r.book.major ?? null} width={64} />
      ) : (
        <View style={[styles.blank, light && styles.blankLight]}>
          <LemonSlice size={52} />
        </View>
      )}
      <View style={{ flex: 1, gap: 3 }}>
        {!!label && <Text style={[styles.label, light && { color: '#8A6A00' }, rtl]} numberOfLines={1}>{label}</Text>}
        <GlideText style={[styles.title, light && { color: colors.ink }, rtl]}>{r.bookTitle}</GlideText>
        {!!chapter && <Text style={[styles.chapter, light && { color: colors.ink }, rtl]} numberOfLines={1}>{chapter}</Text>}
        <Text style={[styles.sub, light && { color: colors.muted }, rtl]} numberOfLines={2}>{sub}</Text>
        {/* The button, and beside it the lemon: one wedge per section, filled as they are read. */}
        <View style={styles.bottom}>
          <View style={styles.pill}>
            <Text style={styles.pillText}>{button}</Text>
          </View>
          {parts && (
            <View style={styles.progress}>
              <Text style={[styles.count, light && { color: colors.muted }]}>
                {toPersianDigits(parts.filter((p) => p === 'done').length)} از {toPersianDigits(parts.length)}
              </Text>
              <LemonProgress parts={parts} size={34} />
            </View>
          )}
        </View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, backgroundColor: colors.ink, borderRadius: 18, padding: 14, minHeight: 128 },
  cardLight: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line },
  blankLight: { backgroundColor: '#F4F0E3' },
  blank: { width: 64, height: 96, borderRadius: 10, backgroundColor: '#24302A', alignItems: 'center', justifyContent: 'center' },
  label: { fontSize: 11, fontWeight: '800', color: colors.lemon },
  title: { fontSize: 15, fontWeight: '900', color: '#FFFFFF' },
  sub: { fontSize: 12, color: '#A9B6AD', lineHeight: 19 },
  chapter: { fontSize: 12, fontWeight: '700', color: '#DCE5DF' },
  bottom: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', marginTop: 4 },
  progress: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
  count: { fontSize: 11, color: '#A9B6AD' },
  pill: { backgroundColor: colors.lemon, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 5 },
  pillText: { fontSize: 12, fontWeight: '800', color: colors.ink },
});
