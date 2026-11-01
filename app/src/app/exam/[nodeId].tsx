import AsyncStorage from '@react-native-async-storage/async-storage';
import { router, useLocalSearchParams, useNavigation } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Pressable, ScrollView, StyleSheet, Switch, View } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints, type ExamDetail } from '../../api/endpoints';
import { LemonProgress, type PartState } from '../../components/LemonProgress';
import { QuestionPicker } from '../../components/QuestionPicker';
import { QuizView, type QuizEvent } from '../../components/QuizView';
import { Text } from '../../components/Text';
import { useFeedback } from '../../components/Feedback';
import { Icon } from '../../components/Icon';
import { Button, Card, Header, Screen } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { usePageTurn } from '../../lib/pageTurn';
import { seeded } from '../../lib/shuffle';
import { type QuizViewState } from '../../lib/quizHtml';
import { colors, rtl, toPersianDigits } from '../../theme';

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
  // The timer's submit must send the answers as they are now, not as they were when the timer started.
  const answersRef = useRef(answers);
  answersRef.current = answers;
  const [index, setIndex] = useState(0);
  const [left, setLeft] = useState(0);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const submitted = useRef(false);
  const { confirm } = useFeedback();
  const [pickerOpen, setPickerOpen] = useState(false);
  const { style: pageStyle, turn } = usePageTurn();
  const go = useCallback(
    (target: number, alreadyOut = false) => {
      if (!exam || target === index || target < 0 || target >= exam.questions.length) return;
      turn(target > index, () => setIndex(target), alreadyOut);
    },
    [exam, index, turn],
  );
  // Choices in a different order in each exam (graded by id on the server, so nothing else changes).
  const shownQ = useMemo(() => {
    const raw = exam?.questions[index];
    return raw ? { ...raw, choices: seeded(raw.choices, exam!.id * 7919 + raw.id) } : null;
  }, [exam, index]);
  const currentId = exam?.questions[index]?.id;
  const picked = currentId != null ? (answers[currentId] ?? null) : null;
  const viewState = useMemo<QuizViewState>(
    () => ({ picked, sending: false, error: null, reported: false, result: null, canPrev: index > 0, canNext: !!exam && index + 1 < exam.questions.length }),
    [picked, index, exam],
  );
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
      await endpoints.submitExam(exam.id, answersRef.current);
      if (storeKey) AsyncStorage.removeItem(storeKey).catch(() => undefined);
      router.replace({ pathname: `/exam-result/${exam.id}`, params: { fresh: '1' } });
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
          <Button label="شروع آزمون" onPress={start} loading={busy} />
        </ScrollView>
      </Screen>
    );
  }

  const q = shownQ!;
  const answeredCount = Object.values(answers).filter((v) => v != null).length;
  const parts: PartState[] = exam.questions.map((x) => (answers[x.id] != null ? 'done' : 'empty'));
  const last = index + 1 >= exam.questions.length;

  const onEvent = (e: QuizEvent) => {
    if (e.type === 'choose') setAnswers((a) => ({ ...a, [q.id]: a[q.id] === e.id ? null : e.id }));
    else if (e.type === 'swipe') go(index + (e.dir === 'next' ? 1 : -1), e.flung);
  };

  const finish = async () =>
    (await confirm({
      title: 'آزمون تمام شود؟',
      message: answeredCount < exam.questions.length ? `${toPersianDigits(exam.questions.length - answeredCount)} سؤال بی‌پاسخ است.` : 'همه‌ی سؤال‌ها پاسخ داده شده‌اند.',
      confirmLabel: 'پایان آزمون',
      icon: 'circle-check',
    })) && submit();

  return (
    <Screen>
      <View style={styles.top}>
        <LemonProgress parts={parts} current={index} size={50} onPress={() => setPickerOpen(true)} accessibilityLabel="پیشرفت آزمون؛ برای رفتن به سؤال دیگر بزنید" />
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={[styles.label, rtl]}>
            سؤال {toPersianDigits(index + 1)} از {toPersianDigits(exam.questions.length)}
          </Text>
          <Text style={[styles.help, rtl]}>{toPersianDigits(answeredCount)} پاسخ داده‌شده</Text>
        </View>
        <View style={styles.clock}>
          <Icon name="timer" size={20} color={left < 60 ? colors.red : colors.ink} />
          <Text style={[styles.timer, left < 60 && { color: colors.red }]}>{clock(left)}</Text>
        </View>
      </View>
      <QuestionPicker
        visible={pickerOpen}
        onClose={() => setPickerOpen(false)}
        parts={parts}
        current={index}
        onPick={(i) => go(i)}
        legend="زرد: پاسخ داده‌شده، سفید: بی‌پاسخ. برای پاک کردن یک پاسخ، دوباره روی همان گزینه بزنید."
      />
      <Animated.View style={[{ flex: 1 }, pageStyle]}>
        <QuizView key={q.id} mode="exam" question={q} state={viewState} onEvent={onEvent} />
      </Animated.View>
      {!!error && <Text style={[styles.error, rtl, { paddingHorizontal: 16 }]}>{error}</Text>}
      <View style={styles.bar}>
        <Button label="قبلی" variant="outline" disabled={index === 0} onPress={() => go(index - 1)} style={{ flex: 1 }} />
        {last ? (
          <Button label="پایان آزمون" loading={busy} onPress={finish} style={{ flex: 1.3 }} />
        ) : (
          <Button label="بعدی" variant="dark" onPress={() => go(index + 1)} style={{ flex: 1 }} />
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
  top: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingTop: 10, paddingBottom: 6 },
  clock: { flexDirection: 'row-reverse', alignItems: 'center', gap: 4, backgroundColor: colors.surface, borderRadius: 14, paddingHorizontal: 10, paddingVertical: 6 },
  timer: { fontSize: 22, fontWeight: '800', color: colors.ink },
  bar: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: colors.line },
});
