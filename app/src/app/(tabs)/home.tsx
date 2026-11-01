import { shelfLabel } from '../../lib/access';
import { setViewAsLearner, useViewAsLearner } from '../../lib/viewAs';
import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useRef, useState } from 'react';
import { Animated, Linking, Pressable, ScrollView, StyleSheet, useWindowDimensions, View, type ScrollViewInstance } from 'react-native';

import { endpoints, type BookListItem, type Major } from '../../api/endpoints';
import { BannerCarousel } from '../../components/BannerCarousel';
import { BookCover } from '../../components/BookCover';
import { Icon, IconBadge } from '../../components/Icon';
import { LemonProgress } from '../../components/LemonProgress';
import { LemonSlice } from '../../components/LemonSlice';
import { Text } from '../../components/Text';
import { ErrorState, Loading, Screen, usePullRefresh } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { storage, type LastSection } from '../../lib/storage';
import { useApi } from '../../lib/useApi';
import { colors, formatToman, rtl, toPersianDigits } from '../../theme';

type MajorRef = { slug: string; name: string; color: string };

/** Read sections as lemon wedges, from a book's share read (0–1) and its number of sections. */
function wedges(progress: number | null, count: number) {
  const n = Math.max(1, Math.min(count || 10, 24));
  const done = Math.round((progress ?? 0) * n);
  return Array.from({ length: n }, (_, i) => (i < done ? ('done' as const) : ('empty' as const)));
}

export default function Home() {
  const { user } = useAuth();
  const { width } = useWindowDimensions();
  const [major, setMajor] = useState<MajorRef | null>(null);
  const asLearner = useViewAsLearner();
  const [last, setLast] = useState<LastSection | null>(null);

  useFocusEffect(
    useCallback(() => {
      storage.getMajor().then((m) => setMajor(m ?? null));
      storage.getLastSection().then(setLast);
    }, []),
  );

  const majors = useApi(() => endpoints.majors(), []);
  // Before a major is picked, the shelf shows every book so a newcomer sees what there is.
  const books = useApi(() => (major ? endpoints.books(major.slug) : endpoints.allBooks()), [major?.slug, user?.id, asLearner]);
  const banners = useApi(() => (major ? endpoints.banners(major.slug) : Promise.resolve([])), [major?.slug]);
  const [due, setDue] = useState(0);
  useFocusEffect(
    useCallback(() => {
      if (user) endpoints.dueFlashcards().then((d) => setDue(d.count)).catch(() => undefined);
      else setDue(0);
    }, [user]),
  );
  // Back from a book or a payment: progress and ownership may have changed.
  const [focused, setFocused] = useState(0);
  useFocusEffect(useCallback(() => setFocused((n) => n + 1), []));
  useEffect(() => {
    if (focused > 1) books.retry();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focused]);

  // The shelf fades in when the major changes.
  const shelf = useRef(new Animated.Value(1)).current;
  const majorsRef = useRef<ScrollViewInstance>(null);
  const pickMajor = (m: Major) => {
    if (m.is_coming_soon || m.slug === major?.slug) return;
    const next = { slug: m.slug, name: m.name, color: m.color };
    shelf.setValue(0);
    setMajor(next);
    storage.setMajor(next);
  };
  useEffect(() => {
    if (!books.loading) Animated.timing(shelf, { toValue: 1, duration: 260, useNativeDriver: true }).start();
  }, [books.loading, shelf]);

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
    majors.retry();
  });


  const openLink = (link: string, id: number) => {
    endpoints.bannerClick(id).catch(() => undefined);
    if (link.startsWith('book/')) router.push(`/book/${link.slice(5)}`);
    else if (link.startsWith('buy/')) router.push(`/buy/${link.slice(4)}`);
    else if (link.startsWith('exam/')) router.push(`/exam/${link.slice(5)}`);
    else if (link === 'review') router.push('/review');
    else if (/^https?:\/\//.test(link)) Linking.openURL(link);
  };

  const list = books.data ?? [];
  const lastBook = last ? list.find((b) => b.slug === last.bookSlug) : undefined;
  // Phones show two covers a row; tablets, desktop browsers and Windows show more, up to six.
  const pageWidth = Math.min(width, 1200);
  const columns = Math.max(2, Math.min(6, Math.floor((pageWidth - 40 + 18) / 200)));
  const coverWidth = Math.floor((pageWidth - 40 - 18 * (columns - 1)) / columns);
  const majorRef = major ? { name: major.name, color: major.color } : null;
  const coverMajor = (b: BookListItem) => majorRef ?? (b.major ? { name: b.major.name, color: b.major.color } : null);

  return (
    <Screen tab>
      <ScrollView contentContainerStyle={styles.page} refreshControl={refresh}>
        <View style={styles.top}>
          <LemonSlice size={36} />
          <View style={{ flex: 1 }}>
            <Text style={[styles.hello, rtl]}>سلام{user?.first_name ? ` ${user.first_name}` : ''}!</Text>
            <Text style={[styles.muted, rtl]}>امروز کدام لیمو را می‌خوانی؟</Text>
          </View>
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

        {last && (
          <Pressable onPress={() => router.push(`/section/${last.id}`)} style={styles.continue} accessibilityRole="button" accessibilityLabel={`ادامه‌ی خواندن ${last.title}`}>
            {lastBook ? (
              <BookCover book={lastBook} major={coverMajor(lastBook)} width={64} />
            ) : (
              <View style={styles.continueLemon}>
                <LemonSlice size={52} />
              </View>
            )}
            <View style={{ flex: 1, gap: 3 }}>
              <Text style={[styles.continueLabel, rtl]}>ادامه‌ی خواندن</Text>
              <Text style={[styles.continueTitle, rtl]} numberOfLines={1}>{last.bookTitle}</Text>
              <Text style={[styles.continueSub, rtl]} numberOfLines={1}>{last.title}</Text>
              <View style={styles.continuePill}>
                <Text style={styles.continuePillText}>ادامه بده</Text>
              </View>
            </View>
            {lastBook?.progress != null && <LemonProgress parts={wedges(lastBook.progress, lastBook.section_count)} size={46} />}
          </Pressable>
        )}

        {due > 0 && (
          <Pressable onPress={() => router.push('/review')} style={styles.review} accessibilityRole="button">
            <IconBadge name="layers" size={44} />
            <View style={{ flex: 1 }}>
              <Text style={[styles.reviewTitle, rtl]}>مرور امروز</Text>
              <Text style={[styles.muted, rtl]}>{toPersianDigits(due)} فلش‌کارت منتظر مرور است</Text>
            </View>
            <Icon name="chevron-left" size={22} color={colors.muted} />
          </Pressable>
        )}

        <Text style={[styles.sectionTitle, rtl]}>رشته‌ات را انتخاب کن</Text>
        {!major && <Text style={[styles.pickHint, rtl]}>رشته‌ات را بزن تا قفسه فقط کتاب‌های همان رشته را نشان دهد.</Text>}
        <ScrollView
          ref={majorsRef}
          horizontal
          showsHorizontalScrollIndicator={false}
          contentContainerStyle={styles.majors}
          style={[styles.majorsWrap, !major && styles.majorsAsk]}
          // Right-to-left: the row starts at its right end, where the first major is.
          onContentSizeChange={() => majorsRef.current?.scrollToEnd({ animated: false })}
        >
          {(majors.data ?? (major ? [{ slug: major.slug, name: major.name, color: major.color, is_coming_soon: false }] : [])).map((m) => {
            const on = m.slug === major?.slug;
            return (
              <Pressable
                key={m.slug}
                onPress={() => pickMajor(m)}
                disabled={m.is_coming_soon}
                accessibilityRole="radio"
                accessibilityState={{ checked: on, disabled: m.is_coming_soon }}
                style={[
                  styles.major,
                  on ? { backgroundColor: m.color, borderColor: m.color, shadowColor: m.color, shadowOpacity: 0.35, shadowRadius: 10, shadowOffset: { width: 0, height: 5 }, elevation: 4 } : null,
                  m.is_coming_soon && { opacity: 0.55 },
                ]}
              >
                <View style={[styles.majorDot, { backgroundColor: on ? '#FFFFFF' : m.color }]} />
                <View>
                  <Text style={[styles.majorSmall, on && { color: '#FFFFFFCC' }]}>{m.is_coming_soon ? 'به‌زودی' : 'لیمو'}</Text>
                  <Text style={[styles.majorName, on && { color: '#FFFFFF' }]}>{m.name}</Text>
                </View>
              </Pressable>
            );
          })}
        </ScrollView>

        {!!banners.data?.length && <BannerCarousel banners={banners.data} onOpen={(b) => openLink(b.link, b.id)} />}

        <View style={styles.shelfHead}>
          <Text style={[styles.shelfTitle, rtl]}>{major ? `کتاب‌های لیمو ${major.name}` : 'همه‌ی کتاب‌ها'}</Text>
          {!!list.length && <Text style={styles.muted}>{toPersianDigits(list.length)} کتاب</Text>}
        </View>

        {books.loading && !list.length ? (
          <Loading />
        ) : books.error ? (
          <ErrorState message={books.error.message} onRetry={books.retry} />
        ) : list.length === 0 ? (
          <Text style={[styles.muted, rtl]}>هنوز کتابی برای این رشته منتشر نشده است.</Text>
        ) : (
          <Animated.View style={[styles.shelf, { opacity: shelf }]}>
            {list.map((book) => {
              const label = shelfLabel(book);
              const { on: waiting, canCancel } = notifyState(book);
              return (
                <View key={book.slug} style={{ width: coverWidth, gap: 8 }}>
                  <Pressable
                    onPress={() => router.push({ pathname: '/book/[slug]', params: { slug: book.slug } })}
                    accessibilityRole="button"
                    accessibilityLabel={`${book.title}${book.is_coming_soon ? '، به‌زودی' : ''}`}
                    style={({ pressed }) => [{ opacity: book.is_coming_soon ? 0.75 : 1 }, pressed && { transform: [{ scale: 0.97 }] }]}
                  >
                    <BookCover book={book} major={coverMajor(book)} width={coverWidth} />
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
                      <Icon name={waiting ? 'bell-ring' : 'bell'} size={15} color={waiting ? colors.ink : colors.ink} />
                      <Text style={styles.notifyText}>{waiting ? (canCancel ? 'خبرت می‌کنیم' : 'خبرت می‌کنیم ✓') : 'خبرم کن'}</Text>
                    </Pressable>
                  ) : (
                    <Text style={styles.price} numberOfLines={1}>
                      {book.owned ? 'در دسترس تو' : book.price ? `${formatToman(book.price)}، یا با اشتراک` : 'رایگان'}
                    </Text>
                  )}
                </View>
              );
            })}
          </Animated.View>
        )}

        <View style={styles.soon}>
          <View style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 8, flex: 1 }}>
            <IconBadge name="sparkles" size={32} />
            <Text style={[styles.soonText, rtl, { flex: 1 }]}>دستیار هوش مصنوعی برای رفع اشکال</Text>
          </View>
          <Text style={styles.soonBadge}>به‌زودی</Text>
        </View>
      </ScrollView>
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
  asLearner: { backgroundColor: '#FFF6CC', borderRadius: 12, paddingVertical: 8, paddingHorizontal: 12 },
  asLearnerText: { fontSize: 12, fontWeight: '700', color: colors.ink, textAlign: 'center' },
  page: { padding: 20, gap: 16, maxWidth: 1200, width: '100%', alignSelf: 'center' },
  top: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10 },
  hello: { fontSize: 20, fontWeight: '900', color: colors.ink },
  muted: { fontSize: 13, color: colors.muted },
  loginPill: { backgroundColor: colors.ink, borderRadius: 999, paddingHorizontal: 18, paddingVertical: 10 },
  loginText: { color: colors.lemon, fontWeight: '800' },
  continue: { flexDirection: 'row-reverse', alignItems: 'center', gap: 14, backgroundColor: colors.ink, borderRadius: 22, padding: 14 },
  continueLemon: { width: 64, height: 96, borderRadius: 10, backgroundColor: '#24302A', alignItems: 'center', justifyContent: 'center' },
  continueLabel: { fontSize: 11, fontWeight: '800', color: colors.lemon },
  continueTitle: { fontSize: 16, fontWeight: '900', color: '#FFFFFF' },
  continueSub: { fontSize: 12, color: '#A9B6AD' },
  continuePill: { alignSelf: 'flex-end', marginTop: 6, backgroundColor: colors.lemon, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 5 },
  continuePillText: { fontSize: 12, fontWeight: '800', color: colors.ink },
  review: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, backgroundColor: colors.surface, borderRadius: 20, padding: 14, borderWidth: 1.5, borderColor: colors.lemon },
  reviewTitle: { fontSize: 16, fontWeight: '800', color: colors.ink },
  sectionTitle: { fontSize: 15, fontWeight: '900', color: colors.ink, marginBottom: -6 },
  majorsWrap: { marginHorizontal: -20, flexGrow: 0 },
  majors: { flexDirection: 'row-reverse', gap: 10, paddingHorizontal: 20, paddingVertical: 4 },
  major: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, minHeight: 52, paddingHorizontal: 14, paddingVertical: 6, borderRadius: 16, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface },
  majorDot: { width: 9, height: 9, borderRadius: 5 },
  majorSmall: { fontSize: 10, color: colors.muted, textAlign: 'right' },
  majorName: { fontSize: 14, fontWeight: '800', color: colors.ink, textAlign: 'right' },
  shelfHead: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'baseline', marginTop: 4 },
  shelfTitle: { fontSize: 18, fontWeight: '900', color: colors.ink },
  shelf: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 18, rowGap: 22 },
  ribbon: { position: 'absolute', top: 12, left: -4, flexDirection: 'row-reverse', alignItems: 'center', gap: 4, paddingHorizontal: 8, paddingVertical: 3, borderTopLeftRadius: 6, borderTopRightRadius: 6, borderBottomRightRadius: 6 },
  ribbonText: { fontSize: 10, fontWeight: '800' },
  pickHint: { fontSize: 13, color: colors.greenDark, marginTop: -4 },
  majorsAsk: { borderRadius: 18, backgroundColor: '#FFF6CC' },
  ribbonFree: { backgroundColor: colors.lemon, color: colors.ink },
  ribbonSoon: { backgroundColor: colors.ink, color: colors.ground },
  ribbonOwned: { backgroundColor: '#3FB8A9', flexDirection: 'row-reverse', alignItems: 'center', gap: 4 },
  ribbonOwnedText: { fontSize: 10, fontWeight: '800', color: '#FFFFFF' },
  progressBadge: { position: 'absolute', bottom: 10, left: 10, flexDirection: 'row-reverse', alignItems: 'center', gap: 5, backgroundColor: 'rgba(23,32,26,0.88)', borderRadius: 10, paddingHorizontal: 7, paddingVertical: 3 },
  progressText: { fontSize: 11, fontWeight: '800', color: colors.lemon },
  notify: { minHeight: 38, borderRadius: 12, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6 },
  notifyOn: { backgroundColor: colors.lemonSoft, borderColor: colors.lemon },
  notifyText: { fontSize: 12, fontWeight: '700', color: colors.ink },
  price: { fontSize: 12, color: colors.muted, minHeight: 38, textAlignVertical: 'center', textAlign: 'center', writingDirection: 'rtl' },
  soon: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', borderWidth: 1, borderStyle: 'dashed', borderColor: '#B9C4BC', borderRadius: 14, padding: 12 },
  soonText: { color: colors.muted, fontSize: 13 },
  soonBadge: { backgroundColor: colors.lemonSoft, color: '#6B5200', fontSize: 12, fontWeight: '700', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 2, overflow: 'hidden' },
});
