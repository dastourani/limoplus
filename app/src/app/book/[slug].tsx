import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Animated, LayoutAnimation, Platform, Pressable, ScrollView, StyleSheet, UIManager, View } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints, type ChapterSummary, type NodeSummary } from '../../api/endpoints';
import { Text } from '../../components/Text';
import { useFeedback } from '../../components/Feedback';
import { LemonProgress } from '../../components/LemonProgress';
import { PageTurn } from '../../components/PageTurn';
import { Icon, IconBadge } from '../../components/Icon';
import { Button, Chip, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { jalaliDate } from '../../lib/jalali';
import { offlineBooks, offlineSupported, removeOfflineBook, saveOfflineBook, type OfflineBook } from '../../lib/offline';
import { storage, type LastSection } from '../../lib/storage';
import { useApi } from '../../lib/useApi';

if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) UIManager.setLayoutAnimationEnabledExperimental(true);
import { colors, formatToman, radius, rtl, toPersianDigits } from '../../theme';

export default function Book() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { user } = useAuth();
  const { data, error, loading, retry } = useApi(() => endpoints.book(String(slug)), [slug, user?.id]);
  // Entering a book: its cover opens like a real book (once per visit).
  const { title: titleParam } = useLocalSearchParams<{ title?: string }>();
  const [coverTitle, setCoverTitle] = useState<string | null>(titleParam ?? '');
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

  // The chapter being read is open; the rest stay folded so a long book is a short list.
  const [last, setLast] = useState<LastSection | null>(null);
  const [openId, setOpenId] = useState<number | null | undefined>(undefined);
  useFocusEffect(
    useCallback(() => {
      storage.getLastSection().then((l) => setLast(l && l.bookSlug === slug ? l : null));
    }, [slug]),
  );
  useEffect(() => {
    if (!data || openId !== undefined) return;
    const withLast = last ? data.chapters.find((c) => c.sections.some((x) => x.id === last.id)) : null;
    setOpenId((withLast ?? data.chapters[0])?.id ?? null);
  }, [data, last, openId]);

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

  if (loading && !data)
    return (
      <Screen>
        <Header subtitle="کتاب" />
        {coverTitle !== null ? <View style={[StyleSheet.absoluteFill, { backgroundColor: colors.ink }]} /> : <Loading />}
      </Screen>
    );
  if (error || !data) return <Screen><Header subtitle="کتاب" /><ErrorState message={error?.message ?? ''} onRetry={retry} /></Screen>;

  const book = data;
  const cover = coverTitle !== null ? <PageTurn kind="cover" title={coverTitle || book.title} onDone={() => setCoverTitle(null)} /> : null;
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

        <Pressable onPress={() => router.push(`/glossary/${book.slug}`)} style={styles.glossary} accessibilityRole="button">
          <Icon name="languages" size={18} color={colors.ink} />
          <Text style={styles.glossaryText}>واژه‌نامه‌ی کتاب</Text>
        </Pressable>

        {!!last && (
          <Pressable onPress={() => router.push(`/section/${last.id}`)} style={styles.resume} accessibilityRole="button">
            <IconBadge name="book-open" size={40} />
            <View style={{ flex: 1 }}>
              <Text style={[styles.resumeLabel, rtl]}>ادامه از همین‌جا</Text>
              <Text style={[styles.resumeTitle, rtl]} numberOfLines={1}>{last.title}</Text>
            </View>
            <Icon name="chevron-left" size={22} color={colors.muted} />
          </Pressable>
        )}

        {book.chapters.map((chapter, index) => (
          <ChapterCard
            key={chapter.id}
            chapter={chapter}
            number={index + 1}
            open={openId === chapter.id}
            onToggle={() => {
              LayoutAnimation.configureNext(LayoutAnimation.create(220, 'easeInEaseOut', 'opacity'));
              setOpenId((v) => (v === chapter.id ? null : chapter.id));
            }}
            done={done}
            owned={book.owned}
          />
        ))}
      </ScrollView>
      {cover && <View style={StyleSheet.absoluteFill}>{cover}</View>}
    </Screen>
  );
}

/** One chapter: a single line when closed; sections (under their group headings) and chapter actions when open. */
function ChapterCard({
  chapter,
  number,
  open,
  onToggle,
  done,
  owned,
}: {
  chapter: ChapterSummary;
  number: number;
  open: boolean;
  onToggle: () => void;
  done: Set<number>;
  owned: boolean;
}) {
  const turn = useRef(new Animated.Value(open ? 1 : 0)).current;
  useEffect(() => {
    Animated.spring(turn, { toValue: open ? 1 : 0, friction: 7, tension: 120, useNativeDriver: true }).start();
  }, [open, turn]);
  const tests = chapter.sections.reduce((n, s) => n + (s.question_count ?? 0), 0);
  let lastGroup = '';
  return (
    <View style={styles.chapter}>
      <Pressable onPress={onToggle} style={styles.chapterHead} accessibilityRole="button" accessibilityState={{ expanded: open }}>
        <LemonProgress parts={chapter.sections.map((x) => (done.has(x.id) ? 'done' : 'empty'))} size={38} />
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={[styles.chapterTitle, rtl]}>
            فصل {toPersianDigits(number)}، {chapter.title}
          </Text>
          <Text style={[styles.sectionMeta, rtl]}>
            {toPersianDigits(chapter.sections.length)} بخش{tests ? `، ${toPersianDigits(tests)} تست` : ''}
          </Text>
        </View>
        {chapter.is_locked ? <Chip label="نسخه‌ی کامل" icon="lock" /> : !owned && <Chip label="رایگان" color={colors.greenDark} background={colors.greenSoft} />}
        <Animated.View style={{ transform: [{ rotate: turn.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '-180deg'] }) }] }}>
          <Icon name="chevron-down" size={22} color={colors.muted} />
        </Animated.View>
      </Pressable>
      {open && (
        <>
          {chapter.has_overview && (
            <Pressable onPress={() => router.push(`/section/${chapter.id}`)} style={({ pressed }) => [styles.section, pressed && { backgroundColor: colors.ground }]}>
              <Icon name="map" size={18} color={colors.greenDark} />
              <Text style={[styles.sectionTitle, rtl, { color: colors.greenDark }]}>نمای کلی فصل</Text>
            </Pressable>
          )}
          {chapter.sections.map((section) => {
            const header = section.group && section.group !== lastGroup ? section.group : '';
            if (section.group) lastGroup = section.group;
            return (
              <View key={section.id}>
                {!!header && <Text style={[styles.group, rtl]}>{header}</Text>}
                <SectionRow section={section} done={done.has(section.id)} />
              </View>
            );
          })}
          {!chapter.is_locked && (
            <View style={styles.actions}>
              <Pressable style={styles.action} onPress={() => router.push(`/quiz/${chapter.id}`)}>
                <Text style={styles.actionText}>تمرین کل فصل</Text>
              </Pressable>
              <Pressable style={styles.action} onPress={() => router.push(`/exam/${chapter.id}`)}>
                <Text style={styles.actionText}>آزمون</Text>
              </Pressable>
              <Pressable style={styles.action} onPress={() => router.push(`/flashcards/${chapter.id}`)}>
                <Text style={styles.actionText}>فلش‌کارت</Text>
              </Pressable>
            </View>
          )}
        </>
      )}
    </View>
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
  chapterHead: { flexDirection: 'row-reverse', alignItems: 'center', padding: 14, gap: 10 },
  group: { fontSize: 12.5, fontWeight: '800', color: colors.muted, paddingHorizontal: 16, paddingTop: 14, paddingBottom: 6, borderTopWidth: 1, borderTopColor: colors.line, backgroundColor: colors.ground },
  glossary: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, alignSelf: 'flex-end', paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line },
  glossaryText: { fontSize: 13, fontWeight: '700', color: colors.ink },
  resume: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.line, padding: 12 },
  resumeLabel: { fontSize: 12, color: colors.muted },
  resumeTitle: { fontSize: 15, fontWeight: '800', color: colors.ink },
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
