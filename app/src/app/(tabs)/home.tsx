import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Linking, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { Text } from '../../components/Text';
import { Icon, IconBadge } from '../../components/Icon';

import { endpoints } from '../../api/endpoints';
import { BannerCarousel } from '../../components/BannerCarousel';
import { ErrorState, Loading, Screen, usePullRefresh } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { storage, type LastSection } from '../../lib/storage';
import { useApi } from '../../lib/useApi';
import { colors, formatToman, radius, rtl, toPersianDigits } from '../../theme';

type MajorRef = { slug: string; name: string; color: string };

export default function Home() {
  const { user } = useAuth();
  const [major, setMajor] = useState<MajorRef | null>(null);
  const [last, setLast] = useState<LastSection | null>(null);

  useFocusEffect(
    useCallback(() => {
      storage.getMajor().then((m) => (m ? setMajor(m) : router.replace('/welcome')));
      storage.getLastSection().then(setLast);
    }, []),
  );

  const books = useApi(() => (major ? endpoints.books(major.slug) : Promise.resolve([])), [major?.slug]);
  const banners = useApi(() => (major ? endpoints.banners(major.slug) : Promise.resolve([])), [major?.slug]);
  const [due, setDue] = useState(0);
  useFocusEffect(
    useCallback(() => {
      if (user) endpoints.dueFlashcards().then((d) => setDue(d.count)).catch(() => undefined);
      else setDue(0);
    }, [user]),
  );

  const refresh = usePullRefresh(books.loading, () => {
    books.retry();
    banners.retry();
  });

  if (!major) return <Loading />;

  const openLink = (link: string, id: number) => {
    endpoints.bannerClick(id).catch(() => undefined);
    if (link.startsWith('book/')) router.push(`/book/${link.slice(5)}`);
    else if (link.startsWith('buy/')) router.push(`/buy/${link.slice(4)}`);
    else if (link.startsWith('exam/')) router.push(`/exam/${link.slice(5)}`);
    else if (link === 'review') router.push('/review');
    else if (/^https?:\/\//.test(link)) Linking.openURL(link);
  };

  return (
    <Screen tab>
      <ScrollView
        contentContainerStyle={styles.page}
        refreshControl={refresh}
      >
        <View style={styles.top}>
          <View style={{ gap: 2 }}>
            <Text style={[styles.hello, rtl]}>سلام{user?.first_name ? ` ${user.first_name}` : ''}</Text>
            <Pressable onPress={() => router.push('/welcome')} style={styles.space} accessibilityRole="button" accessibilityLabel="تغییر رشته">
              <View style={[styles.dot, { backgroundColor: major.color }]} />
              <Text style={styles.spaceText}>لیمو {major.name}</Text>
              <Text style={styles.chev}>▾</Text>
            </Pressable>
          </View>
          {!user && (
            <Pressable onPress={() => router.push('/login')} style={styles.loginPill} accessibilityRole="button">
              <Text style={styles.loginText}>ورود</Text>
            </Pressable>
          )}
        </View>

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

        {last && (
          <Pressable onPress={() => router.push(`/section/${last.id}`)} style={styles.continue} accessibilityRole="button">
            <View style={[styles.continueCover, { backgroundColor: major.color }]}>
              <Text style={[styles.continueSmall, rtl]}>{last.bookTitle}</Text>
              <Text style={[styles.continueTitle, rtl]} numberOfLines={2}>{last.title}</Text>
            </View>
            <View style={styles.continueFoot}>
              <View style={styles.pill}>
                <Text style={styles.pillText}>ادامه بده ←</Text>
              </View>
              <Text style={[styles.muted, rtl]}>از همان‌جا که ماندی</Text>
            </View>
          </Pressable>
        )}

        {!!banners.data?.length && <BannerCarousel banners={banners.data} onOpen={(b) => openLink(b.link, b.id)} />}

        <Text style={[styles.sectionTitle, rtl]}>کتاب‌ها</Text>
        {books.loading && !books.data?.length ? (
          <Loading />
        ) : books.error ? (
          <ErrorState message={books.error.message} onRetry={books.retry} />
        ) : books.data!.length === 0 ? (
          <Text style={[styles.muted, rtl]}>هنوز کتابی برای این رشته منتشر نشده است.</Text>
        ) : (
          books.data!.map((book) => (
            <Pressable key={book.slug} onPress={() => router.push(`/book/${book.slug}`)} style={styles.book} accessibilityRole="button">
              <View style={[styles.cover, { backgroundColor: major.color }]}>
                <Text style={styles.coverText} numberOfLines={3}>{book.title}</Text>
              </View>
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={[styles.bookTitle, rtl]}>{book.title}</Text>
                <Text style={[styles.muted, rtl]}>{toPersianDigits(book.chapter_count)} فصل{book.price ? `، ${formatToman(book.price)}` : ''}</Text>
                {book.owned ? (
                  <View style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 4 }}>
                    <Icon name="circle-check" size={15} color={colors.greenDark} />
                    <Text style={[styles.free, rtl]}>در دسترس شما</Text>
                  </View>
                ) : (
                  book.has_free_part && <Text style={[styles.free, rtl]}>بخشی از کتاب رایگان است</Text>
                )}
              </View>
            </Pressable>
          ))
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

const styles = StyleSheet.create({
  page: { padding: 20, gap: 16 },
  top: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center' },
  hello: { fontSize: 13, color: colors.muted },
  space: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line, borderRadius: 999, paddingHorizontal: 12, paddingVertical: 6 },
  dot: { width: 10, height: 10, borderRadius: 5 },
  spaceText: { fontSize: 15, fontWeight: '700', color: colors.ink },
  chev: { color: colors.ink },
  review: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, backgroundColor: colors.surface, borderRadius: 20, padding: 14, borderWidth: 1.5, borderColor: colors.lemon },
  reviewTitle: { fontSize: 16, fontWeight: '800', color: colors.ink },
  loginPill: { backgroundColor: colors.ink, borderRadius: 999, paddingHorizontal: 18, paddingVertical: 10 },
  loginText: { color: colors.lemon, fontWeight: '800' },
  iconBox: { width: 44, height: 44, borderRadius: 14, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface, alignItems: 'center', justifyContent: 'center' },
  continue: { backgroundColor: colors.surface, borderRadius: 26, overflow: 'hidden', shadowColor: '#17201A', shadowOpacity: 0.1, shadowRadius: 20, shadowOffset: { width: 0, height: 8 }, elevation: 3 },
  continueCover: { padding: 18, minHeight: 110, justifyContent: 'flex-end' },
  continueSmall: { color: '#FFFFFFCC', fontSize: 12 },
  continueTitle: { color: '#FFFFFF', fontSize: 24, fontWeight: '800' },
  continueFoot: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', padding: 14 },
  pill: { backgroundColor: colors.lemon, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8 },
  pillText: { fontWeight: '800', color: colors.ink },
  muted: { fontSize: 13, color: colors.muted },
  sectionTitle: { fontSize: 18, fontWeight: '800', color: colors.ink, marginTop: 4 },
  book: { flexDirection: 'row-reverse', gap: 14, alignItems: 'center', backgroundColor: colors.surface, borderRadius: radius.md, padding: 12, borderWidth: 1, borderColor: colors.line },
  cover: { width: 62, height: 86, borderTopLeftRadius: 10, borderBottomLeftRadius: 10, borderTopRightRadius: 4, borderBottomRightRadius: 4, padding: 6, justifyContent: 'flex-end' },
  coverText: { color: '#fff', fontSize: 10, fontWeight: '700', textAlign: 'right' },
  bookTitle: { fontSize: 16, fontWeight: '800', color: colors.ink },
  free: { fontSize: 12, color: colors.greenDark, fontWeight: '700' },
  soon: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', borderWidth: 1, borderStyle: 'dashed', borderColor: '#B9C4BC', borderRadius: 14, padding: 12 },
  soonText: { color: colors.muted, fontSize: 13 },
  soonBadge: { backgroundColor: colors.lemonSoft, color: '#6B5200', fontSize: 12, fontWeight: '700', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 2, overflow: 'hidden' },
});
