/** «آزمون‌های من»: average, best, trend and the last three exams; opens the full history. Lives in the Stats tab. */
import { router } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import type { ExamPage } from '../api/endpoints';
import { colors, rtl, toPersianDigits } from '../theme';
import { Icon } from './Icon';
import { ScoreTrend } from './ScoreTrend';
import { Text } from './Text';

export function ExamsCard({ exams, book }: { exams: ExamPage; book?: { slug: string; title: string } }) {
  const s = exams.summary;
  const open = () => router.push(book ? { pathname: '/exams', params: { book: book.slug } } : '/exams');
  return (
    <Pressable onPress={open} style={styles.card} accessibilityRole="button" accessibilityLabel="سابقه‌ی آزمون‌ها">
      <View style={styles.head}>
        <Text style={[styles.title, rtl]}>{book ? 'آزمون‌هایم از این کتاب' : 'آزمون‌های من'}</Text>
        <Icon name="chevron-left" size={20} color={colors.lemon} />
      </View>
      <Text style={[styles.line, rtl]}>
        {toPersianDigits(s.count)} آزمون، میانگین {toPersianDigits(Math.round(s.average ?? 0))}٪، بهترین {toPersianDigits(Math.round(s.best ?? 0))}٪
      </Text>
      {s.trend.length > 1 && <ScoreTrend scores={s.trend} height={34} />}
      {exams.results.slice(0, 3).map((e) => (
        <View key={e.id} style={styles.row}>
          <Text style={[styles.examTitle, rtl]} numberOfLines={1}>
            {e.node_title}
          </Text>
          <Text style={styles.score}>{e.submitted_at ? `${toPersianDigits(Math.round(e.score_percent ?? 0))}٪` : 'ناتمام'}</Text>
        </View>
      ))}
      <Text style={[styles.more, rtl]}>همه‌ی آزمون‌ها ←</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.ink, borderRadius: 18, padding: 16, gap: 10 },
  head: { flexDirection: 'row-reverse', alignItems: 'center' },
  title: { flex: 1, fontSize: 15, fontWeight: '800', color: '#FFFFFF' },
  line: { fontSize: 13, color: '#C9D2C6' },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, borderTopWidth: 1, borderTopColor: '#2B3830', paddingTop: 8 },
  examTitle: { flex: 1, fontSize: 15, fontWeight: '700', color: '#EDEFE6' },
  score: { fontSize: 15, fontWeight: '800', color: colors.lemon },
  more: { fontSize: 13, fontWeight: '800', color: colors.lemon },
});
