import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { endpoints } from '../../api/endpoints';
import { useCelebrate } from '../../components/Celebrate';
import { RichText } from '../../components/RichText';
import { Text } from '../../components/Text';
import { Button, Card, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { Pill } from '../../components/Pill';
import { jalaliDate, jalaliDateTime } from '../../lib/jalali';
import { seeded } from '../../lib/shuffle';
import { useApi } from '../../lib/useApi';
import { colors, radius, rtl, toPersianDigits } from '../../theme';

const KEYS = ['الف', 'ب', 'ج', 'د', 'ه', 'و'];

export default function ExamResult() {
  const { id, fresh } = useLocalSearchParams<{ id: string; fresh?: string }>();
  const celebrate = useCelebrate();
  const shown = useRef(false);
  const { data, error, loading, retry } = useApi(() => endpoints.exam(Number(id)), [id]);
  const [open, setOpen] = useState<number | null>(null);
  const [filter, setFilter] = useState<'all' | 'wrong'>('all');

  // Right after finishing an exam: a moment that matches the score (gentle when it went badly).
  useEffect(() => {
    if (!fresh || shown.current || !data?.submitted_at) return;
    shown.current = true;
    const s = data.score_percent ?? 0;
    const exam = { score: s, right: data.correct, wrong: data.wrong, blank: data.blank };
    const back = { label: 'بازگشت به کتاب', onPress: () => router.back() };
    const misses = data.wrong + data.blank;
    if (s >= 80)
      celebrate('great', { title: 'عالی بود!', text: data.wrong ? `فقط ${toPersianDigits(data.wrong)} غلط. همین مسیر را ادامه بده.` : 'بدون غلط! همین مسیر را ادامه بده.', exam, primary: 'دیدن پاسخ‌ها', secondary: back });
    else if (s >= 50)
      celebrate('good', { title: 'خوب بود!', text: `${toPersianDigits(misses)} سؤال مانده تا همه را بلد باشی. غلط‌ها را مرور کن.`, exam, primary: `مرور ${toPersianDigits(misses)} غلط و نزده`, secondary: back });
    else
      celebrate('low', { title: 'شروع خوبی برای یاد گرفتن است', text: 'پاسخ تشریحی غلط‌ها را بخوان؛ دفعه‌ی بعد خیلی بهتر می‌شود.', exam, primary: 'خواندن پاسخ‌ها', secondary: { label: 'بعداً', onPress: () => router.back() } });
    if (s < 80 && misses) setFilter('wrong');
  }, [fresh, data, celebrate]);

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
            {toPersianDigits(data.correct)} درست، {toPersianDigits(data.wrong)} غلط، {toPersianDigits(data.blank)} نزده
          </Text>
          <Text style={styles.heroSmall}>
            {data.negative_marking ? 'با نمره‌ی منفی' : 'بدون نمره‌ی منفی'}، {jalaliDateTime(data.submitted_at)}
          </Text>
        </View>
        <View style={styles.filters}>
          {(['all', 'wrong'] as const).map((f) => (
            <Pill key={f} label={f === 'all' ? 'همه' : 'غلط‌ها و نزده‌ها'} selected={filter === f} onPress={() => setFilter(f)} />
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
              {!!r?.corrected && (
                <View style={styles.corrected}>
                  <Text style={[styles.correctedTitle, rtl]}>اصلاح‌شده: پاسخ‌نامه‌ی این تست در {jalaliDate(r.corrected.at)}، بعد از آزمونت، اصلاح شد.</Text>
                  <RichText text={r.corrected.note} size={13} />
                  <Text style={[styles.correctedText, rtl]}>نمره‌ی این آزمون با پاسخ‌نامه‌ی زمان آزمون حساب شده و تغییر نمی‌کند.</Text>
                </View>
              )}
              {/* The choices in the order the exam showed them. */}
              {(q.fixed_order ? q.choices : seeded(q.choices, data.id * 7919 + q.id)).map((c, ci) => {
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
                  {!!r?.node_id && (
                    <Pressable onPress={() => router.push(`/section/${r.node_id}`)} accessibilityRole="link">
                      <Text style={styles.link}>این نکته در جزوه ←</Text>
                    </Pressable>
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
  qHead: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center' },
  qNum: { fontSize: 15, fontWeight: '700', color: colors.ink },
  badge: { fontSize: 12, fontWeight: '700', paddingHorizontal: 10, paddingVertical: 4, borderRadius: 999, overflow: 'hidden' },
  right: { backgroundColor: colors.greenSoft, color: colors.greenDark },
  wrong: { backgroundColor: colors.redSoft, color: colors.redDark },
  blank: { backgroundColor: colors.disabled, color: colors.muted },
  choice: { flexDirection: 'row-reverse', gap: 10, alignItems: 'center', padding: 8, borderRadius: 12, borderWidth: 1.5, borderColor: 'transparent' },
  choiceRight: { borderColor: colors.green, backgroundColor: colors.greenSoft },
  choiceWrong: { borderColor: colors.red, backgroundColor: colors.redSoft },
  key: { fontWeight: '800', color: colors.muted, width: 24, textAlign: 'center' },
  label: { fontSize: 13, fontWeight: '700', color: colors.greenDark },
  link: { color: colors.greenDark, fontWeight: '800', textAlign: 'right' },
  corrected: { backgroundColor: '#F1EEFC', borderRadius: 12, padding: 10, gap: 4 },
  correctedTitle: { fontSize: 13, fontWeight: '800', color: '#3A2F7A' },
  correctedText: { fontSize: 12, color: '#3A2F7A' },
});
