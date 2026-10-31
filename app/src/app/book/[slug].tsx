import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints, type NodeSummary } from '../../api/endpoints';
import { Text } from '../../components/Text';
import { useFeedback } from '../../components/Feedback';
import { LemonProgress } from '../../components/LemonProgress';
import { Icon } from '../../components/Icon';
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
  const { confirm } = useFeedback();

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

  return (
    <Screen>
      <Header title={book.title} subtitle="کتاب" />
      <ScrollView contentContainerStyle={styles.page}>
        <View style={styles.hero}>
          <Text style={[styles.heroTitle, rtl]}>{book.title}</Text>
          <Text style={[styles.heroMeta, rtl]}>
            {toPersianDigits(book.chapters.length)} فصل، {toPersianDigits(sections.length)} بخش
          </Text>
          {user && (
            <View style={styles.readRow}>
              <LemonProgress parts={sections.map((x) => (done.has(x.id) ? 'done' : 'empty'))} size={48} />
              <Text style={[styles.heroMeta, rtl, { flex: 1 }]}>
                {toPersianDigits(sections.filter((x) => done.has(x.id)).length)} از {toPersianDigits(sections.length)} بخش خوانده شده؛ هر قاچ یک بخش است.
              </Text>
            </View>
          )}
          {book.owned ? (
            <View style={styles.inline}>
              <Icon name="circle-check" size={18} color="#9BE3B4" />
              <Text style={[styles.owned, rtl]}>نسخه‌ی کامل در دسترس شماست</Text>
            </View>
          ) : book.price ? (
            <Button label={`خرید نسخه‌ی کامل — ${formatToman(book.price)}`} onPress={() => router.push(`/buy/${book.slug}`)} />
          ) : null}
          {offlineSupported && (
            <View style={styles.offlineRow}>
              {offline ? (
                <>
                  <Icon name="download" size={16} color="#C9D0C6" />
                  <Text style={[styles.heroMeta, rtl, { flex: 1 }]}>آفلاین تا {jalaliDate(offline.validUntil)}</Text>
                  <Pressable onPress={download} disabled={downloading}><Text style={styles.link}>{downloading ? '…' : 'به‌روزرسانی'}</Text></Pressable>
                  <Pressable onPress={async () => (await confirm({ title: 'نسخه‌ی آفلاین حذف شود؟', message: 'بعداً می‌توانید دوباره دانلودش کنید.', confirmLabel: 'حذف', destructive: true, icon: 'trash' })) && removeOfflineBook(book.slug).then(() => setOffline(null))}><Text style={styles.link}>حذف</Text></Pressable>
                </>
              ) : (
                <Pressable onPress={download} disabled={downloading} style={styles.offlineBtn}>
                  <View style={styles.inline}>
                    <Icon name="download" size={18} color={colors.ground} />
                    <Text style={styles.offlineText}>{downloading ? 'در حال دانلود…' : 'دانلود برای مطالعه‌ی آفلاین'}</Text>
                  </View>
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
                فصل {toPersianDigits(index + 1)}، {chapter.title}
              </Text>
              {chapter.is_locked ? <Chip label="نسخه‌ی کامل" icon="lock" /> : !book.owned && <Chip label="رایگان" color={colors.greenDark} background={colors.greenSoft} />}
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
      <View style={[styles.check, done && styles.checkOn]}>{done && <Icon name="check" size={13} color="#fff" strokeWidth={3} />}</View>
      <Text style={[styles.sectionTitle, rtl, section.is_locked && { color: colors.muted }]}>{section.title}</Text>
      {section.is_locked ? (
        <Icon name="lock" size={16} color={colors.muted} />
      ) : (
        <Text style={styles.sectionMeta}>{`${toPersianDigits(section.question_count ?? 0)} تست، ${toPersianDigits(section.flashcard_count ?? 0)} کارت`}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 14 },
  hero: { backgroundColor: colors.ink, borderRadius: radius.lg, padding: 18, gap: 10 },
  heroTitle: { fontSize: 22, fontWeight: '800', color: colors.lemon },
  heroMeta: { fontSize: 13, color: '#C9D0C6' },
  readRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12 },
  owned: { color: '#9BE3B4', fontWeight: '800' },
  inline: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
  offlineRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 14 },
  offlineBtn: { borderWidth: 1, borderColor: '#56655B', borderRadius: 999, paddingVertical: 10, paddingHorizontal: 14, flex: 1, alignItems: 'center' },
  offlineText: { color: colors.ground, fontWeight: '700', fontSize: 13 },
  link: { color: colors.lemon, fontWeight: '700', fontSize: 13 },
  chapter: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.line, overflow: 'hidden' },
  chapterHead: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', padding: 16, gap: 8 },
  chapterTitle: { flex: 1, fontSize: 17, fontWeight: '800', color: colors.ink },
  section: { flexDirection: 'row-reverse', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 14, borderTopWidth: 1, borderTopColor: colors.line, gap: 10 },
  check: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.line, alignItems: 'center', justifyContent: 'center' },
  checkOn: { backgroundColor: colors.green, borderColor: colors.green },
  checkMark: { color: '#fff', fontSize: 12, fontWeight: '700' },
  sectionTitle: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.ink },
  sectionMeta: { fontSize: 12, color: colors.muted },
  actions: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: colors.line },
  action: { flex: 1, backgroundColor: colors.ground, borderRadius: 14, paddingVertical: 12, alignItems: 'center' },
  actionText: { fontWeight: '700', color: colors.ink, fontSize: 14 },
});
