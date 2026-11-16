import { shelfLabel } from '../../lib/access';
import { setViewAsLearner, useViewAsLearner } from '../../lib/viewAs';
import { router, useFocusEffect } from 'expo-router';
import { Fragment, useCallback, useEffect, useMemo, useRef, useState, type ReactElement, type ReactNode } from 'react';
import { FlatList, Linking, Pressable, ScrollView, StyleSheet, useWindowDimensions, View } from 'react-native';
import { useHomeMax, useWide } from '../../lib/layout';

import { endpoints, type Library, type Today, type BookListItem, type Shelf, type SitePageItem, type TodayTask } from '../../api/endpoints';
import { changedPages } from '../../lib/pages';
import { studyDuration } from '../../lib/duration';
import { BannerCarousel } from '../../components/BannerCarousel';
import { BookCover } from '../../components/BookCover';
import { Icon } from '../../components/Icon';
import { LemonSlice } from '../../components/LemonSlice';
import { Text } from '../../components/Text';
import { ErrorState, Loading, Screen, usePullRefresh, Chip } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { useFeedback } from '../../components/Feedback';
import { HRow } from '../../components/home/HRow';
import { ReadingCards, type ReadingItem } from '../../components/home/ReadingCards';
import { SectionHeader } from '../../components/home/SectionHeader';
import { TodayTiles } from '../../components/home/TodayTiles';
import { BookPill } from '../../components/home/BookPill';
import { storage, type ReadingSpot } from '../../lib/storage';
import { keepIfSame, useApi } from '../../lib/useApi';
import { colors, radius, rtl, toPersianDigits } from '../../theme';


export default function Home() {
  const { user } = useAuth();
  const wide = useWide();
  const homeMax = useHomeMax();
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
  // «اصلاح شد، ممنون»: the learner's reports fixed in the panel since last time (each said once).
  useFocusEffect(
    useCallback(() => {
      if (!user) return;
      endpoints
        .reportsFixed()
        .then(({ fixed }) => {
          if (!fixed.length) return;
          const first = fixed[0].about.replace(/\$[^$]*\$/g, '…').slice(0, 50);
          toast(
            fixed.length === 1
              ? `اشکالی که گزارش دادی («${first}») اصلاح شد. ممنون!`
              : `${toPersianDigits(fixed.length)} اشکالی که گزارش دادی اصلاح شد. ممنون!`,
          );
        })
        .catch(() => undefined);
    }, [user, toast]),
  );
  // «قوانین به‌روز شد»: a site page with an important change the learner has not opened since.
  const [changedPage, setChangedPage] = useState<SitePageItem | null>(null);
  useFocusEffect(
    useCallback(() => {
      endpoints
        .appPages()
        .then((p) => changedPages(p.pages))
        .then((c) => setChangedPage(c[0] ?? null))
        .catch(() => undefined);
    }, []),
  );
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
      bySlug.set(r.book_slug, { slug: r.book_slug, bookTitle: r.book_title, id: r.last_section.id, title: r.last_section.title, at: Date.parse(r.updated_at), book: r.book, next: r.next, chapter: r.chapter });
    for (const s of Object.values(spots)) {
      const had = bySlug.get(s.bookSlug);
      // This phone's own spot is newer: the account's «next section» still counts if it is the same section.
      if (!had || s.at >= had.at)
        bySlug.set(s.bookSlug, { slug: s.bookSlug, bookTitle: s.bookTitle, id: s.id, title: s.title, at: s.at, book: had?.book, next: had?.id === s.id ? had.next : null, chapter: s.chapter ?? (had?.id === s.id ? had.chapter : null) });
    }
    return [...bySlug.values()]
      .map((r) => ({ ...r, book: list.find((b) => b.slug === r.slug) ?? r.book }))
      .filter((r) => !(r.book?.progress != null && r.book.progress >= 1)) // finished books leave the row
      .sort((a, b) => b.at - a.at);
  }, [serverReading, spots, list]);
  // A shelf row shows about two and a half covers on a phone (the cut one says «there is more»), more on wide screens.
  const pageWidth = Math.min(width, 1200);
  const [readingOpen, setReadingOpen] = useState(false);
  const [shelfFilter, setShelfFilter] = useState<string | undefined>(undefined);
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
        </Pressable>
        <BookPill book={book} notify={{ on: waiting, canCancel }} onNotify={() => toggleNotify(book)} />
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
            <Text style={[styles.muted, rtl]}>{greetLine(today?.week)}</Text>
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

        {!!changedPage && (
          <Pressable
            onPress={() => router.push({ pathname: '/page/[slug]', params: { slug: changedPage.slug } })}
            style={styles.changed}
            accessibilityRole="link"
          >
            <Icon name="bell" size={16} color={colors.ink} />
            <Text style={[styles.changedText, rtl]}>«{changedPage.title}» به‌روز شد؛ ببین چه تغییر کرده است</Text>
            <Icon name="chevron-left" size={16} color={colors.muted} />
          </Pressable>
        )}
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
            <SectionHeader icon="book-open" title="ادامه‌ی خواندن" side={reading.length > 1 ? `${toPersianDigits(reading.length)} کتاب` : undefined} />
            <ReadingCards items={readingOpen ? reading : reading.slice(0, 3)} stacked={readingOpen} />
            {reading.length > 3 && (
              <Pressable onPress={() => setReadingOpen((v) => !v)} style={styles.moreRow} accessibilityRole="button">
                <Text style={styles.moreText}>{readingOpen ? 'بستن ▴' : `همه‌ی کتاب‌هایی که می‌خوانی (${toPersianDigits(reading.length)}) ▾`}</Text>
              </Pressable>
            )}
            {!user && (
              // A guest's place lives only on this device: a separate, quiet link to keep it everywhere.
              <Pressable onPress={() => router.push('/login')} style={styles.guestLink} accessibilityRole="link">
                <Text style={[styles.guestLinkText, rtl]}>جای خواندنت فقط روی همین دستگاه است؛ برای نگه داشتنش در همه‌جا وارد شو ←</Text>
              </Pressable>
            )}
          </View>
      ),
    });
  if (user && today && (today.tasks?.length || today.needs_review?.items.length || today.comeback))
    blocks.push({
      key: 'today',
      el: (
        <View style={styles.section}>
          <SectionHeader
            icon="list-checks"
            title="برنامه‌ی امروز"
            sub={today.tasks?.length ? `${toPersianDigits(today.tasks.length)} کار، حدود ${toPersianDigits(today.minutes)} دقیقه` : null}
            side={
              <Pressable onPress={() => router.push('/quick')} style={styles.quick} accessibilityRole="button" accessibilityLabel="فقط ۵ دقیقه وقت دارم">
                <Icon name="timer" size={15} color={colors.ink} />
                <Text style={styles.quickText}>۵ دقیقه وقت دارم</Text>
              </Pressable>
            }
          />
          {/* One card for the day: the planned jobs, then the sections that want another look. */}
          <View style={styles.planCard}>
            <PlanProgress tasks={today.tasks ?? []} />
            {today.comeback && (
              <Text style={[styles.note, rtl]}>
                خوش برگشتی! {toPersianDigits(today.away_days)} روز نبودی؛ یک شروع کوتاه برایت چیدیم، نه همه‌ی کارهای عقب‌افتاده.
              </Text>
            )}
            <TodayTiles tasks={today.tasks ?? []} onError={() => toast('شروع مرور ممکن نشد؛ دوباره امتحان کن.')} />
            {!!today.needs_review?.items.length && (
              <View style={styles.needsList}>
                <Text style={[styles.planSub, rtl]}>یک نگاه دوباره</Text>
                {today.needs_review.items.map((item, i) => (
                  <Pressable
                    key={item.id}
                    onPress={() =>
                      // Wrong answers: just those tests; a section read long ago: the section itself.
                      item.reason === 'mistakes' && item.question_ids?.length
                        ? router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: String(item.id), ids: item.question_ids.join(',') } })
                        : router.push(`/section/${item.id}`)
                    }
                    style={[styles.needsRow, i > 0 && styles.needsRowLine]}
                    accessibilityRole="button"
                  >
                    <Icon name={item.reason === 'mistakes' ? 'notebook-pen' : 'rotate-ccw'} size={18} color={item.reason === 'mistakes' ? colors.red : colors.muted} />
                    <View style={{ flex: 1, gap: 2 }}>
                      <Text style={[styles.needsTitle, rtl]} numberOfLines={1}>{item.title}</Text>
                      <Text style={[styles.needsSub, rtl]} numberOfLines={1}>
                        {item.reason === 'mistakes' ? `${toPersianDigits(item.mistakes)} تست غلط مانده` : `${toPersianDigits(item.days)} روز پیش خواندی`}
                        {`، ${item.book_title}`}
                      </Text>
                    </View>
                    <Icon name="chevron-left" size={18} color={colors.muted} />
                  </Pressable>
                ))}
              </View>
            )}
            {!!today.reviews_waiting && (
              <Text style={[styles.note, rtl]}>{toPersianDigits(today.reviews_waiting)} مرور دیگر هم منتظر است؛ فردا نوبت آن‌هاست.</Text>
            )}
          </View>
        </View>
      ),
    });
  if (!user)
    blocks.push({
      key: 'welcome',
      el: (
        // A guest: no plan or progress yet; one friendly way in instead.
        <View style={[styles.planCard, styles.welcome]}>
          <LemonSlice size={40} />
          <View style={{ flex: 1, gap: 4 }}>
            <Text style={[styles.welcomeTitle, rtl]}>خوش آمدی! یک بخش رایگان را بخوان.</Text>
            <Text style={[styles.needsSub, rtl]}>با ورود، برنامه‌ی روزانه، مرورها و پیشرفتت این‌جا می‌آید.</Text>
            <Pressable onPress={() => router.push('/login')} accessibilityRole="link">
              <Text style={[styles.guestLinkText, rtl]}>ورود یا ثبت‌نام ←</Text>
            </Pressable>
          </View>
        </View>
      ),
    });
  if (banners.data?.length)
    blocks.push({
      key: 'banners',
      el: (
        <View style={styles.section}>
            <SectionHeader icon="sparkles" title="تازه‌های لیمو" />
            <BannerCarousel banners={banners.data!} onOpen={(b) => openLink(b.link, b.id)} paused={pageScrolling} frameWidth={wide ? SIDE_INNER : undefined} />
          </View>
      ),
    });
  if (books.loading && !list.length) blocks.push({ key: 'loading', el: <Loading /> });
  else if (books.error) blocks.push({ key: 'error', el: <ErrorState message={books.error.message} onRetry={books.retry} /> });
  else if (list.length === 0) blocks.push({ key: 'empty', el: <Text style={[styles.muted, rtl]}>هنوز کتابی منتشر نشده است.</Text> });
  else {
    // «کتاب‌ها»: a clear line between the learner's own day above and the catalogue below, with one chip per shelf.
    blocks.push({
      key: 'books-head',
      el: (
        <View style={styles.booksHead}>
          <View style={{ flexDirection: 'row-reverse', alignItems: 'baseline', gap: 8 }}>
            <Text style={[styles.booksTitle, rtl]}>کتاب‌ها</Text>
            <Text style={styles.muted}>{toPersianDigits(list.length)} کتاب</Text>
          </View>
          {shelves.length > 1 && (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
              {[{ key: '', title: 'همه' }, ...shelves.map((x) => ({ key: shelfKey(x), title: x.title }))].map((c) => {
                const on = (shelfFilter ?? '') === c.key;
                return (
                  <Pressable
                    key={c.key || 'all'}
                    onPress={() => setShelfFilter(c.key || undefined)}
                    style={[styles.chip, on && styles.chipOn]}
                    accessibilityRole="button"
                    accessibilityState={{ selected: on }}
                  >
                    <Text style={[styles.chipText, on && { color: colors.ink }]}>{c.title}</Text>
                  </Pressable>
                );
              })}
            </ScrollView>
          )}
        </View>
      ),
    });
    for (const shelf of shelves.filter((x) => shelfFilter === undefined || shelfKey(x) === shelfFilter))
      blocks.push({
        key: `shelf-${shelf.id ?? 'rest'}`,
        el: <ShelfBlock shelf={shelf} tile={bookTile} coverWidth={coverWidth} wide={wide} />,
      });
  }
  blocks.push({
    key: 'soon',
    el: (
        <View style={styles.soon}>
          <View style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 8, flex: 1 }}>
            <Icon name="sparkles" size={16} color={colors.muted} />
            <Text style={[styles.soonText, rtl, { flex: 1 }]}>دستیار هوش مصنوعی برای رفع اشکال</Text>
          </View>
          <Chip label="به‌زودی" color="#6B5200" background={colors.lemonSoft} />
        </View>
    ),
  });

  // A computer: today's jobs and «نیاز به مرور» in a column beside the books.
  if (wide) {
    // «تازه‌های لیمو» under today's jobs: one frame that turns by itself.
    const side = new Set(['today', 'welcome', 'banners']);
    return (
      <Screen tab wide wideMax={homeMax}>
        {/* The books scroll; the side column stays in place and scrolls on its own when it is taller than the window. */}
        <View style={styles.wide}>
          <ScrollView style={{ flex: 1 }} contentContainerStyle={styles.wideMain} refreshControl={refresh}>
            {blocks.filter((b) => !side.has(b.key)).map((b) => (
              <Fragment key={b.key}>{b.el}</Fragment>
            ))}
          </ScrollView>
          <ScrollView style={styles.wideSide} contentContainerStyle={styles.wideSideInner} showsVerticalScrollIndicator={false}>
            {blocks.filter((b) => side.has(b.key)).map((b) => (
              <Fragment key={b.key}>{b.el}</Fragment>
            ))}
          </ScrollView>
        </View>
      </Screen>
    );
  }
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


const SIDE_WIDTH = 380;
const SIDE_PAD = 16;
const SIDE_INNER = SIDE_WIDTH - 2 * SIDE_PAD - 2;

const styles = StyleSheet.create({
  guestLink: { paddingHorizontal: 16, paddingTop: 2, alignSelf: 'stretch' },
  changed: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, backgroundColor: colors.lemonSoft, borderRadius: 14, paddingHorizontal: 12, paddingVertical: 10 },
  changedText: { flex: 1, fontSize: 13, fontWeight: '700', color: colors.ink },
  booksHead: { gap: 10, marginTop: 14, paddingTop: 18, borderTopWidth: 1, borderTopColor: colors.line },
  booksTitle: { fontSize: 22, fontWeight: '900', color: colors.ink },
  chips: { flexDirection: 'row-reverse', gap: 8 },
  chip: { borderWidth: 1, borderColor: colors.line, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 6, backgroundColor: colors.surface },
  chipOn: { backgroundColor: colors.lemon, borderColor: colors.lemon },
  chipText: { fontSize: 13, fontWeight: '700', color: colors.muted },
  grid: { flexDirection: 'row-reverse', flexWrap: 'wrap', paddingHorizontal: 16 },
  moreRow: { alignSelf: 'center', paddingVertical: 6, paddingHorizontal: 16, borderRadius: 999, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface },
  moreText: { fontSize: 13, fontWeight: '800', color: colors.greenDark },
  planCard: { backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 12, gap: 10 },
  planTrack: { height: 6, borderRadius: 3, backgroundColor: colors.line, overflow: 'hidden', flexDirection: 'row-reverse' },
  planFill: { backgroundColor: colors.green, borderRadius: 3 },
  planSub: { fontSize: 12, fontWeight: '800', color: colors.muted, marginTop: 4 },
  welcome: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12 },
  welcomeTitle: { fontSize: 15, fontWeight: '800', color: colors.ink },
  guestLinkText: { fontSize: 12, color: colors.greenDark, fontWeight: '700' },
  wide: { flex: 1, flexDirection: 'row-reverse', gap: 40, paddingLeft: 24 },
  wideMain: { gap: 16, paddingVertical: 24, paddingRight: 24, minWidth: 0 },
  // A very soft, slightly warm panel: the two columns read apart without a colour that catches the eye.
  wideSide: {
    width: SIDE_WIDTH,
    flexGrow: 0,
    marginVertical: 24,
    backgroundColor: '#F9F8EF',
    borderWidth: 1,
    borderColor: '#ECECE1',
    borderRadius: radius.lg,
  },
  wideSideInner: { gap: 16, padding: SIDE_PAD },
  needsList: { gap: 0 },
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
  soon: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', borderWidth: 1, borderStyle: 'dashed', borderColor: '#B9C4BC', borderRadius: 14, paddingHorizontal: 12, paddingVertical: 6 },
  soonText: { color: colors.muted, fontSize: 12 },
});

/** «این هفته ۲ ساعت خواندی ▲»: the last 7 days against the 7 before; the old question when there is little to say. */
function greetLine(week?: { seconds: number; before: number }) {
  if (!week || week.seconds < 600) return 'امروز کدام لیمو را می‌خوانی؟';
  const arrow = week.seconds > week.before * 1.1 ? ' ▲' : '';
  return `این هفته ${studyDuration(week.seconds)} خواندی${arrow}`;
}

/** «۲ از ۵ انجام شد» with a thin bar: questions and cards done today out of all planned today. */
function PlanProgress({ tasks }: { tasks: TodayTask[] }) {
  let done = 0;
  let total = 0;
  for (const t of tasks) {
    const d = t.done ?? 0;
    done += d;
    total += t.kind === 'review' ? Math.max(t.questions, d) : t.count + d;
  }
  if (!total || !done) return null;
  const pct = Math.min(100, Math.round((done / total) * 100));
  return (
    <View style={{ gap: 4 }}>
      <Text style={[styles.planSub, rtl, { marginTop: 0 }]}>
        {toPersianDigits(done)} از {toPersianDigits(total)} انجام شد
      </Text>
      <View style={styles.planTrack}>
        <View style={[styles.planFill, { width: `${pct}%` }]} />
      </View>
    </View>
  );
}

/** A shelf's id, or «rest» for the books on no shelf. */
const shelfKey = (x: Shelf) => (x.id == null ? 'rest' : String(x.id));

/** One shelf. A phone swipes the covers sideways; a computer shows one row that fits, no sideways scroll. Either way
 *  «نمایش همه» opens every book of the shelf in rows right there. */
function ShelfBlock({ shelf, tile, coverWidth, wide }: { shelf: Shelf; tile: (b: BookListItem) => ReactElement; coverWidth: number; wide: boolean }) {
  const [open, setOpen] = useState(false);
  const [w, setW] = useState(0);
  const gap = 14;
  const perRow = Math.max(1, Math.floor((w - 32 + gap) / (coverWidth + gap)));
  const hidden = wide ? shelf.books.length > perRow : shelf.books.length > 2;
  const grid = (books: BookListItem[]) => (
    <View style={[styles.grid, { gap }]}>
      {books.map((b) => (
        <Fragment key={b.slug}>{tile(b)}</Fragment>
      ))}
    </View>
  );
  return (
    <View style={styles.section} onLayout={(e) => setW(e.nativeEvent.layout.width)}>
      <SectionHeader icon="library-big" title={shelf.title} side={`${toPersianDigits(shelf.books.length)} کتاب`} />
      {open ? grid(shelf.books) : wide ? (w ? grid(shelf.books.slice(0, perRow)) : null) : <HRow data={shelf.books} keyOf={(b) => b.slug} render={tile} gap={gap} />}
      {hidden && (
        <Pressable onPress={() => setOpen((v) => !v)} style={styles.moreRow} accessibilityRole="button" accessibilityState={{ expanded: open }}>
          <Text style={styles.moreText}>{open ? 'بستن ▴' : `نمایش همه (${toPersianDigits(shelf.books.length)}) ▾`}</Text>
        </Pressable>
      )}
    </View>
  );
}
