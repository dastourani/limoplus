/** «آزمون‌های من»: average, best, trend and the last three exams, each opening its own report card; «همه‌ی آزمون‌ها»
 * opens the full history. Lives in the Stats tab and on the book page. */
import { router } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import type { ExamPage } from '../api/endpoints';
import { colors, rtl, toPersianDigits } from '../theme';
import { Icon } from './Icon';
import { LemonProgress } from './LemonProgress';
import { ScoreTrend } from './ScoreTrend';
import { Text } from './Text';
import { whenShort } from '../lib/jalali';

export function ExamsCard({ exams, book }: { exams: ExamPage; book?: { slug: string; title: string } }) {
  const s = exams.summary;
  const all = () => router.push(book ? { pathname: '/exams', params: { book: book.slug } } : '/exams');
  return (
    <View style={styles.card}>
      <Pressable onPress={all} style={styles.head} accessibilityRole="button" accessibilityLabel="سابقه‌ی آزمون‌ها">
        <Text style={[styles.title, rtl]}>{book ? 'آزمون‌هایم از این کتاب' : 'آزمون‌های من'}</Text>
        <Icon name="chevron-left" size={20} color={colors.muted} />
      </Pressable>
      <Text style={[styles.line, rtl]}>
        {toPersianDigits(s.count)} آزمون، میانگین {toPersianDigits(Math.round(s.average ?? 0))}٪، بهترین {toPersianDigits(Math.round(s.best ?? 0))}٪
      </Text>
      {s.trend.length > 1 && <ScoreTrend scores={s.trend} height={34} />}
      {exams.results.slice(0, 3).map((e) => {
        const done = !!e.submitted_at;
        const score = Math.max(0, Math.round(e.score_percent ?? 0));
        return (
          <Pressable
            key={e.id}
            // A finished exam opens its report card; one still running opens where it was.
            onPress={() =>
              done
                ? router.push(`/exam-result/${e.id}`)
                : router.push({ pathname: '/exam/[nodeId]', params: { nodeId: String(e.node_id), attempt: String(e.id) } })
            }
            style={({ pressed }) => [styles.row, pressed && { opacity: 0.75 }]}
            accessibilityRole="button"
            accessibilityLabel={`${e.node_title}، ${done ? `${score} درصد` : 'ناتمام'}`}
          >
            <LemonProgress value={done ? score / 100 : 0} segments={10} size={30} />
            <View style={{ flex: 1 }}>
              <Text style={[styles.examTitle, rtl]} numberOfLines={1}>
                {e.number ? `${e.node_title}، آزمون ${toPersianDigits(e.number)}` : e.node_title}
              </Text>
              <Text style={[styles.when, rtl]}>{whenShort(e.started_at)}</Text>
            </View>
            <Text style={[styles.score, !done && styles.unfinished]}>{done ? `${toPersianDigits(score)}٪` : 'ناتمام'}</Text>
            <Icon name="chevron-left" size={16} color="#9FB0A5" />
          </Pressable>
        );
      })}
      <Pressable onPress={all} accessibilityRole="button">
        <Text style={[styles.more, rtl]}>همه‌ی آزمون‌ها ←</Text>
      </Pressable>
    </View>
  );
}

const styles = StyleSheet.create({
  // White like the other cards of the stats page (only the insight card and the streak tile are dark).
  card: { backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 16, gap: 10 },
  head: { flexDirection: 'row-reverse', alignItems: 'center' },
  when: { fontSize: 12, color: colors.muted },
  title: { flex: 1, fontSize: 15, fontWeight: '800', color: colors.ink },
  line: { fontSize: 13, color: colors.muted },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 8 },
  examTitle: { fontSize: 15, fontWeight: '700', color: colors.ink },
  score: { fontSize: 15, fontWeight: '800', color: '#B98A00' },
  unfinished: { color: colors.muted, fontWeight: '700' },
  more: { fontSize: 13, fontWeight: '800', color: colors.greenDark },
});
