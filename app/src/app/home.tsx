import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Linking, Pressable, RefreshControl, ScrollView, StyleSheet, View } from 'react-native';

import { Text } from '../components/Text';

import { endpoints } from '../api/endpoints';
import { ErrorState, Loading, Screen } from '../components/ui';
import { storage, type LastSection } from '../lib/storage';
import { useApi } from '../lib/useApi';
import { colors, formatToman, radius, rtl, toPersianDigits } from '../theme';

type MajorRef = { slug: string; name: string; color: string };

export default function Home() {
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

  if (!major) return <Loading />;

  const openLink = (link: string, id: number) => {
    endpoints.bannerClick(id).catch(() => undefined);
    if (link.startsWith('book/')) router.push(`/book/${link.slice(5)}`);
    else if (/^https?:\/\//.test(link)) Linking.openURL(link);
  };

  return (
    <Screen>
      <ScrollView
        contentContainerStyle={styles.page}
        refreshControl={<RefreshControl refreshing={books.loading && !!books.data} onRefresh={() => { books.retry(); banners.retry(); }} />}
      >
        <View style={styles.top}>
          <View style={{ gap: 2 }}>
            <Text style={[styles.hello, rtl]}>سلام</Text>
            <Pressable onPress={() => router.push('/welcome')} style={styles.space} accessibilityRole="button" accessibilityLabel="تغییر رشته">
              <View style={[styles.dot, { backgroundColor: major.color }]} />
              <Text style={styles.spaceText}>فضای {major.name}</Text>
              <Text style={styles.chev}>▾</Text>
            </Pressable>
          </View>
          <Pressable onPress={() => router.push('/settings')} style={styles.iconBox} accessibilityLabel="تنظیمات">
            <Text style={{ fontSize: 18 }}>⚙</Text>
          </Pressable>
        </View>

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

        {!!banners.data?.length && (
          <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.banners} style={{ marginHorizontal: -20 }}>
            {banners.data.map((b) => (
              <Pressable key={b.id} onPress={() => openLink(b.link, b.id)} style={styles.banner} accessibilityRole="button">
                <View style={styles.bannerLemon} />
                <Text style={[styles.bannerSmall, rtl]}>{b.subtitle || 'ویژه'}</Text>
                <Text style={[styles.bannerTitle, rtl]} numberOfLines={2}>{b.title}</Text>
              </Pressable>
            ))}
          </ScrollView>
        )}

        <Text style={[styles.sectionTitle, rtl]}>کتاب‌ها</Text>
        {books.loading && !books.data ? (
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
                <Text style={[styles.muted, rtl]}>{toPersianDigits(book.chapter_count)} فصل{book.price ? ` · ${formatToman(book.price)}` : ''}</Text>
                {book.has_free_part && <Text style={[styles.free, rtl]}>بخشی از کتاب رایگان است</Text>}
              </View>
            </Pressable>
          ))
        )}

        <View style={styles.soon}>
          <Text style={[styles.soonText, rtl]}>✦ دستیار هوش مصنوعی</Text>
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
  iconBox: { width: 44, height: 44, borderRadius: 14, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface, alignItems: 'center', justifyContent: 'center' },
  continue: { backgroundColor: colors.surface, borderRadius: 26, overflow: 'hidden', shadowColor: '#17201A', shadowOpacity: 0.1, shadowRadius: 20, shadowOffset: { width: 0, height: 8 }, elevation: 3 },
  continueCover: { padding: 18, minHeight: 110, justifyContent: 'flex-end' },
  continueSmall: { color: '#FFFFFFCC', fontSize: 12 },
  continueTitle: { color: '#FFFFFF', fontSize: 24, fontWeight: '900' },
  continueFoot: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', padding: 14 },
  pill: { backgroundColor: colors.lemon, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 8 },
  pillText: { fontWeight: '800', color: colors.ink },
  muted: { fontSize: 13, color: colors.muted },
  banners: { paddingHorizontal: 20, gap: 12, flexDirection: 'row-reverse' },
  banner: { width: 300, minHeight: 110, backgroundColor: colors.ink, borderRadius: 22, padding: 18, justifyContent: 'center', overflow: 'hidden' },
  bannerLemon: { position: 'absolute', left: -30, bottom: -40, width: 120, height: 120, borderRadius: 60, backgroundColor: colors.lemon },
  bannerSmall: { color: '#B9C4BC', fontSize: 12, paddingLeft: 80 },
  bannerTitle: { color: colors.lemon, fontSize: 20, fontWeight: '900', lineHeight: 30, paddingLeft: 80 },
  sectionTitle: { fontSize: 18, fontWeight: '800', color: colors.ink, marginTop: 4 },
  book: { flexDirection: 'row-reverse', gap: 14, alignItems: 'center', backgroundColor: colors.surface, borderRadius: radius.md, padding: 12, borderWidth: 1, borderColor: colors.line },
  cover: { width: 62, height: 86, borderTopLeftRadius: 10, borderBottomLeftRadius: 10, borderTopRightRadius: 4, borderBottomRightRadius: 4, padding: 6, justifyContent: 'flex-end' },
  coverText: { color: '#fff', fontSize: 10, fontWeight: '800', textAlign: 'right' },
  bookTitle: { fontSize: 16, fontWeight: '800', color: colors.ink },
  free: { fontSize: 12, color: colors.greenDark, fontWeight: '700' },
  soon: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', borderWidth: 1, borderStyle: 'dashed', borderColor: '#B9C4BC', borderRadius: 14, padding: 12 },
  soonText: { color: colors.muted, fontSize: 13 },
  soonBadge: { backgroundColor: colors.lemonSoft, color: '#6B5200', fontSize: 11, fontWeight: '800', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 2, overflow: 'hidden' },
});
