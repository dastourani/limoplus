import AsyncStorage from '@react-native-async-storage/async-storage';
import { router, useLocalSearchParams, useNavigation } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Switch, View } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints, type ExamDetail } from '../../api/endpoints';
import { RichText } from '../../components/RichText';
import { Text } from '../../components/Text';
import { useFeedback } from '../../components/Feedback';
import { Icon } from '../../components/Icon';
import { Button, Card, Header, Screen } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { colors, radius, rtl, toPersianDigits } from '../../theme';

const KEYS = ['الف', 'ب', 'ج', 'د', 'ه', 'و'];
const COUNTS = [10, 20, 30, 50];

function clock(seconds: number) {
  const s = Math.max(0, seconds);
  return toPersianDigits(`${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`);
}

/** Exam mode: timed, no feedback until the end, negative marking on by default (as in the konkur). */
export default function Exam() {
  const { nodeId, attempt } = useLocalSearchParams<{ nodeId: string; attempt?: string }>();
  const { user } = useAuth();
  const [count, setCount] = useState(20);
  const [negative, setNegative] = useState(true);
  const [exam, setExam] = useState<ExamDetail | null>(null);
  const [answers, setAnswers] = useState<Record<string, number | null>>({});
  const [index, setIndex] = useState(0);
  const [left, setLeft] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitted = useRef(false);
  const { confirm } = useFeedback();
  type BeforeRemove = { preventDefault: () => void; data: { action: unknown } };
  const navigation = useNavigation() as unknown as {
    addListener: (event: 'beforeRemove', cb: (e: BeforeRemove) => void) => () => void;
    dispatch: (action: unknown) => void;
  };

  // Leaving mid-exam (back button or gesture) asks first; the timer keeps running on the server.
  useEffect(() => {
    if (!exam) return;
    return navigation.addListener('beforeRemove', (e) => {
      if (submitted.current) return;
      e.preventDefault();
      confirm({
        title: 'از آزمون خارج می‌شوید؟',
        message: 'زمان آزمون ادامه دارد. پاسخ‌هایتان روی گوشی می‌ماند و از «سابقه‌ی آزمون‌ها» می‌توانید ادامه دهید.',
        confirmLabel: 'خروج',
        cancelLabel: 'ادامه‌ی آزمون',
        destructive: true,
      }).then((ok) => ok && navigation.dispatch(e.data.action));
    });
  }, [exam, navigation, confirm]);

  const storeKey = exam ? `limo.exam.${exam.id}` : null;

  // Resuming an unfinished exam (e.g. the app was closed): reload it and the answers kept on the phone.
  useEffect(() => {
    if (!attempt) return;
    (async () => {
      try {
        const e = await endpoints.exam(Number(attempt));
        if (e.submitted_at) {
          router.replace(`/exam-result/${e.id}`);
          return;
        }
        const saved = await AsyncStorage.getItem(`limo.exam.${e.id}`).catch(() => null);
        setAnswers(saved ? (JSON.parse(saved) as Record<string, number | null>) : {});
        setExam(e);
      } catch (err) {
        setError(err instanceof ApiError ? err.message : 'بارگذاری آزمون ممکن نشد.');
      }
    })();
  }, [attempt]);

  const start = async () => {
    if (!requireLogin(user, 'آزمون‌ها و نتیجه‌شان روی حساب شما ذخیره می‌شود؛ اول وارد شوید.')) return;
    setBusy(true);
    setError(null);
    try {
      const e = await endpoints.startExam(Number(nodeId), { count, negative_marking: negative });
      setExam(e);
      setAnswers({});
      setIndex(0);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'شروع آزمون ممکن نشد.');
    } finally {
      setBusy(false);
    }
  };

  const submit = async () => {
    if (!exam || submitted.current) return;
    submitted.current = true;
    setBusy(true);
    try {
      await endpoints.submitExam(exam.id, answers);
      if (storeKey) AsyncStorage.removeItem(storeKey).catch(() => undefined);
      router.replace(`/exam-result/${exam.id}`);
    } catch (e) {
      submitted.current = false;
      setError(e instanceof ApiError ? e.message : 'ارسال پاسخ‌ها ممکن نشد. دوباره تلاش کنید.');
    } finally {
      setBusy(false);
    }
  };

  // Countdown; submits by itself when time is up.
  useEffect(() => {
    if (!exam) return;
    const tick = () => {
      const s = Math.round((new Date(exam.ends_at).getTime() - Date.now()) / 1000);
      setLeft(s);
      if (s <= 0) submit();
    };
    tick();
    const t = setInterval(tick, 1000);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [exam]);

  // Keep answers on the phone too, in case the app is closed mid-exam.
  useEffect(() => {
    if (storeKey && Object.keys(answers).length) AsyncStorage.setItem(storeKey, JSON.stringify(answers)).catch(() => undefined);
  }, [answers, storeKey]);

  if (!exam && attempt) {
    return (
      <Screen>
        <Header title="آزمون" />
        {error ? <Text style={[styles.error, rtl, { padding: 16 }]}>{error}</Text> : null}
      </Screen>
    );
  }

  if (!exam) {
    return (
      <Screen>
        <Header title="آزمون" />
        <ScrollView contentContainerStyle={styles.page}>
          <Card>
            <Text style={[styles.label, rtl]}>تعداد سؤال</Text>
            <View style={styles.counts}>
              {COUNTS.map((c) => (
                <Pressable key={c} onPress={() => setCount(c)} style={[styles.count, count === c && styles.countOn]}>
                  <Text style={{ fontWeight: '800', color: count === c ? colors.lemon : colors.ink }}>{toPersianDigits(c)}</Text>
                </Pressable>
              ))}
            </View>
            <View style={styles.switchRow}>
              <Text style={[styles.label, rtl, { flex: 1 }]}>نمره‌ی منفی (هر ۳ غلط، ۱ درست را خنثی می‌کند)</Text>
              <Switch value={negative} onValueChange={setNegative} trackColor={{ true: colors.green }} />
            </View>
            <Text style={[styles.help, rtl]}>زمان بر اساس سطح سؤال‌ها تعیین می‌شود. پاسخ‌ها تا پایان آزمون نشان داده نمی‌شوند.</Text>
          </Card>
          {!!error && <Text style={[styles.error, rtl]}>{error}</Text>}
          <Button label={busy ? '…' : 'شروع آزمون'} onPress={start} disabled={busy} />
        </ScrollView>
      </Screen>
    );
  }

  const q = exam.questions[index];
  const answeredCount = Object.values(answers).filter((v) => v != null).length;

  return (
    <Screen>
      <View style={styles.top}>
        <View style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 6 }}>
          <Icon name="timer" size={22} color={left < 60 ? colors.red : colors.ink} />
          <Text style={[styles.timer, left < 60 && { color: colors.red }]}>{clock(left)}</Text>
        </View>
        <Text style={styles.help}>
          {toPersianDigits(answeredCount)} از {toPersianDigits(exam.questions.length)} پاسخ داده‌شده
        </Text>
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.grid}>
        {exam.questions.map((item, i) => (
          <Pressable key={item.id} onPress={() => setIndex(i)} style={[styles.dot, answers[item.id] != null && styles.dotDone, i === index && styles.dotNow]}>
            <Text style={[styles.dotText, (answers[item.id] != null || i === index) && { color: i === index ? colors.lemon : '#fff' }]}>{toPersianDigits(i + 1)}</Text>
          </Pressable>
        ))}
      </ScrollView>
      <ScrollView contentContainerStyle={styles.page}>
        <Text style={[styles.help, rtl]}>سؤال {toPersianDigits(index + 1)}</Text>
        <RichText text={q.stem} size={17} />
        {q.choices.map((c, i) => {
          const on = answers[q.id] === c.id;
          return (
            <Pressable
              key={c.id}
              onPress={() => setAnswers((a) => ({ ...a, [q.id]: on ? null : c.id }))}
              style={[styles.choice, on && styles.choiceOn]}
              accessibilityRole="radio"
              accessibilityState={{ checked: on }}
            >
              <View style={[styles.key, on && { backgroundColor: colors.ink }]}>
                <Text style={[styles.keyText, on && { color: colors.lemon }]}>{KEYS[i]}</Text>
              </View>
              <View style={{ flex: 1 }}>
                <RichText text={c.text} size={15} />
              </View>
            </Pressable>
          );
        })}
        <Text style={[styles.help, rtl]}>برای پاک کردن پاسخ (نزدن)، دوباره روی همان گزینه بزنید.</Text>
        {!!error && <Text style={[styles.error, rtl]}>{error}</Text>}
      </ScrollView>
      <View style={styles.bar}>
        <Button label="قبلی" variant="outline" disabled={index === 0} onPress={() => setIndex((i) => i - 1)} style={{ flex: 1 }} />
        {index + 1 < exam.questions.length ? (
          <Button label="بعدی" variant="dark" onPress={() => setIndex((i) => i + 1)} style={{ flex: 1 }} />
        ) : (
          <Button
            label={busy ? '…' : 'پایان آزمون'}
            disabled={busy}
            onPress={async () =>
              (await confirm({
                title: 'آزمون تمام شود؟',
                message: answeredCount < exam.questions.length ? `${toPersianDigits(exam.questions.length - answeredCount)} سؤال بی‌پاسخ است.` : 'همه‌ی سؤال‌ها پاسخ داده شده‌اند.',
                confirmLabel: 'پایان آزمون',
                icon: 'circle-check',
              })) && submit()
            }
            style={{ flex: 1.3 }}
          />
        )}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 14 },
  label: { fontSize: 15, fontWeight: '800', color: colors.ink },
  help: { fontSize: 13, color: colors.muted, lineHeight: 22 },
  error: { color: colors.redDark },
  counts: { flexDirection: 'row-reverse', gap: 8 },
  count: { flex: 1, paddingVertical: 12, borderRadius: 14, borderWidth: 1.5, borderColor: colors.line, alignItems: 'center' },
  countOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  switchRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10 },
  top: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingTop: 10 },
  timer: { fontSize: 22, fontWeight: '800', color: colors.ink },
  grid: { gap: 6, paddingHorizontal: 16, paddingVertical: 10, flexDirection: 'row-reverse' },
  dot: { width: 36, height: 36, borderRadius: 12, borderWidth: 1.5, borderColor: colors.line, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.surface },
  dotDone: { backgroundColor: colors.green, borderColor: colors.green },
  dotNow: { backgroundColor: colors.ink, borderColor: colors.ink },
  dotText: { fontSize: 13, fontWeight: '700', color: colors.muted },
  choice: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, minHeight: 58, padding: 12, borderRadius: radius.md, borderWidth: 2, borderColor: colors.line, backgroundColor: colors.surface },
  choiceOn: { borderColor: colors.ink, backgroundColor: colors.lemonSoft },
  key: { width: 30, height: 30, borderRadius: 10, backgroundColor: '#F1F3EC', alignItems: 'center', justifyContent: 'center' },
  keyText: { fontWeight: '800', color: colors.ink },
  bar: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: colors.line },
});
