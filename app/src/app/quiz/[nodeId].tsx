import * as Sharing from 'expo-sharing';
import { captureRef } from 'react-native-view-shot';
import { Icon } from '../../components/Icon';
import { QuestionShareCard } from '../../components/QuestionShareCard';
import { play } from '../../lib/sound';
import AsyncStorage from '@react-native-async-storage/async-storage';
import * as Haptics from 'expo-haptics';
import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Platform, Pressable, ScrollView, StyleSheet, View, type HostInstance } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints } from '../../api/endpoints';
import { useFeedback } from '../../components/Feedback';
import { LemonProgress, type PartState } from '../../components/LemonProgress';
import { QuestionPicker } from '../../components/QuestionPicker';
import { QuizView, type QuizEvent } from '../../components/QuizView';
import { ReportSheet } from '../../components/ReportSheet';
import { Text } from '../../components/Text';
import { Button, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { usePageTurn } from '../../lib/pageTurn';
import { seeded } from '../../lib/shuffle';
import { resultForView, type QuizViewState } from '../../lib/quizHtml';
import { useApi } from '../../lib/useApi';
import { colors, rtl, toPersianDigits } from '../../theme';

type Answer = { picked: number; result: QuizViewState['result'] };
type Order = 'book' | 'shuffle' | 'wrong';
const ORDERS: [Order, string][] = [
  ['book', 'ترتیب کتاب'],
  ['shuffle', 'تصادفی'],
  ['wrong', 'غلط‌ها و نزده‌ها'],
];

export default function Quiz() {
  const { nodeId, book: bookParam, q: openQuestion } = useLocalSearchParams<{ nodeId: string; book?: string; q?: string }>();
  // /quiz/mistakes: the questions of the mistakes notebook (optionally one book), practised like a section's.
  const notebook = nodeId === 'mistakes';
  // /quiz/quick: the three questions of «فقط ۵ دقیقه».
  const quick = nodeId === 'quick';
  const { data, error, loading, retry } = useApi(
    () =>
      quick
        ? endpoints.quick().then((r) => ({ questions: r.questions, locked_count: 0 }))
        : notebook
          ? endpoints.mistakeQuestions(bookParam ?? '')
          : endpoints.questions(Number(nodeId)),
    [nodeId, bookParam],
  );
  const { user } = useAuth();
  const { confirm, toast: flash } = useFeedback();

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
  const [pickerOpen, setPickerOpen] = useState(false);
  const [sharing, setSharing] = useState(false);
  const shareRef = useRef<HostInstance>(null);
  const { style: pageStyle, turn } = usePageTurn();

  // Order of the questions: as in the book, shuffled (choices too), or only the ones not yet right.
  const orderKey = `limo.quiz.${nodeId}.order`;
  const [order, setOrder] = useState<{ order: Order; seed: number; ids?: number[] } | null>(null);
  useEffect(() => {
    AsyncStorage.getItem(orderKey)
      .then((v) => setOrder(v ? JSON.parse(v) : { order: 'book', seed: 0 }))
      .catch(() => setOrder({ order: 'book', seed: 0 }));
  }, [orderKey]);

  const questions = useMemo(() => {
    const base = data?.questions ?? [];
    if (!order || order.order === 'book') return base;
    if (order.order === 'wrong') {
      const keep = new Set(order.ids ?? []);
      return base.filter((q) => keep.has(q.id));
    }
    return seeded(base, order.seed).map((q) => ({ ...q, choices: seeded(q.choices, order.seed + q.id) }));
  }, [data, order]);

  // Signed-in learners continue at the first question they have not answered yet.
  useEffect(() => {
    if (!user || !data || !order || notebook || quick) return;
    endpoints
      .practiceState(Number(nodeId))
      .then((s) => {
        setServerAnswered(s.answered);
        setReported(s.reported);
        if (!resumed.current && !openQuestion) {
          resumed.current = true;
          const first = questions.findIndex((q) => !(String(q.id) in s.answered));
          if (first > 0) setIndex(first);
        }
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [user, data, nodeId, order === null]);

  // From search: open at that question.
  useEffect(() => {
    if (!openQuestion || !questions.length || resumed.current) return;
    resumed.current = true;
    const at = questions.findIndex((x) => String(x.id) === openQuestion);
    if (at > 0) setIndex(at);
  }, [openQuestion, questions]);

  const go = useCallback(
    (target: number, alreadyOut = false) => {
      if (target === index || target < 0 || target >= questions.length) return;
      setAnswerError(null);
      turn(target > index, () => setIndex(target), alreadyOut);
    },
    [index, questions.length, turn],
  );

  if (loading || !order) return <Screen><Header title="تست" /><Loading /></Screen>;
  if (error) return <Screen><Header title="تست" /><ErrorState message={error.message} onRetry={retry} /></Screen>;
  if (questions.length === 0) {
    return (
      <Screen>
        <Header title="تست" />
        <ErrorState
          icon={data!.locked_count ? 'lock' : 'clipboard-list'}
          message={quick ? 'فعلاً تستی برای این چند دقیقه نیست؛ یک بخش را شروع کن.' : notebook ? 'دفترچه‌ی اشتباهات خالی است؛ آفرین!' : data!.locked_count ? 'تست‌های این بخش در نسخه‌ی کامل کتاب است.' : 'برای این بخش هنوز تستی نیست.'}
        />
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
    canPrev: index > 0,
  };

  const choose = async (choiceId: number) => {
    if (current?.result || sending) return;
    setSending(q.id);
    setPending({ id: q.id, picked: choiceId });
    setAnswerError(null);
    try {
      const r = await endpoints.answer(q.id, choiceId);
      setAnswers((a) => ({ ...a, [q.id]: { picked: choiceId, result: { ...resultForView(r), notes: !!(r.node_id ?? q.node_id) } } }));
      if (r.fixed) {
        // «اشتباهی که برطرف شد»
        play('pop');
        flash(r.fixed.days >= 1 ? `اشتباهی که برطرف شد! ${toPersianDigits(r.fixed.days)} روز پیش این را غلط زده بودی.` : 'اشتباهی که برطرف شد! این بار درست زدی.');
      }
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

  const shareQuestion = async () => {
    try {
      if (!(await Sharing.isAvailableAsync())) return;
      setSharing(true);
      await new Promise((r) => setTimeout(r, 900)); // let the card (and its formulas) draw
      const uri = await captureRef(shareRef, { format: 'png', quality: 1 });
      await Sharing.shareAsync(uri, { mimeType: 'image/png', dialogTitle: 'تست لیمو پلاس' });
    } catch {
      // cancelled
    } finally {
      setSharing(false);
    }
  };

  const onEvent = (e: QuizEvent) => {
    if (e.type === 'choose') choose(e.id);
    else if (e.type === 'notes') {
      const node = q.node_id;
      if (node) router.push(`/section/${node}`);
    } else if (e.type === 'report') {
      if (requireLogin(user, 'برای گزارش اشکال وارد شوید.')) setReportOpen(true);
    } else if (e.type === 'swipe') {
      if (e.dir === 'next') {
        if (index + 1 < questions.length) go(index + 1, e.flung);
        else setShowSummary(true);
      } else go(index - 1, e.flung);
    }
  };

  const changeOrder = (next: Order) => {
    if (next === order.order && next !== 'shuffle') return;
    let value: { order: Order; seed: number; ids?: number[] } = { order: next, seed: order.seed };
    if (next === 'shuffle') value = { order: next, seed: Math.floor(Math.random() * 1e9) };
    if (next === 'wrong') {
      const ids = (data?.questions ?? []).filter((q) => status(q.id) !== 'right').map((q) => q.id);
      if (!ids.length) {
        flash('همه‌ی تست‌های این بخش را درست زده‌ای!');
        return;
      }
      value = { order: next, seed: order.seed, ids };
    }
    setOrder(value);
    AsyncStorage.setItem(orderKey, JSON.stringify(value)).catch(() => undefined);
    setAnswerError(null);
    setIndex(0);
  };

  const restart = async () => {
    const ok = await confirm({
      title: 'تست‌ها از اول شروع شود؟',
      message: 'پاسخ‌های قبلی از نوار پیشرفت این بخش برداشته می‌شود؛ در آمار کلی شما می‌ماند.',
      confirmLabel: 'شروع دوباره',
      icon: 'rotate-ccw',
    });
    if (!ok) return;
    if (user && !notebook && !quick) await endpoints.practiceReset(Number(nodeId)).catch(() => undefined);
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
            {toPersianDigits(counts.right)} درست، {toPersianDigits(counts.wrong)} غلط، {toPersianDigits(counts.none)} بی‌جواب
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
          {quick ? (
            <Button label="کافی است برای امروز" variant="dark" onPress={() => router.replace('/home')} style={{ alignSelf: 'stretch' }} />
          ) : notebook ? (
            <Button label="دفترچه‌ی اشتباهات" variant="dark" onPress={() => router.replace('/mistakes')} style={{ alignSelf: 'stretch' }} />
          ) : (
            <Button label="آزمون زمان‌دار با نمره‌ی منفی" variant="dark" onPress={() => router.replace(`/exam/${nodeId}`)} style={{ alignSelf: 'stretch' }} />
          )}
          <Button label="شروع دوباره‌ی تست‌ها" variant="outline" onPress={restart} style={{ alignSelf: 'stretch' }} />
          <Button label="بازگشت" variant="outline" onPress={() => router.back()} style={{ alignSelf: 'stretch' }} />
        </ScrollView>
      </Screen>
    );
  }

  const parts: PartState[] = questions.map((x) => ({ right: 'done', wrong: 'wrong', none: 'empty' })[status(x.id)] as PartState);

  return (
    <Screen>
      <Header title={`سؤال ${toPersianDigits(index + 1)} از ${toPersianDigits(questions.length)}`} />
      <View style={styles.progress}>
        <LemonProgress parts={parts} current={index} size={54} onPress={() => setPickerOpen(true)} accessibilityLabel="پیشرفت تست‌ها؛ برای رفتن به سؤال دیگر بزنید" />
        <View style={{ flex: 1, gap: 2 }}>
          <Text style={[styles.counts, rtl]}>
            {toPersianDigits(counts.right)} درست، {toPersianDigits(counts.wrong)} غلط، {toPersianDigits(counts.none)} مانده
          </Text>
          <Text style={[styles.hint, rtl, { paddingHorizontal: 0, paddingBottom: 0 }]}>بکش تا ورق بخورد؛ لیمو را بزن تا به هر سؤال بروی</Text>
        </View>
      </View>
      <View style={styles.orders}>
        {ORDERS.map(([key, label]) => (
          <Pressable key={key} onPress={() => changeOrder(key)} style={[styles.order, order.order === key && styles.orderOn]} accessibilityRole="button" accessibilityState={{ selected: order.order === key }}>
            <Text style={[styles.orderText, order.order === key && { color: colors.lemon }]}>{label}</Text>
          </Pressable>
        ))}
      </View>
      <QuestionPicker
        visible={pickerOpen}
        onClose={() => setPickerOpen(false)}
        parts={parts}
        current={index}
        onPick={(i) => go(i)}
        legend="زرد: درست، صورتی: غلط، سفید: بی‌جواب"
      />
      {q.shareable && Platform.OS !== 'web' && (
        <Pressable onPress={shareQuestion} style={styles.share} accessibilityRole="button">
          <Icon name="share-2" size={15} color={colors.ink} />
          <Text style={styles.shareText}>این تست را برای دوستت بفرست</Text>
        </Pressable>
      )}
      <Animated.View style={[styles.page, pageStyle]}>
        <QuizView key={q.id} question={q} state={viewState} onEvent={onEvent} />
      </Animated.View>
      {sharing && (
        <View style={styles.offscreen} pointerEvents="none">
          <QuestionShareCard ref={shareRef} question={q} />
        </View>
      )}
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
        <Text style={[styles.hint, rtl]}>{toPersianDigits(counts.none)} تست بی‌جواب مانده؛ با زدن لیمو می‌توانی برگردی.</Text>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  progress: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingBottom: 6 },
  counts: { fontSize: 14, fontWeight: '800', color: colors.ink },
  orders: { flexDirection: 'row-reverse', gap: 6, paddingHorizontal: 16, paddingBottom: 6 },
  order: { borderRadius: 999, paddingHorizontal: 12, paddingVertical: 5, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line },
  orderOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  orderText: { fontSize: 12.5, fontWeight: '700', color: colors.ink },
  page: { flex: 1, backfaceVisibility: 'hidden' },
  share: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, alignSelf: 'flex-end', marginHorizontal: 16, marginBottom: 4, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.lemonSoft },
  shareText: { fontSize: 12.5, fontWeight: '800', color: colors.ink },
  offscreen: { position: 'absolute', left: -2000, top: 0 },
  bar: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: colors.line },
  hint: { fontSize: 12, color: colors.muted, paddingHorizontal: 16, paddingBottom: 8 },
  result: { flexGrow: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  resultPercent: { fontSize: 64, fontWeight: '900', color: colors.ink },
  resultLine: { fontSize: 16, color: colors.muted, marginBottom: 12 },
});
