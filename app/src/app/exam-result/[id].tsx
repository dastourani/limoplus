import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { endpoints } from '../../api/endpoints';
import { RichText } from '../../components/RichText';
import { Text } from '../../components/Text';
import { Button, Card, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { jalaliDateTime } from '../../lib/jalali';
import { useApi } from '../../lib/useApi';
import { colors, radius, rtl, toPersianDigits } from '../../theme';

const KEYS = ['الف', 'ب', 'ج', 'د', 'ه', 'و'];

export default function ExamResult() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data, error, loading, retry } = useApi(() => endpoints.exam(Number(id)), [id]);
  const [open, setOpen] = useState<number | null>(null);
  const [filter, setFilter] = useState<'all' | 'wrong'>('all');

  if (loading) return <Screen><Header title="نتیجه‌ی آزمون" /><Loading /></Screen>;
  if (error || !data) return <Screen><Header title="نتیجه‌ی آزمون" /><ErrorState message={error?.message ?? ''} onRetry={retry} /></Screen>;

  if (!data.submitted_at) {
    return (
      <Screen>
        <Header title="آزمون ناتمام" />
        <View style={styles.page}>
          <Button label="ادامه‌ی آزمون" onPress={() => router.replace({ pathname: `/exam/${data.node_id}`, params: { attempt: String(data.id) } })} />
        </View>
      </Screen>
    );
  }

  const review = new Map((data.review ?? []).map((r) => [r.question_id, r]));
  const questions = data.questions.filter((q) => filter === 'all' || review.get(q.id)?.picked_choice_id !== review.get(q.id)?.correct_choice_id);
  const score = data.score_percent ?? 0;

  return (
    <Screen>
      <Header title="نتیجه‌ی آزمون" subtitle={data.node_title} />
      <ScrollView contentContainerStyle={styles.page}>
        <View style={styles.hero}>
          <Text style={styles.score}>{toPersianDigits(score)}٪</Text>
          <Text style={styles.heroText}>
            {toPersianDigits(data.correct)} درست · {toPersianDigits(data.wrong)} غلط · {toPersianDigits(data.blank)} نزده
          </Text>
          <Text style={styles.heroSmall}>
            {data.negative_marking ? 'با نمره‌ی منفی' : 'بدون نمره‌ی منفی'} · {jalaliDateTime(data.submitted_at)}
          </Text>
        </View>
        <View style={styles.filters}>
          {(['all', 'wrong'] as const).map((f) => (
            <Pressable key={f} onPress={() => setFilter(f)} style={[styles.filter, filter === f && styles.filterOn]}>
              <Text style={{ fontWeight: '800', color: filter === f ? colors.lemon : colors.muted }}>{f === 'all' ? 'همه' : 'غلط‌ها و نزده‌ها'}</Text>
            </Pressable>
          ))}
        </View>
        {questions.map((q) => {
          const r = review.get(q.id);
          const i = data.questions.indexOf(q);
          const state = !r?.picked_choice_id ? 'blank' : r.picked_choice_id === r.correct_choice_id ? 'right' : 'wrong';
          return (
            <Card key={q.id}>
              <Pressable onPress={() => setOpen(open === q.id ? null : q.id)} style={styles.qHead}>
                <Text style={[styles.badge, state === 'right' ? styles.right : state === 'wrong' ? styles.wrong : styles.blank]}>
                  {state === 'right' ? 'درست' : state === 'wrong' ? 'غلط' : 'نزده'}
                </Text>
                <Text style={[styles.qNum, rtl]}>سؤال {toPersianDigits(i + 1)}</Text>
              </Pressable>
              <RichText text={q.stem} size={15} />
              {q.choices.map((c, ci) => {
                const correct = c.id === r?.correct_choice_id;
                const picked = c.id === r?.picked_choice_id;
                return (
                  <View key={c.id} style={[styles.choice, correct && styles.choiceRight, picked && !correct && styles.choiceWrong]}>
                    <Text style={styles.key}>{KEYS[ci]}</Text>
                    <View style={{ flex: 1 }}>
                      <RichText text={c.text} size={14} />
                    </View>
                  </View>
                );
              })}
              {open === q.id ? (
                <View style={{ gap: 8 }}>
                  <Text style={[styles.label, rtl]}>پاسخ تشریحی</Text>
                  <RichText text={r?.explanation ?? ''} size={14} />
                  {!!r?.quick_solution && (
                    <>
                      <Text style={[styles.label, rtl]}>راه‌حل سریع</Text>
                      <RichText text={r.quick_solution} size={14} />
                    </>
                  )}
                  {!!r?.alternative_view && (
                    <>
                      <Text style={[styles.label, rtl]}>زاویه‌ی دیگر</Text>
                      <RichText text={r.alternative_view} size={14} />
                    </>
                  )}
                </View>
              ) : (
                <Pressable onPress={() => setOpen(q.id)}>
                  <Text style={styles.link}>دیدن پاسخ تشریحی</Text>
                </Pressable>
              )}
            </Card>
          );
        })}
        <Button label="آزمون دوباره" onPress={() => router.replace(`/exam/${data.node_id}`)} />
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 12 },
  hero: { backgroundColor: colors.ink, borderRadius: radius.lg, padding: 22, alignItems: 'center', gap: 6 },
  score: { fontSize: 56, fontWeight: '900', color: colors.lemon },
  heroText: { fontSize: 15, color: colors.ground, fontWeight: '700' },
  heroSmall: { fontSize: 12, color: '#B9C4BC' },
  filters: { flexDirection: 'row-reverse', gap: 8 },
  filter: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface },
  filterOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  qHead: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center' },
  qNum: { fontSize: 14, fontWeight: '700', color: colors.ink },
  badge: { fontSize: 12, fontWeight: '700', paddingHorizontal: 10, paddingVertical: 3, borderRadius: 999, overflow: 'hidden' },
  right: { backgroundColor: colors.greenSoft, color: colors.greenDark },
  wrong: { backgroundColor: colors.redSoft, color: colors.redDark },
  blank: { backgroundColor: colors.disabled, color: colors.muted },
  choice: { flexDirection: 'row-reverse', gap: 10, alignItems: 'center', padding: 8, borderRadius: 12, borderWidth: 1.5, borderColor: 'transparent' },
  choiceRight: { borderColor: colors.green, backgroundColor: colors.greenSoft },
  choiceWrong: { borderColor: colors.red, backgroundColor: colors.redSoft },
  key: { fontWeight: '800', color: colors.muted, width: 24, textAlign: 'center' },
  label: { fontSize: 13, fontWeight: '700', color: colors.greenDark },
  link: { color: colors.greenDark, fontWeight: '800', textAlign: 'right' },
});
