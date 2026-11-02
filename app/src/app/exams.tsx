import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { ApiError } from '../api/client';
import { endpoints, type ExamPage } from '../api/endpoints';
import { ScoreTrend } from '../components/ScoreTrend';
import { Text } from '../components/Text';
import { Button, Empty, ErrorState, Header, Loading, Screen, usePullRefresh } from '../components/ui';
import { ListRow } from '../components/ListRow';
import { Pill } from '../components/Pill';
import { jalaliDateTime } from '../lib/jalali';
import { colors, rtl, toPersianDigits } from '../theme';

const pct = (n: number | null | undefined) => `${toPersianDigits(Math.round(n ?? 0))}٪`;

export default function Exams() {
  const start = useLocalSearchParams<{ book?: string }>().book;
  const [book, setBook] = useState(start ?? '');
  const [data, setData] = useState<ExamPage | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async (p: number, slug: string) => {
    setBusy(true);
    setError(null);
    try {
      const next = await endpoints.examPage(p, slug);
      setData((old) => (p === 1 || !old ? next : { ...next, results: [...old.results, ...next.results] }));
      setPage(p);
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, 'error', 'خطا'));
    } finally {
      setBusy(false);
    }
  }, []);
  useEffect(() => {
    load(1, book);
  }, [book, load]);
  const refresh = usePullRefresh(busy, () => load(1, book));

  return (
    <Screen>
      <Header title="سابقه‌ی آزمون‌ها" />
      {!data && busy ? (
        <Loading />
      ) : error && !data ? (
        <ErrorState message={error.message} onRetry={() => load(1, book)} />
      ) : !data || (data.summary.count === 0 && data.results.length === 0 && !book) ? (
        <Empty icon="clipboard-list" title="هنوز آزمونی نداده‌ای" text="در صفحه‌ی کتاب، کنار هر فصل دکمه‌ی «آزمون» هست." />
      ) : (
        <ScrollView contentContainerStyle={styles.page} refreshControl={refresh}>
          <View style={styles.summary}>
            <View style={styles.nums}>
              <Stat label="آزمون" value={toPersianDigits(data.summary.count)} />
              <Stat label="میانگین" value={data.summary.average == null ? '—' : pct(data.summary.average)} />
              <Stat label="بهترین" value={data.summary.best == null ? '—' : pct(data.summary.best)} />
            </View>
            <ScoreTrend scores={data.summary.trend} />
          </View>
          {data.books.length > 1 && (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips}>
              {[{ slug: '', title: 'همه‌ی کتاب‌ها' }, ...data.books].map((b) => (
                <Pill key={b.slug} label={b.title} selected={book === b.slug} onPress={() => setBook(b.slug)} role="radio" />
              ))}
            </ScrollView>
          )}
          {data.results.map((e) => (
            <ListRow
              key={e.id}
              icon="trophy"
              title={e.node_title}
              subtitle={`${e.book_title ? `${e.book_title}، ` : ''}${jalaliDateTime(e.started_at)}، ${toPersianDigits(e.question_count)} سؤال`}
              value={<Text style={[styles.score, !e.submitted_at && { color: colors.muted, fontSize: 15 }]}>{e.submitted_at ? pct(e.score_percent) : 'ناتمام'}</Text>}
              onPress={() => router.push(`/exam-result/${e.id}`)}
            />
          ))}
          {data.has_more && <Button label="آزمون‌های قدیمی‌تر" variant="outline" loading={busy} onPress={() => load(page + 1, book)} />}
        </ScrollView>
      )}
    </Screen>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ alignItems: 'center', flex: 1 }}>
      <Text style={styles.statValue}>{value}</Text>
      <Text style={styles.muted}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 10 },
  summary: { backgroundColor: colors.ink, borderRadius: 18, padding: 16, gap: 14 },
  nums: { flexDirection: 'row-reverse' },
  statValue: { fontSize: 22, fontWeight: '900', color: colors.lemon },
  chips: { flexDirection: 'row-reverse', gap: 8, paddingVertical: 2 },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 14 },
  title: { fontSize: 15, fontWeight: '800', color: colors.ink },
  muted: { fontSize: 12, color: colors.muted },
  score: { fontSize: 18, fontWeight: '800', color: colors.greenDark },
});
