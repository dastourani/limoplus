/**
 * On a computer, beside the text: the chapter's sections (finished ones ticked, the one being read lit) and
 * the chapter's practice, exam, flashcards and boxes. Tapping the book title opens the book page; tapping a section
 * opens it in place. (The chapter's progress lemon sits in the top bar of the section screen.)
 */
import { router } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { endpoints, type BookDetail } from '../api/endpoints';
import { useApi } from '../lib/useApi';
import { colors, radius, rtl, toPersianDigits } from '../theme';
import { Icon } from './Icon';
import { Text } from './Text';

export function ChapterSide({
  bookSlug,
  nodeId,
  dark = false,
  book: passedBook,
  readHere = false,
}: {
  bookSlug: string;
  nodeId: number;
  dark?: boolean;
  book?: BookDetail | null;
  readHere?: boolean;
}) {
  const { data: fetched } = useApi(() => (passedBook !== undefined ? Promise.resolve(passedBook) : endpoints.book(bookSlug)), [bookSlug, passedBook]);
  const data = passedBook !== undefined ? passedBook : fetched;
  if (!data) return <View style={[styles.side, dark && styles.sideDark]} />;
  const chapter = data.chapters.find((c) => c.id === nodeId || c.sections.some((s) => s.id === nodeId));
  if (!chapter) return <View style={[styles.side, dark && styles.sideDark]} />;
  const done = new Set(data.done_ids);
  const read = new Set(data.read_ids ?? []);
  if (readHere) read.add(nodeId);
  const number = data.chapters.indexOf(chapter) + 1;
  const ink = dark ? '#E4E9E2' : colors.ink;
  const rows = [
    ...(chapter.has_overview ? [{ id: chapter.id, title: 'مقدمه‌ی فصل', locked: !!chapter.is_locked }] : []),
    ...chapter.sections.map((s) => ({ id: s.id, title: s.title, locked: !!s.is_locked })),
  ];
  return (
    <View style={[styles.side, dark && styles.sideDark]}>
      <ScrollView contentContainerStyle={{ padding: 16, gap: 4 }}>
        <Pressable
          onPress={() => router.push(`/book/${data.slug}`)}
          style={styles.bookLink}
          accessibilityRole="button"
          accessibilityLabel={`صفحه‌ی کتاب ${data.title}`}
        >
          <Text style={[styles.book, rtl]} numberOfLines={1}>{data.title} ←</Text>
        </Pressable>
        <Text style={[styles.chapter, rtl, { color: ink, marginBottom: 8 }]}>فصل {toPersianDigits(number)}، {chapter.title}</Text>
        {rows.map((r) => {
          const on = r.id === nodeId;
          return (
            <Pressable
              key={r.id}
              onPress={() => !on && (r.locked ? router.push(`/book/${data.slug}`) : router.replace(`/section/${r.id}`))}
              style={[styles.row, on && styles.rowOn]}
              accessibilityRole="button"
              accessibilityState={{ selected: on }}
            >
              {r.locked ? (
                <Icon name="lock" size={16} color={colors.muted} />
              ) : done.has(r.id) ? (
                <Icon name="circle-check" size={16} color={colors.green} />
              ) : (
                <View style={[styles.dot, read.has(r.id) && { borderColor: colors.lemon, backgroundColor: colors.lemonSoft }]} />
              )}
              <Text style={[styles.rowText, rtl, { color: on ? colors.ink : ink }, on && { fontWeight: '900' }]} numberOfLines={2}>
                {r.title}
              </Text>
            </Pressable>
          );
        })}
        <View style={styles.actions}>
          {[
            ['تمرین کل فصل', () => router.push(`/quiz/${chapter.id}`)],
            ['آزمون', () => router.push(`/exam/${chapter.id}`)],
            ['فلش‌کارت', () => router.push(`/flashcards/${chapter.id}`)],
            ['کادرها', () => router.push({ pathname: '/boxes/[nodeId]', params: { nodeId: String(chapter.id) } })],
          ].map(([label, go]) => (
            <Pressable key={label as string} onPress={go as () => void} style={[styles.action, dark && { backgroundColor: '#26302A' }]} accessibilityRole="button">
              <Text style={[styles.actionText, { color: ink }]}>{label as string}</Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  side: { width: 290, borderLeftWidth: 1, borderLeftColor: colors.line, backgroundColor: colors.surface },
  sideDark: { backgroundColor: '#161E19', borderLeftColor: '#26302A' },
  bookLink: { alignSelf: 'flex-end', paddingVertical: 2 },
  book: { fontSize: 12, fontWeight: '700', color: colors.greenDark },
  chapter: { fontSize: 17, fontWeight: '900', lineHeight: 26 },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 12, paddingVertical: 10, borderRadius: radius.sm },
  rowOn: { backgroundColor: colors.lemonSoft },
  rowText: { flex: 1, fontSize: 14 },
  dot: { width: 16, height: 16, borderRadius: 8, borderWidth: 1.5, borderColor: colors.line },
  actions: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8, marginTop: 14 },
  action: { flexGrow: 1, flexBasis: '45%', backgroundColor: colors.ground, borderRadius: 12, paddingVertical: 10, alignItems: 'center' },
  actionText: { fontSize: 13, fontWeight: '700' },
});
