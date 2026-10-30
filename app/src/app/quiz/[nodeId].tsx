import * as Haptics from 'expo-haptics';
import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { Text } from '../../components/Text';

import { ApiError } from '../../api/client';
import { endpoints, type AnswerResult } from '../../api/endpoints';
import { MarkdownView } from '../../components/MarkdownView';
import { Button, Chip, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { useApi } from '../../lib/useApi';
import { colors, DIFFICULTY_LABEL, radius, rtl, toPersianDigits } from '../../theme';

const KEYS = ['الف', 'ب', 'ج', 'د', 'ه', 'و'];

function RichText({ text, size = 16 }: { text: string; size?: number }) {
  // Plain text is drawn natively (fast); anything with formulas or markup goes through the lesson renderer.
  if (/[$*`|!\[]/.test(text)) {
    return (
      <View pointerEvents="none">
        <MarkdownView markdown={text} compact fontSize={size} />
      </View>
    );
  }
  return <Text style={[{ fontSize: size, lineHeight: size * 1.8, color: colors.ink }, rtl]}>{text}</Text>;
}

export default function Quiz() {
  const { nodeId } = useLocalSearchParams<{ nodeId: string }>();
  const { data, error, loading, retry } = useApi(() => endpoints.questions(Number(nodeId)), [nodeId]);
  const [index, setIndex] = useState(0);
  const [picked, setPicked] = useState<number | null>(null);
  const [result, setResult] = useState<AnswerResult | null>(null);
  const [score, setScore] = useState(0);
  const [tab, setTab] = useState<'explanation' | 'quick_solution' | 'alternative_view'>('explanation');
  const [sending, setSending] = useState(false);
  const [answerError, setAnswerError] = useState<string | null>(null);

  if (loading) return <Screen><Header title="تست" /><Loading /></Screen>;
  if (error) return <Screen><Header title="تست" /><ErrorState message={error.message} onRetry={retry} /></Screen>;

  const questions = data!.questions;
  if (questions.length === 0) {
    return (
      <Screen>
        <Header title="تست" />
        <ErrorState message={data!.locked_count ? 'تست‌های این بخش در نسخه‌ی کامل کتاب است.' : 'برای این بخش هنوز تستی نیست.'} />
      </Screen>
    );
  }

  const finished = index >= questions.length;
  if (finished) {
    const percent = Math.round((score / questions.length) * 100);
    return (
      <Screen>
        <View style={styles.result}>
          <Text style={styles.resultPercent}>{toPersianDigits(percent)}٪</Text>
          <Text style={styles.resultLine}>
            {toPersianDigits(score)} از {toPersianDigits(questions.length)} درست
          </Text>
          <Text style={styles.resultCheer}>{percent >= 80 ? 'عالی بود!' : percent >= 50 ? 'خوب پیش رفتی؛ غلط‌ها را مرور کن.' : 'ادامه بده؛ یک بار دیگر بخش را بخوان.'}</Text>
          <Button label="شروع دوباره" onPress={() => { setIndex(0); setScore(0); setPicked(null); setResult(null); }} style={{ alignSelf: 'stretch' }} />
          <Button label="بازگشت" variant="outline" onPress={() => router.back()} style={{ alignSelf: 'stretch' }} />
        </View>
      </Screen>
    );
  }

  const q = questions[index];

  const choose = async (choiceId: number) => {
    if (result || sending) return;
    setPicked(choiceId);
    setSending(true);
    setAnswerError(null);
    try {
      const r = await endpoints.answer(q.id, choiceId);
      setResult(r);
      setTab('explanation');
      if (r.is_correct) setScore((s) => s + 1);
      if (Platform.OS !== 'web') {
        Haptics.notificationAsync(r.is_correct ? Haptics.NotificationFeedbackType.Success : Haptics.NotificationFeedbackType.Warning).catch(() => undefined);
      }
    } catch (e) {
      setPicked(null);
      setAnswerError(e instanceof ApiError ? e.message : 'خطا در ارسال پاسخ.');
    } finally {
      setSending(false);
    }
  };

  const next = () => {
    setIndex((i) => i + 1);
    setPicked(null);
    setResult(null);
  };

  const tabs = result
    ? ([
        ['explanation', 'پاسخ تشریحی'],
        ['quick_solution', 'راه‌حل سریع'],
        ['alternative_view', 'زاویه‌ی دیگر'],
      ] as const).filter(([key]) => !!result[key])
    : [];

  return (
    <Screen>
      <Header title={`سؤال ${toPersianDigits(index + 1)} از ${toPersianDigits(questions.length)}`} />
      <View style={styles.progress}>
        {questions.map((item, i) => (
          <View key={item.id} style={[styles.seg, { backgroundColor: i < index ? colors.green : i === index ? colors.ink : colors.line }]} />
        ))}
      </View>
      <ScrollView contentContainerStyle={styles.page}>
        <View style={styles.badges}>
          <Chip label={DIFFICULTY_LABEL[q.difficulty] ?? q.difficulty} />
          {q.sources.map((s) => (
            <Chip key={`${s.name}${s.year}`} label={`${s.name} ${toPersianDigits(s.year)}`} color="#3B44B8" background="#EEF0FC" />
          ))}
          {q.is_original && <Chip label="تألیفی" />}
        </View>
        <RichText text={q.stem} size={17} />

        <View style={{ gap: 10 }}>
          {q.choices.map((c, i) => {
            const isRight = result && c.id === result.correct_choice_id;
            const isWrong = result && c.id === picked && !result.is_correct;
            return (
              <Pressable
                key={c.id}
                onPress={() => choose(c.id)}
                disabled={!!result || sending}
                accessibilityRole="button"
                style={[
                  styles.choice,
                  picked === c.id && !result && { borderColor: colors.ink },
                  isRight && { backgroundColor: colors.greenSoft, borderColor: colors.green },
                  isWrong && { backgroundColor: colors.redSoft, borderColor: colors.red },
                ]}
              >
                <View style={[styles.key, isRight && { backgroundColor: colors.green }, isWrong && { backgroundColor: colors.red }]}>
                  <Text style={[styles.keyText, (isRight || isWrong) && { color: '#fff' }]}>{KEYS[i]}</Text>
                </View>
                <View style={{ flex: 1 }}>
                  <RichText text={c.text} size={15} />
                </View>
              </Pressable>
            );
          })}
        </View>

        {!!answerError && <Text style={[styles.err, rtl]}>{answerError}</Text>}

        {result && (
          <View style={[styles.feedback, { backgroundColor: result.is_correct ? colors.greenSoft : '#FFF1EF' }]}>
            <Text style={[styles.feedbackTitle, rtl, { color: result.is_correct ? colors.greenDark : colors.redDark }]}>
              {result.is_correct ? 'آفرین، درست بود!' : 'نزدیک بودی؛ ببین چرا:'}
            </Text>
            {tabs.length > 1 && (
              <View style={styles.tabs}>
                {tabs.map(([key, label]) => (
                  <Pressable key={key} onPress={() => setTab(key)} style={[styles.tab, tab === key && styles.tabOn]}>
                    <Text style={[styles.tabText, tab === key && { color: colors.ink }]}>{label}</Text>
                  </Pressable>
                ))}
              </View>
            )}
            <RichText text={result[tab] || result.explanation} size={15} />
            {result.flashcards.length > 0 && (
              <Text style={[styles.related, rtl]}>فلش‌کارت مرتبط: {result.flashcards.map((f) => f.title).join('، ')}</Text>
            )}
          </View>
        )}
      </ScrollView>
      <View style={styles.bar}>
        {result ? (
          <Button label={index + 1 < questions.length ? 'سؤال بعد' : 'دیدن نتیجه'} variant="dark" onPress={next} />
        ) : (
          <Button label={sending ? 'در حال بررسی…' : 'یک گزینه را انتخاب کن'} disabled onPress={() => undefined} />
        )}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  progress: { flexDirection: 'row-reverse', gap: 3, paddingHorizontal: 16 },
  seg: { flex: 1, height: 6, borderRadius: 9 },
  page: { padding: 16, gap: 16 },
  badges: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 6 },
  choice: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, minHeight: 58, padding: 12, borderRadius: radius.md, borderWidth: 2, borderColor: colors.line, backgroundColor: colors.surface },
  key: { width: 30, height: 30, borderRadius: 10, backgroundColor: '#F1F3EC', alignItems: 'center', justifyContent: 'center' },
  keyText: { fontWeight: '800', color: colors.ink },
  feedback: { borderRadius: radius.md, padding: 14, gap: 10 },
  feedbackTitle: { fontSize: 16, fontWeight: '900' },
  tabs: { flexDirection: 'row-reverse', gap: 6, flexWrap: 'wrap' },
  tab: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, backgroundColor: '#FFFFFF88' },
  tabOn: { backgroundColor: colors.surface },
  tabText: { fontSize: 13, fontWeight: '700', color: colors.muted },
  related: { fontSize: 12, color: colors.muted },
  err: { color: colors.redDark },
  bar: { padding: 12, borderTopWidth: 1, borderTopColor: colors.line },
  result: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  resultPercent: { fontSize: 64, fontWeight: '900', color: colors.ink },
  resultLine: { fontSize: 16, color: colors.muted },
  resultCheer: { fontSize: 18, fontWeight: '800', color: colors.greenDark, marginBottom: 12, textAlign: 'center' },
});
