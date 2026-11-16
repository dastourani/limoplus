/** Pieces of the stats page (and the home page): a section title with its «؟», numbers that count up, the paging
 *  insight cards, the weekly ring and the trend chart. Colours stay within the app's own: lemon first, the app's
 *  green for what went well, a quiet grey-green for a second series, red only for a fall. */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { type ReactNode, useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, Pressable, ScrollView, StyleSheet, useWindowDimensions, View } from 'react-native';
import Svg, { Circle, Line, Polyline, Rect, Text as SvgText } from 'react-native-svg';

import { jalaliMonthDay } from '../../lib/jalali';
import { studyDuration } from '../../lib/duration';
import { colors, rtl, toPersianDigits } from '../../theme';
import { IconBadge, type IconName } from '../Icon';
import { Text } from '../Text';
import { HelpTip } from '../HelpTip';
import { Sheet } from '../ui';

export const SECOND = '#9BB0A0'; // the quiet second series (grey-green)

/** Reduce motion on the phone: numbers and bars appear without moving. */
export function useReducedMotion() {
  const [reduce, setReduce] = useState(false);
  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then(setReduce).catch(() => undefined);
  }, []);
  return reduce;
}

/** A section of the page: its title outside the card (icon in a lemon circle), «؟» opens a short explanation. */
export function Section({ icon, title, help, side, children }: { icon: IconName; title: string; help?: string; side?: ReactNode; children: ReactNode }) {
  return (
    <View style={styles.section}>
      <View style={styles.head}>
        <IconBadge name={icon} size={30} />
        <Text style={[styles.title, rtl]}>{title}</Text>
        <View style={{ flex: 1 }} />
        {side}
        {!!help && <HelpTip title={title} text={help} size={26} />}
      </View>
      {children}
    </View>
  );
}

/** A number that counts up from zero once, when it first shows (still when motion is reduced). */
export function CountUp({ value, format = (n) => toPersianDigits(Math.round(n)), style }: { value: number; format?: (n: number) => string; style?: object }) {
  const reduce = useReducedMotion();
  const [shown, setShown] = useState(reduce ? value : 0);
  const anim = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    if (reduce || !value) {
      setShown(value);
      return;
    }
    const id = anim.addListener(({ value: v }) => setShown(v * value));
    anim.setValue(0);
    Animated.timing(anim, { toValue: 1, duration: 700, easing: Easing.out(Easing.cubic), useNativeDriver: false }).start();
    return () => anim.removeListener(id);
  }, [value, reduce, anim]);
  return <Text style={style}>{format(shown)}</Text>;
}

/** One small card of «در یک نگاه». */
export function Glance({ icon, label, value, format, accent }: { icon: IconName; label: string; value: number | null; format?: (n: number) => string; accent?: boolean }) {
  return (
    <View style={[styles.glance, accent && { backgroundColor: colors.ink, borderColor: colors.ink }]}>
      <IconBadge name={icon} size={28} />
      {value === null ? (
        <Text style={[styles.glanceValue, accent && { color: colors.lemon }]}>—</Text>
      ) : (
        <CountUp value={value} format={format} style={[styles.glanceValue, accent && { color: colors.lemon }]} />
      )}
      <Text style={[styles.glanceLabel, accent && { color: '#C9D0C6' }]}>{label}</Text>
    </View>
  );
}

export type Insight = { key: string; kicker: string; text: ReactNode };

/** «کارت‌های بینش»: one at a time, swiped sideways, dots below; the first one changes from day to day. */
export function InsightCards({ items }: { items: Insight[] }) {
  const { width } = useWindowDimensions();
  const [w, setW] = useState(Math.min(width, 760) - 32);
  const [index, setIndex] = useState(0);
  if (!items.length) return null;
  const day = Math.floor(Date.now() / 86_400_000);
  const ordered = items.map((_, i) => items[(i + day) % items.length]);
  return (
    <View onLayout={(e) => setW(e.nativeEvent.layout.width)}>
      <ScrollView
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onMomentumScrollEnd={(e) => setIndex(Math.round(Math.abs(e.nativeEvent.contentOffset.x) / Math.max(1, w)))}
        onScroll={(e) => setIndex(Math.round(Math.abs(e.nativeEvent.contentOffset.x) / Math.max(1, w)))}
        scrollEventThrottle={64}
      >
        {ordered.map((it) => (
          <View key={it.key} style={[styles.insight, { width: w }]}>
            <Text style={[styles.kicker, rtl]}>{it.kicker}</Text>
            <Text style={[styles.insightText, rtl]}>{it.text}</Text>
          </View>
        ))}
      </ScrollView>
      {ordered.length > 1 && (
        <View style={styles.dots}>
          {ordered.map((it, i) => (
            <View key={it.key} style={[styles.dot, i === index && styles.dotOn]} />
          ))}
        </View>
      )}
    </View>
  );
}

/** Highlighted part of an insight sentence. */
export function Strong({ children }: { children: ReactNode }) {
  return <Text style={styles.strong}>{children}</Text>;
}

const GOAL_KEY = 'limo.weekGoalMinutes';
const GOALS = [60, 120, 180, 300, 420, 600];

/** «این هفته»: a lemon ring filling towards the learner's own weekly goal (tap to change it), and three numbers
 *  against the week before. */
export function WeekCard({ seconds, rows }: { seconds: number; rows: { label: string; now: string; up: boolean | null }[] }) {
  const [goal, setGoal] = useState<number>(180);
  const [choosing, setChoosing] = useState(false);
  useEffect(() => {
    AsyncStorage.getItem(GOAL_KEY).then((v) => v && setGoal(Number(v) || 180)).catch(() => undefined);
  }, []);
  const share = Math.min(1, seconds / 60 / goal);
  const size = 84;
  const stroke = 10;
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  return (
    <View style={styles.card}>
      <View style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 16 }}>
        <Pressable onPress={() => setChoosing(true)} accessibilityRole="button" accessibilityLabel={`هدف هفتگی ${studyDuration(goal * 60)}؛ برای تغییر بزنید`}>
          <Svg width={size} height={size}>
            <Circle cx={size / 2} cy={size / 2} r={r} stroke={colors.line} strokeWidth={stroke} fill="none" />
            <Circle
              cx={size / 2}
              cy={size / 2}
              r={r}
              stroke={colors.lemon}
              strokeWidth={stroke}
              fill="none"
              strokeLinecap="round"
              strokeDasharray={`${c * share} ${c}`}
              transform={`rotate(-90 ${size / 2} ${size / 2})`}
            />
          </Svg>
          <View style={[StyleSheet.absoluteFill, { alignItems: 'center', justifyContent: 'center' }]}>
            <Text style={styles.ringText}>{toPersianDigits(Math.round(share * 100))}٪</Text>
          </View>
        </Pressable>
        <View style={{ flex: 1, gap: 4 }}>
          {rows.map((row) => (
            <View key={row.label} style={styles.weekRow}>
              <Text style={[styles.weekLabel, rtl]}>{row.label}</Text>
              <Text style={styles.weekValue}>{row.now}</Text>
              {row.up !== null && <Text style={{ color: row.up ? colors.green : colors.red, fontSize: 12 }}>{row.up ? '▲' : '▼'}</Text>}
            </View>
          ))}
          <Text style={[styles.muted, rtl]}>هدف هفتگی: {studyDuration(goal * 60)} (برای تغییر، حلقه را بزن)</Text>
        </View>
      </View>
      <Sheet visible={choosing} onClose={() => setChoosing(false)} title="هدف مطالعه در هفته">
        <View style={{ flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 }}>
          {GOALS.map((g) => (
            <Pressable
              key={g}
              onPress={() => {
                setGoal(g);
                AsyncStorage.setItem(GOAL_KEY, String(g)).catch(() => undefined);
                setChoosing(false);
              }}
              style={[styles.goal, g === goal && styles.goalOn]}
            >
              <Text style={styles.goalText}>{studyDuration(g * 60)}</Text>
            </Pressable>
          ))}
        </View>
      </Sheet>
    </View>
  );
}

export type TrendDay = { date: string; seconds: number; answers: number; sections: number };
type Measure = 'seconds' | 'answers' | 'sections';
const MEASURES: [Measure, string][] = [
  ['seconds', 'زمان'],
  ['answers', 'تست'],
  ['sections', 'بخش'],
];

/** «روند»: one bar a day from the first day of study to today, scrolled sideways (opens on today, at the left);
 *  a tap on a day says its numbers. Bars: the chosen measure; the line: tests (or time, when tests are the bars). */
export function TrendChart({ days }: { days: TrendDay[] }) {
  const [measure, setMeasure] = useState<Measure>('seconds');
  const [picked, setPicked] = useState<number | null>(null);
  const reduce = useReducedMotion();
  const grow = useRef(new Animated.Value(reduce ? 1 : 0)).current;
  useEffect(() => {
    if (reduce) return;
    Animated.timing(grow, { toValue: 1, duration: 600, easing: Easing.out(Easing.cubic), useNativeDriver: false }).start();
  }, [grow, reduce]);
  const [scale, setScale] = useState(reduce ? 1 : 0);
  useEffect(() => {
    const id = grow.addListener(({ value }) => setScale(value));
    return () => grow.removeListener(id);
  }, [grow]);

  const lineOf: Measure = measure === 'answers' ? 'seconds' : 'answers';
  const slot = 18;
  const h = 130;
  const top = 10;
  const inner = h - top - 22;
  const peak = Math.max(1, ...days.map((d) => d[measure]));
  const linePeak = Math.max(1, ...days.map((d) => d[lineOf]));
  const width = Math.max(days.length * slot, 1);
  // Newest at the left: day i (oldest first) sits at the right end.
  const x = (i: number) => width - (i + 1) * slot;
  const points = days.map((d, i) => `${x(i) + slot / 2},${top + inner - (inner * d[lineOf]) / linePeak}`).join(' ');
  const show = (d: TrendDay) =>
    `${toPersianDigits(jalaliMonthDay(d.date)[1])} ${jalaliMonthDay(d.date)[0]}: ${studyDuration(d.seconds)}، ${toPersianDigits(d.answers)} تست، ${toPersianDigits(d.sections)} بخش`;
  return (
    <View style={styles.card}>
      <View style={styles.switch}>
        {MEASURES.map(([m, label]) => (
          <Pressable key={m} onPress={() => setMeasure(m)} style={[styles.switchItem, measure === m && styles.switchOn]} accessibilityRole="button" accessibilityState={{ selected: measure === m }}>
            <Text style={[styles.switchText, measure === m && { color: colors.ink }]}>{label}</Text>
          </Pressable>
        ))}
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <Svg width={width} height={h}>
          <Line x1={0} x2={width} y1={top + inner} y2={top + inner} stroke={colors.line} strokeWidth={1} />
          {days.map((d, i) => {
            const bh = (inner * d[measure] * scale) / peak;
            return (
              <Rect
                key={d.date}
                x={x(i) + 3}
                y={top + inner - bh}
                width={slot - 6}
                height={Math.max(bh, d[measure] ? 2 : 0)}
                rx={3}
                fill={picked === i ? colors.greenDark : colors.lemon}
                onPress={() => setPicked(i)}
              />
            );
          })}
          <Polyline points={points} fill="none" stroke={SECOND} strokeWidth={2} strokeLinejoin="round" opacity={scale} />
          {days.map((d, i) => {
            const [month, day] = jalaliMonthDay(d.date);
            if (day !== 1 && i !== days.length - 1) return null;
            return (
              <SvgLabel key={`l${d.date}`} x={x(i) + slot / 2} y={h - 6} text={day === 1 ? month : 'امروز'} />
            );
          })}
        </Svg>
      </ScrollView>
      <Text style={[styles.muted, rtl]}>
        {picked !== null && days[picked] ? show(days[picked]) : `ستون زرد: ${MEASURES.find((m) => m[0] === measure)![1]}؛ خط: ${lineOf === 'answers' ? 'تست' : 'زمان'}. برای روزهای قبل، کنار بکش.`}
      </Text>
    </View>
  );
}

function SvgLabel({ x, y, text }: { x: number; y: number; text: string }) {
  return (
    <SvgText x={x} y={y} fontSize={10} fill={colors.muted} textAnchor="middle" fontFamily="Vazirmatn_400Regular">
      {text}
    </SvgText>
  );
}

const styles = StyleSheet.create({
  section: { gap: 8, marginBottom: 20 },
  head: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  title: { fontSize: 17, fontWeight: '800', color: colors.ink },
  q: { width: 26, height: 26, borderRadius: 13, borderWidth: 1, borderColor: colors.line, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.surface },
  qText: { fontSize: 14, fontWeight: '800', color: colors.muted },
  help: { fontSize: 15, lineHeight: 26, color: colors.ink },
  card: { backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 14, gap: 10 },
  glance: { flexBasis: '30%', minWidth: 140, flexGrow: 1, backgroundColor: colors.surface, borderRadius: 18, padding: 12, borderWidth: 1, borderColor: colors.line, gap: 4, alignItems: 'flex-end' },
  glanceValue: { fontSize: 22, fontWeight: '800', color: colors.ink, textAlign: 'right' },
  glanceLabel: { fontSize: 12, color: colors.muted, textAlign: 'right' },
  insight: { backgroundColor: colors.ink, borderRadius: 18, padding: 18, minHeight: 104, justifyContent: 'center', gap: 4 },
  kicker: { fontSize: 12, color: '#B9C8BE', fontWeight: '700' },
  insightText: { fontSize: 17, color: '#FFFFFF', lineHeight: 28 },
  strong: { color: colors.lemon, fontWeight: '900', fontSize: 20 },
  dots: { flexDirection: 'row-reverse', justifyContent: 'center', gap: 6, marginTop: 8 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.line },
  dotOn: { backgroundColor: colors.lemon, width: 16 },
  ringText: { fontSize: 15, fontWeight: '900', color: colors.ink },
  weekRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
  weekLabel: { fontSize: 13, color: colors.muted, width: 52 },
  weekValue: { fontSize: 15, fontWeight: '800', color: colors.ink },
  muted: { fontSize: 12, color: colors.muted },
  goal: { paddingHorizontal: 14, paddingVertical: 8, borderRadius: 999, borderWidth: 1, borderColor: colors.line },
  goalOn: { backgroundColor: colors.lemonSoft, borderColor: colors.lemon },
  goalText: { fontSize: 14, color: colors.ink },
  switch: { flexDirection: 'row-reverse', alignSelf: 'flex-start', backgroundColor: colors.ground, borderRadius: 10, padding: 3, gap: 2 },
  switchItem: { paddingHorizontal: 12, paddingVertical: 5, borderRadius: 8 },
  switchOn: { backgroundColor: colors.surface },
  switchText: { fontSize: 13, color: colors.muted, fontWeight: '700' },
});
