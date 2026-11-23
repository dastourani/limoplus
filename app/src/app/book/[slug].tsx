import { accessLabel } from '../../lib/access';
import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Animated, LayoutAnimation, Platform, Pressable, ScrollView, Share, StyleSheet, UIManager, useWindowDimensions, View } from 'react-native';
import Svg, { Defs, LinearGradient as SvgGradient, Rect, Stop } from 'react-native-svg';

import { ApiError } from '../../api/client';
import { endpoints, type ChapterSummary, type NodeSummary, type ReviewItem } from '../../api/endpoints';
import { openReview } from '../../lib/reviews';
import { BookCover } from '../../components/BookCover';
import { Pill } from '../../components/Pill';
import { MarkdownView } from '../../components/MarkdownView';
import { Text } from '../../components/Text';
import { useFeedback } from '../../components/Feedback';
import { useCelebrate } from '../../components/Celebrate';
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
import { useAppearance } from '../../lib/coverTheme';
import { celebrateProgress } from '../../lib/milestones';
import { studyDuration } from '../../lib/duration';
import { currentPrice, percentLabel } from '../../lib/pricing';

if (Platform.OS === 'android' && UIManager.setLayoutAnimationEnabledExperimental) UIManager.setLayoutAnimationEnabledExperimental(true);
import { colors, formatToman, radius, rtl, toPersianDigits, toPersianOrdinal } from '../../theme';
import { BookSide } from '../../components/ChapterSide';
import { HelpTip } from '../../components/HelpTip';
import { useWide } from '../../lib/layout';

export default function Book() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { user } = useAuth();
  const wide = useWide();
  const { data, error, loading, retry } = useApi(() => endpoints.book(String(slug)), [slug, user?.id]);
  const celebrate = useCelebrate();
  // Coming back with a section, a chapter or the whole book newly finished: celebrated here, once each.
  useEffect(() => {
    if (user && data && data.slug === slug) celebrateProgress(user.id, data, celebrate).catch(() => undefined);
  }, [data, user, slug, celebrate]);
  const refresh = usePullRefresh(loading, retry);
  // Entering a book: its cover opens like a real book (once per visit).
  const { title: titleParam } = useLocalSearchParams<{ title?: string }>();
  const [coverTitle, setCoverTitle] = useState<string | null>(titleParam ?? '');
  const [offline, setOffline] = useState<OfflineBook | null>(null);
  const [downloading, setDownloading] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const { confirm, toast } = useFeedback();
  const { width } = useWindowDimensions();
  const [notify, setNotify] = useState<{ on: boolean; canCancel: boolean } | null>(null);
  // «درباره‌ی کتاب»: three lines that fade out, with «ادامه‌ی معرفی ▾» (or a tap on the text); opened by the learner,
  // it stays open on later visits.
  const [aboutOpen, setAboutOpen] = useState<boolean | null>(null);
  // تب‌های سه‌گانه: «درباره کتاب» | «درباره نویسنده» | «نظرات»
  const [activeTab, setActiveTab] = useState<'book' | 'author' | 'reviews'>('book');
  const [reviewRating, setReviewRating] = useState(5);
  const [reviewBody, setReviewBody] = useState('');
  const [submittingReview, setSubmittingReview] = useState(false);
  const [showReviewForm, setShowReviewForm] = useState(false);

  useEffect(() => {
    setAboutOpen(null);
    storage.getAbout(String(slug)).then((v) => setAboutOpen(v === 'open'));
  }, [slug]);
  const handleSendReview = async () => {
    if (!requireLogin(user, 'برای ثبت نظر ابتدا وارد حساب خود شوید.')) return;
    if (!reviewBody.trim()) {
      toast('لطفاً متن نظر خود را بنویسید.');
      return;
    }
    setSubmittingReview(true);
    try {
      await endpoints.submitReview(String(slug), {
        rating: reviewRating,
        satisfaction_percent: reviewRating * 20,
        body: reviewBody.trim(),
      });
      toast('نظر شما با موفقیت ثبت شد.');
      setReviewBody('');
      setShowReviewForm(false);
      retry();
    } catch (e: any) {
      toast(e?.message || 'خطا در ثبت نظر');
    } finally {
      setSubmittingReview(false);
    }
  };

  const toggleAbout = () => {
    const open = !aboutOpen;
    if (Platform.OS !== 'web') LayoutAnimation.configureNext(LayoutAnimation.create(260, 'easeInEaseOut', 'opacity'));
    setAboutOpen(open);
    storage.setAbout(String(slug), open ? 'open' : 'seen');
  };
  // «کنکورهای سال‌های قبل»: the past exams that have tests in this book.
  const { data: past } = useApi(() => endpoints.pastExams(String(slug)), [slug, user?.id]);
  const [pastOpen, setPastOpen] = useState(false);
  const [pastNames, setPastNames] = useState<string[]>([]);
  // The green part with the cover stays put; the page slides up over it. A bar with the buttons stays on top, and the
  // book's name shows in it once the cover is covered.
  const scrollY = useRef(new Animated.Value(0)).current;
  const scrollRef = useRef<any>(null);
  const chapterOffsets = useRef<Record<number, number>>({});
  // «ظاهر اپ»: the top of the page is dark green, or warm cream when the learner chose the light look.
  const light = useAppearance() === 'light';
  const top = light
    ? { bg: '#EFEADA', fg: colors.ink, button: 'rgba(23,32,26,0.07)', stat: 'rgba(23,32,26,0.06)', value: '#7A5B00', label: colors.muted }
    : { bg: colors.ink, fg: '#FFFFFF', button: 'rgba(255,255,255,0.08)', stat: 'rgba(255,255,255,0.07)', value: colors.lemon, label: '#C9D3CC' };
  const [heroH, setHeroH] = useState(0);

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
  const bookPrice = currentPrice(book);
  // The cover is the width of the page (less its margins) divided by the golden ratio, in its 2:3 book shape: about a
  // fifth larger than before on a phone, and still leaving the counts under it in view on a small screen.
  const coverW = Math.round(Math.min((Math.min(width, 760) - 32) / 1.618, 240));
  const cover =
    coverTitle !== null ? (
      <PageTurn kind="cover" title={coverTitle || book.title} face={<BookCover book={book} major={book.major ?? null} width={Math.min(width * 0.62, 300)} />} onDone={() => setCoverTitle(null)} />
    ) : null;
  const done = new Set(book.done_ids);
  const read = new Set(book.read_ids ?? []);
  const sections = book.chapters.flatMap((c) => c.sections);
  // The book's own counts come summed from the server (a chapter already carries its sections' totals).
  const tests = book.chapters.reduce((n, c) => n + (c.question_count ?? 0), 0);
  const cards = book.chapters.reduce((n, c) => n + (c.flashcard_count ?? 0), 0);
  const readCount = sections.filter((x) => done.has(x.id)).length;
  const firstOpen = book.chapters.find((chapter) => !chapter.is_locked || chapter.sections.some((section) => !section.is_locked));
  const firstOpenIndex = firstOpen ? book.chapters.indexOf(firstOpen) + 1 : 0;
  const firstPreview = book.product_status.preview === 'sample' ? firstOpen : undefined;
  const previewLabel = firstPreview
    ? !firstPreview.is_locked && firstPreview.sections.every((section) => !section.is_locked)
      ? `فصل ${toPersianOrdinal(firstOpenIndex)} رایگان`
      : 'بخشی رایگان'
    : null;
  const startFree = () => {
    if (!firstPreview) return;
    const target = firstPreview.has_overview ? firstPreview.id : firstPreview.sections.find((section) => !section.is_locked)?.id;
    if (target) router.push(`/section/${target}`);
  };
  // Only the book-level is_free flag (reported as state=free) grants the whole book; a free chapter is a preview.
  const fullAccess = book.owned || book.product_status.state === 'free';
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

  // Measured once laid out; until then a close guess, so the page doesn't jump.
  const heroHeight = heroH || coverW * 1.5 + 110;
  const barShade = scrollY.interpolate({ inputRange: [heroHeight - 90, heroHeight - 30], outputRange: [0, 1], extrapolate: 'clamp' });
  const barTitle = scrollY.interpolate({ inputRange: [heroHeight - 60, heroHeight - 10], outputRange: [0, 1], extrapolate: 'clamp' });
  // The cover fades back a little as the page comes over it (it doesn't move).
  const heroFade = scrollY.interpolate({ inputRange: [0, heroHeight], outputRange: [1, 0.35], extrapolate: 'clamp' });

  const isPreparing = book.product_status.state === 'coming_soon' || book.product_status.state === 'preparing';

  return (
    <Screen background={colors.ground} wide={wide}>
      <View style={{ flex: 1, flexDirection: 'row-reverse' }}>
      {wide && !isPreparing && (
        <BookSide
          book={book}
          openId={openId}
          onSelect={(cid) => {
            LayoutAnimation.configureNext(LayoutAnimation.create(220, 'easeInEaseOut', 'opacity'));
            setOpenId((prev) => (prev === cid ? null : cid));
            // اسکرول نرم به سمت کارت فصل در بدنه اصلی صفحه
            const y = chapterOffsets.current[cid];
            if (y != null && scrollRef.current) {
              scrollRef.current.scrollTo({ y: Math.max(0, y - 40), animated: true });
            }
          }}
        />
      )}
      <View style={{ flex: 1, minWidth: 0 }}>
      <View style={[styles.inkBack, { height: BAR_H + heroHeight + 40, backgroundColor: top.bg }]} />
      {/* The margin is on a wrapper: on the web a refresh control gives the scroll view's style to two elements. */}
      <View style={{ flex: 1, marginTop: BAR_H }}>
      <Animated.ScrollView
        ref={scrollRef}
        contentContainerStyle={styles.scroll}
        refreshControl={refresh}
        scrollEventThrottle={16}
        onScroll={Animated.event([{ nativeEvent: { contentOffset: { y: scrollY } } }], { useNativeDriver: Platform.OS !== 'web' })}
      >
        <Animated.View
          style={[
            styles.hero,
            {
              opacity: heroFade,
              backgroundColor: top.bg,
              ...(Platform.OS !== 'web' ? { transform: [{ translateY: scrollY }] } : null),
            },
          ]}
          onLayout={(e) => {
            const h = Math.round(e.nativeEvent.layout.height);
            if (h && h !== heroH) setHeroH(h);
          }}
        >
          <View style={{ alignItems: 'center' }}>
            {/* The cover carries the title (and author), so it is not written again under it; screen readers hear it here. */}
            <View accessible accessibilityRole="header" accessibilityLabel={[book.title, coverByline(book.author, book.edition)].filter(Boolean).join('، ')}>
              <BookCover book={book} major={book.major ?? null} width={coverW} edge />
              {book.owned && (
                <View style={styles.ownedRibbon}>
                  <Icon name="circle-check" size={12} color="#FFFFFF" />
                  <Text style={styles.ownedRibbonText}>{accessLabel(book)}</Text>
                </View>
              )}
            </View>
          </View>
          {/* An uploaded cover image may not show the title clearly: then it stays, small. */}
          {!!book.cover && <Text style={[styles.heroTitle, { color: top.fg }]}>{book.title}</Text>}
          {!isPreparing && (
            <View style={styles.stats}>
              {(
                [
                  [book.chapters.length, 'فصل'],
                  [sections.length, 'بخش'],
                  [tests, 'تست'],
                  [cards, 'فلش‌کارت'],
                ] as const
              )
                .filter(([n], i) => i < 2 || n > 0)
                .map(([n, label]) => (
                  <View key={label} style={[styles.stat, { backgroundColor: top.stat }]}>
                    <Text style={[styles.statValue, { color: top.value }]}>{toPersianDigits(n)}</Text>
                    <Text style={[styles.statLabel, { color: top.label }]}>{label}</Text>
                  </View>
                ))}
              {!!user && !!book.words && (
                <View style={[styles.stat, { backgroundColor: top.stat }]}>
                  <Text style={[styles.statValue, { color: top.value }]}>
                    {toPersianDigits(book.words.learned)} از {toPersianDigits(book.words.total)}
                  </Text>
                  <View style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 4 }}>
                    <Text style={[styles.statLabel, { color: top.label }]}>لغت حفظ‌شده</Text>
                    <HelpTip size={18} title="لغت حفظ‌شده" text="فلش‌کارت‌های لغت این کتاب که به جعبه‌ی ۴ یا بالاتر مرور رسیده‌اند، یعنی چند بار پشت‌سرهم بلدشان بوده‌ای." />
                  </View>
                </View>
              )}
            </View>
          )}
        </Animated.View>
        <View style={styles.sheet}>
        <View style={styles.page}>
          {isPreparing ? (
            <View style={styles.cta}>
              <View style={styles.ctaHead}>
                <IconBadge name="bell" size={30} />
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={[styles.ctaTitle, rtl]}>این کتاب در حال آماده‌سازی است و به‌زودی منتشر می‌شود</Text>
                  {!!book.release_estimate && (
                    <Text style={[styles.ctaSmall, rtl, { color: colors.greenDark, fontWeight: '800' }]}>
                      زمان حدودی انتشار: {book.release_estimate}
                    </Text>
                  )}
                </View>
                <HelpTip
                  size={22}
                  title={`زمان حدودی انتشار: ${book.release_estimate || 'به‌زودی'}`}
                  text="با زدن دکمه‌ی «خبرم کن»، به محض انتشار فصل اول رایگان این کتاب، یک پیامک اطلاع‌رسانی برای شما ارسال می‌شود."
                />
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
              <HelpTip
                size={54}
                title="لیموی پیشرفت کتاب"
                text={`${user ? `${toPersianDigits(readCount)} از ${toPersianDigits(sections.length)} بخش این کتاب تمام شده است. ` : ''}هر برش لیمو یک بخش کتاب است. برش پررنگ: بخش را تا آخر خوانده‌ای. برش کم‌رنگ: شروعش کرده‌ای. برش خالی: هنوز نخوانده‌ای.`}
              >
                <LemonProgress parts={sections.map((x) => (done.has(x.id) ? 'done' : read.has(x.id) ? 'soft' : 'empty'))} size={54} />
              </HelpTip>
              <View style={{ flex: 1, gap: 2 }}>
                <View style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 6 }}>
                  <Text style={[styles.ctaSmall, rtl]}>
                    {user ? `${toPersianDigits(readCount)} از ${toPersianDigits(sections.length)} بخش تمام‌شده` : 'برای ذخیره‌ی پیشرفت وارد شو'}
                  </Text>
                  {!!user && <HelpTip size={18} title="لیموی پیشرفت" text="هر برش لیمو یک بخش کتاب است. برش پررنگ: بخش را تا آخر خوانده‌ای. برش کم‌رنگ: شروعش کرده‌ای. برش خالی: هنوز نخوانده‌ای." />}
                </View>
                <Text style={[styles.ctaTitle, rtl]} numberOfLines={1}>{last ? last.title : 'از اول کتاب شروع کن'}</Text>
              </View>
              <Pressable onPress={() => (last ? router.push(`/section/${last.id}`) : startFree())} style={styles.ctaButton} accessibilityRole="button">
                <Text style={styles.ctaButtonText}>{last ? 'ادامه بده' : 'شروع'}</Text>
              </Pressable>
            </View>
          ) : (
            <View style={styles.cta}>
              {!!firstPreview && (
                <View style={styles.ctaHead}>
                  <IconBadge name="gift" size={30} />
                  <Text style={[styles.ctaTitle, rtl, { flex: 1 }]}>
                    {previewLabel === 'بخشی رایگان'
                      ? 'بخشی از کتاب رایگان است؛ بدون خرید شروع کن'
                      : `${previewLabel} است؛ بدون خرید شروع کن`}
                  </Text>
                </View>
              )}
              {!!last && (
                <Pressable onPress={() => router.push(`/section/${last.id}`)} style={styles.resumeLine} accessibilityRole="button">
                  <Icon name="book-open" size={16} color={colors.greenDark} />
                  <Text style={[styles.resumeLineText, rtl]} numberOfLines={1}>ادامه از «{last.title}»</Text>
                </Pressable>
              )}
              {!!firstPreview && !last && <Button label={`شروع رایگان از فصل ${toPersianDigits(firstOpenIndex)}`} onPress={startFree} />}
              {book.product_status.state === 'paid' && (
                <>
                  <Pressable onPress={() => router.push(`/buy/${book.slug}`)} style={[styles.unlock, !(firstPreview && !last) && styles.unlockMain]} accessibilityRole="button">
                    <Icon name="lock-open" size={18} color={colors.ink} />
                    <Text style={styles.unlockText}>باز کردن همه‌ی کتاب</Text>
                  </Pressable>
                  {bookPrice.price != null && (bookPrice.discount ? (
                    <View style={styles.priceDetails}>
                      <View style={styles.priceLine}>
                        <Text style={[styles.ctaSmall, rtl]}>قیمت عادی</Text>
                        <Text style={styles.oldPrice}>{formatToman(bookPrice.regularPrice ?? bookPrice.price)}</Text>
                      </View>
                      <View style={styles.priceLine}>
                        <Text style={[styles.ctaSmall, rtl]}>قیمت ویژه</Text>
                        <View style={styles.saleAmountLine}>
                          <Text style={styles.salePrice}>{formatToman(bookPrice.price)}</Text>
                          <Text style={styles.discountChip}>{percentLabel(bookPrice.discount.percent)}٪ تخفیف</Text>
                        </View>
                      </View>
                      {!!previewLabel && <Text style={[styles.samplePriceText, rtl]}>{previewLabel}</Text>}
                      <Text style={[styles.saving, rtl]}>
                        صرفه‌جویی {formatToman(bookPrice.discount.amount)} · یا با اشتراک لیمو
                      </Text>
                    </View>
                  ) : (
                    <Text style={[styles.ctaSmall, { textAlign: 'center' }]}>
                      {formatToman(bookPrice.price)}، یا با اشتراک ماهانه‌ی لیمو
                      {!!previewLabel && <Text style={styles.samplePriceText}> · {previewLabel}</Text>}
                    </Text>
                  ))}
                </>
              )}
              {book.product_status.state === 'unpriced' && <Text style={[styles.ctaSmall, rtl]}>قیمت نسخه‌ی کامل هنوز تعیین نشده است.</Text>}
              {book.product_status.state === 'unavailable' && <Text style={[styles.ctaSmall, rtl]}>این کتاب فعلاً برای خرید در دسترس نیست.</Text>}
            </View>
          )}

          {!isPreparing && (
            <View style={styles.shortcuts}>
              {/* The book's flashcards, only from finished (green) sections: what was learned gets reviewed. */}
              {!!user && book.chapters.some((c) => c.flashcard_count || c.sections.some((s) => s.flashcard_count)) && (
                <Pressable
                  onPress={() =>
                    book.done_card_count
                      ? router.push({ pathname: '/flashcards/[nodeId]', params: { nodeId: String(book.id), done: '1' } })
                      : toast('هر بخشی را که تمام کنی (تیک سبز)، فلش‌کارت‌هایش اینجا برای مرور می‌آید.')
                  }
                  style={[styles.shortcut, !book.done_card_count && { opacity: 0.55 }]}
                  accessibilityRole="button"
                  accessibilityState={{ disabled: !book.done_card_count }}
                >
                  <Icon name="layers" size={18} color={colors.ink} />
                  <Text style={styles.shortcutText}>
                    {book.done_card_count ? `مرور کارت‌ها (${toPersianDigits(book.done_card_count)})` : 'مرور کارت‌ها'}
                  </Text>
                </Pressable>
              )}
              <Pressable onPress={() => router.push({ pathname: '/boxes/[nodeId]', params: { nodeId: String(book.id) } })} style={styles.shortcut} accessibilityRole="button">
                <Icon name="clipboard-list" size={18} color={colors.ink} />
                <Text style={styles.shortcutText}>کادرهای کتاب</Text>
              </Pressable>
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
          {/* Information, not a button: last, the full width (long times such as «۱۲ ساعت» never wrap), quiet. */}
          {!isPreparing && !!book.mine?.time_seconds && book.mine.time_seconds >= 60 && (
            <View style={styles.timeRow} accessible accessibilityLabel={`تا الان ${studyDuration(book.mine.time_seconds)} روی این کتاب وقت گذاشتی`}>
              <Icon name="time-spent" size={16} color={colors.muted} />
              <Text style={styles.timeText}>تا الان {studyDuration(book.mine.time_seconds)} وقت گذاشتی</Text>
            </View>
          )}
          {/* «آخرین به‌روزرسانی»: the book's last important update; tap for «تغییرات کتاب». */}
          {!!book.updated_on && (
            <Pressable onPress={() => router.push({ pathname: '/changes/[slug]', params: { slug: book.slug } })} style={styles.timeRow} accessibilityRole="button">
              <Icon name="sparkles" size={16} color={colors.muted} />
              <Text style={styles.timeText}>آخرین به‌روزرسانی: {jalaliDate(book.updated_on)}</Text>
              <Text style={[styles.timeText, { color: colors.greenDark, fontWeight: '800' }]}>تغییرات کتاب ←</Text>
            </Pressable>
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

          {/* تب‌های سه‌گانه همگن: درباره کتاب | درباره نویسنده | نظرات */}
          <View style={styles.tabsContainer}>
            <View style={styles.tabHeader}>
              <Pressable
                onPress={() => setActiveTab('book')}
                style={[styles.tabButton, activeTab === 'book' && styles.tabButtonActive]}
                accessibilityRole="tab"
              >
                <Icon name="book-open" size={16} color={activeTab === 'book' ? colors.ink : colors.muted} />
                <Text style={[styles.tabButtonText, activeTab === 'book' && styles.tabButtonTextActive]}>درباره‌ی کتاب</Text>
              </Pressable>

              <Pressable
                onPress={() => setActiveTab('author')}
                style={[styles.tabButton, activeTab === 'author' && styles.tabButtonActive]}
                accessibilityRole="tab"
              >
                <Icon name="user" size={16} color={activeTab === 'author' ? colors.ink : colors.muted} />
                <Text style={[styles.tabButtonText, activeTab === 'author' && styles.tabButtonTextActive]}>درباره‌ی نویسنده</Text>
              </Pressable>

              <Pressable
                onPress={() => setActiveTab('reviews')}
                style={[styles.tabButton, activeTab === 'reviews' && styles.tabButtonActive]}
                accessibilityRole="tab"
              >
                <Icon name="message-square" size={16} color={activeTab === 'reviews' ? colors.ink : colors.muted} />
                <Text style={[styles.tabButtonText, activeTab === 'reviews' && styles.tabButtonTextActive]}>
                  نظرات {book.community_reviews?.total_count ? `(${toPersianDigits(book.community_reviews.total_count)})` : ''}
                </Text>
              </Pressable>
            </View>

            {/* محتوای تب ۱: درباره کتاب */}
            {activeTab === 'book' && (
              <View style={styles.tabContent}>
                {book.about ? (
                  shortAbout(book.about) ? (
                    <MarkdownView markdown={book.about} compact />
                  ) : (
                    <>
                      <View style={[styles.aboutBody, aboutOpen ? styles.aboutBodyOpen : styles.aboutFolded]}>
                        <MarkdownView markdown={book.about} compact />
                        {!aboutOpen && (
                          <>
                            <Svg pointerEvents="none" style={styles.aboutFade} width="100%" height={44}>
                              <Defs>
                                <SvgGradient id="aboutFade" x1="0" y1="0" x2="0" y2="1">
                                  <Stop offset="0" stopColor={colors.surface} stopOpacity={0} />
                                  <Stop offset="1" stopColor={colors.surface} stopOpacity={1} />
                                </SvgGradient>
                              </Defs>
                              <Rect x="0" y="0" width="100%" height="44" fill="url(#aboutFade)" />
                            </Svg>
                            <Pressable onPress={toggleAbout} style={StyleSheet.absoluteFill} accessibilityLabel="ادامه‌ی معرفی" />
                          </>
                        )}
                      </View>
                      <Pressable onPress={toggleAbout} style={styles.aboutMore} accessibilityRole="button" accessibilityState={{ expanded: aboutOpen ?? false }}>
                        <Text style={[styles.aboutMoreText, rtl]}>{aboutOpen ? 'بستن معرفی ▴' : 'ادامه‌ی معرفی ▾'}</Text>
                      </Pressable>
                    </>
                  )
                ) : (
                  <Text style={[styles.emptyNote, rtl]}>توضیحاتی برای این اثر ثبت نشده است.</Text>
                )}
              </View>
            )}

            {/* محتوای تب ۲: درباره نویسنده / استاد */}
            {activeTab === 'author' && (
              <View style={styles.tabContent}>
                <View style={styles.authorHeader}>
                  <View style={styles.authorAvatar}>
                    <Icon name="user" size={32} color={colors.muted} />
                  </View>
                  <View style={{ flex: 1, gap: 4 }}>
                    <Text style={[styles.authorName, rtl]}>{book.author_profile?.name || book.author || 'مؤلف اثر'}</Text>
                    {!!book.author_profile?.academic_title && (
                      <Text style={[styles.authorTitle, rtl]}>{book.author_profile.academic_title}</Text>
                    )}
                  </View>
                </View>

                {book.author_profile?.bio ? (
                  <View style={{ marginTop: 12 }}>
                    <MarkdownView markdown={book.author_profile.bio} compact />
                  </View>
                ) : (
                  <Text style={[styles.emptyNote, rtl]}>رزومه و اطلاعات تکمیلی مؤلف به زودی قرار می‌گیرد.</Text>
                )}

                {!!book.author_profile?.contact_email && (
                  <View style={styles.authorMetaRow}>
                    <Icon name="mail" size={14} color={colors.muted} />
                    <Text style={styles.authorMetaText}>{book.author_profile.contact_email}</Text>
                  </View>
                )}
              </View>
            )}

            {/* محتوای تب ۳: نظرات و امتیازها */}
            {activeTab === 'reviews' && (
              <View style={styles.tabContent}>
                {/* خلاصه امتیازها و شاخص رضایت */}
                <View style={styles.reviewStatsBox}>
                  <View style={styles.reviewStatCol}>
                    <Text style={styles.reviewBigScore}>{toPersianDigits(book.community_reviews?.average_rating ?? 5)}</Text>
                    <View style={{ flexDirection: 'row-reverse', gap: 2 }}>
                      {[1, 2, 3, 4, 5].map((star) => (
                        <Text key={star} style={{ color: star <= Math.round(book.community_reviews?.average_rating ?? 5) ? '#eab308' : '#d1d5db', fontSize: 14 }}>
                          ★
                        </Text>
                      ))}
                    </View>
                    <Text style={styles.reviewSubLabel}>از ۵ ستاره</Text>
                  </View>

                  <View style={styles.reviewStatDivider} />

                  <View style={{ flex: 1, gap: 6, justifyContent: 'center' }}>
                    <View style={styles.reviewHighlightRow}>
                      <Icon name="thumbs-up" size={14} color={colors.greenDark} />
                      <Text style={[styles.reviewHighlightText, rtl]}>
                        <Text style={{ fontWeight: '900', color: colors.greenDark }}>{toPersianDigits(book.community_reviews?.satisfaction_rate ?? 100)}٪</Text> رضایت خوانندگان
                      </Text>
                    </View>
                    <View style={styles.reviewHighlightRow}>
                      <Icon name="award" size={14} color="#0284c7" />
                      <Text style={[styles.reviewHighlightText, rtl]}>
                        امتیاز خوانندگان جدی (+۵۰٪ مطالعه): <Text style={{ fontWeight: '900', color: '#0284c7' }}>{toPersianDigits(book.community_reviews?.serious_readers_rating ?? 5)}</Text>
                      </Text>
                    </View>
                  </View>
                </View>

                {/* دکمه ثبت نظر */}
                {!showReviewForm ? (
                  <Pressable onPress={() => setShowReviewForm(true)} style={styles.writeReviewButton} accessibilityRole="button">
                    <Icon name="edit-3" size={16} color={colors.ink} />
                    <Text style={styles.writeReviewText}>ثبت نظر و امتیاز شما برای این کتاب</Text>
                  </Pressable>
                ) : (
                  <View style={styles.reviewFormBox}>
                    <Text style={[styles.formTitle, rtl]}>دیدگاه و امتیاز شما درباره کتاب:</Text>
                    <View style={styles.starsSelectRow}>
                      <Text style={[styles.starLabel, rtl]}>امتیاز شما:</Text>
                      <View style={{ flexDirection: 'row-reverse', gap: 6 }}>
                        {[1, 2, 3, 4, 5].map((s) => (
                          <Pressable key={s} onPress={() => setReviewRating(s)}>
                            <Text style={{ fontSize: 24, color: s <= reviewRating ? '#eab308' : '#d1d5db' }}>★</Text>
                          </Pressable>
                        ))}
                      </View>
                    </View>
                    <View style={styles.textAreaWrap}>
                      <MarkdownView markdown={reviewBody || ' '} />
                    </View>
                    {/* Native / Web Input Simulation via Prompt or direct TextInput */}
                    <Button
                      label={submittingReview ? 'در حال ارسال...' : 'ارسال نظر'}
                      disabled={submittingReview}
                      onPress={() => {
                        if (Platform.OS === 'web') {
                          const val = window.prompt('نظر خود را بنویسید:', reviewBody);
                          if (val !== null) {
                            setReviewBody(val);
                            endpoints.submitReview(String(slug), { rating: reviewRating, satisfaction_percent: reviewRating * 20, body: val.trim() })
                              .then(() => { toast('نظر شما ثبت شد.'); setShowReviewForm(false); retry(); })
                              .catch((err) => toast(err?.message || 'خطا در ثبت'));
                          }
                        } else {
                          handleSendReview();
                        }
                      }}
                    />
                  </View>
                )}

                {/* لیست نظرات */}
                {book.community_reviews?.reviews?.length ? (
                  <View style={{ gap: 12, marginTop: 14 }}>
                    {book.community_reviews.reviews.map((r) => (
                      <View key={r.id} style={styles.singleReviewCard}>
                        <View style={styles.reviewUserHead}>
                          <View style={{ flex: 1, gap: 2 }}>
                            <Text style={[styles.reviewUserName, rtl]}>{r.display_name}</Text>
                            <View style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                              <View style={styles.studyBadge}>
                                <Text style={styles.studyBadgeText}>{toPersianDigits(r.study_percent)}٪ مطالعه</Text>
                              </View>
                              {r.test_percent > 0 && (
                                <View style={[styles.studyBadge, { backgroundColor: '#f0fdf4' }]}>
                                  <Text style={[styles.studyBadgeText, { color: '#166534' }]}>{toPersianDigits(r.test_percent)}٪ تست</Text>
                                </View>
                              )}
                              <Text style={styles.reviewDate}>{r.created_at}</Text>
                            </View>
                          </View>
                          <View style={{ flexDirection: 'row-reverse', gap: 1 }}>
                            {[1, 2, 3, 4, 5].map((st) => (
                              <Text key={st} style={{ color: st <= r.rating ? '#eab308' : '#e5e7eb', fontSize: 13 }}>★</Text>
                            ))}
                          </View>
                        </View>
                        <Text style={[styles.reviewBodyText, rtl]}>{r.body}</Text>

                        {/* کادر پاسخ استاد */}
                        {!!r.teacher_reply && (
                          <View style={styles.teacherReplyBox}>
                            <View style={styles.teacherReplyHead}>
                              <Icon name="corner-down-left" size={14} color="#0369a1" />
                              <Text style={styles.teacherReplyBadge}>پاسخ مؤلف / استاد</Text>
                            </View>
                            <Text style={[styles.teacherReplyBody, rtl]}>{r.teacher_reply}</Text>
                          </View>
                        )}
                      </View>
                    ))}
                  </View>
                ) : (
                  <Text style={[styles.emptyNote, rtl]}>هنوز نظری برای این کتاب ثبت نشده است. اولین نفری باشید که دیدگاه خود را می‌نویسد!</Text>
                )}
              </View>
            )}
          </View>

          {!isPreparing && !!past?.exams.length && (
            <View style={styles.about}>
              <Pressable onPress={() => setPastOpen((v) => !v)} style={styles.aboutHead} accessibilityRole="button" accessibilityState={{ expanded: pastOpen }}>
                <Text style={[styles.aboutTitle, rtl, { flex: 1 }]}>
                  کنکورهای سال‌های قبل ({toPersianDigits(past.exams.length)} کنکور، {toPersianDigits(past.total)} تست)
                </Text>
                <View style={styles.aboutActions}>
                  <HelpTip
                    size={26}
                    title="آمادگی برای کنکورها"
                    text="لیموی کنار هر کنکور «آمادگی» توست: چند درصد تست‌های آن کنکور از فصل‌هایی است که تمامشان کرده‌ای. هر چه پرتر، آن کنکور را راحت‌تر می‌توانی بزنی."
                  />
                  <View style={[styles.chevronCircle, pastOpen && styles.chevronCircleOn, pastOpen && { transform: [{ rotate: '-180deg' }] }]}>
                    <Icon name="chevron-down" size={16} color={pastOpen ? colors.ink : colors.muted} />
                  </View>
                </View>
              </Pressable>
              {pastOpen && (
                <View style={{ gap: 8 }}>
                  {past.exams.map((x) => (
                    <View key={x.id} style={styles.pastRow}>
                      {/* «آمادگی»: the share of its tests from chapters already studied. */}
                      {x.ready != null && <LemonProgress value={x.ready / 100} segments={8} size={30} />}
                      <View style={{ flex: 1 }}>
                        <Text style={[styles.pastTitle, rtl]}>
                          {x.name} {toPersianDigits(x.year)}
                        </Text>
                        <Text style={[styles.sectionMeta, rtl]}>
                          {toPersianDigits(x.count)} تست، حدود {toPersianDigits(x.minutes)} دقیقه
                        </Text>
                        {x.ready != null &&
                          (x.ready >= 100 ? (
                            <Text style={[styles.ready, rtl]}>آماده‌ای: همه‌ی فصل‌هایش را تمام کرده‌ای</Text>
                          ) : (
                            <Text style={[styles.sectionMeta, rtl]}>آمادگی: {toPersianDigits(x.ready)}٪ تست‌هایش از فصل‌های تمام‌شده است</Text>
                          ))}
                      </View>
                      <Pressable
                        onPress={() => router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: 'past', book: book.slug, source: String(x.id) } })}
                        style={styles.pastBtn}
                        accessibilityRole="button"
                      >
                        <Text style={styles.pastBtnText}>تمرین</Text>
                      </Pressable>
                      <Pressable
                        onPress={() =>
                          router.push({ pathname: '/exam/[nodeId]', params: { nodeId: String(book.id), source: String(x.id), title: `${x.name} ${toPersianDigits(x.year)}` } })
                        }
                        style={[styles.pastBtn, styles.pastBtnMain]}
                        accessibilityRole="button"
                      >
                        <Text style={styles.pastBtnText}>آزمون</Text>
                      </Pressable>
                    </View>
                  ))}
                  {!!past.repeats && (
                    <View style={[styles.pastRepeats]}>
                      <Text style={[styles.pastTitle, rtl]}>تکراری‌ها و مشابه‌ها</Text>
                      <Text style={[styles.sectionMeta, rtl]}>
                        تست‌هایی که عیناً یا با کمی تغییر در چند کنکور آمده‌اند، کنار هم. کنکور یا کنکورهایی را که می‌خواهی انتخاب کن (هیچ: همه).
                      </Text>
                      {(past.names ?? []).length > 1 && (
                        <View style={styles.pastNames}>
                          {(past.names ?? []).map((n) => (
                            <Pill
                              key={n.name}
                              small
                              label={`${n.name} (${toPersianDigits(n.repeats)})`}
                              selected={pastNames.includes(n.name)}
                              onPress={() => setPastNames((l) => (l.includes(n.name) ? l.filter((x) => x !== n.name) : [...l, n.name]))}
                            />
                          ))}
                        </View>
                      )}
                      <Pressable
                        onPress={() => router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: 'repeats', book: book.slug, names: pastNames.join('|') } })}
                        style={[styles.pastBtn, styles.pastBtnMain, { alignSelf: 'flex-end' }]}
                        accessibilityRole="button"
                      >
                        <Text style={styles.pastBtnText}>
                          تمرین {toPersianDigits(pastNames.length ? (past.names ?? []).filter((n) => pastNames.includes(n.name)).reduce((a, n) => a + n.repeats, 0) : past.repeats)} گروه
                        </Text>
                      </Pressable>
                    </View>
                  )}
                  {!!past.locked && <Text style={[styles.sectionMeta, rtl]}>{toPersianDigits(past.locked)} تست کنکور دیگر در فصل‌های نسخه‌ی کامل است.</Text>}
                </View>
              )}
            </View>
          )}

          {!isPreparing && <Text style={[styles.chaptersTitle, rtl]}>فصل‌ها</Text>}
          {book.chapters.map((chapter, index) => (
            <View
              key={chapter.id}
              onLayout={(e) => {
                chapterOffsets.current[chapter.id] = e.nativeEvent.layout.y;
              }}
            >
            <ChapterCard
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
            </View>
          ))}
        </View>
        </View>
      </Animated.ScrollView>
      </View>
      <View style={styles.bar}>
        <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.barShade, { opacity: barShade, backgroundColor: top.bg }]} />
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/home'))} style={[styles.heroButton, { backgroundColor: top.button }]} accessibilityRole="button" accessibilityLabel="بازگشت">
          <Icon name="arrow-right" size={22} color={top.fg} />
        </Pressable>
        <Animated.View style={{ flex: 1, opacity: barTitle }}>
          <Text numberOfLines={1} style={[styles.barTitle, { color: top.fg }]}>{book.title}</Text>
        </Animated.View>
        <Pressable
          onPress={() => router.push({ pathname: '/search', params: { book: book.slug, bookTitle: book.title } })}
          style={[styles.heroButton, { backgroundColor: top.button }]}
          accessibilityRole="button"
          accessibilityLabel="جست‌وجو در این کتاب"
        >
          <Icon name="search" size={20} color={top.fg} />
        </Pressable>
        <Pressable
          onPress={() => Share.share({ message: `«${book.title}» را در لیموخوان بخوان: خلاصه، جزوه، تست و فلش‌کارت.${book.share_link ? `\n${book.share_link}` : ''}` }).catch(() => undefined)}
          style={[styles.heroButton, { backgroundColor: top.button }]}
          accessibilityRole="button"
          accessibilityLabel="معرفی به دوست"
        >
          <Icon name="share-2" size={20} color={top.fg} />
        </Pressable>
      </View>
      </View>
      </View>
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
  review: { id?: number; step: number; days: number; done: number } | null;
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
  const { toast } = useFeedback();
  useEffect(() => {
    Animated.spring(turn, { toValue: open ? 1 : 0, friction: 7, tension: 120, useNativeDriver: true }).start();
  }, [open, turn]);
  // The chapter's totals come summed from the server, the same numbers the buttons below follow.
  const tests = chapter.question_count ?? 0;
  const cards = chapter.flashcard_count ?? 0;
  let lastGroup = '';
  return (
    <View style={styles.chapter}>
      <Pressable onPress={onToggle} style={styles.chapterHead} accessibilityRole="button" accessibilityState={{ expanded: open }}>
        {/* As tall as two lines of the title, so the lemon and the name read as one. */}
        <HelpTip
          size={46}
          title={`فصل ${toPersianDigits(number)}، ${chapter.title}`}
          text={`${toPersianDigits(chapter.sections.filter((s) => done.has(s.id)).length)} از ${toPersianDigits(chapter.sections.length)} بخش این فصل تمام شده است.`}
        >
          <LemonProgress parts={chapter.sections.map((x) => (done.has(x.id) ? 'done' : read.has(x.id) ? 'soft' : 'empty'))} size={46} />
        </HelpTip>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={[styles.chapterTitle, rtl]} numberOfLines={2}>
            فصل {toPersianDigits(number)}، {chapter.title}
          </Text>
          {/* Counts and the free/locked label share one line, so the title keeps the width. */}
          <View style={styles.metaRow}>
            <Text style={[styles.sectionMeta, rtl]}>
              {toPersianDigits(chapter.sections.length)} بخش{tests ? `، ${toPersianDigits(tests)} تست` : ''}
            </Text>
            {chapter.is_locked ? <Chip label="نسخه‌ی کامل" icon="lock" /> : !owned && <Chip label="رایگان" color={colors.greenDark} background={colors.greenSoft} />}
          </View>
        </View>
        <Animated.View style={[styles.chevronCircle, open && styles.chevronCircleOn, { transform: [{ rotate: turn.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '-180deg'] }) }] }]}>
          <Icon name="chevron-down" size={16} color={open ? colors.ink : colors.muted} />
        </Animated.View>
      </Pressable>
      {/* A quiet strip for what is the learner's own: time spent and the next review. Nothing when there is none. */}
      {(seconds >= 60 || !!review) && (
        <View style={styles.strip}>
          {seconds >= 60 ? (
            <View style={styles.stripItem}>
              <Icon name="time-spent" size={14} color={colors.muted} />
              <Text style={styles.stripText}>{studyDuration(seconds)} وقت گذاشتی</Text>
            </View>
          ) : (
            <View />
          )}
          {!!review &&
            (review.days > 0 ? (
              <View style={styles.stripItem}>
                <Icon name="calendar" size={14} color={colors.muted} />
                <Text style={styles.stripText}>مرور فصل: {toPersianDigits(review.days)} روز دیگر</Text>
              </View>
            ) : (
              // Its day has come (or passed): a tap starts the chapter's review, as the home page's tile does.
              <Pressable
                onPress={() =>
                  review.id &&
                  openReview({ kind: 'chapter', id: review.id, chapter_id: chapter.id } as ReviewItem).catch((e: Error) => toast(e.message || 'مرور شروع نشد.'))
                }
                accessibilityRole="button"
                accessibilityLabel={review.days === 0 ? 'مرور فصل، امروز' : 'مرور فصل، عقب افتاده'}
              >
                {review.days === 0 ? (
                  <Chip label="مرور فصل: امروز ←" icon="rotate-ccw" color={colors.ink} background={colors.lemon} />
                ) : (
                  <Chip label={`مرور فصل: ${toPersianDigits(-review.days)} روز عقب ←`} icon="rotate-ccw" color={colors.amberDark} background={colors.amberSoft} />
                )}
              </Pressable>
            ))}
        </View>
      )}
      {open && (
        <>
          {chapter.has_overview && (
            <Pressable onPress={() => router.push(`/section/${chapter.id}`)} style={({ pressed }) => [styles.section, pressed && { backgroundColor: colors.ground }]}>
              <Icon name="map" size={18} color={colors.greenDark} />
              <Text style={[styles.sectionTitle, rtl, { color: colors.greenDark }]}>مقدمه‌ی فصل</Text>
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
              {/* Only the practice this chapter actually has: no tests, no «تمرین کل فصل» and «آزمون». */}
              {!!tests && (
                <Pressable style={styles.action} onPress={() => router.push(`/quiz/${chapter.id}`)}>
                  <Text style={styles.actionText}>تمرین کل فصل</Text>
                </Pressable>
              )}
              {!!tests && (
                <Pressable style={styles.action} onPress={() => router.push(`/exam/${chapter.id}`)}>
                  <Text style={styles.actionText}>آزمون</Text>
                </Pressable>
              )}
              {!!cards && (
                <Pressable style={styles.action} onPress={() => router.push(`/flashcards/${chapter.id}`)}>
                  <Text style={styles.actionText}>فلش‌کارت</Text>
                </Pressable>
              )}
              <Pressable style={styles.action} onPress={() => router.push({ pathname: '/boxes/[nodeId]', params: { nodeId: String(chapter.id) } })}>
                <Text style={styles.actionText}>کادرها</Text>
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
      {section.badge === 'updated' && <Text style={styles.updated}>به‌روز شده</Text>}
      {section.is_locked ? (
        <Icon name="lock" size={16} color={colors.muted} />
      ) : (
        <Text style={styles.sectionMeta}>{`${toPersianDigits(section.question_count ?? 0)} تست، ${toPersianDigits(section.flashcard_count ?? 0)} کارت`}</Text>
      )}
    </Pressable>
  );
}

/** The top bar with the back, search and share buttons. */
const BAR_H = 58;

const styles = StyleSheet.create({
  scroll: { flexGrow: 1 },
  updated: { fontSize: 11, fontWeight: '800', color: '#4A3A9E', backgroundColor: '#E8E4FA', borderRadius: 999, paddingHorizontal: 8, paddingVertical: 1, overflow: 'hidden' },
  inkBack: { position: 'absolute', top: 0, left: 0, right: 0, backgroundColor: colors.ink },
  sheet: { flexGrow: 1, backgroundColor: colors.ground, borderTopLeftRadius: 28, borderTopRightRadius: 28, paddingBottom: 28, zIndex: 2 },
  bar: { position: 'absolute', top: 0, left: 0, right: 0, height: BAR_H, flexDirection: 'row-reverse', alignItems: 'center', gap: 10, paddingHorizontal: 16, zIndex: 2 },
  // Once the page covers the cover: a soft shadow under the bar, so the page seems to slide beneath it.
  barShade: { backgroundColor: colors.ink, shadowColor: '#000000', shadowOpacity: 0.28, shadowRadius: 10, shadowOffset: { width: 0, height: 4 }, elevation: 6 },
  barTitle: { textAlign: 'center', fontSize: 16, fontWeight: '900', color: '#FFFFFF' },
  page: { padding: 16, gap: 14, maxWidth: 760, width: '100%', alignSelf: 'center' },
  hero: { backgroundColor: colors.ink, paddingHorizontal: 16, paddingTop: 4, paddingBottom: 36, gap: 6, zIndex: 1 },
  heroButton: { width: 44, height: 44, borderRadius: 14, backgroundColor: 'rgba(255,255,255,0.08)', alignItems: 'center', justifyContent: 'center' },
  heroTitle: { marginTop: 10, textAlign: 'center', fontSize: 15, fontWeight: '800', color: '#FFFFFF' },
  // Equal boxes across the width of the cards below them, so their edges line up.
  stats: { flexDirection: 'row-reverse', gap: 8, marginTop: 16, width: '100%', maxWidth: 728, alignSelf: 'center' },
  stat: { flex: 1, alignItems: 'center', gap: 2, paddingVertical: 8, borderRadius: 12, backgroundColor: 'rgba(255,255,255,0.07)' },
  statValue: { fontSize: 18, fontWeight: '900', color: colors.lemon },
  statLabel: { fontSize: 12, color: '#C9D3CC' },
  ownedRibbon: { position: 'absolute', top: 12, left: -6, flexDirection: 'row-reverse', alignItems: 'center', gap: 4, backgroundColor: '#3FB8A9', paddingHorizontal: 8, paddingVertical: 3, borderTopLeftRadius: 6, borderTopRightRadius: 6, borderBottomRightRadius: 6 },
  ownedRibbonText: { fontSize: 11, fontWeight: '800', color: '#FFFFFF' },
  cta: { marginTop: -34, backgroundColor: colors.surface, borderRadius: radius.md, padding: 16, gap: 10, shadowColor: '#17201A', shadowOpacity: 0.12, shadowRadius: 18, shadowOffset: { width: 0, height: 8 }, elevation: 4 },
  ctaRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 14 },
  ctaHead: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  ctaTitle: { fontSize: 15, fontWeight: '800', color: colors.ink },
  ctaSmall: { fontSize: 12, color: colors.muted },
  priceDetails: { gap: 4, padding: 10, backgroundColor: colors.redSoft, borderRadius: 12 },
  priceLine: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  oldPrice: { color: colors.muted, textDecorationLine: 'line-through', fontSize: 12 },
  salePrice: { color: colors.redDark, fontSize: 14, fontWeight: '900' },
  saleAmountLine: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
  discountChip: { borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2, backgroundColor: colors.redDark, color: '#FFFFFF', fontSize: 10, fontWeight: '900', overflow: 'hidden' },
  samplePriceText: { color: colors.greenDark, fontWeight: '800' },
  saving: { textAlign: 'center', fontSize: 11, fontWeight: '800', color: colors.redDark },
  ctaButton: { backgroundColor: colors.lemon, borderRadius: 12, paddingHorizontal: 18, minHeight: 46, justifyContent: 'center' },
  ctaButtonText: { color: colors.ink, fontWeight: '900', fontSize: 15 },
  unlock: { minHeight: 52, borderRadius: radius.md, borderWidth: 1.5, borderColor: colors.ink, backgroundColor: colors.surface, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
  // The one main action of the box is lemon; next to «شروع رایگان» it is the outlined second.
  unlockMain: { backgroundColor: colors.lemon, borderColor: colors.lemon },
  unlockText: { fontSize: 15, fontWeight: '900', color: colors.ink },
  resumeLine: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, backgroundColor: colors.greenSoft, borderRadius: 12, paddingHorizontal: 12, minHeight: 44 },
  resumeLineText: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.greenDark },
  shortcuts: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  shortcut: { flexGrow: 1, flexBasis: '45%', minHeight: 46, borderRadius: 14, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, paddingHorizontal: 8 },
  timeRow: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 4 },
  timeText: { fontSize: 13, color: colors.muted },
  shortcutText: { fontSize: 13, fontWeight: '700', color: colors.ink },
  smallLink: { fontSize: 12, color: colors.muted, textDecorationLine: 'underline' },
  note: { fontSize: 13, color: colors.muted },
  pastRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingVertical: 6, borderTopWidth: 1, borderTopColor: colors.line },
  pastTitle: { fontSize: 14, fontWeight: '800', color: colors.ink },
  ready: { fontSize: 12, fontWeight: '800', color: colors.greenDark },
  pastRepeats: { gap: 6, paddingTop: 8, borderTopWidth: 1, borderTopColor: colors.line },
  pastNames: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 6 },
  pastBtn: { borderRadius: 999, borderWidth: 1, borderColor: colors.line, paddingHorizontal: 12, paddingVertical: 6 },
  pastBtnMain: { backgroundColor: colors.lemon, borderColor: colors.lemon },
  pastBtnText: { fontSize: 13, fontWeight: '800', color: colors.ink },
  // استایل‌های تب‌های سه‌گانه
  tabsContainer: { backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, overflow: 'hidden' },
  tabHeader: { flexDirection: 'row-reverse', borderBottomWidth: 1, borderBottomColor: colors.line, backgroundColor: colors.ground },
  tabButton: { flex: 1, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6, paddingVertical: 12 },
  tabButtonActive: { borderBottomWidth: 2.5, borderBottomColor: colors.ink, backgroundColor: colors.surface },
  tabButtonText: { fontSize: 13, fontWeight: '700', color: colors.muted },
  tabButtonTextActive: { color: colors.ink, fontWeight: '900' },
  tabContent: { padding: 16 },
  emptyNote: { fontSize: 13, color: colors.muted, textAlign: 'center', paddingVertical: 18 },
  // نویسنده
  authorHeader: { flexDirection: 'row-reverse', alignItems: 'center', gap: 14, paddingBottom: 12, borderBottomWidth: 1, borderBottomColor: colors.line },
  authorAvatar: { width: 54, height: 54, borderRadius: 27, backgroundColor: colors.ground, alignItems: 'center', justifyContent: 'center', borderWidth: 1, borderColor: colors.line },
  authorName: { fontSize: 16, fontWeight: '900', color: colors.ink },
  authorTitle: { fontSize: 12.5, fontWeight: '700', color: colors.greenDark },
  authorMetaRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, marginTop: 12 },
  authorMetaText: { fontSize: 12, color: colors.muted },
  // نظرات
  reviewStatsBox: { flexDirection: 'row-reverse', alignItems: 'center', gap: 14, backgroundColor: colors.ground, borderRadius: 12, padding: 14, marginBottom: 14 },
  reviewStatCol: { alignItems: 'center', gap: 2 },
  reviewBigScore: { fontSize: 28, fontWeight: '900', color: colors.ink },
  reviewSubLabel: { fontSize: 11, color: colors.muted },
  reviewStatDivider: { width: 1, height: 44, backgroundColor: colors.line },
  reviewHighlightRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
  reviewHighlightText: { fontSize: 12, color: colors.ink },
  writeReviewButton: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8, paddingVertical: 11, borderRadius: 12, backgroundColor: colors.ground, borderWidth: 1, borderColor: colors.line },
  writeReviewText: { fontSize: 13, fontWeight: '800', color: colors.ink },
  reviewFormBox: { backgroundColor: colors.ground, borderRadius: 12, padding: 12, gap: 10 },
  formTitle: { fontSize: 13, fontWeight: '800', color: colors.ink },
  starsSelectRow: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between' },
  starLabel: { fontSize: 12, color: colors.muted },
  textAreaWrap: { minHeight: 80, backgroundColor: colors.surface, borderRadius: 8, padding: 8, borderWidth: 1, borderColor: colors.line },
  singleReviewCard: { backgroundColor: colors.surface, borderRadius: 12, borderWidth: 1, borderColor: colors.line, padding: 12, gap: 8 },
  reviewUserHead: { flexDirection: 'row-reverse', alignItems: 'flex-start', justifyContent: 'space-between' },
  reviewUserName: { fontSize: 13.5, fontWeight: '800', color: colors.ink },
  studyBadge: { backgroundColor: '#e0f2fe', borderRadius: 6, paddingHorizontal: 6, paddingVertical: 2 },
  studyBadgeText: { fontSize: 10.5, fontWeight: '800', color: '#0369a1' },
  reviewDate: { fontSize: 11, color: colors.muted },
  reviewBodyText: { fontSize: 13, lineHeight: 1.8, color: colors.ink },
  teacherReplyBox: { backgroundColor: '#f0f9ff', borderRadius: 8, borderRightWidth: 3, borderRightColor: '#0284c7', padding: 10, marginTop: 4, gap: 4 },
  teacherReplyHead: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
  teacherReplyBadge: { fontSize: 11.5, fontWeight: '900', color: '#0284c7' },
  teacherReplyBody: { fontSize: 12.5, lineHeight: 1.8, color: '#0f172a' },

  // About four lines of the compact text (16px, line height 1.9).
  aboutBody: { overflow: 'hidden', ...(Platform.OS === 'web' ? ({ transitionProperty: 'max-height', transitionDuration: '260ms' } as object) : null) },
  aboutFolded: { maxHeight: 92 }, // three lines of the compact text (16px × 1.9)
  aboutBodyOpen: { maxHeight: 4000 },
  aboutFade: { position: 'absolute', left: 0, right: 0, bottom: 0 },
  aboutMore: { height: 44, borderRadius: 12, backgroundColor: colors.ground, alignItems: 'center', justifyContent: 'center' },
  aboutMoreText: { fontSize: 14, fontWeight: '700', color: colors.greenDark },
  about: { backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 14, gap: 6 },
  aboutHead: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', gap: 10 },
  aboutActions: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  chevronCircle: { width: 26, height: 26, borderRadius: 13, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface, alignItems: 'center', justifyContent: 'center' },
  chevronCircleOn: { backgroundColor: colors.lemon, borderColor: colors.lemon },
  aboutTitle: { fontSize: 15, fontWeight: '900', color: colors.ink },
  chaptersTitle: { fontSize: 18, fontWeight: '900', color: colors.ink, marginTop: 6 },
  chapter: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, overflow: 'hidden' },
  chapterHead: { flexDirection: 'row-reverse', alignItems: 'center', padding: 16, gap: 12 },
  strip: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', gap: 8, paddingHorizontal: 16, paddingVertical: 8, minHeight: 40, backgroundColor: '#F9FAF5', borderTopWidth: 1, borderTopColor: colors.line },
  metaRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  stripItem: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
  stripText: { fontSize: 12, color: colors.muted },
  group: { fontSize: 12.5, fontWeight: '800', color: colors.muted, paddingHorizontal: 16, paddingTop: 14, paddingBottom: 6, borderTopWidth: 1, borderTopColor: colors.line, backgroundColor: colors.ground },
  glossary: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, alignSelf: 'flex-end', paddingHorizontal: 12, paddingVertical: 7, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line },
  glossaryText: { fontSize: 13, fontWeight: '700', color: colors.ink },
  resume: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, padding: 12 },
  resumeLabel: { fontSize: 12, color: colors.muted },
  resumeTitle: { fontSize: 15, fontWeight: '800', color: colors.ink },
  chapterTitle: { flex: 1, fontSize: 18, fontWeight: '800', color: colors.ink },
  section: { flexDirection: 'row-reverse', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 14, borderTopWidth: 1, borderTopColor: colors.line, gap: 10 },
  check: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: colors.line, alignItems: 'center', justifyContent: 'center' },
  checkOn: { backgroundColor: colors.green, borderColor: colors.green },
  checkRead: { borderColor: colors.lemon, overflow: 'hidden', alignItems: 'flex-end' },
  half: { width: '50%', height: '100%', backgroundColor: colors.lemon },
  checkMark: { color: '#fff', fontSize: 12, fontWeight: '700' },
  sectionTitle: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.ink },
  sectionMeta: { fontSize: 12, color: colors.muted, flexShrink: 0 },
  reviewLine: { fontSize: 12, fontWeight: '700', color: colors.greenDark },
  // Two by two, so «تمرین کل فصل» never wraps on a small phone.
  actions: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: colors.line },
  action: { flexGrow: 1, flexBasis: '45%', backgroundColor: colors.ground, borderRadius: 12, paddingVertical: 12, alignItems: 'center' },
  actionText: { fontWeight: '700', color: colors.ink, fontSize: 15 },
});

/** A short «درباره‌ی کتاب» (about three lines) is shown whole, without «بیشتر». */
function shortAbout(md: string): boolean {
  const lines = md.split('\n').filter((l) => l.trim());
  const text = lines.join(' ').replace(/[#*_>`\[\]()|-]/g, '').trim();
  return lines.length <= 3 && text.length <= 200;
}
