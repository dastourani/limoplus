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
import { endpoints, type Flashcard, type Question, type ReviewSessionData } from '../../api/endpoints';
import { useFeedback } from '../../components/Feedback';
import { LemonProgress, type PartState } from '../../components/LemonProgress';
import { PageHeader } from '../../components/PageHeader';
import { setMacros } from '../../lib/macros';
import { QuestionPicker } from '../../components/QuestionPicker';
import { QuizView, type QuizEvent } from '../../components/QuizView';
import { ReportSheet } from '../../components/ReportSheet';
import { Text } from '../../components/Text';
import { Button, ErrorState, Header, Loading, Screen, Sheet } from '../../components/ui';
import { RichText } from '../../components/RichText';
import { Pill } from '../../components/Pill';
import { requireLogin, useAuth } from '../../lib/auth';
import { useGuestNudge } from '../../lib/guestNudge';
import { placeLabel } from '../../lib/place';
import { useStudyTimer } from '../../lib/studyTime';
import { usePageTurn } from '../../lib/pageTurn';
import { seeded } from '../../lib/shuffle';
import { resultForView, type QuizViewState } from '../../lib/quizHtml';
import { useApi } from '../../lib/useApi';
import { colors, rtl, toPersianDigits } from '../../theme';

/** cards: the answer's linked flashcards (their book, and ids), opened from «فلش‌کارت مرتبط». */
type Answer = { picked: number; result: QuizViewState['result']; cards?: { book: number; ids: number[] } };
type Order = 'book' | 'shuffle' | 'wrong';
const ORDERS: [Order, string][] = [
  ['book', 'ترتیب کتاب'],
  ['shuffle', 'تصادفی'],
  ['wrong', 'غلط‌ها و نزده‌ها'],
];

export default function Quiz() {
  // ?ids=…: only these tests (from a flashcard's «تست‌های این نکته»).
  const { nodeId, book: bookParam, q: openQuestion, session, ids, source, names } = useLocalSearchParams<{
    nodeId: string;
    book?: string;
    q?: string;
    session?: string;
    ids?: string;
    /** /quiz/past?book=…&source=…: the tests of one past exam, in its own order. */
    source?: string;
    /** /quiz/repeats?book=…&names=a|b: «تکراری‌ها و مشابه‌ها» of those konkurs, each group together. */
    names?: string;
  }>();
  // /quiz/review?session=N: a chapter or book review, five questions at a time («۵ تست دیگر»).
  const review = nodeId === 'review';
  // /quiz/mistakes: the questions of the mistakes notebook (optionally one book), practised like a section's.
  const notebook = nodeId === 'mistakes';
  // /quiz/quick: the three questions of «فقط ۵ دقیقه».
  const quick = nodeId === 'quick';
  const repeats = nodeId === 'repeats';
  const past = nodeId === 'past' || repeats;
  const { data, error, loading, retry } = useApi(
    () =>
      review
        ? endpoints.reviewSession(Number(session)).then((r) => ({ questions: r.questions, locked_count: 0, session: r }))
        : quick
        ? endpoints.quick().then((r) => ({ questions: r.questions, locked_count: 0 }))
        : notebook
          ? endpoints.mistakeQuestions(bookParam ?? '')
          : repeats
            ? endpoints.pastRepeats(bookParam ?? '', (names ?? '').split('|').filter(Boolean))
            : past
            ? endpoints.pastQuestions(bookParam ?? '', Number(source))
            : endpoints.questions(Number(nodeId), ids),
    [nodeId, bookParam, session, ids, source, names],
  );
  // A review grows by five when the learner asks for more; its result comes from the server when it ends.
  const [reviewQs, setReviewQs] = useState<Question[] | null>(null);
  const [reviewInfo, setReviewInfo] = useState<ReviewSessionData | null>(null);
  const [reviewBusy, setReviewBusy] = useState(false);
  const { user } = useAuth();
  const { confirm, toast: flash } = useFeedback();

  const [index, setIndex] = useState(0);
  // «فلش‌کارت مرتبط» opens over the test, so going back never loses the place.
  const [cardSheet, setCardSheet] = useState<{ book: number; ids: number[]; cards: Flashcard[] | null } | null>(null);
  const openCards = (book: number, ids: number[]) => {
    setCardSheet({ book, ids, cards: null });
    endpoints
      .flashcards(book, false, ids.join(','))
      .then((r) => {
        setMacros(r.macros);
        setCardSheet((s) => (s ? { ...s, cards: ids.map((id) => r.flashcards.find((f) => f.id === id)).filter(Boolean) as Flashcard[] } : s));
      })
      .catch(() => setCardSheet((s) => (s ? { ...s, cards: [] } : s)));
  };
  const [answers, setAnswers] = useState<Record<number, Answer>>({});
  const [serverAnswered, setServerAnswered] = useState<Record<string, boolean>>({});
  const [reported, setReported] = useState<number[]>([]);
  const [sending, setSending] = useState<number | null>(null);
  const [pending, setPending] = useState<{ id: number; picked: number } | null>(null);
  const [answerError, setAnswerError] = useState<string | null>(null);
  const [reportOpen, setReportOpen] = useState(false);
  const [showSummary, setShowSummary] = useState(false);
  const resumed = useRef(false);
  const hydratedSession = useRef<number | null>(null);
  const [resumedNote, setResumedNote] = useState<string | null>(null);
  const [pickerOpen, setPickerOpen] = useState(false);
  const [sharing, setSharing] = useState(false);
  const shareRef = useRef<HostInstance>(null);
  const { style: pageStyle, turn } = usePageTurn();

  // Order of the questions: as in the book, shuffled (choices too), or only the ones not yet right.
  const orderKey = `limo.quiz.${nodeId}${ids ? `.${ids}` : ''}${source ? `.s${source}` : ''}${names ? `.n${names}` : ''}.order`;
  const [order, setOrder] = useState<{ order: Order; seed: number; ids?: number[] } | null>(null);
  useEffect(() => {
    AsyncStorage.getItem(orderKey)
      .then((v) => setOrder(v ? JSON.parse(v) : { order: 'book', seed: 0 }))
      .catch(() => setOrder({ order: 'book', seed: 0 }));
  }, [orderKey]);

  // «تست تکمیلی»: a section's extra tests come after its own, once the learner asks for «تمرین بیشتر».
  const [withExtra, setWithExtra] = useState(false);
  const sectionQuiz = !review && !notebook && !quick && !past;
  // «دستورهای فرمول» before any formula is drawn.
  setMacros((data as { macros?: Record<string, string> } | undefined)?.macros);
  const extraCount = sectionQuiz ? (data?.questions ?? []).filter((q) => q.extra).length : 0;
  const questions = useMemo(() => {
    const all = reviewQs ?? data?.questions ?? [];
    const base = sectionQuiz && !withExtra ? all.filter((q) => !q.extra) : all;
    let list = base;
    if (!review && order && order.order === 'wrong') {
      const keep = new Set(order.ids ?? []);
      list = base.filter((q) => keep.has(q.id));
    } else if (!review && order && order.order === 'shuffle') {
      // Choices like «گزینه‌های ۱ و ۳» keep their place (fixed_order).
      list = seeded(base, order.seed).map((q) => (q.fixed_order ? q : { ...q, choices: seeded(q.choices, order.seed + q.id) }));
    }
    return sectionQuiz && withExtra ? [...list.filter((q) => !q.extra), ...list.filter((q) => q.extra)] : list;
  }, [data, order, reviewQs, review, sectionQuiz, withExtra]);

  // Review sitting: hydrate answers already recorded in this session and resume at the first unanswered question.
  useEffect(() => {
    if (!review) return;
    const s = (data as { session?: ReviewSessionData } | undefined)?.session;
    if (!s || hydratedSession.current === s.id) return;
    hydratedSession.current = s.id;
    const sessionAnswers = s.answers ?? {};
    const hydrated: Record<number, Answer> = {};
    for (const [qidStr, item] of Object.entries(sessionAnswers)) {
      const qid = Number(qidStr);
      const cards =
        item.result.book_id && item.result.flashcards.length
          ? { book: item.result.book_id, ids: item.result.flashcards.map((f) => f.id) }
          : undefined;
      hydrated[qid] = {
        picked: item.picked,
        result: { ...resultForView(item.result), notes: !!(item.result.node_id ?? qid) },
        cards,
      };
    }
    if (Object.keys(hydrated).length) setAnswers((prev) => ({ ...hydrated, ...prev }));
    const first = s.questions.findIndex((x) => !(String(x.id) in sessionAnswers));
    const answeredCount = Object.keys(sessionAnswers).length;
    if (first === -1 && s.questions.length > 0) {
      setShowSummary(true);
    } else if (first > 0) {
      setIndex(first);
      if (answeredCount > 0) {
        setResumedNote(`${toPersianDigits(answeredCount)} از ${toPersianDigits(s.questions.length)} پاسخ داده‌ای؛ ادامه از سؤال ${toPersianDigits(first + 1)}`);
      }
    }
  }, [review, data]);

  // Signed-in learners continue at the first question they have not answered yet.
  useEffect(() => {
    if (!user || !data || !order || notebook || quick || review || past) return;
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

  // A review is counted (and its next date set) when its summary opens; asking again is harmless.
  useEffect(() => {
    if (!review || !showSummary || !session) return;
    endpoints.finishReview(Number(session)).then(setReviewInfo).catch(() => undefined);
  }, [review, showSummary, session]);

  const moreReview = async () => {
    if (!session || reviewBusy) return;
    setReviewBusy(true);
    try {
      const s = await endpoints.reviewMore(Number(session));
      const before = questions.length;
      setReviewQs(s.questions);
      setReviewInfo(s);
      setShowSummary(false);
      if (s.questions.length > before) setIndex(before);
    } catch {
      flash('گرفتن تست‌های بیشتر ممکن نشد.');
    } finally {
      setReviewBusy(false);
    }
  };

  // From search: open at that question.
  useEffect(() => {
    if (openQuestion && !withExtra && data?.questions.some((x) => String(x.id) === openQuestion && x.extra)) {
      setWithExtra(true);
      return;
    }
    if (!openQuestion || !questions.length || resumed.current) return;
    resumed.current = true;
    const at = questions.findIndex((x) => String(x.id) === openQuestion);
    if (at > 0) setIndex(at);
  }, [openQuestion, questions, withExtra, data]);

  const go = useCallback(
    (target: number, alreadyOut = false) => {
      if (target === index || target < 0 || target >= questions.length) return;
      setAnswerError(null);
      turn(target > index, () => setIndex(target), alreadyOut);
    },
    [index, questions.length, turn],
  );

  // A guest who answered every question here hears once that nothing is kept without an account.
  const nudgeGuest = useGuestNudge();
  const answeredHere = Object.values(answers).filter((a) => a.result).length;
  useEffect(() => {
    if (!user && questions.length > 0 && (showSummary || answeredHere >= questions.length)) nudgeGuest();
  }, [user, showSummary, answeredHere, questions.length, nudgeGuest]);

  // «زمان مطالعه»: counted on the section of the question on screen (a review counts as review).
  useStudyTimer(questions[Math.min(index, questions.length - 1)]?.node_id, review ? 'review' : 'quiz', !showSummary);

  if (loading || !order) return <Screen><Header title="تست" /><Loading /></Screen>;
  if (error) return <Screen><Header title="تست" /><ErrorState message={error.message} onRetry={retry} /></Screen>;
  if (questions.length === 0) {
    return (
      <Screen>
        <Header title="تست" />
        <ErrorState
          icon={data!.locked_count ? 'lock' : 'clipboard-list'}
          message={quick ? 'فعلاً تستی برای این چند دقیقه نیست؛ یک بخش را شروع کن.' : notebook ? '«اشتباهات من» خالی است؛ آفرین!' : data!.locked_count ? 'تست‌های این بخش در نسخه‌ی کامل کتاب است.' : 'برای این بخش هنوز تستی نیست.'}
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
      const r = await endpoints.answer(q.id, choiceId, review ? Number(session) : undefined);
      setResumedNote(null);
      const cards = r.book_id && r.flashcards.length ? { book: r.book_id, ids: r.flashcards.map((f) => f.id) } : undefined;
      setAnswers((a) => ({ ...a, [q.id]: { picked: choiceId, result: { ...resultForView(r), notes: !!(r.node_id ?? q.node_id) }, cards } }));
      if (r.fixed?.step === 'settled') {
        // «اشتباهی که برطرف شد»: right again on a later day.
        play('pop');
        flash(r.fixed.days >= 1 ? `تثبیت شد! ${toPersianDigits(r.fixed.days)} روز پیش این را غلط زده بودی؛ از «اشتباهات من» بیرون رفت.` : 'تثبیت شد! از «اشتباهات من» بیرون رفت.');
      } else if (r.fixed?.step === 'settling') {
        flash(`درست زدی! ${toPersianDigits(r.fixed.due_in ?? 3)} روز دیگر یک بار دیگر می‌پرسیم تا مطمئن شویم یادت مانده.`);
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
      await Sharing.shareAsync(uri, { mimeType: 'image/png', dialogTitle: 'تست لیموخوان' });
    } catch {
      // cancelled
    } finally {
      setSharing(false);
    }
  };

  const onEvent = (e: QuizEvent) => {
    if (e.type === 'choose') choose(e.id);
    else if (e.type === 'card') {
      // The tapped card first, then the other cards of this answer, in a sheet over the test (back stays here).
      const c = answers[q.id]?.cards;
      if (c) openCards(c.book, [e.id, ...c.ids.filter((x) => x !== e.id)]);
    } else if (e.type === 'similar') {
      router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: String(e.node), ids: String(e.id) } });
    } else if (e.type === 'ref') {
      if (e.node) router.push({ pathname: '/section/[id]', params: { id: e.node, find: '#' + e.name } });
    } else if (e.type === 'notes') {
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
    if (user && !notebook && !quick && !review && !past) await endpoints.practiceReset(Number(nodeId)).catch(() => undefined);
    setAnswers({});
    setServerAnswered({});
    setShowSummary(false);
    setIndex(0);
  };

  if (showSummary && review) {
    const info = reviewInfo ?? (data as { session?: ReviewSessionData } | undefined)?.session ?? null;
    const left = info ? Math.max(0, info.minimum - info.answered) : 0;
    return (
      <Screen>
        <Header title={info?.title ?? 'مرور'} />
        <ScrollView contentContainerStyle={styles.result}>
          <Text style={styles.resultPercent}>
            {toPersianDigits(counts.right)} از {toPersianDigits(counts.right + counts.wrong)}
          </Text>
          <Text style={styles.resultLine}>
            {info?.finished
              ? info.next_in_days != null
                ? `مرور انجام شد. مرور بعدی این ${info.kind === 'book' ? 'کتاب' : 'فصل'}: ${toPersianDigits(info.next_in_days)} روز دیگر.`
                : 'مرور انجام شد.'
              : left > 0
                ? `برای اینکه این مرور حساب شود، ${toPersianDigits(left)} تست دیگر بزن.`
                : 'در حال ثبت…'}
          </Text>
          {counts.wrong > 0 && <Text style={[styles.resultLine, { fontSize: 13 }]}>تست‌های غلط به «اشتباهات من» رفتند.</Text>}
          {(info?.more ?? true) && (
            <Button
              label={reviewBusy ? 'صبر کن…' : `۵ تست دیگر از این ${info?.kind === 'book' ? 'کتاب' : 'فصل'}`}
              onPress={moreReview}
              disabled={reviewBusy}
              style={{ alignSelf: 'stretch' }}
            />
          )}
          {info && !info.more && <Text style={[styles.resultLine, { fontSize: 13 }]}>همه‌ی تست‌های این {info.kind === 'book' ? 'کتاب' : 'فصل'} را در این مرور زدی.</Text>}
          <Button label="کافی است برای امروز" variant={info?.more ? 'outline' : 'primary'} onPress={() => router.replace('/home')} style={{ alignSelf: 'stretch' }} />
        </ScrollView>
      </Screen>
    );
  }

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
          {sectionQuiz && extraCount > 0 && !withExtra && (
            <Button
              label={`تمرین بیشتر: ${toPersianDigits(extraCount)} تست تکمیلی`}
              variant={firstOpen >= 0 ? 'outline' : 'primary'}
              onPress={() => {
                const before = questions.length;
                setWithExtra(true);
                setShowSummary(false);
                setIndex(before);
              }}
              style={{ alignSelf: 'stretch' }}
            />
          )}
          {quick ? (
            <Button label="کافی است برای امروز" variant={firstOpen >= 0 ? 'outline' : 'primary'} onPress={() => router.replace('/home')} style={{ alignSelf: 'stretch' }} />
          ) : notebook ? (
            <Button label="اشتباهات من" variant={firstOpen >= 0 ? 'outline' : 'primary'} onPress={() => router.replace('/mistakes')} style={{ alignSelf: 'stretch' }} />
          ) : (
            <Button label="آزمون زمان‌دار با نمره‌ی منفی" variant={firstOpen >= 0 ? 'outline' : 'primary'} onPress={() => router.replace(`/exam/${nodeId}`)} style={{ alignSelf: 'stretch' }} />
          )}
          <Button label="شروع دوباره‌ی تست‌ها" variant="outline" onPress={restart} style={{ alignSelf: 'stretch' }} />
          <Button label="بازگشت" variant="outline" onPress={() => router.back()} style={{ alignSelf: 'stretch' }} />
        </ScrollView>
      </Screen>
    );
  }

  const parts: PartState[] = questions.map((x) => ({ right: 'done', wrong: 'wrong', none: 'empty' })[status(x.id)] as PartState);
  const reviewSessionKind = (reviewInfo ?? (data as { session?: ReviewSessionData } | undefined)?.session)?.kind;

  return (
    <Screen>
      <PageHeader
        icon={notebook ? 'notebook-pen' : review ? 'rotate-ccw' : repeats ? 'repeat' : past ? 'graduation-cap' : 'list-checks'}
        title={notebook ? 'تمرین اشتباه‌ها' : review ? (reviewSessionKind === 'book' ? 'مرور ترکیبی کتاب' : 'مرور فصل') : quick ? 'فقط ۵ دقیقه' : past ? ((data as { title?: string } | undefined)?.title ?? 'کنکور') : 'تمرین تست'}
        status={`تست ${toPersianDigits(index + 1)} از ${toPersianDigits(questions.length)}`}
        lemon={<LemonProgress parts={parts} current={index} size={46} onPress={() => setPickerOpen(true)} accessibilityLabel="پیشرفت تست‌ها؛ برای رفتن به سؤال دیگر بزنید" />}
      />
      <Text style={[styles.place, rtl]} numberOfLines={1}>
        {[placeLabel(q.node_title, q.chapter_number), `${toPersianDigits(counts.right)} درست، ${toPersianDigits(counts.wrong)} غلط، ${toPersianDigits(counts.none)} مانده`].filter(Boolean).join('؛ ')}
      </Text>
      {!!resumedNote && (
        <Text style={[styles.resumedNote, rtl]} numberOfLines={1}>{resumedNote}</Text>
      )}
      {!review && <View style={styles.orders}>
        {ORDERS.map(([key, label]) => (
          <Pill key={key} label={label} small selected={order.order === key} onPress={() => changeOrder(key)} />
        ))}
      </View>}
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
          <QuestionShareCard ref={shareRef} questions={[q]} />
        </View>
      )}
      <Sheet visible={!!cardSheet} onClose={() => setCardSheet(null)} title="فلش‌کارت مرتبط">
        {cardSheet && !cardSheet.cards && <Loading />}
        {cardSheet?.cards?.length === 0 && <Text style={[styles.hint, rtl]}>کارت پیدا نشد.</Text>}
        {cardSheet?.cards?.map((c) => (
          <View key={c.id} style={styles.cardBox}>
            <Text style={[styles.cardTitle, rtl]}>{c.title}</Text>
            <RichText text={c.point} size={15} />
            {!!c.formula && <RichText text={`$$${c.formula}$$`} size={15} />}
          </View>
        ))}
        {!!cardSheet?.cards?.length && (
          <Button
            label="مرور این کارت‌ها در فلش‌کارت‌ها"
            variant="outline"
            onPress={() => {
              const s = cardSheet;
              setCardSheet(null);
              router.push({ pathname: '/flashcards/[nodeId]', params: { nodeId: String(s.book), ids: s.ids.join(','), keep: '1' } });
            }}
          />
        )}
      </Sheet>
      <ReportSheet
        visible={reportOpen}
        onClose={() => setReportOpen(false)}
        kind="question"
        onSend={(reason, note) => endpoints.reportQuestion(q.id, reason, note)}
        onDone={() => setReported((r) => [...r, q.id])}
      />
      <View style={styles.bar}>
        <Button label="قبلی" variant="outline" disabled={index === 0} onPress={() => go(index - 1)} style={{ flex: 1 }} />
        {index + 1 < questions.length ? (
          <Button label={current?.result ? 'سؤال بعد' : 'بعداً جواب می‌دهم'} variant={current?.result ? 'primary' : 'outline'} onPress={() => go(index + 1)} style={{ flex: 1.6 }} />
        ) : (
          <Button label="دیدن نتیجه" variant="primary" onPress={() => setShowSummary(true)} style={{ flex: 1.6 }} />
        )}
      </View>
      {!!counts.none && index + 1 === questions.length && (
        <Text style={[styles.hint, rtl]}>{toPersianDigits(counts.none)} تست بی‌جواب مانده؛ با زدن لیمو می‌توانی برگردی.</Text>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  place: { fontSize: 12.5, color: colors.muted, paddingHorizontal: 16, paddingBottom: 6 },
  resumedNote: { fontSize: 12.5, fontWeight: '700', color: colors.greenDark, paddingHorizontal: 16, paddingBottom: 6 },
  orders: { flexDirection: 'row-reverse', gap: 6, paddingHorizontal: 16, paddingBottom: 6 },
  page: { flex: 1, backfaceVisibility: 'hidden' },
  share: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, alignSelf: 'flex-end', marginHorizontal: 16, marginBottom: 4, paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, backgroundColor: colors.lemonSoft },
  shareText: { fontSize: 12.5, fontWeight: '800', color: colors.ink },
  offscreen: { position: 'absolute', left: -2000, top: 0 },
  bar: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: colors.line },
  hint: { fontSize: 12, color: colors.muted, paddingHorizontal: 16, paddingBottom: 8 },
  cardBox: { backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.line, padding: 14, gap: 6 },
  cardTitle: { fontSize: 16, fontWeight: '900', color: colors.ink },
  result: { flexGrow: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  resultPercent: { fontSize: 64, fontWeight: '900', color: colors.ink },
  resultLine: { fontSize: 15, color: colors.muted, marginBottom: 12 },
});
