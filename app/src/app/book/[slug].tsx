import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints, type NodeSummary } from '../../api/endpoints';
import { Text } from '../../components/Text';
import { Button, Chip, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { jalaliDate } from '../../lib/jalali';
import { offlineBooks, offlineSupported, removeOfflineBook, saveOfflineBook, type OfflineBook } from '../../lib/offline';
import { useApi } from '../../lib/useApi';
import { colors, formatToman, radius, rtl, toPersianDigits } from '../../theme';

export default function Book() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { user } = useAuth();
  const { data, error, loading, retry } = useApi(() => endpoints.book(String(slug)), [slug, user?.id]);
  const [offline, setOffline] = useState<OfflineBook | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [note, setNote] = useState<string | null>(null);

  useFocusEffect(
    useCallback(() => {
      offlineBooks().then((list) => setOffline(list.find((b) => b.slug === slug) ?? null));
    }, [slug]),
  );
  // Coming back from payment or from reading: reload so ownership and read marks are fresh.
  const [focused, setFocused] = useState(0);
  useFocusEffect(useCallback(() => setFocused((n) => n + 1), []));
  useEffect(() => {
    if (focused > 1) retry();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focused]);

  useEffect(() => setNote(null), [slug]);

  const download = async () => {
    if (!requireLogin(user, 'برای دانلود آفلاین وارد شوید.')) return;
    setDownloading(true);
    setNote(null);
    try {
      setOffline(await saveOfflineBook(await endpoints.offline(String(slug))));
      setNote('دانلود شد. بخش‌های در دسترس بدون اینترنت هم باز می‌شوند.');
    } catch (e) {
      setNote(e instanceof ApiError ? e.message : 'دانلود ممکن نشد.');
    } finally {
      setDownloading(false);
    }
  };

  if (loading && !data) return <Screen><Header subtitle="کتاب" /><Loading /></Screen>;
  if (error || !data) return <Screen><Header subtitle="کتاب" /><ErrorState message={error?.message ?? ''} onRetry={retry} /></Screen>;

  const book = data;
  const done = new Set(book.done_ids);
  const sections = book.chapters.flatMap((c) => c.sections);
  const readable = sections.filter((s) => !s.is_locked);
  const percent = sections.length ? Math.round((readable.filter((s) => done.has(s.id)).length / sections.length) * 100) : 0;

  return (
    <Screen>
      <Header title={book.title} subtitle="کتاب" />
      <ScrollView contentContainerStyle={styles.page}>
        <View style={styles.hero}>
          <Text style={[styles.heroTitle, rtl]}>{book.title}</Text>
          <Text style={[styles.heroMeta, rtl]}>
            {toPersianDigits(book.chapters.length)} فصل · {toPersianDigits(sections.length)} بخش
            {user ? ` · ${toPersianDigits(percent)}٪ خوانده‌شده` : ''}
          </Text>
          {user && (
            <View style={styles.track}>
              <View style={[styles.fill, { width: `${percent}%` }]} />
            </View>
          )}
          {book.owned ? (
            <Text style={[styles.owned, rtl]}>✓ نسخه‌ی کامل در دسترس شماست</Text>
          ) : book.price ? (
            <Button label={`خرید نسخه‌ی کامل · ${formatToman(book.price)}`} onPress={() => router.push(`/buy/${book.slug}`)} />
          ) : null}
          {offlineSupported && (
            <View style={styles.offlineRow}>
              {offline ? (
                <>
                  <Text style={[styles.heroMeta, rtl, { flex: 1 }]}>⬇ آفلاین تا {jalaliDate(offline.validUntil)}</Text>
                  <Pressable onPress={download} disabled={downloading}><Text style={styles.link}>{downloading ? '…' : 'به‌روزرسانی'}</Text></Pressable>
                  <Pressable onPress={() => removeOfflineBook(book.slug).then(() => setOffline(null))}><Text style={styles.link}>حذف</Text></Pressable>
                </>
              ) : (
                <Pressable onPress={download} disabled={downloading} style={styles.offlineBtn}>
                  <Text style={styles.offlineText}>{downloading ? 'در حال دانلود…' : '⬇ دانلود برای مطالعه‌ی آفلاین'}</Text>
                </Pressable>
              )}
            </View>
          )}
          {!!note && <Text style={[styles.heroMeta, rtl]}>{note}</Text>}
        </View>

        {book.chapters.map((chapter, index) => (
          <View key={chapter.id} style={styles.chapter}>
            <View style={styles.chapterHead}>
              <Text style={[styles.chapterTitle, rtl]}>
                فصل {toPersianDigits(index + 1)} · {chapter.title}
              </Text>
              {chapter.is_locked ? <Chip label="🔒 نسخه‌ی کامل" /> : !book.owned && <Chip label="رایگان" color={colors.greenDark} background={colors.greenSoft} />}
            </View>
            {chapter.sections.map((section) => (
              <SectionRow key={section.id} section={section} done={done.has(section.id)} />
            ))}
            {!chapter.is_locked && (
              <View style={styles.actions}>
                <Pressable style={styles.action} onPress={() => router.push(`/quiz/${chapter.id}`)}>
                  <Text style={styles.actionText}>تمرین</Text>
                </Pressable>
                <Pressable style={styles.action} onPress={() => router.push(`/exam/${chapter.id}`)}>
                  <Text style={styles.actionText}>آزمون</Text>
                </Pressable>
                <Pressable style={styles.action} onPress={() => router.push(`/flashcards/${chapter.id}`)}>
                  <Text style={styles.actionText}>فلش‌کارت</Text>
                </Pressable>
              </View>
            )}
          </View>
        ))}
      </ScrollView>
    </Screen>
  );
}

function SectionRow({ section, done }: { section: NodeSummary; done: boolean }) {
  return (
    <Pressable
      onPress={() => router.push(`/section/${section.id}`)}
      style={({ pressed }) => [styles.section, pressed && { backgroundColor: colors.ground }]}
      accessibilityRole="button"
    >
      <View style={[styles.check, done && styles.checkOn]}>{done && <Text style={styles.checkMark}>✓</Text>}</View>
      <Text style={[styles.sectionTitle, rtl, section.is_locked && { color: colors.muted }]}>{section.title}</Text>
      <Text style={styles.sectionMeta}>
        {section.is_locked ? '🔒' : `${toPersianDigits(section.question_count ?? 0)} تست · ${toPersianDigits(section.flashcard_count ?? 0)} کارت`}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 14 },
  hero: { backgroundColor: colors.ink, borderRadius: radius.lg, padding: 18, gap: 10 },
  heroTitle: { fontSize: 22, fontWeight: '900', color: colors.lemon },
  heroMeta: { fontSize: 13, color: '#C9D0C6' },
  track: { height: 8, borderRadius: 4, backgroundColor: '#2C3A31', overflow: 'hidden', flexDirection: 'row-reverse' },
  fill: { backgroundColor: colors.lemon, borderRadius: 4 },
  owned: { color: '#9BE3B4', fontWeight: '800' },
  offlineRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 14 },
  offlineBtn: { borderWidth: 1, borderColor: '#56655B', borderRadius: 999, paddingVertical: 10, paddingHorizontal: 14, flex: 1, alignItems: 'center' },
  offlineText: { color: colors.ground, fontWeight: '700', fontSize: 13 },
  link: { color: colors.lemon, fontWeight: '800', fontSize: 13 },
  chapter: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.line, overflow: 'hidden' },
  chapterHead: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', padding: 16, gap: 8 },
  chapterTitle: { flex: 1, fontSize: 17, fontWeight: '900', color: colors.ink },
  section: { flexDirection: 'row-reverse', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 14, borderTopWidth: 1, borderTopColor: colors.line, gap: 10 },
  check: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.line, alignItems: 'center', justifyContent: 'center' },
  checkOn: { backgroundColor: colors.green, borderColor: colors.green },
  checkMark: { color: '#fff', fontSize: 12, fontWeight: '900' },
  sectionTitle: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.ink },
  sectionMeta: { fontSize: 12, color: colors.muted },
  actions: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: colors.line },
  action: { flex: 1, backgroundColor: colors.ground, borderRadius: 14, paddingVertical: 12, alignItems: 'center' },
  actionText: { fontWeight: '800', color: colors.ink, fontSize: 14 },
});
