import { router, useFocusEffect } from 'expo-router';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, useWindowDimensions, View } from 'react-native';

import { endpoints, type ExamPage, type Stats, type StudyKindName, type StudyTimeTotals } from '../../api/endpoints';
import { useCelebrate } from '../../components/Celebrate';
import { ExamsCard } from '../../components/ExamsCard';
import { type IconName } from '../../components/Icon';
import { Text } from '../../components/Text';
import { Button, Empty, ErrorState, Loading, Screen, usePullRefresh } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { jalaliMonthDay } from '../../lib/jalali';
import { Glance, InsightCards, Section, SECOND, Strong, TrendChart, WeekCard, type Insight, type TrendDay } from '../../components/stats/parts';
import { YearGrid } from '../../components/YearGrid';
import { studyDuration } from '../../lib/duration';
import { colors, rtl, toPersianDigits } from '../../theme';

export default function StatsTab() {
  const { user } = useAuth();
  const { width } = useWindowDimensions();
  const [data, setData] = useState<Stats | null>(null);
  const [exams, setExams] = useState<ExamPage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const celebrate = useCelebrate();
  const load = useCallback(() => {
    if (!user) return;
    setLoading(true);
    endpoints.examPage(1).then(setExams).catch(() => undefined);
    endpoints
      .stats()
      .then((d) => {
        setData(d);
        setError(null);
        // Streak milestones are celebrated once each.
        // 7, 30 and 100 days in a row get the big moment once each; an ordinary day of a streak, a banner once a day.
        const milestone = [100, 30, 7].find((m) => d.streak_days >= m);
        const key = milestone ? `limo.streak.${user.id}.${milestone}` : '';
        AsyncStorage.getItem(key || 'limo.none')
          .catch(() => '1')
          .then((seen) => {
            if (milestone && !seen) {
              AsyncStorage.setItem(key, '1').catch(() => undefined);
              celebrate('streak', { title: milestone === 7 ? 'یک هفته‌ی کامل!' : `${toPersianDigits(milestone)} روز پشت سر هم!`, text: 'عادت مطالعه‌ات دارد شکل می‌گیرد. فردا هم یک بخش کوتاه بخوان.', days: d.streak_days });
            } else if (d.streak_days >= 2) {
              celebrate('small', { title: `${toPersianDigits(d.streak_days)} روز پیاپی!`, text: 'فردا هم سر بزن تا زنجیره نشکند.', once: `streak-day.${user.id}.${new Date().toDateString()}` });
            }
          });
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [user, celebrate]);
  useFocusEffect(load);
  const refresh = usePullRefresh(loading, load);

  if (!user) {
    return (
      <Screen tab>
        <Text style={[styles.title, rtl]}>آمار من</Text>
        <Empty
          icon="chart-column"
          title="پیشرفتت را ببین"
          text="بعد از ورود، روزهای پیاپی مطالعه، درصد پاسخ درست و بخش‌هایی که باید بیشتر کار کنی اینجا نشان داده می‌شود."
          action={<Button label="ورود یا ثبت‌نام" onPress={() => router.push('/login')} style={{ alignSelf: 'stretch' }} />}
        />
      </Screen>
    );
  }
  if (!data) return <Screen tab>{error ? <ErrorState message={error} onRetry={load} /> : <Loading />}</Screen>;

  // This week and the one before, from the year's days (local dates, the week ending today).
  const days = data.year?.days ?? [];
  const sumSince = (from: number, to: number, k: 'seconds' | 'answers' | 'sections') =>
    days.filter((d) => {
      const ago = Math.round((Date.parse(todayKey()) - Date.parse(d.date)) / 86_400_000);
      return ago >= from && ago < to;
    }).reduce((n, d) => n + (d[k] ?? 0), 0);
  const week = { seconds: sumSince(0, 7, 'seconds'), answers: sumSince(0, 7, 'answers'), sections: sumSince(0, 7, 'sections') };
  const before = { seconds: sumSince(7, 14, 'seconds'), answers: sumSince(7, 14, 'answers'), sections: sumSince(7, 14, 'sections') };
  const up = (a: number, b: number) => (a === b || (!a && !b) ? null : a > b);
  const insights = buildInsights(data, week, before);
  const trend = trendDays(days, data.year?.since);
  const wide = width >= 1000;

  const main = (
    <>
      <InsightCards items={insights} />
      <View style={{ height: 20 }} />
      <Section icon="gauge" title="در یک نگاه" help={HELP.glance}>
        <View style={styles.tiles}>
          <Glance accent icon="flame" label="روز پشت‌سرهم" value={data.streak_days} />
          <Glance icon="target" label="دقت تست‌ها" value={data.accuracy} format={(n) => `${toPersianDigits(Math.round(n))}٪`} />
          <Glance icon="book-open" label="بخش خوانده‌شده" value={data.sections_done} />
          <Glance icon="circle-check" label="تست زده‌شده" value={data.answers} />
          <Glance icon="layers" label="کارت به‌خاطرسپرده" value={data.cards_mastered} />
          <Glance icon="trophy" label="آزمون داده‌شده" value={data.exams} />
        </View>
      </Section>
      <Section icon="calendar" title="این هفته" help={HELP.week}>
        <WeekCard
          seconds={week.seconds}
          rows={[
            { label: 'زمان', now: week.seconds ? studyDuration(week.seconds) : '—', up: up(week.seconds, before.seconds) },
            { label: 'تست', now: week.answers ? toPersianDigits(week.answers) : '—', up: up(week.answers, before.answers) },
            { label: 'بخش', now: week.sections ? toPersianDigits(week.sections) : '—', up: up(week.sections, before.sections) },
          ]}
        />
      </Section>
      {trend.length > 1 && (
        <Section icon="chart-column" title="روند" help={HELP.trend}>
          <TrendChart days={trend} />
        </Section>
      )}
      {data.year && (
        <Section icon="calendar" title="عادت مطالعه" help={HELP.year}>
          <View style={styles.card}>
            <YearGrid days={data.year.days} longest={data.year.longest_streak} studyDays={data.study_days} />
          </View>
        </Section>
      )}
      {!!data.time && data.time.seconds >= 60 && (
        <Section icon="time-spent" title="زمان مطالعه" help={HELP.time}>
          <StudyTimeCard time={data.time} />
        </Section>
      )}
    </>
  );
  const side = (
    <>
      {data.books.length > 0 ? (
        <Section icon="library-big" title="کتاب‌ها" help={HELP.books}>
          <View style={styles.card}>
            {data.books.map((b) => {
              const pct = b.total ? Math.round((b.done / b.total) * 100) : 0;
              const words = data.words?.find((w) => w.slug === b.slug);
              return (
                <Pressable key={b.slug} onPress={() => router.push(`/book/${b.slug}`)} style={{ gap: 6 }}>
                  <View style={{ flexDirection: 'row-reverse', justifyContent: 'space-between', gap: 8 }}>
                    <Text style={[styles.bookTitle, rtl, { flex: 1 }]} numberOfLines={1}>{b.title}</Text>
                    <Text style={styles.muted}>
                      {toPersianDigits(b.done)} از {toPersianDigits(b.total)} بخش ({toPersianDigits(pct)}٪)
                    </Text>
                  </View>
                  <View style={styles.progressTrack}>
                    <View style={[styles.progressFill, { width: `${pct}%` }]} />
                  </View>
                  {!!words && (
                    <Text style={[styles.muted, rtl]}>
                      {toPersianDigits(words.learned)} از {toPersianDigits(words.total)} لغت حفظ شده
                    </Text>
                  )}
                </Pressable>
              );
            })}
          </View>
        </Section>
      ) : (
        <Invite icon="library-big" title="کتاب‌ها" text="اولین بخش یک کتاب را بخوان تا پیشرفتش این‌جا بیاید." />
      )}
      {!!data.improvement && data.improvement.wrong > 0 && (
        <Section icon="repeat" title="اشتباه‌هایی که جبران کردی" help={HELP.improvement}>
          <View style={styles.card}>
            <Text style={[styles.better, rtl]}>
              از {toPersianDigits(data.improvement.wrong)} تستی که در {toPersianDigits(data.improvement.days)} روز گذشته غلط زدی،{' '}
              {toPersianDigits(data.improvement.fixed)} تا را بعداً درست جواب دادی و {toPersianDigits(data.improvement.settled)} تا تثبیت شد.
            </Text>
            <View style={styles.progressTrack}>
              <View style={[styles.progressFill, { width: `${Math.round((data.improvement.settled / data.improvement.wrong) * 100)}%` }]} />
              <View style={[styles.progressPart, { width: `${Math.round(((data.improvement.fixed - data.improvement.settled) / data.improvement.wrong) * 100)}%` }]} />
            </View>
            <Text style={[styles.muted, rtl]}>سبز: تثبیت‌شده؛ زرد: یک بار درست زده‌ای.</Text>
          </View>
        </Section>
      )}
      {data.weak_sections.length > 0 && (
        <Section icon="target" title="تمرکزم کجا باشد؟" help={HELP.focus}>
          <View style={styles.card}>
            {data.weak_sections.map((w) => (
              <Pressable key={w.id} onPress={() => router.push(`/quiz/${w.id}`)} style={styles.weak}>
                <Text style={[styles.bookTitle, rtl, { flex: 1 }]}>{w.title}</Text>
                <Text style={[styles.muted, { color: colors.redDark }]}>{toPersianDigits(w.accuracy)}٪ درست</Text>
              </Pressable>
            ))}
          </View>
        </Section>
      )}
      {exams && exams.summary.count > 0 ? (
        <Section icon="trophy" title="آزمون‌ها" help={HELP.exams}>
          <ExamsCard exams={exams} />
        </Section>
      ) : (
        <Invite icon="trophy" title="آزمون‌ها" text="اولین آزمونت را بده تا این‌جا پر شود." />
      )}
    </>
  );

  return (
    <Screen tab>
      <ScrollView contentContainerStyle={styles.page} refreshControl={refresh}>
        <Text style={[styles.title, rtl, { paddingHorizontal: 0, paddingTop: 0, marginTop: -4, marginBottom: 12 }]}>آمار من</Text>
        {wide ? (
          <View style={{ flexDirection: 'row-reverse', gap: 28, alignItems: 'flex-start' }}>
            <View style={{ flex: 3 }}>{main}</View>
            <View style={{ flex: 2 }}>{side}</View>
          </View>
        ) : (
          <>
            {main}
            {side}
          </>
        )}
      </ScrollView>
    </Screen>
  );
}

/** A section with nothing yet: one line that invites, instead of an empty card. */
function Invite({ icon, title, text }: { icon: IconName; title: string; text: string }) {
  return (
    <Section icon={icon} title={title}>
      <Text style={[styles.muted, rtl, { fontSize: 13 }]}>{text}</Text>
    </Section>
  );
}

const HELP = {
  glance: 'روز پشت‌سرهم: چند روز پیاپی تا امروز درس خوانده‌ای (خواندن، تست یا فلش‌کارت). دقت تست‌ها: درصد پاسخ‌های درست در تمرین و آزمون. کارت به‌خاطرسپرده: فلش‌کارتی که به جعبه‌ی ۴ یا بالاتر رسیده است.',
  week: 'هفت روز اخیر، تا امروز. فلش‌ها نسبت به هفت روز پیش از آن است. هدف هفتگی را خودت می‌گذاری: حلقه را بزن.',
  trend: 'هر ستون یک روز است، از اولین روز مطالعه تا امروز (امروز سمت چپ). با دکمه‌های بالا انتخاب کن ستون‌ها چه را نشان دهند. روی هر روز بزن تا عددهایش را ببینی.',
  year: 'هر مربع یک روز از یک سال اخیر است؛ هر ستون یک هفته (شنبه بالا). هر چه بیشتر خوانده باشی، رنگ پررنگ‌تر است. خط‌های نازک مرز ماه‌هاست.',
  time: 'زمانی که در اپ درس خوانده‌ای. وقتی دو دقیقه به صفحه دست نزنی، شمردن می‌ایستد.',
  books: 'بخشی خوانده‌شده حساب می‌شود که تا آخرش رفته باشی. فقط بخش‌های منتشرشده‌ی فعلی کتاب شمرده می‌شوند؛ تست‌ها و فلش‌کارت‌ها جدا حساب می‌شوند.',
  improvement: 'تست‌هایی که غلط زدی و بعداً درست جواب دادی. «تثبیت‌شده» یعنی چند روز بعد هم باز درست زده‌ای.',
  focus: 'بخش‌هایی که درصد پاسخ درستت در آن‌ها کمتر است. بزن تا تست‌هایش را تمرین کنی.',
  exams: 'آزمون‌های زمان‌دار و نمره‌هایشان، با نمره‌ی منفی.',
};

function todayKey() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

/** Every day from the first day of study to today (days without study are zero), oldest first. */
function trendDays(days: { date: string; seconds: number; answers: number; sections: number }[], since?: string): TrendDay[] {
  if (!days.length) return [];
  const by = new Map(days.map((d) => [d.date, d]));
  const first = [...days].map((d) => d.date).sort()[0] ?? since;
  const out: TrendDay[] = [];
  const end = new Date(`${todayKey()}T12:00:00`);
  for (let t = new Date(`${first}T12:00:00`); t <= end; t = new Date(t.getTime() + 86_400_000)) {
    const k = `${t.getFullYear()}-${String(t.getMonth() + 1).padStart(2, '0')}-${String(t.getDate()).padStart(2, '0')}`;
    const d = by.get(k);
    out.push({ date: k, seconds: d?.seconds ?? 0, answers: d?.answers ?? 0, sections: d?.sections ?? 0 });
  }
  return out;
}

function buildInsights(data: Stats, week: { seconds: number; answers: number }, before: { seconds: number; answers: number }): Insight[] {
  const out: Insight[] = [];
  const f = data.insights?.forecast?.[0];
  if (f) {
    const [month, day] = jalaliMonthDay(f.finish_on);
    out.push({
      key: 'forecast',
      kicker: 'پیش‌بینی',
      text: (
        <>
          با سرعت دو هفته‌ی اخیر، «{f.title}» <Strong>{`${toPersianDigits(day)} ${month}`}</Strong> تمام می‌شود.
        </>
      ),
    });
  }
  if (before.seconds >= 600 && week.seconds !== before.seconds) {
    const pct = Math.round((Math.abs(week.seconds - before.seconds) / before.seconds) * 100);
    out.push({
      key: 'week',
      kicker: 'این هفته',
      text:
        week.seconds > before.seconds ? (
          <>این هفته <Strong>{`${toPersianDigits(pct)}٪`}</Strong> بیشتر از هفته‌ی قبل خواندی. ▲</>
        ) : (
          <>این هفته {toPersianDigits(pct)}٪ کمتر از هفته‌ی قبل خواندی؛ <Strong>امروز</Strong> جبرانش کن.</>
        ),
    });
  }
  const b = data.insights?.best_hours;
  if (b) {
    out.push({
      key: 'hours',
      kicker: 'بهترین ساعت',
      text: (
        <>
          بیشتر تست‌هایت را بین <Strong>{`${toPersianDigits(b.from)} تا ${toPersianDigits(b.to)}`}</Strong> می‌زنی.
        </>
      ),
    });
  }
  if (data.streak_days >= 2) {
    out.push({ key: 'streak', kicker: 'زنجیره', text: <><Strong>{`${toPersianDigits(data.streak_days)} روز`}</Strong> پشت‌سرهم درس خوانده‌ای؛ امروز هم بخوان.</> });
  }
  return out;
}

const KIND_LABEL: [StudyKindName, string][] = [
  ['read', 'جزوه'],
  ['quiz', 'تست'],
  ['cards', 'فلش‌کارت'],
  ['review', 'مرور'],
  ['exam', 'آزمون'],
];

/** «زمان مطالعه»: the totals and what the time went to (the days themselves are in «روند»). */
function StudyTimeCard({ time }: { time: StudyTimeTotals }) {
  const kinds = KIND_LABEL.filter(([k]) => (time.by_kind[k] ?? 0) >= 60);
  const total = Math.max(1, kinds.reduce((n, [k]) => n + (time.by_kind[k] ?? 0), 0));
  return (
    <View style={styles.card}>
      <Text style={[styles.better, rtl]}>
        این هفته {studyDuration(time.week_seconds)}؛ تا الان روی هم {studyDuration(time.seconds)}
      </Text>
      {kinds.length > 0 && (
        <View style={styles.split}>
          {kinds.map(([k], i) => (
            <View key={k} style={{ flex: (time.by_kind[k] ?? 0) / total, backgroundColor: SPLIT[i % SPLIT.length] }} />
          ))}
        </View>
      )}
      {kinds.length > 0 && (
        <View style={{ flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 10 }}>
          {kinds.map(([k, label], i) => (
            <View key={k} style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 4 }}>
              <View style={{ width: 8, height: 8, borderRadius: 2, backgroundColor: SPLIT[i % SPLIT.length] }} />
              <Text style={styles.muted}>{label}: {studyDuration(time.by_kind[k] ?? 0)}</Text>
            </View>
          ))}
        </View>
      )}
    </View>
  );
}

const SPLIT = [colors.lemon, colors.green, SECOND, '#E9D98F', '#C8D3CB'];

const styles = StyleSheet.create({
  title: { fontSize: 22, fontWeight: '800', color: colors.ink, paddingHorizontal: 16, paddingTop: 12 },
  page: { padding: 16, gap: 14 },
  tiles: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 10 },
  bookTitle: { fontSize: 15, fontWeight: '700', color: colors.ink },
  muted: { fontSize: 12, color: colors.muted },
  progressTrack: { height: 8, backgroundColor: colors.line, borderRadius: 4, overflow: 'hidden', flexDirection: 'row-reverse' },
  progressFill: { backgroundColor: colors.green, borderRadius: 4 },
  progressPart: { backgroundColor: colors.lemon },
  card: { backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 14, gap: 10 },
  split: { flexDirection: 'row-reverse', height: 10, borderRadius: 5, overflow: 'hidden' },
  better: { fontSize: 15, color: colors.ink, lineHeight: 24 },
  weak: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, paddingVertical: 6 },
});
