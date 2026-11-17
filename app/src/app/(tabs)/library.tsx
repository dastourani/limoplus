import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { endpoints, type Library } from '../../api/endpoints';
import { Text } from '../../components/Text';
import { Icon } from '../../components/Icon';
import { LemonProgress, type PartState } from '../../components/LemonProgress';
import { Button, Card, Empty, ErrorState, Loading, Screen, usePullRefresh } from '../../components/ui';
import { ListRow } from '../../components/ListRow';
import { Pill } from '../../components/Pill';
import { useAuth } from '../../lib/auth';
import { useFeedback } from '../../components/Feedback';
import { QuoteView } from '../../components/QuoteView';
import { relativeDay } from '../../lib/jalali';
import { colors, radius, rtl, toPersianDigits } from '../../theme';

const TABS = [
  ['reading', 'در حال مطالعه'],
  ['bookmarks', 'نشان‌شده‌ها'],
  ['notes', 'یادداشت‌ها'],
] as const;

/** Always shown, even empty: where wrong and blank answers gather (harmonized with TodayTiles & ReadingCards). */
function NotebookCard({ counts }: { counts?: Library['mistakes'] }) {
  const n = counts?.count ?? 0;
  const settling = counts?.settling ?? 0;
  const due = counts?.due ?? 0;
  const parts: PartState[] =
    n === 0
      ? ['empty']
      : Array.from({ length: Math.min(24, n) }, (_, i) => (i < Math.round((settling / Math.max(1, n)) * Math.min(24, n)) ? 'soft' : 'wrong'));
  const sub =
    n === 0
      ? 'تست‌های غلط و بی‌پاسخت این‌جا جمع می‌شوند.'
      : [counts!.open ? `${toPersianDigits(counts!.open)} منتظر جبران` : '', counts!.settling ? `${toPersianDigits(counts!.settling)} در حال تثبیت` : '']
          .filter(Boolean)
          .join('، ');
  return (
    <Pressable
      onPress={() => router.push('/mistakes')}
      style={({ pressed }) => [styles.notebookRow, pressed && { opacity: 0.9 }]}
      accessibilityRole="button"
      accessibilityLabel="اشتباهات من"
    >
      <LemonProgress parts={parts} size={44} />
      <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
        <Text style={[styles.itemTitle, rtl]} numberOfLines={1}>اشتباهات من</Text>
        <Text style={[styles.muted, rtl]} numberOfLines={1}>{sub}</Text>
      </View>
      {due > 0 ? (
        <View style={styles.go}>
          <Text style={styles.goText}>مرور {toPersianDigits(due)} تست</Text>
        </View>
      ) : n > 0 ? (
        <View style={[styles.go, { backgroundColor: colors.ground, borderWidth: 1, borderColor: colors.line }]}>
          <Text style={styles.goText}>{toPersianDigits(n)} تست</Text>
        </View>
      ) : (
        <Icon name="chevron-left" size={18} color={colors.muted} />
      )}
    </Pressable>
  );
}

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
  const { toast } = useFeedback();
  // × on a note: gone at once, with «برگرداندن» for a few seconds (the server only archives it).
  const removeNote = async (n: Library['notes'][number]) => {
    try {
      await endpoints.deleteNote(n.id);
    } catch {
      toast('حذف نشد. اتصال اینترنت را بررسی کنید.');
      return;
    }
    setData((d) => (d ? { ...d, notes: d.notes.filter((x) => x.id !== n.id) } : d));
    toast(n.quote && !n.body ? 'هایلایت حذف شد.' : 'یادداشت حذف شد.', {
      label: 'برگرداندن',
      onPress: () => {
        endpoints
          .addNote(n.node_id, { quote: n.quote, body: n.body, color: n.color, mode: n.mode })
          .then(() => load())
          .catch(() => toast('برگرداندن ممکن نشد.'));
      },
    });
  };
  const refresh = usePullRefresh(loading, load);

  if (!user) {
    return (
      <Screen tab desktopMax={1600}>
        <Text style={[styles.title, rtl]}>کتابخانه‌ی من</Text>
        <Empty
          icon="library-big"
          title="کتابخانه‌ات اینجاست"
          text="بعد از ورود، کتاب‌هایی که می‌خوانی، بخش‌های نشان‌شده و یادداشت‌هایت اینجا جمع می‌شوند و روی همه‌ی دستگاه‌هایت هست."
          action={<Button label="ورود یا ثبت‌نام" onPress={() => router.push('/login')} style={{ alignSelf: 'stretch' }} />}
        />
      </Screen>
    );
  }

  return (
    <Screen tab desktopMax={1600}>
      <Text style={[styles.title, rtl]}>کتابخانه‌ی من</Text>
      <View style={styles.tabs}>
        {TABS.map(([key, label]) => (
          <Pill key={key} label={label} selected={tab === key} onPress={() => setTab(key)} role="tab" />
        ))}
      </View>
      {!data ? (
        error ? <ErrorState message={error} onRetry={load} /> : <Loading />
      ) : (
        <ScrollView contentContainerStyle={styles.page} refreshControl={refresh}>
          <NotebookCard counts={data.mistakes} />
          {tab === 'reading' &&
            (data!.reading.length === 0 ? (
              <Empty title="هنوز کتابی را شروع نکرده‌ای" text="از صفحه‌ی خانه یک کتاب باز کن." />
            ) : (
              data!.reading.map((r) => (
                <ListRow
                  key={r.book_slug}
                  icon="book-open"
                  title={r.book_title}
                  subtitle={`آخرین بخش: ${r.last_section.title}، ${relativeDay(r.updated_at)}`}
                  onPress={() => router.push(`/book/${r.book_slug}`)}
                  value={
                    <Pressable onPress={() => router.push(`/section/${r.last_section.id}`)} style={styles.go} accessibilityRole="button" accessibilityLabel={`ادامه‌ی ${r.book_title}`}>
                      <Text style={styles.goText}>ادامه</Text>
                    </Pressable>
                  }
                />
              ))
            ))}
          {tab === 'bookmarks' &&
            (data!.bookmarks.length === 0 ? (
              <Empty icon="bookmark" title="بخشی نشان نکرده‌ای" text="در صفحه‌ی درس، دکمه‌ی نشان را بزن تا اینجا بیاید." />
            ) : (
              data!.bookmarks.map((b) => (
                <ListRow key={b.id} icon="bookmark" title={b.title} subtitle={relativeDay(b.created_at)} onPress={() => router.push(`/section/${b.id}`)} chevron />
              ))
            ))}
          {tab === 'notes' &&
            (data!.notes.length === 0 ? (
              <Empty icon="notebook-pen" title="یادداشتی نداری" text="در صفحه‌ی درس متنی را انتخاب کن تا هایلایت یا یادداشت بگذاری." />
            ) : (
              data!.notes.map((n) => (
                <Pressable key={n.id} onPress={() => router.push(`/section/${n.node_id}`)}>
                  <Card>
                    <View style={styles.noteHead}>
                      <Text style={[styles.muted, rtl, { flex: 1 }]}>{n.node_title}، {relativeDay(n.updated_at)}</Text>
                      <Pressable onPress={() => removeNote(n)} hitSlop={10} style={styles.noteX} accessibilityRole="button" accessibilityLabel="حذف">
                        <Icon name="x" size={18} color={colors.muted} />
                      </Pressable>
                    </View>
                    {!!n.quote && <QuoteView quote={n.quote} color={NOTE_COLORS[n.color] ?? NOTE_COLORS.yellow} maxHeight={160} />}
                    {!!n.body && <Text selectable style={[styles.body, rtl]}>{n.body}</Text>}
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
  notebookRow: {
    flexDirection: 'row-reverse',
    alignItems: 'center',
    gap: 12,
    padding: 14,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line,
  },
  go: { backgroundColor: colors.lemon, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 7 },
  goText: { fontSize: 12, fontWeight: '800', color: colors.ink },
  // The four tabs start alike: the page title 12 from the top, on the 16 margin.
  title: { fontSize: 22, fontWeight: '800', color: colors.ink, paddingHorizontal: 16, paddingTop: 12 },
  tabs: { flexDirection: 'row-reverse', gap: 8, paddingHorizontal: 16, paddingVertical: 12 },
  page: { padding: 16, paddingTop: 0, gap: 12 },
  itemTitle: { fontSize: 15, fontWeight: '800', color: colors.ink },
  muted: { fontSize: 12, color: colors.muted },
  quote: { fontSize: 15, lineHeight: 28, color: colors.ink, borderRadius: 8, padding: 8 },
  body: { fontSize: 15, lineHeight: 24, color: colors.ink },
  noteHead: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  noteX: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center', marginVertical: -6 },
});
