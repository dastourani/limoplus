/** Pieces of the stats page (and the home page): a section title with its «؟», numbers that count up, the paging
 *  insight cards, the weekly ring and the trend chart. Colours stay within the app's own: lemon first, the app's
 *  green for what went well, a quiet grey-green for a second series, red only for a fall. */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { type ReactNode, type RefObject, useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Dimensions, Platform, Easing, Pressable, ScrollView, StyleSheet, useWindowDimensions, View, type ScrollViewInstance, type ViewInstance } from 'react-native';
import Svg, { Circle, Line, Polyline, Rect, Text as SvgText } from 'react-native-svg';

import { jalaliMonthDay } from '../../lib/jalali';
import { studyDuration } from '../../lib/duration';
import { colors, rtl, toPersianDigits } from '../../theme';
import { Icon, IconBadge, type IconName } from '../Icon';
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

/** Numbers that have already counted up since the app was opened: they show still after that. */
const counted = new Set<string>();

/** Calls back once when the view is (at least partly) on the screen: IntersectionObserver on the web, a light poll of its
 *  place on the screen on a phone (stops as soon as it has been seen). */
function useSeen(ref: RefObject<ViewInstance | null>, active: boolean, onSeen: () => void) {
  useEffect(() => {
    if (!active) return;
    let done = false;
    const fire = () => {
      if (done) return;
      done = true;
      onSeen();
    };
    const node = ref.current as unknown as Element | null;
    if (Platform.OS === 'web' && node && typeof IntersectionObserver !== 'undefined' && node instanceof Element) {
      const io = new IntersectionObserver((entries) => entries.some((e) => e.isIntersecting) && fire(), { threshold: 0.4 });
      io.observe(node);
      return () => io.disconnect();
    }
    const id = setInterval(() => {
      ref.current?.measureInWindow((_x, y, _w, h) => {
        const screen = Dimensions.get('window').height;
        if (h > 0 && y < screen - h * 0.4 && y + h * 0.6 > 0) {
          clearInterval(id);
          fire();
        }
      });
    }, 250);
    return () => {
      done = true;
      clearInterval(id);
    };
    // onSeen is stable enough for one firing; only the switch matters.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [active, ref]);
}

/** A number that counts up from zero in about a second, slowing at the end, the first time it comes into view after
 *  the app was opened (`id` names it; `delay` lets tiles go one after another). Still when motion is reduced. */
export function CountUp({ id, value, delay = 0, format = (n) => toPersianDigits(Math.round(n)), style }: { id?: string; value: number; delay?: number; format?: (n: number) => string; style?: object }) {
  const reduce = useReducedMotion();
  const once = !id || !counted.has(id);
  const animate = once && !reduce && !!value;
  const [shown, setShown] = useState(animate ? 0 : value);
  const anim = useRef(new Animated.Value(0)).current;
  const box = useRef<ViewInstance>(null);
  useEffect(() => {
    if (!animate) setShown(value);
  }, [animate, value]);
  useSeen(box, animate, () => {
    if (id) counted.add(id);
    const listener = anim.addListener(({ value: v }) => setShown(v * value));
    anim.setValue(0);
    Animated.timing(anim, { toValue: 1, duration: 1000, delay, easing: Easing.out(Easing.cubic), useNativeDriver: false }).start(() => {
      anim.removeListener(listener);
      setShown(value);
    });
  });
  return (
    <View ref={box} collapsable={false}>
      <Text style={style}>{format(shown)}</Text>
    </View>
  );
}

/** One small card of «در یک نگاه»; `order` is its place, so the tiles count one after another. */
export function Glance({ icon, label, value, format, accent, order = 0 }: { icon: IconName; label: string; value: number | null; format?: (n: number) => string; accent?: boolean; order?: number }) {
  return (
    <View style={[styles.glance, accent && { backgroundColor: colors.ink, borderColor: colors.ink }]}>
      <IconBadge name={icon} size={28} />
      {value === null ? (
        <Text style={[styles.glanceValue, accent && { color: colors.lemon }]}>—</Text>
      ) : (
        <CountUp id={`glance.${label}`} value={value} delay={order * 150} format={format} style={[styles.glanceValue, accent && { color: colors.lemon }]} />
      )}
      <Text style={[styles.glanceLabel, accent && { color: '#C9D0C6' }]}>{label}</Text>
    </View>
  );
}

export type Insight = { key: string; kicker: string; text: ReactNode };

/** «کارت‌های بینش»: one at a time, turning by itself slowly (like the banners; it waits while a pointer is over it or
 *  a finger has just moved it), swiped sideways or picked with the dots; the first one changes from day to day. */
export function InsightCards({ items }: { items: Insight[] }) {
  const { width } = useWindowDimensions();
  const [w, setW] = useState(Math.min(width, 760) - 32);
  const [index, setIndex] = useState(0);
  const scroller = useRef<ScrollViewInstance>(null);
  const holdUntil = useRef(0);
  const hovering = useRef(false);
  const reduce = useReducedMotion();
  const count = items.length;
  useEffect(() => {
    if (count < 2 || reduce) return;
    const id = setInterval(() => {
      if (hovering.current || Date.now() < holdUntil.current) return;
      setIndex((i) => {
        const next = (i + 1) % count;
        scroller.current?.scrollTo({ x: next * w, animated: true });
        return next;
      });
    }, 7000);
    return () => clearInterval(id);
  }, [count, w, reduce]);
  if (!count) return null;
  const day = Math.floor(Date.now() / 86_400_000);
  const ordered = items.map((_, i) => items[(i + day) % count]);
  const go = (i: number) => {
    holdUntil.current = Date.now() + 15_000;
    setIndex(i);
    scroller.current?.scrollTo({ x: i * w, animated: true });
  };
  return (
    <Pressable
      onLayout={(e) => setW(e.nativeEvent.layout.width)}
      onHoverIn={() => (hovering.current = true)}
      onHoverOut={() => (hovering.current = false)}
      accessible={false}
      style={{ cursor: 'auto' } as object}
    >
      <ScrollView
        ref={scroller}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        onScrollBeginDrag={() => (holdUntil.current = Date.now() + 15_000)}
        onMomentumScrollEnd={(e) => setIndex(Math.round(Math.abs(e.nativeEvent.contentOffset.x) / Math.max(1, w)))}
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
            <Pressable key={it.key} onPress={() => go(i)} hitSlop={8} accessibilityRole="button" accessibilityLabel={`کارت ${toPersianDigits(i + 1)}`}>
              <View style={[styles.dot, i === index && styles.dotOn]} />
            </Pressable>
          ))}
        </View>
      )}
    </Pressable>
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
export function WeekCard({ seconds, rows }: { seconds: number; rows: { label: string; now: string; before: string; up: boolean | null }[] }) {
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
        <Pressable onPress={() => setChoosing(true)} style={{ alignItems: 'center', gap: 4 }} accessibilityRole="button" accessibilityLabel={`${toPersianDigits(Math.round(share * 100))} درصد از هدف هفتگی ${studyDuration(goal * 60)}؛ برای تغییر بزنید`}>
          <View>
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
            <Icon name="target" size={26} color={share >= 1 ? colors.green : colors.muted} />
          </View>
          </View>
          <Text style={styles.ringText}>{toPersianDigits(Math.round(share * 100))}٪ از هدف</Text>
        </Pressable>
        <View style={{ flex: 1, gap: 4 }}>
          <Text style={[styles.muted, rtl, { fontWeight: '700' }]}>در مقایسه با هفته‌ی قبل</Text>
          {rows.map((row) => (
            <View key={row.label} style={styles.weekRow}>
              <Text style={[styles.weekLabel, rtl]}>{row.label}</Text>
              <View style={{ flex: 1, alignItems: 'flex-end' }}>
                <View style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 6 }}>
                  <Text style={styles.weekValue}>{row.now}</Text>
                  {row.up !== null && <Text style={{ color: row.up ? colors.green : colors.red, fontSize: 12 }}>{row.up ? '▲' : '▼'}</Text>}
                </View>
                <Text style={[styles.weekBefore, rtl]}>هفته‌ی قبل {row.before}</Text>
              </View>
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
/** The three series, each on its own scale: time as bars, tests as a line, sections as dots. */
const SERIES: { m: Measure; label: string; mark: string; color: string }[] = [
  { m: 'seconds', label: 'زمان', mark: '▮', color: colors.lemon },
  { m: 'answers', label: 'تست', mark: '—', color: SECOND },
  { m: 'sections', label: 'بخش', mark: '●', color: colors.green },
];
const amount = (m: Measure, n: number) =>
  m === 'seconds' ? studyDuration(n) : `${toPersianDigits(n)} ${m === 'answers' ? 'تست' : 'بخش'}`;
const dayName = (date: string) => {
  const [month, day] = jalaliMonthDay(date);
  return `${toPersianDigits(day)} ${month}`;
};

/** «روند»: one column a day from the first day of study to today (today at the left), scrolled sideways. Time is the
 *  bars, tests the line and sections the dots; the legend on top says which is which and turns each on or off, with
 *  the most of each (every series has its own height). Weeks are shaded in turn, a dashed line marks the daily average
 *  of time, a small lemon sits on the best day, and a tap (or the pointer) on a day shows its numbers above it. */
export function TrendChart({ days }: { days: TrendDay[] }) {
  const [on, setOn] = useState<Record<Measure, boolean>>({ seconds: true, answers: true, sections: false });
  const [picked, setPicked] = useState<number | null>(null);
  const [boxW, setBoxW] = useState(320);
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

  const peak = (m: Measure) => Math.max(1, ...days.map((d) => d[m]));
  const peaks = { seconds: peak('seconds'), answers: peak('answers'), sections: peak('sections') };
  // Few days: wider columns to fill the card; many: 18 px and a scroll.
  const slot = Math.min(40, Math.max(18, Math.floor(boxW / Math.max(1, days.length))));
  const h = 150;
  const top = 34; // room for the bubble's arrow and the lemon
  const inner = h - top - 22;
  const width = Math.max(days.length * slot, 1);
  const x = (i: number) => width - (i + 1) * slot; // newest at the left
  const y = (m: Measure, v: number) => top + inner - (inner * v * scale) / peaks[m];
  const best = days.reduce((b, d, i) => (d.seconds > (days[b]?.seconds ?? 0) ? i : b), 0);
  // Weeks start on Saturday; every other week is shaded.
  const weekOf = (date: string) => Math.floor((Date.parse(`${date}T12:00:00Z`) / 86_400_000 + 5) / 7);
  const last30 = days.slice(-30);
  const sum = (m: Measure) => last30.reduce((n, d) => n + d[m], 0);
  // The daily average of the last 30 days (days without study count as zero).
  const avg = sum('seconds') / Math.max(1, last30.length);
  const toggle = (m: Measure) =>
    setOn((o) => {
      const next = { ...o, [m]: !o[m] };
      return Object.values(next).some(Boolean) ? next : o; // at least one stays on
    });
  const p = picked !== null ? days[picked] : null;

  return (
    <View style={styles.card} onLayout={(e) => setBoxW(e.nativeEvent.layout.width - 28)}>
      <Text style={[styles.trendSum, rtl]}>
        {toPersianDigits(Math.min(30, days.length))} روز اخیر: {studyDuration(sum('seconds'))}، {toPersianDigits(sum('answers'))} تست،{' '}
        {toPersianDigits(sum('sections'))} بخش
      </Text>
      <View style={styles.legend}>
        {SERIES.map((s) => (
          <Pressable
            key={s.m}
            onPress={() => toggle(s.m)}
            style={[styles.legendItem, !on[s.m] && { opacity: 0.45 }]}
            accessibilityRole="switch"
            accessibilityState={{ checked: on[s.m] }}
          >
            <Text style={[styles.legendMark, { color: s.color }]}>{s.mark}</Text>
            <Text style={styles.legendText}>{s.label}</Text>
            <Text style={styles.legendMax}>تا {amount(s.m, peaks[s.m])}</Text>
          </Pressable>
        ))}
      </View>
      <ScrollView horizontal showsHorizontalScrollIndicator={false}>
        <View style={{ width, height: h }}>
          <Svg width={width} height={h}>
            {days.map((d, i) =>
              weekOf(d.date) % 2 ? <Rect key={`w${d.date}`} x={x(i)} y={top - 6} width={slot} height={inner + 6} fill="#F5F3EA" /> : null,
            )}
            <Line x1={0} x2={width} y1={top + inner} y2={top + inner} stroke={colors.line} strokeWidth={1} />
            {on.seconds &&
              days.map((d, i) => {
                const bh = top + inner - y('seconds', d.seconds);
                return (
                  <Rect
                    key={d.date}
                    x={x(i) + slot * 0.18}
                    y={top + inner - bh}
                    width={slot * 0.64}
                    height={Math.max(bh, d.seconds ? 2 : 0)}
                    rx={3}
                    fill={picked === i ? '#C99A00' : colors.lemon}
                  />
                );
              })}
            {on.seconds && avg > 0 && (
              <Line x1={0} x2={width} y1={y('seconds', avg)} y2={y('seconds', avg)} stroke="#C99A00" strokeWidth={1} strokeDasharray="4 4" opacity={0.8} />
            )}
            {on.answers && (
              <Polyline
                points={days.map((d, i) => `${x(i) + slot / 2},${y('answers', d.answers)}`).join(' ')}
                fill="none"
                stroke={SECOND}
                strokeWidth={2}
                strokeLinejoin="round"
              />
            )}
            {on.sections &&
              days.map((d, i) =>
                d.sections ? <Circle key={`s${d.date}`} cx={x(i) + slot / 2} cy={y('sections', d.sections)} r={3.5} fill={colors.green} /> : null,
              )}
            {on.seconds && days[best]?.seconds > 0 && (
              <Circle cx={x(best) + slot / 2} cy={y('seconds', days[best].seconds) - 9} r={5} fill={colors.lemon} stroke="#C99A00" strokeWidth={1.5} />
            )}
            {picked !== null && <Line x1={x(picked) + slot / 2} x2={x(picked) + slot / 2} y1={top - 4} y2={top + inner} stroke={colors.ink} strokeWidth={1} opacity={0.35} />}
            {days.map((d, i) => {
              const [month, day] = jalaliMonthDay(d.date);
              if (day !== 1 && i !== days.length - 1) return null;
              return <SvgLabel key={`l${d.date}`} x={x(i) + slot / 2} y={h - 6} text={i === days.length - 1 ? 'امروز' : month} />;
            })}
          </Svg>
          {/* One invisible column per day: tap, or point with the mouse, to see its numbers. */}
          {days.map((d, i) => (
            <Pressable
              key={`p${d.date}`}
              onPress={() => setPicked(i)}
              onHoverIn={() => setPicked(i)}
              style={{ position: 'absolute', left: x(i), top: 0, width: slot, height: h }}
              accessibilityLabel={dayName(d.date)}
            />
          ))}
          {p && (
            <View pointerEvents="none" style={[styles.bubble, { left: Math.max(0, Math.min(width - 190, x(picked!) + slot / 2 - 95)) }]}>
              <Text style={[styles.bubbleText, rtl]} numberOfLines={1}>
                {dayName(p.date)}: {p.seconds >= 60 ? studyDuration(p.seconds) : 'بی‌مطالعه'}
                {p.answers ? `، ${toPersianDigits(p.answers)} تست` : ''}
                {p.sections ? `، ${toPersianDigits(p.sections)} بخش` : ''}
              </Text>
            </View>
          )}
        </View>
      </ScrollView>
      <Text style={[styles.muted, rtl]}>
        هر ستون یک روز است و امروز سمت چپ؛ برای روزهای قبل کنار بکش. خط‌چین: میانگین زمان روزانه در ۳۰ روز اخیر ({studyDuration(Math.round(avg))}). لیموی کوچک: پربارترین روز.
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
  trendSum: { fontSize: 13, fontWeight: '700', color: colors.ink },
  legend: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  legendItem: { flexDirection: 'row-reverse', alignItems: 'center', gap: 4, borderWidth: 1, borderColor: colors.line, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  legendMark: { fontSize: 13, fontWeight: '900' },
  legendText: { fontSize: 12, fontWeight: '700', color: colors.ink },
  legendMax: { fontSize: 11, color: colors.muted },
  bubble: { position: 'absolute', top: 0, width: 190, backgroundColor: colors.ink, borderRadius: 8, paddingHorizontal: 8, paddingVertical: 4 },
  bubbleText: { fontSize: 11, color: '#FFFFFF', textAlign: 'center' },
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
  ringText: { fontSize: 12, fontWeight: '800', color: colors.ink },
  weekBefore: { fontSize: 11, color: '#A3ADA5' },
  weekRow: { flexDirection: 'row-reverse', alignItems: 'flex-start', gap: 6 },
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
