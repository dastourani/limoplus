import { shelfLabel } from '../../lib/access';
import { setViewAsLearner, useViewAsLearner } from '../../lib/viewAs';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { FlatList, Linking, Pressable, StyleSheet, useWindowDimensions, View } from 'react-native';

import { endpoints, type Library, type Today, type BookListItem } from '../../api/endpoints';
import { BannerCarousel } from '../../components/BannerCarousel';
import { BookCover } from '../../components/BookCover';
import { Icon, IconBadge } from '../../components/Icon';
import { LemonProgress } from '../../components/LemonProgress';
import { LemonSlice } from '../../components/LemonSlice';
import { Text } from '../../components/Text';
import { ErrorState, Loading, Screen, usePullRefresh, Chip } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { useFeedback } from '../../components/Feedback';
import { HRow } from '../../components/home/HRow';
import { ReadingCards, type ReadingItem } from '../../components/home/ReadingCards';
import { SectionHeader } from '../../components/home/SectionHeader';
import { TodayTiles } from '../../components/home/TodayTiles';
import { storage, type ReadingSpot } from '../../lib/storage';
import { keepIfSame, useApi } from '../../lib/useApi';
import { colors, formatToman, radius, rtl, toPersianDigits } from '../../theme';


/** Read sections as lemon wedges, from a book's share read (0–1) and its number of sections. */
function wedges(progress: number | null, count: number) {
  const n = Math.max(1, Math.min(count || 10, 24));
  const done = Math.round((progress ?? 0) * n);
  return Array.from({ length: n }, (_, i) => (i < done ? ('done' as const) : ('empty' as const)));
}

export default function Home() {
  const { user } = useAuth();
  const { width } = useWindowDimensions();
  const asLearner = useViewAsLearner();
  const { toast } = useFeedback();
  // While the page is being scrolled the banners don't turn by themselves (a turn mid-scroll made it jump).
  const pageScrolling = useRef(false);
  const [idle, setIdle] = useState(false);
  useEffect(() => {
    let idleId: number | undefined;
    const t = setTimeout(() => {
      if (typeof requestIdleCallback === 'function') idleId = requestIdleCallback(() => setIdle(true), { timeout: 1500 });
      else setIdle(true);
    }, 600);
    return () => {
      clearTimeout(t);
      if (idleId !== undefined && typeof cancelIdleCallback === 'function') cancelIdleCallback(idleId);
    };
  }, []);
  const [spots, setSpots] = useState<Record<string, ReadingSpot>>({});
  const [serverReading, setServerReading] = useState<Library['reading']>([]);
  useFocusEffect(
    useCallback(() => {
      if (user) endpoints.library().then((l) => setServerReading(keepIfSame(l.reading))).catch(() => undefined);
      else setServerReading(keepIfSame<Library['reading']>([]));
    }, [user]),
  );

  useFocusEffect(
    useCallback(() => {
      storage.getReading().then((r) => setSpots(keepIfSame(r)));
    }, []),
  );

  // «قفسه‌ها»: one row per subject, set in the panel; books on no shelf come last.
  const books = useApi(() => endpoints.shelves(), [user?.id, asLearner]);
  const banners = useApi(() => endpoints.banners(), [user?.id]);
  const [today, setToday] = useState<Today | null>(null);
  useFocusEffect(
    useCallback(() => {
      if (user) {
        endpoints.today().then((t) => setToday(keepIfSame<Today | null>(t))).catch(() => undefined);
      } else {
        setToday(null);
      }
    }, [user]),
  );
  // Back from a book or a payment: progress and ownership may have changed.
  const [focused, setFocused] = useState(0);
  useFocusEffect(useCallback(() => setFocused((n) => n + 1), []));
  useEffect(() => {
    if (focused > 1) books.retry();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focused]);


  const [notify, setNotify] = useState<Record<string, { on: boolean; canCancel: boolean }>>({});
  const notifyState = (book: BookListItem) => notify[book.slug] ?? { on: book.notify, canCancel: !!book.notify_can_cancel };
  const toggleNotify = async (book: BookListItem) => {
    if (!requireLogin(user, 'برای «خبرم کن» وارد شوید تا وقتی کتاب آماده شد خبرتان کنیم.')) return;
    const now = notifyState(book);
    if (now.on && !now.canCancel) return; // asked again after a cancel: stays on
    const on = !now.on;
    setNotify((n) => ({ ...n, [book.slug]: { on, canCancel: on } })); // the server's answer settles it
    endpoints
      .notifyBook(book.slug, on)
      .then((r) => setNotify((n) => ({ ...n, [book.slug]: { on: r.notify, canCancel: r.can_cancel } })))
      .catch(() => setNotify((n) => ({ ...n, [book.slug]: now })));
  };

  const refresh = usePullRefresh(books.loading, () => {
    books.retry();
    banners.retry();
  });


  const openLink = (link: string, id: number) => {
    endpoints.bannerClick(id).catch(() => undefined);
    if (link.startsWith('book/')) router.push(`/book/${link.slice(5)}`);
    else if (link.startsWith('buy/')) router.push(`/buy/${link.slice(4)}`);
    else if (link.startsWith('exam/')) router.push(`/exam/${link.slice(5)}`);
    else if (link === 'review') router.push('/review');
    else if (/^https?:\/\//.test(link)) Linking.openURL(link);
  };

  const shelves = useMemo(() => books.data ?? [], [books.data]);
  const list = useMemo(() => shelves.flatMap((s) => s.books), [shelves]);
  // Books being read, newest first: this phone's own spots, and (signed in) the account's from other devices.
  const reading = useMemo(() => {
    const bySlug = new Map<string, ReadingItem & { at: number }>();
    for (const r of serverReading)
      bySlug.set(r.book_slug, { slug: r.book_slug, bookTitle: r.book_title, id: r.last_section.id, title: r.last_section.title, at: Date.parse(r.updated_at), book: r.book, next: r.next });
    for (const s of Object.values(spots)) {
      const had = bySlug.get(s.bookSlug);
      // This phone's own spot is newer: the account's «next section» still counts if it is the same section.
      if (!had || s.at >= had.at)
        bySlug.set(s.bookSlug, { slug: s.bookSlug, bookTitle: s.bookTitle, id: s.id, title: s.title, at: s.at, book: had?.book, next: had?.id === s.id ? had.next : null });
    }
    return [...bySlug.values()]
      .map((r) => ({ ...r, book: list.find((b) => b.slug === r.slug) ?? r.book }))
      .filter((r) => !(r.book?.progress != null && r.book.progress >= 1)) // finished books leave the row
      .sort((a, b) => b.at - a.at);
  }, [serverReading, spots, list]);
  // A shelf row shows about two and a half covers on a phone (the cut one says «there is more»), more on wide screens.
  const pageWidth = Math.min(width, 1200);
  const coverWidth = Math.max(120, Math.min(170, Math.floor((pageWidth - 32) / 2.4)));

  const bookTile = (book: BookListItem) => {
    const label = shelfLabel(book);
    const { on: waiting, canCancel } = notifyState(book);
    return (
      <View style={{ width: coverWidth, gap: 8 }}>
        <Pressable
          onPress={() => router.push({ pathname: '/book/[slug]', params: { slug: book.slug } })}
          accessibilityRole="button"
          accessibilityLabel={`${book.title}${book.is_coming_soon ? '، به‌زودی' : ''}`}
          style={({ pressed }) => [{ opacity: book.is_coming_soon ? 0.75 : 1 }, pressed && { transform: [{ scale: 0.97 }] }]}
        >
          <BookCover book={book} major={book.major ?? null} width={coverWidth} />
          <View style={[styles.ribbon, RIBBON[label.kind].box]}>
            {RIBBON[label.kind].icon && <Icon name={RIBBON[label.kind].icon!} size={12} color={RIBBON[label.kind].color} />}
            <Text style={[styles.ribbonText, { color: RIBBON[label.kind].color }]}>{label.text}</Text>
          </View>
          {book.progress != null && (
            <View style={styles.progressBadge}>
              <LemonProgress parts={wedges(book.progress, book.section_count)} size={18} />
              <Text style={styles.progressText}>{toPersianDigits(Math.round(book.progress * 100))}٪</Text>
            </View>
          )}
        </Pressable>
        {book.is_coming_soon ? (
          <Pressable
            onPress={() => toggleNotify(book)}
            disabled={waiting && !canCancel}
            style={[styles.notify, waiting && styles.notifyOn]}
            accessibilityRole="button"
            accessibilityState={{ selected: waiting }}
          >
            <Icon name={waiting ? 'bell-ring' : 'bell'} size={15} color={colors.ink} />
            <Text style={styles.notifyText}>{waiting ? (canCancel ? 'خبرت می‌کنیم' : 'خبرت می‌کنیم ✓') : 'خبرم کن'}</Text>
          </Pressable>
        ) : (
          <Text style={styles.price} numberOfLines={1}>
            {book.owned ? 'در دسترس تو' : book.all_free || !book.price ? 'رایگان' : `${formatToman(book.price)}، یا با اشتراک`}
          </Text>
        )}
      </View>
    );
  };

  // The page is a lazy list: each section is made only when it comes near the screen, so the shelves far below don't
  // slow down the top, and a section off screen doesn't redraw.
  const blocks: { key: string; el: ReactNode }[] = [
    {
      key: 'top',
      el: (
        <View style={{ gap: 12 }}>
        <View style={styles.top}>
          <LemonSlice size={36} />
          <View style={{ flex: 1 }}>
            <Text style={[styles.hello, rtl]}>سلام{user?.first_name ? ` ${user.first_name}` : ''}!</Text>
            <Text style={[styles.muted, rtl]}>امروز کدام لیمو را می‌خوانی؟</Text>
          </View>
          <Pressable onPress={() => router.push('/search')} style={styles.searchButton} accessibilityRole="button" accessibilityLabel="جست‌وجو">
            <Icon name="search" size={22} color={colors.ink} />
          </Pressable>
          {!user && (
            <Pressable onPress={() => router.push('/login')} style={styles.loginPill} accessibilityRole="button">
              <Text style={styles.loginText}>ورود</Text>
            </Pressable>
          )}
        </View>

        {asLearner && (
          <Pressable onPress={() => setViewAsLearner(false)} style={styles.asLearner} accessibilityRole="button">
            <Text style={styles.asLearnerText}>نمایش مثل کاربر عادی روشن است؛ برای خاموش کردن بزنید</Text>
          </Pressable>
        )}
        </View>
      ),
    },
  ];
  if (reading.length > 0)
    blocks.push({
      key: 'reading',
      el: (
        <View style={styles.section}>
            <SectionHeader title="ادامه‌ی خواندن" side={reading.length > 1 ? `${toPersianDigits(reading.length)} کتاب` : undefined} />
            <ReadingCards items={reading} />
          </View>
      ),
    });
  if (user && today)
    blocks.push({
      key: 'today',
      el: (
        <View style={styles.section}>
            <SectionHeader
              title="کارهای امروز"
              sub={
                today.tasks?.length
                  ? `${toPersianDigits(today.tasks.length)} کار، حدود ${toPersianDigits(today.minutes)} دقیقه`
                  : null
              }
              side={
                <Pressable onPress={() => router.push('/quick')} style={styles.quick} accessibilityRole="button" accessibilityLabel="فقط ۵ دقیقه وقت دارم">
                  <Icon name="timer" size={15} color={colors.ink} />
                  <Text style={styles.quickText}>۵ دقیقه وقت دارم</Text>
                </Pressable>
              }
            />
            {today.comeback && (
              <Text style={[styles.note, rtl]}>
                خوش برگشتی! {toPersianDigits(today.away_days)} روز نبودی؛ یک شروع کوتاه برایت چیدیم، نه همه‌ی کارهای عقب‌افتاده.
              </Text>
            )}
            <TodayTiles tasks={today.tasks ?? []} onError={() => toast('شروع مرور ممکن نشد؛ دوباره امتحان کن.')} />
            {!!today.reviews_waiting && (
              <Text style={[styles.note, rtl]}>{toPersianDigits(today.reviews_waiting)} مرور دیگر هم منتظر است؛ فردا نوبت آن‌هاست.</Text>
            )}
          </View>
      ),
    });
  if (user && today?.needs_review?.items.length)
    blocks.push({
      key: 'needs-review',
      el: (
        <View style={styles.section}>
          <SectionHeader title="نیاز به مرور" sub="بخش‌هایی که یک نگاه دوباره می‌خواهند" />
          <View style={styles.needsList}>
            {today.needs_review.items.map((item, i) => (
              <Pressable
                key={item.id}
                onPress={() => router.push(`/section/${item.id}`)}
                style={[styles.needsRow, i > 0 && styles.needsRowLine]}
                accessibilityRole="button"
              >
                <Icon name={item.reason === 'mistakes' ? 'notebook-pen' : 'rotate-ccw'} size={18} color={item.reason === 'mistakes' ? colors.red : colors.muted} />
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={[styles.needsTitle, rtl]} numberOfLines={1}>{item.title}</Text>
                  <Text style={[styles.needsSub, rtl]} numberOfLines={1}>
                    {item.reason === 'mistakes'
                      ? `${toPersianDigits(item.mistakes)} تست غلط مانده`
                      : `${toPersianDigits(item.days)} روز پیش خواندی`}
                    {`، ${item.book_title}`}
                  </Text>
                </View>
                <Icon name="chevron-left" size={18} color={colors.muted} />
              </Pressable>
            ))}
          </View>
        </View>
      ),
    });
  if (banners.data?.length)
    blocks.push({
      key: 'banners',
      el: (
        <View style={styles.section}>
            <SectionHeader title="تازه‌های لیمو" />
            <BannerCarousel banners={banners.data!} onOpen={(b) => openLink(b.link, b.id)} paused={pageScrolling} />
          </View>
      ),
    });
  if (books.loading && !list.length) blocks.push({ key: 'loading', el: <Loading /> });
  else if (books.error) blocks.push({ key: 'error', el: <ErrorState message={books.error.message} onRetry={books.retry} /> });
  else if (list.length === 0) blocks.push({ key: 'empty', el: <Text style={[styles.muted, rtl]}>هنوز کتابی منتشر نشده است.</Text> });
  else
    for (const shelf of shelves)
      blocks.push({
        key: `shelf-${shelf.id ?? 'rest'}`,
        el: (
          <View style={styles.section}>
            <SectionHeader title={shelf.title} side={`${toPersianDigits(shelf.books.length)} کتاب`} />
            <HRow data={shelf.books} keyOf={(b) => b.slug} render={bookTile} gap={14} />
          </View>
        ),
      });
  blocks.push({
    key: 'soon',
    el: (
        <View style={styles.soon}>
          <View style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 8, flex: 1 }}>
            <IconBadge name="sparkles" size={32} />
            <Text style={[styles.soonText, rtl, { flex: 1 }]}>دستیار هوش مصنوعی برای رفع اشکال</Text>
          </View>
          <Chip label="به‌زودی" color="#6B5200" background={colors.lemonSoft} />
        </View>
    ),
  });

  return (
    <Screen tab>
      <FlatList
        data={blocks}
        keyExtractor={(b) => b.key}
        renderItem={({ item }) => <>{item.el}</>}
        contentContainerStyle={styles.page}
        refreshControl={refresh}
        initialNumToRender={4}
        // First the top of the page; a moment later, while the phone is idle, the shelves below are made too, so
        // scrolling down meets them ready (with many shelves, a few screens ahead are kept ready).
        windowSize={idle ? 21 : 5}
        maxToRenderPerBatch={1}
        updateCellsBatchingPeriod={120}
        onScrollBeginDrag={() => (pageScrolling.current = true)}
        onMomentumScrollEnd={() => (pageScrolling.current = false)}
        onScrollEndDrag={(e) => {
          if (!e.nativeEvent.velocity || Math.abs(e.nativeEvent.velocity.y) < 0.05) pageScrolling.current = false;
        }}
      />
    </Screen>
  );
}

/** One look per kind of shelf label. */
const RIBBON: Record<'soon' | 'access' | 'free' | 'locked', { box: object; color: string; icon?: 'circle-check' | 'lock' | 'gift' }> = {
  soon: { box: { backgroundColor: '#8A938C' }, color: '#FFFFFF' },
  access: { box: { backgroundColor: '#3FB8A9' }, color: '#FFFFFF', icon: 'circle-check' },
  free: { box: { backgroundColor: colors.lemon }, color: colors.ink, icon: 'gift' },
  locked: { box: { backgroundColor: colors.ink }, color: colors.ground, icon: 'lock' },
};


const styles = StyleSheet.create({
  needsList: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, overflow: 'hidden' },
  needsRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, paddingHorizontal: 14, paddingVertical: 12 },
  needsRowLine: { borderTopWidth: 1, borderTopColor: colors.line },
  needsTitle: { fontSize: 15, fontWeight: '800', color: colors.ink },
  needsSub: { fontSize: 12, color: colors.muted },
  section: { gap: 10, marginTop: 8 },
  note: { fontSize: 12, color: colors.muted, lineHeight: 20 },
  quick: { flexDirection: 'row-reverse', alignItems: 'center', gap: 5, backgroundColor: colors.lemon, borderRadius: 999, paddingHorizontal: 11, paddingVertical: 7 },
  quickText: { fontSize: 12, fontWeight: '800', color: colors.ink },
  searchButton: { width: 44, height: 44, borderRadius: 14, backgroundColor: colors.lemon, alignItems: 'center', justifyContent: 'center' },
  asLearner: { backgroundColor: '#FFF6CC', borderRadius: 12, paddingVertical: 8, paddingHorizontal: 12 },
  asLearnerText: { fontSize: 12, fontWeight: '700', color: colors.ink, textAlign: 'center' },
  page: { padding: 16, gap: 16, maxWidth: 1200, width: '100%', alignSelf: 'center' },
  top: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10 },
  hello: { fontSize: 22, fontWeight: '900', color: colors.ink },
  muted: { fontSize: 13, color: colors.muted },
  loginPill: { backgroundColor: colors.ink, borderRadius: 999, paddingHorizontal: 18, paddingVertical: 10 },
  loginText: { color: colors.lemon, fontWeight: '800' },
  ribbon: { position: 'absolute', top: 12, left: -4, flexDirection: 'row-reverse', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderTopLeftRadius: 6, borderTopRightRadius: 6, borderBottomRightRadius: 6 },
  ribbonText: { fontSize: 11, fontWeight: '800' },
  ribbonFree: { backgroundColor: colors.lemon, color: colors.ink },
  ribbonSoon: { backgroundColor: colors.ink, color: colors.ground },
  ribbonOwned: { backgroundColor: '#3FB8A9', flexDirection: 'row-reverse', alignItems: 'center', gap: 4 },
  ribbonOwnedText: { fontSize: 11, fontWeight: '800', color: '#FFFFFF' },
  progressBadge: { position: 'absolute', bottom: 10, left: 10, flexDirection: 'row-reverse', alignItems: 'center', gap: 5, backgroundColor: 'rgba(23,32,26,0.88)', borderRadius: 10, paddingHorizontal: 7, paddingVertical: 3 },
  progressText: { fontSize: 11, fontWeight: '800', color: colors.lemon },
  notify: { minHeight: 38, borderRadius: 12, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6 },
  notifyOn: { backgroundColor: colors.lemonSoft, borderColor: colors.lemon },
  notifyText: { fontSize: 12, fontWeight: '700', color: colors.ink },
  price: { fontSize: 12, color: colors.muted, minHeight: 38, textAlignVertical: 'center', textAlign: 'center', writingDirection: 'rtl' },
  soon: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', borderWidth: 1, borderStyle: 'dashed', borderColor: '#B9C4BC', borderRadius: 14, padding: 12 },
  soonText: { color: colors.muted, fontSize: 13 },
});
