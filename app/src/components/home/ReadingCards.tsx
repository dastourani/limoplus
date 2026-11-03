/** «ادامه‌ی خواندن»: one card per book being read, all the same size, side by side. A finished section opens the next
 * one; at the end of a chapter the card says so and starts the next chapter (or, if it is locked, opens the book). */
import { router } from 'expo-router';
import { Pressable, StyleSheet, View, useWindowDimensions } from 'react-native';

import type { BookListItem } from '../../api/endpoints';
import { colors, rtl, toPersianDigits } from '../../theme';
import { BookCover } from '../BookCover';
import { useAppearance } from '../../lib/coverTheme';
import { LemonProgress } from '../LemonProgress';
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
export type ReadingItem = { slug: string; bookTitle: string; id: number; title: string; book?: BookListItem; next?: ReadingNext | null };

function wedges(progress: number | null | undefined, sections: number) {
  const n = Math.max(1, Math.min(sections || 8, 12));
  const done = Math.round((progress ?? 0) * n);
  return Array.from({ length: n }, (_, i) => (i < done ? ('done' as const) : ('empty' as const)));
}

export function ReadingCards({ items }: { items: ReadingItem[] }) {
  const { width } = useWindowDimensions();
  const cardW = items.length > 1 ? Math.min(Math.round(Math.min(width, 760) * 0.82), 420) : Math.min(width, 760) - 32;
  return <HRow data={items} keyOf={(r) => r.slug} render={(r) => <Card r={r} width={cardW} />} initial={2} />;
}

function Card({ r, width }: { r: ReadingItem; width: number }) {
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
  return (
    <Pressable onPress={open} style={[styles.card, light && styles.cardLight, { width }]} accessibilityRole="button" accessibilityLabel={`${r.bookTitle}، ${sub}`}>
      {r.book ? (
        <BookCover book={r.book} major={r.book.major ?? null} width={64} />
      ) : (
        <View style={[styles.blank, light && styles.blankLight]}>
          <LemonSlice size={52} />
        </View>
      )}
      <View style={{ flex: 1, gap: 3 }}>
        {!!label && <Text style={[styles.label, light && { color: '#8A6A00' }, rtl]} numberOfLines={1}>{label}</Text>}
        <Text style={[styles.title, light && { color: colors.ink }, rtl]} numberOfLines={1}>{r.bookTitle}</Text>
        <Text style={[styles.sub, light && { color: colors.muted }, rtl]} numberOfLines={2}>{sub}</Text>
        <View style={styles.pill}>
          <Text style={styles.pillText}>{button}</Text>
        </View>
      </View>
      {r.book?.progress != null && <LemonProgress parts={wedges(r.book.progress, r.book.section_count)} size={42} />}
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
  pill: { alignSelf: 'flex-end', marginTop: 4, backgroundColor: colors.lemon, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 5 },
  pillText: { fontSize: 12, fontWeight: '800', color: colors.ink },
});
