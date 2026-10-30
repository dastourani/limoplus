import * as Haptics from 'expo-haptics';
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Easing, Platform, Pressable, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints } from '../../api/endpoints';
import { useFeedback } from '../../components/Feedback';
import { QuizView, type QuizEvent } from '../../components/QuizView';
import { ReportSheet } from '../../components/ReportSheet';
import { Text } from '../../components/Text';
import { Button, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { resultForView, type QuizViewState } from '../../lib/quizHtml';
import { useApi } from '../../lib/useApi';
import { colors, rtl, toPersianDigits } from '../../theme';

type Answer = { picked: number; result: QuizViewState['result'] };

/**
 * Practice mode. Questions turn like pages (swipe or buttons); answering is never required to move on.
 * Graded on the server one question at a time; the progress strip shows right / wrong / not answered.
 */
export default function Quiz() {
  const { nodeId } = useLocalSearchParams<{ nodeId: string }>();
  const { data, error, loading, retry } = useApi(() => endpoints.questions(Number(nodeId)), [nodeId]);
  const { user } = useAuth();
  const { confirm } = useFeedback();
  const { width } = useWindowDimensions();

  const [index, setIndex] = useState(0);
  const [answers, setAnswers] = useState<Record<number, Answer>>({});
  const [serverAnswered, setServerAnswered] = useState<Record<string, boolean>>({});
  const [reported, setReported] = useState<number[]>([]);
  const [sending, setSending] = useState<number | null>(null);
  const [pending, setPending] = useState<{ id: number; picked: number } | null>(null);
  const [answerError, setAnswerError] = useState<string | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const resumed = useRef(false);
  const page = useRef(new Animated.Value(0)).current;

  const questions = useMemo(() => data?.questions ?? [], [data]);

  // Signed-in learners continue at the first question they have not answered yet.
  useEffect(() => {
    if (!user || !data) return;
    endpoints
      .practiceState(Number(nodeId))
      .then((s) => {
        setServerAnswered(s.answered);
        setReported(s.reported);
        if (!resumed.current) {
          resumed.current = true;
          const first = data.questions.findIndex((q) => !(String(q.id) in s.answered));
          if (first > 0) setIndex(first);
        }
      })
      .catch(() => undefined);
  }, [user, data, nodeId]);

  // Page turn: the current question slides away with a slight paper tilt, the next one comes in from the other side.
  const go = useCallback(
    (target: number) => {
      if (target === index || target < 0 || target >= questions.length) return;
      const forward = target > index;
      setAnswerError(null);
      Animated.timing(page, { toValue: forward ? 1 : -1, duration: 160, easing: Easing.in(Easing.quad), useNativeDriver: true }).start(() => {
        setIndex(target);
        page.setValue(forward ? -1 : 1);
        Animated.timing(page, { toValue: 0, duration: 220, easing: Easing.out(Easing.cubic), useNativeDriver: true }).start();
      });
    },
    [index, questions.length, page],
  );

  if (loading) return <Screen><Header title="تست" /><Loading /></Screen>;
  if (error) return <Screen><Header title="تست" /><ErrorState message={error.message} onRetry={retry} /></Screen>;
  if (questions.length === 0) {
    return (
      <Screen>
        <Header title="تست" />
        <ErrorState icon={data!.locked_count ? 'lock' : 'clipboard-list'} message={data!.locked_count ? 'تست‌های این بخش در نسخه‌ی کامل کتاب است.' : 'برای این بخش هنوز تستی نیست.'} />
      </Screen>
    );
  }

  const status = (id: number): 'right' | 'wrong' | 'none' => {
    const a = answers[id];
    if (a?.result) return a.result.is_correct ? 'right' : 'wrong';
    if (String(id) in serverAnswered) return serverAnswered[id] ? 'right' : 'wrong';
    return 'none';
  };
  const counts = questions.reduce(
    (c, q) => {
      c[status(q.id)] += 1;
      return c;
    },
    { right: 0, wrong: 0, none: 0 },
  );

  const q = questions[Math.min(index, questions.length - 1)];
  const current = answers[q.id];
  const viewState: QuizViewState = {
    picked: current?.picked ?? (pending?.id === q.id ? pending.picked : null),
    sending: sending === q.id,
    error: answerError,
    reported: reported.includes(q.id),
    result: current?.result ?? null,
  };

  const choose = async (choiceId: number) => {
    if (current?.result || sending) return;
    setSending(q.id);
    setPending({ id: q.id, picked: choiceId });
    setAnswerError(null);
    try {
      const r = await endpoints.answer(q.id, choiceId);
      setAnswers((a) => ({ ...a, [q.id]: { picked: choiceId, result: resultForView(r) } }));
      if (Platform.OS !== 'web') {
        Haptics.notificationAsync(r.is_correct ? Haptics.NotificationFeedbackType.Success : Haptics.NotificationFeedbackType.Warning).catch(() => undefined);
      }
    } catch (e) {
      setAnswerError(e instanceof ApiError ? e.message : 'خطا در ارسال پاسخ.');
    } finally {
      setSending(null);
      setPending(null);
    }
  };

  const onEvent = (e: QuizEvent) => {
    if (e.type === 'choose') choose(e.id);
    else if (e.type === 'report') {
      if (requireLogin(user, 'برای گزارش اشکال وارد شوید.')) setReportOpen(true);
    } else if (e.type === 'swipe') {
      if (e.dir === 'next') {
        if (index + 1 < questions.length) go(index + 1);
        else setShowSummary(true);
      } else go(index - 1);
    }
  };

  const restart = async () => {
    const ok = await confirm({
      title: 'تست‌ها از اول شروع شود؟',
      message: 'پاسخ‌های قبلی از نوار پیشرفت این بخش برداشته می‌شود؛ در آمار کلی شما می‌ماند.',
      confirmLabel: 'شروع دوباره',
      icon: 'rotate-ccw',
    });
    if (!ok) return;
    if (user) await endpoints.practiceReset(Number(nodeId)).catch(() => undefined);
    setAnswers({});
    setServerAnswered({});
    setShowSummary(false);
    setIndex(0);
  };

  if (showSummary) {
    const done = counts.right + counts.wrong;
    const percent = done ? Math.round((counts.right / questions.length) * 100) : 0;
    const firstOpen = questions.findIndex((x) => status(x.id) === 'none');
    return (
      <Screen>
        <Header title="نتیجه‌ی تمرین" />
        <ScrollView contentContainerStyle={styles.result}>
          <Text style={styles.resultPercent}>{toPersianDigits(percent)}٪</Text>
          <Text style={styles.resultLine}>
            {toPersianDigits(counts.right)} درست · {toPersianDigits(counts.wrong)} غلط · {toPersianDigits(counts.none)} بی‌جواب
          </Text>
          {firstOpen >= 0 && (
            <Button
              label={`رفتن به ${toPersianDigits(counts.none)} تست بی‌جواب`}
              onPress={() => {
                setShowSummary(false);
                setIndex(firstOpen);
              }}
              style={{ alignSelf: 'stretch' }}
            />
          )}
          <Button label="آزمون زمان‌دار با نمره‌ی منفی" variant="dark" onPress={() => router.replace(`/exam/${nodeId}`)} style={{ alignSelf: 'stretch' }} />
          <Button label="شروع دوباره‌ی تست‌ها" variant="outline" onPress={restart} style={{ alignSelf: 'stretch' }} />
          <Button label="بازگشت" variant="outline" onPress={() => router.back()} style={{ alignSelf: 'stretch' }} />
        </ScrollView>
      </Screen>
    );
  }

  const translateX = page.interpolate({ inputRange: [-1, 0, 1], outputRange: [-width * 0.35, 0, width * 0.35] });
  const rotateY = page.interpolate({ inputRange: [-1, 0, 1], outputRange: ['-18deg', '0deg', '18deg'] });
  const opacity = page.interpolate({ inputRange: [-1, 0, 1], outputRange: [0, 1, 0] });

  return (
    <Screen>
      <Header title={`سؤال ${toPersianDigits(index + 1)} از ${toPersianDigits(questions.length)}`} />
      <View style={styles.progress}>
        {questions.map((item, i) => {
          const st = status(item.id);
          return (
            <Pressable key={item.id} onPress={() => go(i)} style={styles.segHit} accessibilityLabel={`سؤال ${i + 1}`}>
              <View
                style={[
                  styles.seg,
                  { backgroundColor: st === 'right' ? colors.green : st === 'wrong' ? colors.red : colors.line },
                  i === index && styles.segNow,
                ]}
              />
            </Pressable>
          );
        })}
      </View>
      <Animated.View style={[styles.page, { opacity, transform: [{ perspective: 900 }, { translateX }, { rotateY }] }]}>
        <QuizView key={q.id} question={q} state={viewState} onEvent={onEvent} />
      </Animated.View>
      <ReportSheet
        visible={reportOpen}
        onClose={() => setReportOpen(false)}
        onSend={(reason, note) => endpoints.reportQuestion(q.id, reason, note)}
        onDone={() => setReported((r) => [...r, q.id])}
      />
      <View style={styles.bar}>
        <Button label="قبلی" variant="outline" disabled={index === 0} onPress={() => go(index - 1)} style={{ flex: 1 }} />
        {index + 1 < questions.length ? (
          <Button label={current?.result ? 'سؤال بعد' : 'بعداً جواب می‌دهم'} variant="dark" onPress={() => go(index + 1)} style={{ flex: 1.6 }} />
        ) : (
          <Button label="دیدن نتیجه" variant="dark" onPress={() => setShowSummary(true)} style={{ flex: 1.6 }} />
        )}
      </View>
      {!!counts.none && index + 1 === questions.length && (
        <Text style={[styles.hint, rtl]}>{toPersianDigits(counts.none)} تست بی‌جواب مانده؛ از نوار بالا می‌توانی برگردی.</Text>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  progress: { flexDirection: 'row-reverse', paddingHorizontal: 12 },
  segHit: { flex: 1, paddingVertical: 8, paddingHorizontal: 1.5 },
  seg: { height: 6, borderRadius: 3 },
  segNow: { height: 10, marginTop: -2, borderWidth: 2, borderColor: colors.ink },
  page: { flex: 1, backfaceVisibility: 'hidden' },
  bar: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: colors.line },
  hint: { fontSize: 12, color: colors.muted, paddingHorizontal: 16, paddingBottom: 8 },
  result: { flexGrow: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  resultPercent: { fontSize: 64, fontWeight: '900', color: colors.ink },
  resultLine: { fontSize: 16, color: colors.muted, marginBottom: 12 },
});
