import { router, useFocusEffect } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { endpoints, type Stats } from '../../api/endpoints';
import { useCelebrate } from '../../components/Celebrate';
import { IconBadge, type IconName } from '../../components/Icon';
import { Text } from '../../components/Text';
import { Button, Card, Empty, ErrorState, Loading, Screen, usePullRefresh } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { weekdayShort } from '../../lib/jalali';
import { colors, rtl, toPersianDigits } from '../../theme';

function Tile({ label, value, accent, icon }: { label: string; value: string; accent?: boolean; icon: IconName }) {
  return (
    <View style={[styles.tile, accent && { backgroundColor: colors.ink }]}>
      <IconBadge name={icon} size={32} />
      <Text style={[styles.tileValue, accent && { color: colors.lemon }]}>{value}</Text>
      <Text style={[styles.tileLabel, accent && { color: '#C9D0C6' }]}>{label}</Text>
    </View>
  );
}

export default function StatsTab() {
  const { user } = useAuth();
  const [data, setData] = useState<Stats | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const celebrate = useCelebrate();
  const load = useCallback(() => {
    if (!user) return;
    setLoading(true);
    endpoints
      .stats()
      .then((d) => {
        setData(d);
        setError(null);
        // Streak milestones are celebrated once each.
        const milestone = [100, 30, 7, 3].find((m) => d.streak_days >= m);
        if (milestone) {
          const key = `limo.streak.${user.id}.${milestone}`;
          AsyncStorage.getItem(key)
            .then((seen) => {
              if (seen) return;
              AsyncStorage.setItem(key, '1').catch(() => undefined);
              celebrate('streak', { title: milestone === 7 ? 'یک هفته‌ی کامل!' : `${toPersianDigits(milestone)} روز پشت سر هم!`, text: 'عادت مطالعه‌ات دارد شکل می‌گیرد. فردا هم یک بخش کوتاه بخوان.', days: d.streak_days });
            })
            .catch(() => undefined);
        }
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [user, celebrate]);
  useFocusEffect(load);
  const refresh = usePullRefresh(loading, load);

  if (!user) {
    return (
      <Screen tab>
        <Text style={[styles.title, rtl]}>آمار من</Text>
        <Empty
          icon="chart-column"
          title="پیشرفتت را ببین"
          text="بعد از ورود، روزهای پیاپی مطالعه، درصد پاسخ درست و بخش‌هایی که باید بیشتر کار کنی اینجا نشان داده می‌شود."
          action={<Button label="ورود یا ثبت‌نام" onPress={() => router.push('/login')} style={{ alignSelf: 'stretch' }} />}
        />
      </Screen>
    );
  }
  if (!data) return <Screen tab>{error ? <ErrorState message={error} onRetry={load} /> : <Loading />}</Screen>;

  const peak = Math.max(1, ...data.last_14_days.map((d) => d.sections + d.answers + d.cards));

  return (
    <Screen tab>
      <ScrollView contentContainerStyle={styles.page} refreshControl={refresh}>
        <Text style={[styles.title, rtl, { padding: 0 }]}>آمار من</Text>
        <View style={styles.tiles}>
          <Tile accent icon="flame" label="روز پیاپی" value={toPersianDigits(data.streak_days)} />
          <Tile icon="target" label="درصد پاسخ درست" value={data.accuracy === null ? '—' : `${toPersianDigits(data.accuracy)}٪`} />
          <Tile icon="book-open" label="بخش خوانده‌شده" value={toPersianDigits(data.sections_done)} />
          <Tile icon="circle-check" label="تست حل‌شده" value={toPersianDigits(data.answers)} />
          <Tile icon="layers" label="کارت مسلط" value={`${toPersianDigits(data.cards_mastered)} از ${toPersianDigits(data.cards_reviewed)}`} />
          <Tile icon="trophy" label="آزمون" value={toPersianDigits(data.exams)} />
        </View>

        <Card>
          <Text style={[styles.cardTitle, rtl]}>فعالیت ۱۴ روز اخیر</Text>
          <View style={styles.chart}>
            {data.last_14_days.map((d) => {
              const total = d.sections + d.answers + d.cards;
              return (
                <View key={d.date} style={styles.barCol}>
                  <View style={styles.barTrack}>
                    <View style={[styles.bar, { height: `${Math.max(total ? 8 : 0, (total / peak) * 100)}%` }]} />
                  </View>
                  <Text style={styles.barLabel}>{weekdayShort(d.date)}</Text>
                </View>
              );
            })}
          </View>
        </Card>

        {data.books.length > 0 && (
          <Card>
            <Text style={[styles.cardTitle, rtl]}>پیشرفت کتاب‌ها</Text>
            {data.books.map((b) => {
              const pct = b.total ? Math.round((b.done / b.total) * 100) : 0;
              return (
                <Pressable key={b.slug} onPress={() => router.push(`/book/${b.slug}`)} style={{ gap: 6 }}>
                  <View style={{ flexDirection: 'row-reverse', justifyContent: 'space-between' }}>
                    <Text style={[styles.bookTitle, rtl]}>{b.title}</Text>
                    <Text style={styles.muted}>{toPersianDigits(pct)}٪</Text>
                  </View>
                  <View style={styles.progressTrack}>
                    <View style={[styles.progressFill, { width: `${pct}%` }]} />
                  </View>
                </Pressable>
              );
            })}
          </Card>
        )}

        {data.weak_sections.length > 0 && (
          <Card>
            <Text style={[styles.cardTitle, rtl]}>بیشتر کار کن روی…</Text>
            {data.weak_sections.map((w) => (
              <Pressable key={w.id} onPress={() => router.push(`/quiz/${w.id}`)} style={styles.weak}>
                <Text style={[styles.bookTitle, rtl, { flex: 1 }]}>{w.title}</Text>
                <Text style={[styles.muted, { color: colors.redDark }]}>{toPersianDigits(w.accuracy)}٪ درست</Text>
              </Pressable>
            ))}
          </Card>
        )}
        <Button label="سابقه‌ی آزمون‌ها" variant="outline" onPress={() => router.push('/exams')} />
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  title: { fontSize: 24, fontWeight: '800', color: colors.ink, padding: 20, paddingBottom: 0 },
  page: { padding: 16, gap: 14 },
  tiles: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 10 },
  tile: { flexBasis: '30%', flexGrow: 1, backgroundColor: colors.surface, borderRadius: 18, padding: 12, borderWidth: 1, borderColor: colors.line, gap: 6, alignItems: 'flex-end' },
  tileValue: { fontSize: 20, fontWeight: '800', color: colors.ink, textAlign: 'right' },
  tileLabel: { fontSize: 12, color: colors.muted, textAlign: 'right' },
  cardTitle: { fontSize: 15, fontWeight: '800', color: colors.ink },
  chart: { flexDirection: 'row-reverse', gap: 4, height: 120, alignItems: 'flex-end' },
  barCol: { flex: 1, alignItems: 'center', gap: 4, height: '100%' },
  barTrack: { flex: 1, width: '100%', justifyContent: 'flex-end' },
  bar: { width: '100%', backgroundColor: colors.lemon, borderRadius: 6 },
  barLabel: { fontSize: 12, color: colors.muted },
  bookTitle: { fontSize: 14, fontWeight: '700', color: colors.ink },
  muted: { fontSize: 12, color: colors.muted },
  progressTrack: { height: 8, backgroundColor: colors.line, borderRadius: 4, overflow: 'hidden', flexDirection: 'row-reverse' },
  progressFill: { backgroundColor: colors.green, borderRadius: 4 },
  weak: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingVertical: 6 },
});
