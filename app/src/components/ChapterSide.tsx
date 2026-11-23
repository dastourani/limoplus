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
import { LemonProgress } from './LemonProgress';
import { Text } from './Text';

/**
 * On a computer, beside the book page (/book/[slug]): the book's chapters with their progress lemons and quick links
 * (shares the same column width, border and row style as ChapterSide).
 */
export function BookSide({
  book,
  openId,
  onSelect,
}: {
  book: BookDetail;
  openId: number | null | undefined;
  onSelect: (chapterId: number) => void;
}) {
  const done = new Set(book.done_ids);
  const read = new Set(book.read_ids ?? []);
  return (
    <View style={styles.side}>
      <ScrollView contentContainerStyle={{ padding: 16, gap: 4 }}>
        <Text style={[styles.chapter, rtl, { color: colors.ink, marginBottom: 12, marginTop: 4 }]}>فهرست فصل‌ها</Text>
        {book.chapters.map((ch, idx) => {
          const on = openId === ch.id;
          const parts = ch.sections.map((s) => (done.has(s.id) ? ('done' as const) : read.has(s.id) ? ('soft' as const) : ('empty' as const)));
          return (
            <View key={ch.id} style={{ gap: 2 }}>
              <Pressable
                onPress={() => onSelect(ch.id)}
                style={[styles.row, on && styles.rowOn]}
                accessibilityRole="button"
                accessibilityState={{ selected: on }}
              >
                {ch.is_locked ? (
                  <Icon name="lock" size={16} color={colors.muted} />
                ) : (
                  <LemonProgress parts={parts} size={24} />
                )}
                <Text style={[styles.rowText, rtl, { color: colors.ink }, on && { fontWeight: '900' }]} numberOfLines={2}>
                  فصل {toPersianDigits(idx + 1)}، {ch.title}
                </Text>
                <View style={[styles.chevronMini, on && styles.chevronMiniOn]}>
                  <Icon name={on ? 'chevron-up' : 'chevron-down'} size={13} color={colors.ink} />
                </View>
              </Pressable>

              {/* زیرمنوی درختی بخش‌های فصل در حالت باز */}
              {on && !!ch.sections.length && (
                <View style={styles.subSectionsBox}>
                  {ch.has_overview && (
                    <Pressable
                      onPress={() => router.push(`/section/${ch.id}`)}
                      style={styles.subRow}
                      accessibilityRole="button"
                    >
                      <Icon name="map" size={14} color={colors.greenDark} />
                      <Text style={[styles.subRowText, rtl, { color: colors.greenDark, fontWeight: '700' }]} numberOfLines={2}>مقدمه‌ی فصل</Text>
                    </Pressable>
                  )}
                  {ch.sections.map((sec) => {
                    const isDone = done.has(sec.id);
                    const isRead = read.has(sec.id);
                    return (
                      <Pressable
                        key={sec.id}
                        onPress={() => router.push(`/section/${sec.id}`)}
                        style={styles.subRow}
                        accessibilityRole="button"
                      >
                        {sec.is_locked ? (
                          <Icon name="lock" size={13} color={colors.muted} />
                        ) : isDone ? (
                          <Icon name="circle-check" size={14} color={colors.green} />
                        ) : isRead ? (
                          <View style={styles.lemonSlicePart}>
                            <LemonProgress parts={['soft']} size={14} />
                          </View>
                        ) : (
                          <View style={styles.lemonSlicePart}>
                            <LemonProgress parts={['empty']} size={14} />
                          </View>
                        )}
                        <Text style={[styles.subRowText, rtl, sec.is_locked && { color: colors.muted }]} numberOfLines={2}>
                          {sec.title}
                        </Text>
                      </Pressable>
                    );
                  })}
                </View>
              )}
            </View>
          );
        })}
        <View style={styles.actions}>
          {[
            ...(book.chapters.some((c) => c.flashcard_count || c.sections.some((s) => s.flashcard_count))
              ? [[book.done_card_count ? `مرور کارت‌ها (${toPersianDigits(book.done_card_count)})` : 'مرور کارت‌ها', 'layers', () => router.push({ pathname: '/flashcards/[nodeId]', params: { nodeId: String(book.id), done: '1' } })]]
              : []),
            ['کادرهای کتاب', 'clipboard-list', () => router.push({ pathname: '/boxes/[nodeId]', params: { nodeId: String(book.id) } })],
            ['واژه‌نامه‌ی کتاب', 'languages', () => router.push(`/glossary/${book.slug}`)],
            ...(book.mine?.mistakes.count
              ? [[`اشتباه‌هایم (${toPersianDigits(book.mine.mistakes.count)})`, 'notebook-pen', () => router.push({ pathname: '/mistakes', params: { book: book.slug } })]]
              : []),
          ].map(([label, iconName, go]) => (
            <Pressable key={label as string} onPress={go as () => void} style={styles.action} accessibilityRole="button">
              <Icon name={iconName as any} size={15} color={colors.ink} />
              <Text style={[styles.actionText, { color: colors.ink }]}>{label as string}</Text>
            </Pressable>
          ))}
        </View>
      </ScrollView>
    </View>
  );
}

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
  // What this chapter has to practise, summed by the server. A chapter with none keeps only «کادرها».
  const tests = chapter.question_count ?? 0;
  const cards = chapter.flashcard_count ?? 0;
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
            ...(tests ? [['تمرین کل فصل', () => router.push(`/quiz/${chapter.id}`)]] : []),
            ...(tests ? [['آزمون', () => router.push(`/exam/${chapter.id}`)]] : []),
            ...(cards ? [['فلش‌کارت', () => router.push(`/flashcards/${chapter.id}`)]] : []),
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
  subSectionsBox: { paddingRight: 24, paddingLeft: 8, paddingVertical: 4, gap: 2, borderRightWidth: 2, borderRightColor: colors.lemon, marginRight: 12 },
  subRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, paddingVertical: 5, paddingHorizontal: 6, borderRadius: radius.xs },
  subRowText: { flex: 1, fontSize: 12.5, color: colors.ink, lineHeight: 18 },
  lemonSlicePart: { width: 14, height: 14, alignItems: 'center', justifyContent: 'center' },
  chevronMini: { width: 22, height: 22, borderRadius: 11, backgroundColor: colors.ground, alignItems: 'center', justifyContent: 'center' },
  chevronMiniOn: { backgroundColor: colors.lemon },
  subDot: { width: 8, height: 8, borderRadius: 4, borderWidth: 1, borderColor: colors.line, backgroundColor: 'transparent' },
  subDotRead: { backgroundColor: colors.lemon, borderColor: colors.lemon },
  subDotDone: { backgroundColor: colors.green, borderColor: colors.green },
  side: { width: 290, borderLeftWidth: 1, borderLeftColor: colors.line, backgroundColor: colors.surface },
  sideDark: { backgroundColor: '#161E19', borderLeftColor: '#26302A' },
  bookLink: { alignSelf: 'flex-end', paddingVertical: 2 },
  book: { fontSize: 12, fontWeight: '700', color: colors.muted },
  chapter: { fontSize: 17, fontWeight: '900', lineHeight: 26 },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingHorizontal: 12, paddingVertical: 10, borderRadius: radius.sm },
  rowOn: { backgroundColor: colors.lemonSoft },
  rowText: { flex: 1, fontSize: 14 },
  dot: { width: 16, height: 16, borderRadius: 8, borderWidth: 1.5, borderColor: colors.line },
  actions: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8, marginTop: 14 },
  action: { flexGrow: 1, flexBasis: '45%', flexDirection: 'row-reverse', backgroundColor: colors.ground, borderRadius: 12, paddingVertical: 9, paddingHorizontal: 10, alignItems: 'center', justifyContent: 'center', gap: 6, borderWidth: 1, borderColor: colors.line },
  actionText: { fontSize: 13, fontWeight: '700' },
});
