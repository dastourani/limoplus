import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, RefreshControl, ScrollView, StyleSheet, View } from 'react-native';

import { endpoints, type Library } from '../../api/endpoints';
import { Text } from '../../components/Text';
import { Button, Card, Empty, ErrorState, Loading, Screen } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { relativeDay } from '../../lib/jalali';
import { colors, rtl } from '../../theme';

const TABS = [
  ['reading', 'در حال مطالعه'],
  ['bookmarks', 'نشان‌شده‌ها'],
  ['notes', 'یادداشت‌ها'],
] as const;

const NOTE_COLORS: Record<string, string> = { yellow: '#FFE98A', green: '#BFE8CF', blue: '#C9DBFF', pink: '#FFD0DF' };

export default function LibraryTab() {
  const { user } = useAuth();
  const [tab, setTab] = useState<(typeof TABS)[number][0]>('reading');
  const [data, setData] = useState<Library | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const load = useCallback(() => {
    if (!user) return;
    setLoading(true);
    endpoints
      .library()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [user]);
  useFocusEffect(load);

  if (!user) {
    return (
      <Screen tab>
        <Text style={[styles.title, rtl]}>کتابخانه‌ی من</Text>
        <Empty
          icon="📚"
          title="کتابخانه‌ات اینجاست"
          text="بعد از ورود، کتاب‌هایی که می‌خوانی، بخش‌های نشان‌شده و یادداشت‌هایت اینجا جمع می‌شوند و روی همه‌ی دستگاه‌هایت هست."
          action={<Button label="ورود یا ثبت‌نام" onPress={() => router.push('/login')} style={{ alignSelf: 'stretch' }} />}
        />
      </Screen>
    );
  }

  return (
    <Screen tab>
      <Text style={[styles.title, rtl]}>کتابخانه‌ی من</Text>
      <View style={styles.tabs}>
        {TABS.map(([key, label]) => (
          <Pressable key={key} onPress={() => setTab(key)} style={[styles.tab, tab === key && styles.tabOn]} accessibilityRole="tab">
            <Text style={[styles.tabText, tab === key && { color: colors.lemon }]}>{label}</Text>
          </Pressable>
        ))}
      </View>
      {!data ? (
        error ? <ErrorState message={error} onRetry={load} /> : <Loading />
      ) : (
        <ScrollView contentContainerStyle={styles.page} refreshControl={<RefreshControl refreshing={loading} onRefresh={load} />}>
          {tab === 'reading' &&
            (data!.reading.length === 0 ? (
              <Empty title="هنوز کتابی را شروع نکرده‌ای" text="از صفحه‌ی خانه یک کتاب باز کن." />
            ) : (
              data!.reading.map((r) => (
                <Pressable key={r.book_slug} onPress={() => router.push(`/book/${r.book_slug}`)}>
                  <Card>
                    <Text style={[styles.itemTitle, rtl]}>{r.book_title}</Text>
                    <Text style={[styles.muted, rtl]}>آخرین بخش: {r.last_section.title} · {relativeDay(r.updated_at)}</Text>
                    <Button label="ادامه‌ی مطالعه" variant="dark" onPress={() => router.push(`/section/${r.last_section.id}`)} />
                  </Card>
                </Pressable>
              ))
            ))}
          {tab === 'bookmarks' &&
            (data!.bookmarks.length === 0 ? (
              <Empty icon="🔖" title="بخشی نشان نکرده‌ای" text="در صفحه‌ی درس، دکمه‌ی نشان را بزن تا اینجا بیاید." />
            ) : (
              data!.bookmarks.map((b) => (
                <Pressable key={b.id} onPress={() => router.push(`/section/${b.id}`)} style={styles.rowItem}>
                  <Text style={[styles.itemTitle, rtl, { flex: 1 }]}>🔖 {b.title}</Text>
                  <Text style={styles.muted}>{relativeDay(b.created_at)}</Text>
                </Pressable>
              ))
            ))}
          {tab === 'notes' &&
            (data!.notes.length === 0 ? (
              <Empty icon="✎" title="یادداشتی نداری" text="در صفحه‌ی درس متنی را انتخاب کن تا هایلایت یا یادداشت بگذاری." />
            ) : (
              data!.notes.map((n) => (
                <Pressable key={n.id} onPress={() => router.push(`/section/${n.node_id}`)}>
                  <Card>
                    <Text style={[styles.muted, rtl]}>{n.node_title} · {relativeDay(n.updated_at)}</Text>
                    {!!n.quote && <Text style={[styles.quote, rtl, { backgroundColor: NOTE_COLORS[n.color] ?? NOTE_COLORS.yellow }]}>{n.quote}</Text>}
                    {!!n.body && <Text style={[styles.body, rtl]}>{n.body}</Text>}
                  </Card>
                </Pressable>
              ))
            ))}
        </ScrollView>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 24, fontWeight: '900', color: colors.ink, paddingHorizontal: 20, paddingTop: 12 },
  tabs: { flexDirection: 'row-reverse', gap: 8, paddingHorizontal: 20, paddingVertical: 12 },
  tab: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line },
  tabOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  tabText: { fontWeight: '800', color: colors.muted, fontSize: 13 },
  page: { padding: 16, paddingTop: 0, gap: 12 },
  itemTitle: { fontSize: 16, fontWeight: '800', color: colors.ink },
  muted: { fontSize: 12, color: colors.muted },
  rowItem: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, backgroundColor: colors.surface, borderRadius: 16, padding: 14, borderWidth: 1, borderColor: colors.line },
  quote: { fontSize: 15, lineHeight: 28, color: colors.ink, borderRadius: 8, padding: 8 },
  body: { fontSize: 14, lineHeight: 24, color: colors.ink },
});
