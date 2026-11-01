import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { ApiError } from '../api/client';
import { endpoints, type Mistakes } from '../api/endpoints';
import { Icon } from '../components/Icon';
import { Text } from '../components/Text';
import { Button, Empty, ErrorState, Header, Loading, Screen, usePullRefresh } from '../components/ui';
import { requireLogin, useAuth } from '../lib/auth';
import { jalaliDate } from '../lib/jalali';
import { colors, rtl, toPersianDigits } from '../theme';

/** «دفترچه‌ی اشتباهات»: every question whose latest answer was wrong (or blank in an exam), with the learner's reason. */
export default function MistakesScreen() {
  const { user } = useAuth();
  const [book, setBook] = useState('');
  const [data, setData] = useState<Mistakes | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);

  const load = useCallback(async () => {
    if (!user) return;
    setBusy(true);
    setError(null);
    try {
      setData(await endpoints.mistakes(book));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, 'error', 'خطا'));
    } finally {
      setBusy(false);
    }
  }, [book, user]);
  // Back from practising: fixed questions have left the notebook.
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );
  const refresh = usePullRefresh(busy, load);

  const setReason = (questionId: number, reason: string) => {
    if (!data) return;
    const before = data;
    setData({ ...data, items: data.items.map((i) => (i.question_id === questionId ? { ...i, reason } : i)) });
    endpoints.mistakeReason(questionId, reason).catch(() => setData(before));
  };

  if (!user) {
    return (
      <Screen>
        <Header title="دفترچه‌ی اشتباهات" />
        <Empty icon="notebook-pen" title="برای دفترچه‌ی اشتباهات وارد شوید" text="تست‌هایی که غلط می‌زنی این‌جا جمع می‌شوند تا دوباره تمرینشان کنی." />
        <View style={{ padding: 16 }}>
          <Button label="ورود" onPress={() => requireLogin(user, 'برای دفترچه‌ی اشتباهات وارد شوید.')} />
        </View>
      </Screen>
    );
  }

  return (
    <Screen>
      <Header title="دفترچه‌ی اشتباهات" />
      {!data && busy ? (
        <Loading />
      ) : error && !data ? (
        <ErrorState message={error.message} onRetry={load} />
      ) : !data || (data.count === 0 && !book) ? (
        <Empty icon="circle-check" title="دفترچه خالی است" text="تست‌هایی که غلط بزنی یا در آزمون نزنی این‌جا می‌آیند؛ هر کدام را درست جواب بدهی، از دفترچه بیرون می‌رود." />
      ) : (
        <ScrollView contentContainerStyle={styles.page} refreshControl={refresh}>
          <View style={styles.top}>
            <Text style={[styles.topTitle, rtl]}>{toPersianDigits(data.count)} تست منتظر جبران</Text>
            <Text style={[styles.topText, rtl]}>هر کدام را درست جواب بدهی، از دفترچه بیرون می‌رود.</Text>
            {data.count > 0 && (
              <Button
                label="تمرین همین اشتباه‌ها"
                onPress={() => router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: 'mistakes', ...(book ? { book } : {}) } })}
              />
            )}
          </View>
          {data.books.length > 1 && (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips} style={{ transform: [{ scaleX: -1 }] }}>
              {[{ slug: '', title: 'همه‌ی کتاب‌ها' }, ...data.books].map((b) => (
                <Pressable
                  key={b.slug}
                  onPress={() => setBook(b.slug)}
                  style={[styles.chip, book === b.slug && styles.chipOn, { transform: [{ scaleX: -1 }] }]}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: book === b.slug }}
                >
                  <Text style={[styles.chipText, book === b.slug && { color: colors.lemon }]}>{b.title}</Text>
                </Pressable>
              ))}
            </ScrollView>
          )}
          {data.items.map((m) => (
            <View key={m.question_id} style={styles.row}>
              <Text style={[styles.text, rtl]} numberOfLines={3}>{m.text || 'سؤال تصویری'}</Text>
              <Pressable onPress={() => router.push(`/section/${m.node_id}`)} style={styles.where} accessibilityRole="link">
                <Icon name="book-open" size={14} color={colors.greenDark} />
                <Text style={[styles.whereText, rtl]} numberOfLines={1}>
                  {m.book_title}، {m.node_title}
                </Text>
              </Pressable>
              <Text style={[styles.meta, rtl]}>
                {m.blank ? 'در آزمون نزده' : m.wrong_count > 1 ? `${toPersianDigits(m.wrong_count)} بار غلط` : 'غلط'}، {jalaliDate(m.last_at)}
              </Text>
              <View style={styles.reasons}>
                {data.reasons.map((r) => {
                  const on = m.reason === r.key;
                  return (
                    <Pressable
                      key={r.key}
                      onPress={() => setReason(m.question_id, on ? '' : r.key)}
                      style={[styles.reason, on && styles.reasonOn]}
                      accessibilityRole="radio"
                      accessibilityState={{ checked: on }}
                    >
                      <Text style={[styles.reasonText, on && { color: colors.ink }]}>{r.label}</Text>
                    </Pressable>
                  );
                })}
              </View>
            </View>
          ))}
        </ScrollView>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 10 },
  top: { backgroundColor: colors.ink, borderRadius: 20, padding: 16, gap: 8 },
  topTitle: { fontSize: 18, fontWeight: '900', color: colors.lemon },
  topText: { fontSize: 13, color: '#C9D2C6' },
  chips: { gap: 8, paddingVertical: 2 },
  chip: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, borderWidth: 1.5, borderColor: colors.line, backgroundColor: colors.surface },
  chipOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  chipText: { fontSize: 13, fontWeight: '700', color: colors.ink },
  row: { backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 14, gap: 6 },
  text: { fontSize: 15, color: colors.ink, lineHeight: 26 },
  where: { flexDirection: 'row-reverse', alignItems: 'center', gap: 5 },
  whereText: { flex: 1, fontSize: 12, fontWeight: '700', color: colors.greenDark },
  meta: { fontSize: 12, color: colors.muted },
  reasons: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 6, marginTop: 2 },
  reason: { paddingHorizontal: 10, paddingVertical: 5, borderRadius: 999, borderWidth: 1, borderColor: colors.line },
  reasonOn: { backgroundColor: colors.lemon, borderColor: colors.lemon },
  reasonText: { fontSize: 12, fontWeight: '700', color: colors.muted },
});
