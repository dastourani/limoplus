import AsyncStorage from '@react-native-async-storage/async-storage';
import { router, useLocalSearchParams, useNavigation } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Pressable, ScrollView, StyleSheet, Switch, View } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints, type ExamDetail } from '../../api/endpoints';
import { LemonProgress, type PartState } from '../../components/LemonProgress';
import { PageHeader, TimerChip } from '../../components/PageHeader';
import { Pill } from '../../components/Pill';
import { QuestionPicker } from '../../components/QuestionPicker';
import { QuizView, type QuizEvent } from '../../components/QuizView';
import { Text } from '../../components/Text';
import { useFeedback } from '../../components/Feedback';
import { Icon } from '../../components/Icon';
import { Button, Card, Header, Screen } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { useStudyTimer } from '../../lib/studyTime';
import { usePageTurn } from '../../lib/pageTurn';
import { examSizes } from '../../lib/examSizes';
import { seeded } from '../../lib/shuffle';
import { type QuizViewState } from '../../lib/quizHtml';
import { colors, rtl, toPersianDigits } from '../../theme';
import { HelpTip } from '../../components/HelpTip';

/** Sent when the number of questions could not be learned: the server gives all there are (it never gives more). */
const ALL_THERE_ARE = 100;

function clock(seconds: number) {
  const s = Math.max(0, seconds);
  return toPersianDigits(`${String(Math.floor(s / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`);
}

/** Exam mode: timed, no feedback until the end, negative marking on by default (as in the konkur). */
export default function Exam() {
  const { nodeId, attempt, count: suggested, source, title: sourceTitle } = useLocalSearchParams<{
    nodeId: string;
    attempt?: string;
    count?: string;
    /** One past exam of the book («کنکور ارشد ۱۴۰۱»), taken whole in its own order. */
    source?: string;
    title?: string;
  }>();
  const { user } = useAuth();
  // Sizes come from how many questions there really are (examSizes). Until the server says, nothing is offered; if
  // it cannot be asked, only «همه‌ی تست‌ها». The end of a chapter suggests a size, chosen here to begin with.
  const [pool, setPool] = useState<number | 'unknown' | null>(null);
  const [count, setCount] = useState(0);
  // «فقط تست‌های کنکور», and which years (none chosen: every year).
  const [konkur, setKonkur] = useState<{ total: number; years: { year: number; count: number }[] }>({ total: 0, years: [] });
  const [konkurOnly, setKonkurOnly] = useState(false);
  const [years, setYears] = useState<number[]>([]);
  const [allPool, setAllPool] = useState(0);
  // A past konkur with tests from chapters not studied yet: «فقط فصل‌های خوانده‌شده» or «همه».
  const [unread, setUnread] = useState<{ count: number; unread: number; unread_chapters: string[] } | null>(null);
  const [onlyStudied, setOnlyStudied] = useState(false);
  useEffect(() => {
    if (attempt) return;
    endpoints
      .examInfo(Number(nodeId), source ? Number(source) : undefined)
      .then((info) => {
        if (info.source && info.source.unread > 0) setUnread(info.source);
        setAllPool(info.questions);
        setKonkur({ total: info.konkur ?? 0, years: info.years ?? [] });
        setPool(info.questions);
        const sizes = examSizes(info.questions);
        const wish = Number(suggested) > 0 ? Number(suggested) : info.questions;
        setCount([...sizes].reverse().find((c) => c <= wish) ?? info.questions);
      })
      .catch(() => {
        setPool('unknown');
        setCount(ALL_THERE_ARE);
      });
  }, [nodeId, attempt, suggested]);
  // Narrowed to the konkur tests (of the chosen years): the sizes follow.
  useEffect(() => {
    if (pool === null || pool === 'unknown' || !allPool) return;
    const n = !konkurOnly ? allPool : years.length ? Math.min(konkur.total, konkur.years.filter((y) => years.includes(y.year)).reduce((a, y) => a + y.count, 0)) : konkur.total;
    setPool(n);
    setCount((c) => (c > n || c === 0 ? n : c));
  }, [konkurOnly, years, allPool]); // eslint-disable-line react-hooks/exhaustive-deps
  const counts = typeof pool === 'number' ? examSizes(pool) : pool === 'unknown' ? [ALL_THERE_ARE] : [];
  const [negative, setNegative] = useState(true);
  const [focus, setFocus] = useState(false);
  const [exam, setExam] = useState<ExamDetail | null>(null);
  const [answers, setAnswers] = useState<Record<string, number | null>>({});
  // The timer's submit must send the answers as they are now, not as they were when the timer started.
  const answersRef = useRef(answers);
  answersRef.current = answers;
  const [index, setIndex] = useState(0);
  // «شک‌دار»: questions marked to look at again before finishing (kept on the phone with the answers).
  const [flags, setFlags] = useState<number[]>([]);
  // Sent with the answers: «شک‌دار» questions come back in the chapter reviews.
  const flagsRef = useRef<number[]>([]);
  flagsRef.current = flags;
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
    return raw ? (raw.fixed_order ? raw : { ...raw, choices: seeded(raw.choices, exam!.id * 7919 + raw.id) }) : null;
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
        const savedFlags = await AsyncStorage.getItem(`limo.exam.${e.id}.flags`).catch(() => null);
        setFlags(savedFlags ? (JSON.parse(savedFlags) as number[]) : []);
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
      const e = await endpoints.startExam(
        Number(nodeId),
        source
          ? { count: 100, negative_marking: negative, source: Number(source), only_studied: onlyStudied }
          : { count, negative_marking: negative, focus_mistakes: focus, konkur_only: konkurOnly, years: konkurOnly ? years : [] },
      );
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
      await endpoints.submitExam(exam.id, answersRef.current, flagsRef.current);
      if (storeKey) AsyncStorage.multiRemove([storeKey, `${storeKey}.flags`]).catch(() => undefined);
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

  // «زمان مطالعه»: the exam counts on its chapter while it runs.
  useStudyTimer(exam && !exam.submitted_at ? exam.node_id : null, 'exam');

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
          {source ? (
            <Card>
              <Text style={[styles.label, rtl]}>آزمون «{sourceTitle}»</Text>
              <Text style={[styles.help, rtl]}>همه‌ی تست‌های این کنکور که در این کتاب هست، به ترتیب شماره‌ی اصلی سؤال‌ها، مثل جلسه‌ی کنکور.</Text>
              {!!unread && (
                <View style={styles.warn}>
                  <Text style={[styles.warnTitle, rtl]}>
                    {unread.unread === unread.count
                      ? 'هیچ‌کدام از فصل‌های این کنکور را هنوز تمام نکرده‌ای.'
                      : `${toPersianDigits(unread.unread)} تست از ${toPersianDigits(unread.count)} تست این کنکور از فصل‌هایی است که هنوز تمام نکرده‌ای.`}
                  </Text>
                  {!!unread.unread_chapters.length && <Text style={[styles.help, rtl]}>{unread.unread_chapters.join('؛ ')}</Text>}
                  <Text style={[styles.help, rtl]}>زدن تست فصل نخوانده نمره را پایین می‌آورد و آن تست‌ها را پیش از خواندن فصل لو می‌دهد.</Text>
                  <View style={styles.years}>
                    {unread.unread < unread.count && (
                      <Pill label={`فقط فصل‌های خوانده‌شده (${toPersianDigits(unread.count - unread.unread)} تست)`} selected={onlyStudied} onPress={() => setOnlyStudied(true)} />
                    )}
                    <Pill label={`همه (${toPersianDigits(unread.count)} تست)`} selected={!onlyStudied} onPress={() => setOnlyStudied(false)} />
                  </View>
                </View>
              )}
              <View style={styles.switchRow}>
                <Text style={[styles.label, rtl, { flex: 1 }]}>نمره‌ی منفی (هر ۳ غلط، ۱ درست را خنثی می‌کند)</Text>
                <HelpTip title="نمره‌ی منفی" text="در آزمون با نمره‌ی منفی، هر پاسخ غلط یک‌سوم نمره‌ی یک پاسخ درست را کم می‌کند (مثل کنکور). پس اگر مطمئن نیستی، بی‌پاسخ گذاشتن بهتر از حدس است. نمره = (درست − غلط÷۳) ÷ همه‌ی تست‌ها." />
                <Switch value={negative} onValueChange={setNegative} trackColor={{ true: colors.green }} />
              </View>
            </Card>
          ) : (
          <Card>
            {konkur.total > 0 && (
              <View style={{ gap: 8 }}>
                <View style={styles.switchRow}>
                  <View style={{ flex: 1, gap: 2 }}>
                    <Text style={[styles.label, rtl]}>فقط تست‌های کنکور</Text>
                    <Text style={[styles.help, rtl]}>{toPersianDigits(konkur.total)} تست این‌جا از کنکورهای سال‌های قبل است.</Text>
                  </View>
                  <Switch value={konkurOnly} onValueChange={setKonkurOnly} trackColor={{ true: colors.green }} />
                </View>
                {konkurOnly && konkur.years.length > 1 && (
                  <View style={styles.years}>
                    {konkur.years.map((y) => (
                      <Pill
                        key={y.year}
                        small
                        label={`${toPersianDigits(y.year)} (${toPersianDigits(y.count)})`}
                        selected={years.includes(y.year)}
                        onPress={() => setYears((list) => (list.includes(y.year) ? list.filter((x) => x !== y.year) : [...list, y.year]))}
                      />
                    ))}
                    <Text style={[styles.help, rtl, { width: '100%' }]}>{years.length ? 'فقط سال‌های انتخاب‌شده' : 'هیچ سالی انتخاب نشده: همه‌ی سال‌ها'}</Text>
                  </View>
                )}
              </View>
            )}
            <Text style={[styles.label, rtl]}>تعداد سؤال</Text>
            <View style={styles.counts}>
              {pool === null && <Text style={[styles.help, rtl, { flex: 1 }]}>در حال بارگذاری…</Text>}
              {typeof pool === 'number' && pool === 0 && <Text style={[styles.help, rtl, { flex: 1 }]}>برای این بخش هنوز تستی نیست.</Text>}
              {counts.map((c) => (
                <Pressable key={c} onPress={() => setCount(c)} style={[styles.count, count === c && styles.countOn]}>
                  <Text style={{ fontWeight: '800', color: count === c ? colors.lemon : colors.ink }}>
                    {pool === 'unknown' ? 'همه‌ی تست‌ها' : c === pool ? `همه‌ی ${toPersianDigits(c)}` : toPersianDigits(c)}
                  </Text>
                </Pressable>
              ))}
            </View>
            <View style={styles.switchRow}>
              <Text style={[styles.label, rtl, { flex: 1 }]}>نمره‌ی منفی (هر ۳ غلط، ۱ درست را خنثی می‌کند)</Text>
                <HelpTip title="نمره‌ی منفی" text="در آزمون با نمره‌ی منفی، هر پاسخ غلط یک‌سوم نمره‌ی یک پاسخ درست را کم می‌کند (مثل کنکور). پس اگر مطمئن نیستی، بی‌پاسخ گذاشتن بهتر از حدس است. نمره = (درست − غلط÷۳) ÷ همه‌ی تست‌ها." />
              <Switch value={negative} onValueChange={setNegative} trackColor={{ true: colors.green }} />
            </View>
            {/* Up to half of the questions from the learner's own mistakes; off by default so a plain exam shows the true level. */}
            {typeof pool === 'number' && count < pool && (
              <View style={styles.switchRow}>
                <View style={{ flex: 1, gap: 2 }}>
                  <Text style={[styles.label, rtl]}>تمرکز روی اشتباه‌هایم</Text>
                  <Text style={[styles.help, rtl]}>تا نیمی از سؤال‌ها از تست‌هایی که غلط زده‌ای یا شک داشتی.</Text>
                </View>
                <Switch value={focus} onValueChange={setFocus} trackColor={{ true: colors.green }} />
              </View>
            )}
            <Text style={[styles.help, rtl]}>زمان بر اساس سطح سؤال‌ها تعیین می‌شود. پاسخ‌ها تا پایان آزمون نشان داده نمی‌شوند.</Text>
          </Card>
          )}
          {!!error && <Text style={[styles.error, rtl]}>{error}</Text>}
          <Button label="شروع آزمون" onPress={start} loading={busy} disabled={!source && !count} />
        </ScrollView>
      </Screen>
    );
  }

  const q = shownQ!;
  const answeredCount = Object.values(answers).filter((v) => v != null).length;
  const parts: PartState[] = exam.questions.map((x) => (flags.includes(x.id) ? 'flag' : answers[x.id] != null ? 'done' : 'empty'));
  const flagged = flags.includes(q.id);
  const toggleFlag = () => {
    const next = flagged ? flags.filter((f) => f !== q.id) : [...flags, q.id];
    setFlags(next);
    if (storeKey) AsyncStorage.setItem(`${storeKey}.flags`, JSON.stringify(next)).catch(() => undefined);
  };
  // Next marked question after this one (round the end), for «مرور شک‌دارها».
  const nextFlag = () => {
    const order = exam.questions.map((x) => x.id);
    for (let k = 1; k <= order.length; k++) {
      const i = (index + k) % order.length;
      if (flags.includes(order[i])) return i;
    }
    return -1;
  };
  const last = index + 1 >= exam.questions.length;

  const onEvent = (e: QuizEvent) => {
    if (e.type === 'choose') setAnswers((a) => ({ ...a, [q.id]: a[q.id] === e.id ? null : e.id }));
    else if (e.type === 'swipe') go(index + (e.dir === 'next' ? 1 : -1), e.flung);
  };

  const finish = async () =>
    (await confirm({
      title: 'آزمون تمام شود؟',
      message:
        (answeredCount < exam.questions.length ? `${toPersianDigits(exam.questions.length - answeredCount)} سؤال بی‌پاسخ است.` : 'همه‌ی سؤال‌ها پاسخ داده شده‌اند.') +
        (flags.length ? ` ${toPersianDigits(flags.length)} سؤال را شک‌دار علامت زده‌ای.` : ''),
      confirmLabel: 'پایان آزمون',
      icon: 'circle-check',
    })) && submit();

  return (
    <Screen>
      <PageHeader
        icon="timer"
        title="آزمون"
        status={`سؤال ${toPersianDigits(index + 1)} از ${toPersianDigits(exam.questions.length)}`}
        extra={
          <>
            <Pressable
              onPress={toggleFlag}
              style={[styles.flag, flagged && styles.flagOn]}
              accessibilityRole="switch"
              accessibilityState={{ checked: flagged }}
              accessibilityLabel="علامت شک‌دار برای مرور دوباره"
            >
              <Icon name="flag" size={18} color={colors.ink} />
            </Pressable>
            <TimerChip text={clock(left)} urgent={left < 60} />
          </>
        }
        lemon={<LemonProgress parts={parts} current={index} size={46} onPress={() => setPickerOpen(true)} accessibilityLabel="پیشرفت آزمون؛ برای رفتن به سؤال دیگر بزنید" />}
      />
      <QuestionPicker
        visible={pickerOpen}
        onClose={() => setPickerOpen(false)}
        parts={parts}
        current={index}
        onPick={(i) => go(i)}
        legend="زرد: پاسخ داده‌شده، نارنجی با پرچم: شک‌دار، سفید: بی‌پاسخ. برای پاک کردن یک پاسخ، دوباره روی همان گزینه بزنید."
      />
      <Animated.View style={[{ flex: 1 }, pageStyle]}>
        <QuizView key={q.id} mode="exam" question={q} state={viewState} onEvent={onEvent} />
      </Animated.View>
      {!!error && <Text style={[styles.error, rtl, { paddingHorizontal: 16 }]}>{error}</Text>}
      <View style={styles.bar}>
        <Button label="قبلی" variant="outline" disabled={index === 0} onPress={() => go(index - 1)} style={{ flex: 1 }} />
        {flags.length > 0 && (flags.length > 1 || !flagged) && (
          <Button label={`شک‌دارها (${toPersianDigits(flags.length)})`} variant="outline" onPress={() => go(nextFlag())} style={{ flex: 1.2 }} />
        )}
        {last ? (
          <Button label="پایان آزمون" loading={busy} onPress={finish} style={{ flex: 1.3 }} />
        ) : (
          <Button label="بعدی" variant="primary" onPress={() => go(index + 1)} style={{ flex: 1 }} />
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
  years: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 6 },
  warn: { backgroundColor: '#FFF3E0', borderRadius: 14, padding: 12, gap: 6, marginTop: 6 },
  warnTitle: { fontSize: 14, fontWeight: '800', color: '#8A4B00' },
  top: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, paddingHorizontal: 16, paddingTop: 10, paddingBottom: 6 },
  clock: { flexDirection: 'row-reverse', alignItems: 'center', gap: 4, backgroundColor: colors.surface, borderRadius: 14, paddingHorizontal: 10, paddingVertical: 6 },
  timer: { fontSize: 22, fontWeight: '800', color: colors.ink },
  flag: { width: 36, height: 36, borderRadius: 12, borderWidth: 1.5, borderColor: colors.line, alignItems: 'center', justifyContent: 'center' },
  flagOn: { backgroundColor: colors.amber, borderColor: colors.amber },
  bar: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: colors.line },
});
