/**
 * «روزهای مطالعه»: a year of study as a grid of days, like GitHub's — one square per day, a column per week
 * (Saturday at the top), from the oldest week on the right to this week on the left. The more done that day,
 * the deeper the lemon yellow. Tap (or point at) a day to see what was done. On a phone the grid scrolls sideways
 * and opens on the latest weeks.
 */
import { useMemo, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View, useWindowDimensions } from 'react-native';

import { colors, rtl, toPersianDigits } from '../theme';
import { jalaliMonthDay } from '../lib/jalali';
import { WIDE } from '../lib/layout';
import { Text } from './Text';

type Day = { date: string; sections: number; answers: number; cards: number; seconds: number };

const SHADES = ['#ECEEE6', '#FBEFAE', '#F8DC5C', '#F2C200', '#C99A00'];
const WEEKS = 53;
const ROW_NAMES = ['ش', '', 'د', '', 'چ', '', 'ج']; // Saturday … Friday

function key(d: Date): string {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function score(d: Day | undefined): number {
  if (!d) return 0;
  return d.sections * 3 + d.answers + d.cards * 0.5 + d.seconds / 60;
}

function describe(date: Date, d: Day | undefined): string {
  const [month, day] = jalaliMonthDay(date);
  const head = `${toPersianDigits(day)} ${month}`;
  if (!d || score(d) === 0) return `${head}: مطالعه‌ای ثبت نشده`;
  const parts = [
    d.seconds >= 60 && `${toPersianDigits(Math.round(d.seconds / 60))} دقیقه`,
    d.sections > 0 && `${toPersianDigits(d.sections)} بخش`,
    d.answers > 0 && `${toPersianDigits(d.answers)} تست`,
    d.cards > 0 && `${toPersianDigits(d.cards)} کارت`,
  ].filter(Boolean);
  return `${head}: ${parts.join('، ')}`;
}

export function YearGrid({ days, longest, studyDays }: { days: Day[]; longest: number; studyDays: number }) {
  const { width } = useWindowDimensions();
  const cell = width >= WIDE ? 12 : 13;
  const gap = 3;
  const [picked, setPicked] = useState<string | null>(null);

  const { weeks, byDate, max, inYear } = useMemo(() => {
    const byDate = new Map(days.map((d) => [d.date, d]));
    const today = new Date();
    today.setHours(12, 0, 0, 0);
    // The column of this week starts on the last Saturday (getDay() 6).
    const thisSaturday = new Date(today);
    thisSaturday.setDate(today.getDate() - ((today.getDay() + 1) % 7));
    const weeks: { start: Date; cells: (Date | null)[]; month: string | null }[] = [];
    let lastMonth = '';
    for (let w = WEEKS - 1; w >= 0; w--) {
      const start = new Date(thisSaturday);
      start.setDate(thisSaturday.getDate() - w * 7);
      const cells: (Date | null)[] = [];
      for (let i = 0; i < 7; i++) {
        const d = new Date(start);
        d.setDate(start.getDate() + i);
        cells.push(d > today ? null : d);
      }
      const [month] = jalaliMonthDay(start);
      weeks.push({ start, cells, month: month !== lastMonth ? month : null });
      lastMonth = month;
    }
    weeks[0].month = null; // a half month at the start says nothing
    const max = Math.max(1, ...days.map(score));
    const inYear = days.filter((d) => score(d) > 0).length;
    return { weeks, byDate, max, inYear };
  }, [days]);

  const level = (d: Day | undefined) => {
    const s = score(d);
    return s <= 0 ? 0 : Math.min(4, Math.ceil((s / max) * 4));
  };
  const pickedDay = picked ? byDate.get(picked) : undefined;
  const latest = key(new Date());

  return (
    <View style={{ gap: 10 }}>
      <View style={styles.wrap}>
        <View style={[styles.rowNames, { gap, paddingTop: 18 }]}>
          {ROW_NAMES.map((n, i) => (
            <Text key={i} style={[styles.rowName, { height: cell, lineHeight: cell }]}>{n}</Text>
          ))}
        </View>
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ flex: 1 }} contentContainerStyle={{ flexGrow: 1, justifyContent: 'flex-end' }}>
          {/* Oldest week on the right, this week on the left; a phone's scroller starts at the left, so it opens on now. */}
          <View style={{ flexDirection: 'row-reverse', gap }}>
            {weeks.map((w) => (
              // A thin line where a month starts (the older weeks are on its right).
              <View key={key(w.start)} style={[{ gap }, !!w.month && styles.monthStart]}>
                {/* The month's name hangs over the next columns without widening this one. */}
                <View style={{ width: cell, height: 15, overflow: 'visible' }}>
                  {!!w.month && <Text style={styles.month}>{w.month}</Text>}
                </View>
                {w.cells.map((d, i) => {
                  if (!d) return <View key={i} style={{ width: cell, height: cell }} />;
                  const k = key(d);
                  const day = byDate.get(k);
                  return (
                    <Pressable
                      key={i}
                      onPress={() => setPicked(k)}
                      onHoverIn={() => setPicked(k)}
                      accessibilityLabel={describe(d, day)}
                      style={[
                        styles.cell,
                        { width: cell, height: cell, backgroundColor: SHADES[level(day)] },
                        (picked === k || (!picked && k === latest)) && styles.cellOn,
                      ]}
                    />
                  );
                })}
              </View>
            ))}
          </View>
        </ScrollView>
      </View>

      <Text style={[styles.info, rtl]}>{describe(picked ? new Date(`${picked}T12:00:00`) : new Date(), picked ? pickedDay : byDate.get(latest))}</Text>
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
    </View>
  );
}

const styles = StyleSheet.create({
  wrap: { flexDirection: 'row-reverse', gap: 6 },
  rowNames: { width: 14 },
  rowName: { fontSize: 10, color: colors.muted, textAlign: 'center' },
  month: { position: 'absolute', right: 0, width: 56, maxWidth: 56, fontSize: 10, color: colors.muted, textAlign: 'right', flexWrap: 'nowrap' },
  cell: { borderRadius: 3 },
  monthStart: { borderRightWidth: 1, borderRightColor: '#CBD3C6', paddingRight: 2, marginRight: -1 },
  cellOn: { borderWidth: 1.5, borderColor: colors.ink },
  info: { fontSize: 13, color: colors.ink },
  foot: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', flexWrap: 'wrap', gap: 8 },
  legend: { flexDirection: 'row-reverse', alignItems: 'center', gap: 3 },
  muted: { fontSize: 11, color: colors.muted },
});
