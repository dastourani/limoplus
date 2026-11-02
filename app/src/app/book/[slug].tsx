import { accessLabel } from '../../lib/access';
import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Animated, LayoutAnimation, Platform, Pressable, ScrollView, Share, StyleSheet, UIManager, useWindowDimensions, View } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints, type ChapterSummary, type NodeSummary } from '../../api/endpoints';
import { BookCover } from '../../components/BookCover';
import { MarkdownView } from '../../components/MarkdownView';
import { Text } from '../../components/Text';
import { useFeedback } from '../../components/Feedback';
import { LemonProgress } from '../../components/LemonProgress';
import { PageTurn } from '../../components/PageTurn';
import { Icon, IconBadge } from '../../components/Icon';
import { Button, Chip, ErrorState, Header, Loading, Screen, usePullRefresh } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { coverByline } from '../../lib/cover';
import { jalaliDate } from '../../lib/jalali';
import { offlineBooks, offlineSupported, removeOfflineBook, saveOfflineBook, type OfflineBook } from '../../lib/offline';
import { storage, type LastSection } from '../../lib/storage';
import { useApi } from '../../lib/useApi';
import { studyDuration } from '../../lib/duration';

if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) UIManager.setLayoutAnimationEnabledExperimental(true);
import { colors, formatToman, radius, rtl, toPersianDigits } from '../../theme';

export default function Book() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { user } = useAuth();
  const { data, error, loading, retry } = useApi(() => endpoints.book(String(slug)), [slug, user?.id]);
  const refresh = usePullRefresh(loading, retry);
  // Entering a book: its cover opens like a real book (once per visit).
  const { title: titleParam } = useLocalSearchParams<{ title?: string }>();
  const [coverTitle, setCoverTitle] = useState<string | null>(titleParam ?? '');
  const [offline, setOffline] = useState<OfflineBook | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const { confirm } = useFeedback();
  const { width } = useWindowDimensions();
  const [notify, setNotify] = useState<{ on: boolean; canCancel: boolean } | null>(null);
  const [aboutOpen, setAboutOpen] = useState(true);

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
  const coverW = Math.min(width * 0.46, 200);
  const cover =
    coverTitle !== null ? (
      <PageTurn kind="cover" title={coverTitle || book.title} face={<BookCover book={book} major={book.major ?? null} width={Math.min(width * 0.62, 300)} />} onDone={() => setCoverTitle(null)} />
    ) : null;
  const done = new Set(book.done_ids);
  const read = new Set(book.read_ids ?? []);
  const sections = book.chapters.flatMap((c) => c.sections);
  const tests = sections.reduce((n, x) => n + (x.question_count ?? 0), 0);
  const cards = sections.reduce((n, x) => n + (x.flashcard_count ?? 0), 0);
  const readCount = sections.filter((x) => done.has(x.id)).length;
  const firstOpen = book.chapters.find((c) => !c.is_locked);
  const firstOpenIndex = firstOpen ? book.chapters.indexOf(firstOpen) + 1 : 0;
  const startFree = () => {
    if (!firstOpen) return;
    const target = firstOpen.has_overview ? firstOpen.id : firstOpen.sections.find((x) => !x.is_locked)?.id;
    if (target) router.push(`/section/${target}`);
  };
  // A book that is free from start to end has nothing to buy: it reads like an owned one (no price, no «باز کردن»).
  const fullAccess = book.owned || !book.price || !!book.all_free;
  const now = notify ?? { on: book.notify, canCancel: !!book.notify_can_cancel };
  const waiting = now.on;
  const toggleNotify = async () => {
    if (!requireLogin(user, 'برای «خبرم کن» وارد شوید تا وقتی کتاب آماده شد خبرتان کنیم.')) return;
    if (now.on && !now.canCancel) return; // asked again after a cancel: stays on
    const on = !now.on;
    setNotify({ on, canCancel: on });
    endpoints
      .notifyBook(book.slug, on)
      .then((r) => setNotify({ on: r.notify, canCancel: r.can_cancel }))
      .catch(() => setNotify(now));
  };

  return (
    <Screen background={colors.ground}>
      <ScrollView contentContainerStyle={styles.scroll} refreshControl={refresh}>
        <View style={styles.hero}>
          <View style={styles.heroTop}>
            <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/home'))} style={styles.heroButton} accessibilityRole="button" accessibilityLabel="بازگشت">
              <Icon name="arrow-right" size={22} color="#FFFFFF" />
            </Pressable>
            <View style={{ flex: 1 }} />
            <Pressable
              onPress={() => router.push({ pathname: '/search', params: { book: book.slug, bookTitle: book.title } })}
              style={styles.heroButton}
              accessibilityRole="button"
              accessibilityLabel="جست‌وجو در این کتاب"
            >
              <Icon name="search" size={20} color="#FFFFFF" />
            </Pressable>
            <Pressable
              onPress={() => Share.share({ message: `«${book.title}» را در لیمو پلاس بخوان: خلاصه، جزوه، تست و فلش‌کارت.` }).catch(() => undefined)}
              style={styles.heroButton}
              accessibilityRole="button"
              accessibilityLabel="معرفی به دوست"
            >
              <Icon name="share-2" size={20} color="#FFFFFF" />
            </Pressable>
          </View>
          <View style={{ alignItems: 'center' }}>
            <View>
              <BookCover book={book} major={book.major ?? null} width={coverW} edge />
              {book.owned && (
                <View style={styles.ownedRibbon}>
                  <Icon name="circle-check" size={12} color="#FFFFFF" />
                  <Text style={styles.ownedRibbonText}>{accessLabel(book)}</Text>
                </View>
              )}
            </View>
          </View>
          <Text style={styles.heroTitle}>{book.title}</Text>
          {!!coverByline(book.author, book.edition) && <Text style={styles.heroSub}>{coverByline(book.author, book.edition)}</Text>}
          {!book.is_coming_soon && (
            <View style={styles.pills}>
              <Text style={styles.pill}>{toPersianDigits(book.chapters.length)} فصل، {toPersianDigits(sections.length)} بخش</Text>
              {!!tests && <Text style={styles.pill}>{toPersianDigits(tests)} تست</Text>}
              {!!cards && <Text style={styles.pill}>{toPersianDigits(cards)} فلش‌کارت</Text>}
            </View>
          )}
        </View>

        <View style={styles.page}>
          {book.is_coming_soon ? (
            <View style={styles.cta}>
              <View style={styles.ctaHead}>
                <IconBadge name="bell" size={30} />
                <Text style={[styles.ctaTitle, rtl, { flex: 1 }]}>این کتاب به‌زودی منتشر می‌شود</Text>
              </View>
              <Button
                label={waiting ? (now.canCancel ? 'خبرت می‌کنیم (لغو)' : 'خبرت می‌کنیم ✓') : 'خبرم کن'}
                variant={waiting ? 'outline' : 'dark'}
                disabled={waiting && !now.canCancel}
                onPress={toggleNotify}
              />
            </View>
          ) : fullAccess ? (
            <View style={[styles.cta, styles.ctaRow]}>
              <LemonProgress parts={sections.map((x) => (done.has(x.id) ? 'done' : read.has(x.id) ? 'soft' : 'empty'))} size={54} />
              <View style={{ flex: 1, gap: 2 }}>
                <Text style={[styles.ctaSmall, rtl]}>
                  {user ? `${toPersianDigits(readCount)} از ${toPersianDigits(sections.length)} بخش تمام‌شده` : 'برای ذخیره‌ی پیشرفت وارد شو'}
                </Text>
                <Text style={[styles.ctaTitle, rtl]} numberOfLines={1}>{last ? last.title : 'از اول کتاب شروع کن'}</Text>
              </View>
              <Pressable onPress={() => (last ? router.push(`/section/${last.id}`) : startFree())} style={styles.ctaButton} accessibilityRole="button">
                <Text style={styles.ctaButtonText}>{last ? 'ادامه بده' : 'شروع'}</Text>
              </Pressable>
            </View>
          ) : (
            <View style={styles.cta}>
              {!!firstOpen && (
                <View style={styles.ctaHead}>
                  <IconBadge name="gift" size={30} />
                  <Text style={[styles.ctaTitle, rtl, { flex: 1 }]}>
                    {firstOpen.sections.every((x) => !x.is_locked) ? `فصل ${toPersianDigits(firstOpenIndex)} رایگان است؛ بدون خرید شروع کن` : 'بخشی از کتاب رایگان است؛ بدون خرید شروع کن'}
                  </Text>
                </View>
              )}
              {!!last && (
                <Pressable onPress={() => router.push(`/section/${last.id}`)} style={styles.resumeLine} accessibilityRole="button">
                  <Icon name="book-open" size={16} color={colors.greenDark} />
                  <Text style={[styles.resumeLineText, rtl]} numberOfLines={1}>ادامه از «{last.title}»</Text>
                </Pressable>
              )}
              {!!firstOpen && !last && <Button label={`شروع رایگان از فصل ${toPersianDigits(firstOpenIndex)}`} variant="dark" onPress={startFree} />}
              <Pressable onPress={() => router.push(`/buy/${book.slug}`)} style={styles.unlock} accessibilityRole="button">
                <Icon name="lock-open" size={18} color={colors.ink} />
                <Text style={styles.unlockText}>باز کردن همه‌ی کتاب</Text>
              </Pressable>
              {!!book.price && <Text style={[styles.ctaSmall, { textAlign: 'center' }]}>{formatToman(book.price)}، یا با اشتراک ماهانه‌ی لیمو</Text>}
            </View>
          )}

          {!book.is_coming_soon && (
            <View style={styles.shortcuts}>
              <Pressable onPress={() => router.push(`/glossary/${book.slug}`)} style={styles.shortcut} accessibilityRole="button">
                <Icon name="languages" size={18} color={colors.ink} />
                <Text style={styles.shortcutText}>واژه‌نامه‌ی کتاب</Text>
              </Pressable>
              {!!book.mine?.mistakes.count && (
                <Pressable onPress={() => router.push({ pathname: '/mistakes', params: { book: book.slug } })} style={styles.shortcut} accessibilityRole="button">
                  <Icon name="notebook-pen" size={18} color={colors.ink} />
                  <Text style={styles.shortcutText}>اشتباه‌هایم ({toPersianDigits(book.mine.mistakes.count)})</Text>
                </Pressable>
              )}
              {!!book.sample_count && (
                <Pressable onPress={() => router.push({ pathname: '/share/[slug]', params: { slug: book.slug } })} style={styles.shortcut} accessibilityRole="button">
                  <Icon name="share-2" size={18} color={colors.ink} />
                  <Text style={styles.shortcutText}>تست‌های نمونه ({toPersianDigits(book.sample_count)})</Text>
                </Pressable>
              )}
              {!!book.mine?.exams && (
                <Pressable onPress={() => router.push({ pathname: '/exams', params: { book: book.slug } })} style={styles.shortcut} accessibilityRole="button">
                  <Icon name="trophy" size={18} color={colors.ink} />
                  <Text style={styles.shortcutText}>آزمون‌هایم ({toPersianDigits(book.mine.exams)})</Text>
                </Pressable>
              )}
              {!!book.mine?.time_seconds && book.mine.time_seconds >= 60 && (
                <View style={styles.shortcut} accessibilityLabel={`زمان مطالعه‌ی تو در این کتاب: ${studyDuration(book.mine.time_seconds)}`}>
                  <Icon name="timer" size={18} color={colors.ink} />
                  <Text style={styles.shortcutText}>زمان مطالعه: {studyDuration(book.mine.time_seconds)}</Text>
                </View>
              )}
              {offlineSupported && (
                <Pressable onPress={download} disabled={downloading} style={styles.shortcut} accessibilityRole="button">
                  <Icon name={offline ? 'circle-check' : 'download'} size={18} color={offline ? colors.greenDark : colors.ink} />
                  <Text style={styles.shortcutText}>
                    {downloading ? 'در حال دانلود…' : offline ? `آفلاین تا ${jalaliDate(offline.validUntil)}` : 'دانلود آفلاین'}
                  </Text>
                </Pressable>
              )}
            </View>
          )}
          {!!offline && offlineSupported && (
            <Pressable
              onPress={async () =>
                (await confirm({ title: 'نسخه‌ی آفلاین حذف شود؟', message: 'بعداً می‌توانید دوباره دانلودش کنید.', confirmLabel: 'حذف', destructive: true, icon: 'trash' })) &&
                removeOfflineBook(book.slug).then(() => setOffline(null))
              }
              accessibilityRole="button"
            >
              <Text style={[styles.smallLink, rtl]}>حذف نسخه‌ی آفلاین</Text>
            </Pressable>
          )}
          {!!note && <Text style={[styles.note, rtl]}>{note}</Text>}

          {!!book.about && (
            <View style={styles.about}>
              <Pressable onPress={() => setAboutOpen((v) => !v)} style={styles.aboutHead} accessibilityRole="button" accessibilityState={{ expanded: aboutOpen }}>
                <Text style={[styles.aboutTitle, rtl]}>درباره‌ی کتاب</Text>
                <Icon name="chevron-down" size={20} color={colors.muted} />
              </Pressable>
              {aboutOpen && <MarkdownView markdown={book.about} compact />}
            </View>
          )}

          {!book.is_coming_soon && <Text style={[styles.chaptersTitle, rtl]}>فصل‌ها</Text>}
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
              read={read}
              owned={book.owned}
              bookSlug={book.slug}
              seconds={book.mine?.chapter_seconds?.[String(chapter.id)] ?? 0}
              review={book.reviews?.chapters[String(chapter.id)] ?? null}
              canFinish={!!user && !!book.reviews}
              onFinish={async () => {
                const ok = await confirm({
                  title: 'این فصل را تمام کردی؟',
                  message: 'مرورهای این فصل زمان‌بندی می‌شوند: فردا، یک هفته بعد و یک ماه بعد. فلش‌کارت‌هایش هم به مرور روزانه اضافه می‌شوند.',
                  confirmLabel: 'تمام کردم',
                  icon: 'circle-check',
                });
                if (!ok) return;
                endpoints.finishChapter(chapter.id).then(retry).catch(() => undefined);
              }}
            />
          ))}
        </View>
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
  read,
  owned,
  bookSlug,
  review,
  canFinish,
  onFinish,
  seconds,
}: {
  seconds: number;
  bookSlug: string;
  /** «مرور بعدی: ۶ روز دیگر» once the chapter is finished. */
  review: { step: number; days: number; done: number } | null;
  canFinish: boolean;
  onFinish: () => void;
  chapter: ChapterSummary;
  number: number;
  open: boolean;
  onToggle: () => void;
  done: Set<number>;
  read: Set<number>;
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
        <LemonProgress parts={chapter.sections.map((x) => (done.has(x.id) ? 'done' : read.has(x.id) ? 'soft' : 'empty'))} size={38} />
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={[styles.chapterTitle, rtl]}>
            فصل {toPersianDigits(number)}، {chapter.title}
          </Text>
          <Text style={[styles.sectionMeta, rtl]}>
            {toPersianDigits(chapter.sections.length)} بخش{tests ? `، ${toPersianDigits(tests)} تست` : ''}
          </Text>
          {seconds >= 60 && <Text style={[styles.sectionMeta, rtl]}>زمان مطالعه: {studyDuration(seconds)}</Text>}
          {!!review && (
            <Text style={[styles.reviewLine, rtl, review.days <= 0 && { color: colors.redDark }]}>
              {review.days > 0 ? `مرور بعدی: ${toPersianDigits(review.days)} روز دیگر` : review.days === 0 ? 'مرور این فصل: امروز' : 'مرور این فصل عقب افتاده'}
            </Text>
          )}
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
                <SectionRow section={section} state={done.has(section.id) ? 'done' : read.has(section.id) ? 'read' : 'none'} />
              </View>
            );
          })}
          {!!chapter.term_count && (
            <Pressable
              onPress={() => router.push({ pathname: '/glossary/[slug]', params: { slug: bookSlug, chapter: String(chapter.id) } })}
              style={({ pressed }) => [styles.section, pressed && { backgroundColor: colors.ground }]}
              accessibilityRole="button"
            >
              <Icon name="languages" size={18} color={colors.greenDark} />
              <Text style={[styles.sectionTitle, rtl, { color: colors.greenDark }]}>واژه‌های این فصل</Text>
              <Text style={styles.sectionMeta}>{toPersianDigits(chapter.term_count)} واژه</Text>
            </Pressable>
          )}
          {!chapter.is_locked && canFinish && !review && (
            <Pressable onPress={onFinish} style={({ pressed }) => [styles.section, pressed && { backgroundColor: colors.ground }]} accessibilityRole="button">
              <Icon name="circle-check" size={18} color={colors.greenDark} />
              <Text style={[styles.sectionTitle, rtl, { color: colors.greenDark }]}>این فصل را تمام کردم</Text>
            </Pressable>
          )}
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

/** A section in the contents: the title takes up to two lines (then «…»; a long press shows it whole), the counts stay at
 * its left so the list never grows wider. */
/** none: not started; read: half (the notes read, or most of its questions answered); done: «تمام شد» (green tick: both). */
function SectionRow({ section, state }: { section: NodeSummary; state: 'none' | 'read' | 'done' }) {
  const done = state === 'done';
  const { toast } = useFeedback();
  return (
    <Pressable
      onPress={() => router.push(`/section/${section.id}`)}
      onLongPress={() => toast(section.title)}
      delayLongPress={350}
      style={({ pressed }) => [styles.section, pressed && { backgroundColor: colors.ground }]}
      accessibilityRole="button"
    >
      <View
        style={[styles.check, done && styles.checkOn, state === 'read' && styles.checkRead]}
        accessibilityLabel={done ? 'تمام شد' : state === 'read' ? 'نیمه‌کاره: جزوه یا تست‌هایش مانده' : 'شروع‌نشده'}
      >
        {done && <Icon name="check" size={13} color="#fff" strokeWidth={3} />}
        {state === 'read' && <View style={styles.half} />}
      </View>
      <Text style={[styles.sectionTitle, rtl, section.is_locked && { color: colors.muted }]} numberOfLines={2}>
        {section.title}
      </Text>
      {section.is_locked ? (
        <Icon name="lock" size={16} color={colors.muted} />
      ) : (
        <Text style={styles.sectionMeta}>{`${toPersianDigits(section.question_count ?? 0)} تست، ${toPersianDigits(section.flashcard_count ?? 0)} کارت`}</Text>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  scroll: { paddingBottom: 28 },
  page: { padding: 16, gap: 14, maxWidth: 760, width: '100%', alignSelf: 'center' },
  hero: { backgroundColor: colors.ink, paddingHorizontal: 16, paddingTop: 10, paddingBottom: 36, borderBottomLeftRadius: 28, borderBottomRightRadius: 28, gap: 6 },
  heroTop: { flexDirection: 'row-reverse', justifyContent: 'space-between', marginBottom: 4 },
  heroButton: { width: 44, height: 44, borderRadius: 14, backgroundColor: 'rgba(255,255,255,0.08)', alignItems: 'center', justifyContent: 'center' },
  heroTitle: { marginTop: 14, textAlign: 'center', fontSize: 22, fontWeight: '900', color: '#FFFFFF' },
  heroSub: { textAlign: 'center', fontSize: 13, color: '#A9B6AD' },
  pills: { flexDirection: 'row-reverse', justifyContent: 'center', flexWrap: 'wrap', gap: 8, marginTop: 8 },
  pill: { fontSize: 12, color: '#FFFFFF', backgroundColor: 'rgba(255,255,255,0.08)', paddingHorizontal: 11, paddingVertical: 5, borderRadius: 10, overflow: 'hidden' },
  ownedRibbon: { position: 'absolute', top: 12, left: -6, flexDirection: 'row-reverse', alignItems: 'center', gap: 4, backgroundColor: '#3FB8A9', paddingHorizontal: 8, paddingVertical: 3, borderTopLeftRadius: 6, borderTopRightRadius: 6, borderBottomRightRadius: 6 },
  ownedRibbonText: { fontSize: 10, fontWeight: '800', color: '#FFFFFF' },
  cta: { marginTop: -34, backgroundColor: colors.surface, borderRadius: 22, padding: 16, gap: 10, shadowColor: '#17201A', shadowOpacity: 0.12, shadowRadius: 18, shadowOffset: { width: 0, height: 8 }, elevation: 4 },
  ctaRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 14 },
  ctaHead: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  ctaTitle: { fontSize: 15, fontWeight: '800', color: colors.ink },
  ctaSmall: { fontSize: 12, color: colors.muted },
  ctaButton: { backgroundColor: colors.ink, borderRadius: 14, paddingHorizontal: 16, minHeight: 46, justifyContent: 'center' },
  ctaButtonText: { color: colors.lemon, fontWeight: '900', fontSize: 14 },
  unlock: { minHeight: 52, borderRadius: 16, backgroundColor: colors.lemon, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
  unlockText: { fontSize: 15, fontWeight: '900', color: colors.ink },
  resumeLine: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, backgroundColor: colors.greenSoft, borderRadius: 12, paddingHorizontal: 12, minHeight: 44 },
  resumeLineText: { flex: 1, fontSize: 14, fontWeight: '700', color: colors.greenDark },
  shortcuts: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  shortcut: { flexGrow: 1, flexBasis: '45%', minHeight: 46, borderRadius: 14, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, paddingHorizontal: 8 },
  shortcutText: { fontSize: 13, fontWeight: '700', color: colors.ink },
  smallLink: { fontSize: 12, color: colors.muted, textDecorationLine: 'underline' },
  note: { fontSize: 13, color: colors.muted },
  about: { backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 14, gap: 6 },
  aboutHead: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center' },
  aboutTitle: { fontSize: 15, fontWeight: '900', color: colors.ink },
  chaptersTitle: { fontSize: 17, fontWeight: '900', color: colors.ink, marginTop: 6 },
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
  checkRead: { borderColor: colors.lemon, overflow: 'hidden', alignItems: 'flex-end' },
  half: { width: '50%', height: '100%', backgroundColor: colors.lemon },
  checkMark: { color: '#fff', fontSize: 12, fontWeight: '700' },
  sectionTitle: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.ink },
  sectionMeta: { fontSize: 12, color: colors.muted, flexShrink: 0 },
  reviewLine: { fontSize: 12, fontWeight: '700', color: colors.greenDark },
  actions: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: colors.line },
  action: { flex: 1, backgroundColor: colors.ground, borderRadius: 14, paddingVertical: 12, alignItems: 'center' },
  actionText: { fontWeight: '700', color: colors.ink, fontSize: 14 },
});
