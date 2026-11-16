/**
 * «عادت مطالعه»: a year of study as a grid of days, like GitHub's — one square per day, a column per week
 * (Saturday at the top), from the oldest week on the right to this week on the left. The more done that day,
 * the deeper the lemon yellow. A dot marks a day with an exam, a gold frame the longest run of days in a row, a dark
 * frame today. Tap (or point at) a day: its details show in the line under the grid. When the whole year fits (a
 * computer), the squares shrink to fit; on a phone the grid scrolls sideways and opens on the latest weeks.
 */
import { type ReactNode, useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { colors, rtl, toPersianDigits } from '../theme';
import { jalaliMonthDay } from '../lib/jalali';
import { studyDuration } from '../lib/duration';
import { Text } from './Text';

type Day = { date: string; sections: number; answers: number; correct?: number; cards: number; exams?: number; seconds: number };

const SHADES = ['#ECEEE6', '#FBEFAE', '#F8DC5C', '#F2C200', '#C99A00'];
const WEEKS = 53;
const ROW_NAMES = ['ش', '', 'د', '', 'چ', '', 'ج']; // Saturday … Friday
const NAMES_W = 14;
const MONTH_LINE = 2; // extra width a month's first column takes for its line

function key(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function score(d: Day | undefined): number {
  if (!d) return 0;
  return d.sections * 3 + d.answers + d.cards * 0.5 + d.seconds / 60 + (d.exams ?? 0) * 5;
}

export function YearGrid({
  days,
  longest,
  longestFrom,
  longestTo,
  studyDays,
}: {
  days: Day[];
  longest: number;
  longestFrom?: string | null;
  longestTo?: string | null;
  studyDays: number;
}) {
  const [boxW, setBoxW] = useState(0);
  const [picked, setPicked] = useState<string | null>(null);
  // The whole year in the box when the squares can stay 9 px or more; otherwise 13 px and a scroll.
  const fitGap = 2;
  const fit = boxW ? Math.floor((boxW - NAMES_W - 6 - (WEEKS - 1) * fitGap - 12 * MONTH_LINE) / WEEKS) : 0;
  const fits = fit >= 9;
  const cell = fits ? Math.min(14, fit) : 13;
  const gap = fits ? fitGap : 3;

  const { weeks, months, byDate, max, inYear } = useMemo(() => {
    const byDate = new Map(days.map((d) => [d.date, d]));
    const today = new Date();
    today.setHours(12, 0, 0, 0);
    // The column of this week starts on the last Saturday (getDay() 6).
    const thisSaturday = new Date(today);
    thisSaturday.setDate(today.getDate() - ((today.getDay() + 1) % 7));
    const weeks: { start: Date; cells: (Date | null)[]; month: string; first: boolean }[] = [];
    for (let w = WEEKS - 1; w >= 0; w--) {
      const start = new Date(thisSaturday);
      start.setDate(thisSaturday.getDate() - w * 7);
      const cells: (Date | null)[] = [];
      for (let i = 0; i < 7; i++) {
        const d = new Date(start);
        d.setDate(start.getDate() + i);
        cells.push(d > today ? null : d);
      }
      // A week belongs to the month of its Wednesday (its middle day).
      const mid = new Date(start);
      mid.setDate(start.getDate() + 4);
      const [month] = jalaliMonthDay(mid);
      weeks.push({ start, cells, month, first: !weeks.length || weeks[weeks.length - 1].month !== month });
    }
    weeks[0].first = false; // no line at the very edge
    // Runs of weeks per month, oldest first, for the names centred over them.
    const months: { name: string; weeks: number; line: boolean }[] = [];
    for (const w of weeks) {
      const last = months[months.length - 1];
      if (last && last.name === w.month) last.weeks++;
      else months.push({ name: w.month, weeks: 1, line: w.first });
    }
    const max = Math.max(1, ...days.map(score));
    const inYear = days.filter((d) => score(d) > 0).length;
    return { weeks, months, byDate, max, inYear };
  }, [days]);

  const level = (d: Day | undefined) => {
    const s = score(d);
    return s <= 0 ? 0 : Math.min(4, Math.ceil((s / max) * 4));
  };
  const todayKey = key(new Date());
  const inRun = (k: string) => !!longestFrom && !!longestTo && k >= longestFrom && k <= longestTo;

  const describe = (k: string) => {
    const d = byDate.get(k);
    const [month, day] = jalaliMonthDay(new Date(`${k}T12:00:00`));
    const head = `${toPersianDigits(day)} ${month}${k === todayKey ? ' (امروز)' : ''}`;
    const tags = inRun(k) ? `؛ از طولانی‌ترین زنجیره (${toPersianDigits(longest)} روز)` : '';
    if (!d || score(d) === 0) return `${head}: مطالعه‌ای ثبت نشده${tags}`;
    const right = d.answers && d.correct != null ? ` (${toPersianDigits(Math.round((d.correct / d.answers) * 100))}٪ درست)` : '';
    const parts = [
      d.seconds >= 60 && studyDuration(d.seconds),
      d.sections > 0 && `${toPersianDigits(d.sections)} بخش`,
      d.answers > 0 && `${toPersianDigits(d.answers)} تست${right}`,
      d.cards > 0 && `${toPersianDigits(d.cards)} کارت`,
      !!d.exams && `${toPersianDigits(d.exams)} آزمون`,
    ].filter(Boolean);
    return `${head}: ${parts.join('، ')}${tags}`;
  };

  const grid = (
    <View style={{ gap: 3 }}>
      {/* Month names, each centred over its weeks; a month with fewer than three weeks here gets none. */}
      <View style={{ flexDirection: 'row-reverse', height: 14 }}>
        {months.map((m, i) => (
          <View key={i} style={{ width: m.weeks * (cell + gap) + (m.line ? MONTH_LINE : 0), alignItems: 'center' }}>
            {m.weeks >= 3 && <Text style={styles.month} numberOfLines={1}>{m.name}</Text>}
          </View>
        ))}
      </View>
      <View style={{ flexDirection: 'row-reverse', gap }}>
        {weeks.map((w) => (
          // A thin line where a month starts (the older weeks are on its right).
          <View key={key(w.start)} style={[{ gap }, w.first && styles.monthStart]}>
            {w.cells.map((d, i) => {
              if (!d) return <View key={i} style={{ width: cell, height: cell }} />;
              const k = key(d);
              const day = byDate.get(k);
              return (
                <Pressable
                  key={i}
                  onPress={() => setPicked(k)}
                  onHoverIn={() => setPicked(k)}
                  accessibilityLabel={describe(k)}
                  style={[
                    styles.cell,
                    { width: cell, height: cell, backgroundColor: SHADES[level(day)] },
                    inRun(k) && styles.cellRun,
                    k === todayKey && styles.cellToday,
                    picked === k && styles.cellOn,
                  ]}
                >
                  {!!day?.exams && <View style={styles.exam} />}
                </Pressable>
              );
            })}
          </View>
        ))}
      </View>
    </View>
  );

  return (
    <View style={{ gap: 10 }} onLayout={(e) => setBoxW(e.nativeEvent.layout.width)}>
      <View style={styles.wrap}>
        <View style={[styles.rowNames, { gap, paddingTop: 17 }]}>
          {ROW_NAMES.map((n, i) => (
            <Text key={i} style={[styles.rowName, { height: cell, lineHeight: cell }]}>{n}</Text>
          ))}
        </View>
        {fits ? (
          grid
        ) : (
          // Oldest week on the right, this week on the left; a phone's scroller starts at the left, so it opens on now.
          <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flex: 1 }}>
            {grid}
          </ScrollView>
        )}
      </View>

      {/* Two lines kept for the details, so the card does not jump as the pointer moves. */}
      <Text style={[styles.info, rtl]} numberOfLines={2}>{describe(picked ?? todayKey)}</Text>
      <View style={styles.foot}>
        <Text style={[styles.muted, rtl]}>
          {toPersianDigits(inYear)} روز مطالعه در یک سال گذشته؛ طولانی‌ترین زنجیره: {toPersianDigits(longest)} روز
          {studyDays > inYear ? `؛ همه‌ی روزها: ${toPersianDigits(studyDays)}` : ''}
        </Text>
        <View style={styles.legend}>
          <Text style={styles.muted}>کم</Text>
          {SHADES.map((c) => (
            <View key={c} style={[styles.cell, { width: 11, height: 11, backgroundColor: c }]} />
          ))}
          <Text style={styles.muted}>زیاد</Text>
        </View>
      </View>
      {/* What the marks mean, each with a real sample square. */}
      <View style={styles.key}>
        <KeyItem label="آزمون" sample={<View style={[styles.cell, styles.sample, { backgroundColor: SHADES[2] }]}><View style={styles.exam} /></View>} />
        <KeyItem label="طولانی‌ترین زنجیره" sample={<View style={[styles.cell, styles.sample, styles.cellRun, { backgroundColor: SHADES[1] }]} />} />
        <KeyItem label="امروز" sample={<View style={[styles.cell, styles.sample, styles.cellToday, { backgroundColor: SHADES[0] }]} />} />
        <KeyItem label="روز انتخاب‌شده" sample={<View style={[styles.cell, styles.sample, styles.cellOn, { backgroundColor: SHADES[3] }]} />} />
      </View>
    </View>
  );
}

function KeyItem({ label, sample }: { label: string; sample: ReactNode }) {
  return (
    <View style={styles.keyItem}>
      {sample}
      <Text style={styles.muted}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  key: { flexDirection: 'row-reverse', flexWrap: 'wrap', columnGap: 14, rowGap: 6 },
  keyItem: { flexDirection: 'row-reverse', alignItems: 'center', gap: 5 },
  sample: { width: 13, height: 13 },
  wrap: { flexDirection: 'row-reverse', gap: 6 },
  rowNames: { width: NAMES_W },
  rowName: { fontSize: 10, color: colors.muted, textAlign: 'center' },
  month: { fontSize: 10, color: colors.muted },
  cell: { borderRadius: 3, alignItems: 'center', justifyContent: 'center' },
  monthStart: { borderRightWidth: 1, borderRightColor: '#CBD3C6', paddingRight: MONTH_LINE - 1 },
  cellRun: { borderWidth: 1.5, borderColor: '#B98A00' },
  cellToday: { borderWidth: 1.5, borderColor: colors.ink },
  cellOn: { borderWidth: 2, borderColor: colors.greenDark },
  exam: { width: 4, height: 4, borderRadius: 2, backgroundColor: colors.ink },
  info: { fontSize: 13, color: colors.ink, minHeight: 40, lineHeight: 20 },
  foot: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  legend: { flexDirection: 'row-reverse', alignItems: 'center', gap: 3 },
  muted: { fontSize: 11, color: colors.muted },
});
