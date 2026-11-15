import { router, useFocusEffect, useLocalSearchParams } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { ApiError } from '../api/client';
import { endpoints, type Mistakes } from '../api/endpoints';
import { Icon } from '../components/Icon';
import { RichText } from '../components/RichText';
import { Text } from '../components/Text';
import { Button, Empty, ErrorState, Header, Loading, Screen, Sheet, usePullRefresh } from '../components/ui';
import { useFeedback } from '../components/Feedback';
import { Pill } from '../components/Pill';
import { PageHeader } from '../components/PageHeader';
import { requireLogin, useAuth } from '../lib/auth';
import { jalaliDate } from '../lib/jalali';
import { colors, rtl, toPersianDigits } from '../theme';

/** «دفترچه‌ی اشتباهات»: questions got wrong (or blank in an exam), with the learner's reason. One right answer moves a
 * question to «نیازمند تثبیت»; a right answer on a later day takes it out. */
export default function MistakesScreen() {
  const { user } = useAuth();
  const start = useLocalSearchParams<{ book?: string }>().book;
  const [book, setBook] = useState(start ?? '');
  const [data, setData] = useState<Mistakes | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  // Twenty at a time: each item with a formula is drawn by the lesson renderer.
  const [shown, setShown] = useState(20);

  const load = useCallback(async () => {
    if (!user) return;
    setBusy(true);
    setError(null);
    try {
      setData(await endpoints.mistakes(book));
    } catch (e) {
      setError(e instanceof ApiError ? e : new ApiError(0, 'error', 'خطا'));
    } finally {
      setBusy(false);
    }
  }, [book, user]);
  // Back from practising: fixed questions have left the notebook.
  useFocusEffect(
    useCallback(() => {
      load();
    }, [load]),
  );
  const refresh = usePullRefresh(busy, load);

  const { toast } = useFeedback();
  const [help, setHelp] = useState(false);
  const setReason = (questionId: number, reason: string) => {
    if (!data) return;
    const before = data;
    setData({ ...data, items: data.items.map((i) => (i.question_id === questionId ? { ...i, reason } : i)) });
    endpoints
      .mistakeReason(questionId, reason)
      .then((r) => {
        if (reason === 'forgot' && r.cards) toast(`${toPersianDigits(r.cards)} فلش‌کارت این تست به «مرور کارت‌ها»ی امروز اضافه شد.`);
        if (reason === 'careless') load();
      })
      .catch(() => setData(before));
  };
  /** One question again, right now (any time, even before its turn). */
  const retry = (m: Mistakes['items'][number]) =>
    router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: String(m.node_id), ids: String(m.question_id) } });

  if (!user) {
    return (
      <Screen>
        <Header title="دفترچه‌ی اشتباهات" />
        <Empty icon="notebook-pen" title="برای دفترچه‌ی اشتباهات وارد شوید" text="تست‌هایی که غلط می‌زنی این‌جا جمع می‌شوند تا دوباره تمرینشان کنی." />
        <View style={{ padding: 16 }}>
          <Button label="ورود" onPress={() => requireLogin(user, 'برای دفترچه‌ی اشتباهات وارد شوید.')} />
        </View>
      </Screen>
    );
  }

  return (
    <Screen>
      <PageHeader
        icon="notebook-pen"
        title="دفترچه‌ی اشتباهات"
        status={
          data && data.count
            ? [data.open ? `${toPersianDigits(data.open)} منتظر جبران` : '', data.settling ? `${toPersianDigits(data.settling)} نیازمند تثبیت` : ''].filter(Boolean).join('، ')
            : undefined
        }
      />
      {!data && busy ? (
        <Loading />
      ) : error && !data ? (
        <ErrorState message={error.message} onRetry={load} />
      ) : !data || (data.count === 0 && !book) ? (
        <Empty
          icon="circle-check"
          title="دفترچه خالی است"
          text="تست‌های غلط و بی‌پاسخت این‌جا جمع می‌شوند. هر کدام را دو بار، با چند روز فاصله، درست جواب بدهی، از دفترچه بیرون می‌رود."
        />
      ) : (
        <ScrollView contentContainerStyle={styles.page} refreshControl={refresh}>
          <View style={styles.top}>
            <Text style={[styles.topTitle, rtl]}>
              {data.open > 0 ? `${toPersianDigits(data.open)} تست منتظر جبران` : 'همه را یک بار جبران کرده‌ای'}
            </Text>
            {data.settling > 0 && (
              <Text style={[styles.topText, rtl]}>{toPersianDigits(data.settling)} تست نیازمند تثبیت؛ یک بار درست زده‌ای و چند روز بعد دوباره پرسیده می‌شود.</Text>
            )}
            <Pressable onPress={() => setHelp(true)} style={styles.helpRow} accessibilityRole="button">
              <Icon name="circle-alert" size={16} color={colors.lemon} />
              <Text style={[styles.topText, rtl, { flex: 1, color: '#E4E9E2' }]}>
                هر تست را یک بار درست بزنی به «تثبیت» می‌رود؛ {toPersianDigits(data.settle_days)} روز بعد اگر باز درست زدی، از دفترچه بیرون می‌رود. توضیح بیشتر ←
              </Text>
            </Pressable>
            {data.due > 0 ? (
              <Button
                label={`تمرین ${toPersianDigits(data.due)} تست`}
                onPress={() => router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: 'mistakes', ...(book ? { book } : {}) } })}
              />
            ) : (
              data.count > 0 && <Text style={[styles.topText, rtl, { color: colors.lemon }]}>فعلاً تستی نوبتش نرسیده؛ چند روز دیگر سر بزن.</Text>
            )}
          </View>
          {data.books.length > 1 && (
            <ScrollView horizontal showsHorizontalScrollIndicator={false} contentContainerStyle={styles.chips} style={{ transform: [{ scaleX: -1 }] }}>
              {[{ slug: '', title: 'همه‌ی کتاب‌ها' }, ...data.books].map((b) => (
                <Pill key={b.slug} label={b.title} selected={book === b.slug} onPress={() => setBook(b.slug)} role="radio" style={{ transform: [{ scaleX: -1 }] }} />
              ))}
            </ScrollView>
          )}
          {data.items.slice(0, shown).map((m) => (
            <View key={m.question_id} style={styles.row}>
              {m.text ? <RichText text={m.text} size={15} /> : <Text style={[styles.text, rtl]}>سؤال تصویری</Text>}
              <Pressable onPress={() => router.push(`/section/${m.node_id}`)} style={styles.where} accessibilityRole="link">
                <Icon name="book-open" size={14} color={colors.greenDark} />
                <Text style={[styles.whereText, rtl]} numberOfLines={1}>
                  {m.book_title}، {m.node_title}
                </Text>
              </Pressable>
              <Text style={[styles.meta, rtl]}>
                {m.blank ? 'در آزمون نزده' : m.wrong_count > 1 ? `${toPersianDigits(m.wrong_count)} بار غلط` : 'غلط'}، {jalaliDate(m.last_at)}
              </Text>
              {m.state === 'settling' && (
                <Text style={[styles.settling, rtl]}>
                  {m.is_due ? 'نیازمند تثبیت: نوبتش رسیده، دوباره بزنش.' : `نیازمند تثبیت: ${m.due_on ? jalaliDate(m.due_on) : ''} دوباره پرسیده می‌شود.`}
                </Text>
              )}
              {m.corrected && (
                <Text style={[styles.corrected, rtl]}>اصلاح‌شده: پاسخ‌نامه‌ی این تست بعد از جواب تو اصلاح شد؛ دوباره بزنش.</Text>
              )}
              <Text style={[styles.ask, rtl]}>چرا غلط شد؟</Text>
              <View style={styles.reasons}>
                {data.reasons.map((r) => {
                  const on = m.reason === r.key;
                  return (
                    <Pill key={r.key} label={r.label} small selected={on} onPress={() => setReason(m.question_id, on ? '' : r.key)} role="radio" />
                  );
                })}
              </View>
              {m.reason === 'unknown' && (
                <Text style={[styles.tip, rtl]}>اول این نکته را در درسنامه بخوان، بعد دوباره بزن.</Text>
              )}
              {m.reason === 'forgot' && <Text style={[styles.tip, rtl]}>فلش‌کارت‌های این تست به «مرور کارت‌ها» اضافه شد.</Text>}
              {m.reason === 'careless' && (
                <Text style={[styles.tip, rtl]}>بلد بودی؛ برای همین زودتر (یک روز بعد از جواب درست) از دفترچه بیرون می‌رود.</Text>
              )}
              {m.reason === 'time' && (
                <Text style={[styles.tip, rtl]}>
                  {m.seconds ? `زمان این تست حدود ${toPersianDigits(m.seconds)} ثانیه است. ` : ''}
                  {m.solutions?.length ? `بعد از جواب، «${m.solutions.join('»، «')}» را ببین؛ راه کوتاه‌تر است.` : 'بعد از جواب، دنبال راه کوتاه‌تر بگرد.'}
                </Text>
              )}
              <View style={styles.actions}>
                <Pressable onPress={() => retry(m)} style={[styles.action, styles.actionMain]} accessibilityRole="button">
                  <Icon name="rotate-ccw" size={15} color={colors.ink} />
                  <Text style={styles.actionText}>دوباره بزن</Text>
                </Pressable>
                {m.reason === 'unknown' && (
                  <Pressable onPress={() => router.push(`/section/${m.node_id}`)} style={styles.action} accessibilityRole="button">
                    <Icon name="book-open" size={15} color={colors.ink} />
                    <Text style={styles.actionText}>خواندن درسنامه</Text>
                  </Pressable>
                )}
              </View>
            </View>
          ))}
          {data.items.length > shown && <Button label="بیشتر" variant="outline" onPress={() => setShown((n) => n + 20)} />}
        </ScrollView>
      )}
      <Sheet visible={help} onClose={() => setHelp(false)} title="دفترچه چطور کار می‌کند؟">
        <Text style={[styles.helpText, rtl]}>
          هر تستی که غلط بزنی یا در آزمون بی‌جواب بگذاری این‌جا می‌آید و دو مرحله دارد:
        </Text>
        <Text style={[styles.helpText, rtl]}>
          <Text style={{ fontWeight: '900' }}>۱. منتظر جبران: </Text>
          هنوز درستش نزده‌ای. هر وقت بخواهی با «دوباره بزن» یا «تمرین» امتحانش کن.
        </Text>
        <Text style={[styles.helpText, rtl]}>
          <Text style={{ fontWeight: '900' }}>۲. نیازمند تثبیت: </Text>
          یک بار درست زده‌ای، ولی شاید فقط جواب یادت مانده بود. {toPersianDigits(data?.settle_days ?? 3)} روز بعد دوباره پرسیده می‌شود؛ اگر باز درست
          زدی، از دفترچه بیرون می‌رود. (برای «بی‌دقتی» یک روز بعد.)
        </Text>
        <Text style={[styles.helpText, rtl]}>هر بار دوباره غلط بزنی، تست به مرحله‌ی ۱ برمی‌گردد و علت را دوباره می‌پرسیم.</Text>
        <Text style={[styles.helpText, rtl]}>
          <Text style={{ fontWeight: '900' }}>علت‌ها چه می‌کنند؟ </Text>
          «بلد نبودم»: راه درسنامه را نشانت می‌دهد. «فراموش کردم»: فلش‌کارت‌های تست به «مرور کارت‌ها» می‌روند. «بی‌دقتی»: زودتر تثبیت می‌شود.
          «کمبود وقت»: زمان تست و راه‌حل‌های کوتاه‌ترش را نشان می‌دهد.
        </Text>
      </Sheet>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 10 },
  top: { backgroundColor: colors.ink, borderRadius: 18, padding: 16, gap: 8 },
  topTitle: { fontSize: 18, fontWeight: '900', color: colors.lemon },
  topText: { fontSize: 13, color: '#C9D2C6' },
  chips: { gap: 8, paddingVertical: 2 },
  row: { backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 14, gap: 6 },
  text: { fontSize: 15, color: colors.ink, lineHeight: 26 },
  where: { flexDirection: 'row-reverse', alignItems: 'center', gap: 5 },
  whereText: { flex: 1, fontSize: 12, fontWeight: '700', color: colors.greenDark },
  meta: { fontSize: 12, color: colors.muted },
  settling: { alignSelf: 'flex-end', fontSize: 12, fontWeight: '700', color: colors.greenDark, backgroundColor: '#E3F3E9', borderRadius: 8, paddingHorizontal: 8, paddingVertical: 2 },
  corrected: { alignSelf: 'flex-end', fontSize: 12, fontWeight: '700', color: '#3A2F7A', backgroundColor: '#F1EEFC', borderRadius: 8, paddingHorizontal: 8, paddingVertical: 2 },
  reasons: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 6, marginTop: 2 },
  ask: { fontSize: 12, fontWeight: '700', color: colors.muted, marginTop: 4 },
  tip: { fontSize: 12.5, lineHeight: 21, color: colors.ink, backgroundColor: colors.lemonSoft, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 6 },
  actions: { flexDirection: 'row-reverse', gap: 8, marginTop: 4 },
  action: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, borderRadius: 999, borderWidth: 1, borderColor: colors.line, paddingHorizontal: 14, paddingVertical: 8 },
  actionMain: { backgroundColor: colors.lemon, borderColor: colors.lemon },
  actionText: { fontSize: 13, fontWeight: '800', color: colors.ink },
  helpRow: { flexDirection: 'row-reverse', alignItems: 'flex-start', gap: 6 },
  helpText: { fontSize: 14, lineHeight: 25, color: colors.ink },
});
