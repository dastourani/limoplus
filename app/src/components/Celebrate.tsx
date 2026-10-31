/**
 * Moments worth marking. Each has its own scene on the app's dark ground:
 *   great / good / low — exam result: the lemon fills segment by segment to the score; great squeezes and
 *                        sprays juice, good hops, low breathes quietly.
 *   deck              — flashcards done: the lemon completes, spins once and sprays.
 *   streak            — days in a row: small slices turn juicy one by one.
 *   purchase          — the padlock on the book jiggles, pops open and falls; the book lights up.
 *   login             — a small banner from the top (does not block the screen).
 * Motion is spring-based and runs on the native driver; drops follow precomputed physics (gravity, drag, wobble,
 * a crown and a stain where they land, small drops splitting off). Sounds and a short buzz mark the peak.
 */
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { AccessibilityInfo, Animated, Easing, Pressable, StyleSheet, View, useWindowDimensions } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';
import Svg, { Circle, Defs, Ellipse, G, Path, RadialGradient, Rect, Stop } from 'react-native-svg';

import * as Device from 'expo-device';

import { buzz, play, preloadSounds } from '../lib/sound';
import { colors, rtl, toPersianDigits } from '../theme';
import { Text } from './Text';

export type CelebrationKind = 'great' | 'good' | 'low' | 'login' | 'purchase' | 'deck' | 'streak';
export type CelebrationOptions = {
  title: string;
  text?: string;
  /** Exam: the numbers the lemon fills to. */
  exam?: { score: number; right: number; wrong: number; blank: number };
  /** Main button (closes) and a second one. */
  primary?: string;
  secondary?: { label: string; onPress: () => void };
  /** Streak: number of days. */
  days?: number;
};
type Celebration = CelebrationOptions & { kind: CelebrationKind; key: number };

const Ctx = createContext<(kind: CelebrationKind, o: CelebrationOptions) => void>(() => undefined);
export const useCelebrate = () => useContext(Ctx);

// ---------- lemon drawing ----------
function P(r: number, deg: number) {
  const a = ((deg - 90) * Math.PI) / 180;
  return [r * Math.cos(a), r * Math.sin(a)];
}
const f2 = (p: number[]) => `${p[0].toFixed(2)} ${p[1].toFixed(2)}`;
function segPath(i: number, n: number, rIn: number, rOut: number) {
  const st = 360 / n;
  const gap = n > 12 ? 2 : 3;
  const a0 = i * st + gap;
  const a1 = (i + 1) * st - gap;
  const mid = (a0 + a1) / 2;
  const c0 = P(rOut * 0.58, a0 - st * 0.04);
  const c1 = P(rOut * 0.58, a1 + st * 0.04);
  return `M ${f2(P(rIn, mid))} Q ${f2(c0)} ${f2(P(rOut, a0))} A ${rOut} ${rOut} 0 0 1 ${f2(P(rOut, a1))} Q ${f2(c1)} ${f2(P(rIn, mid))} Z`;
}

function LemonDefs() {
  return (
    <Defs>
      <RadialGradient id="cRind" cx="38%" cy="32%" r="72%">
        <Stop offset="0" stopColor="#FFE766" />
        <Stop offset="0.62" stopColor="#F5C518" />
        <Stop offset="1" stopColor="#CF9608" />
      </RadialGradient>
      <RadialGradient id="cPith" cx="50%" cy="50%" r="50%">
        <Stop offset="0.8" stopColor="#FFFCEF" />
        <Stop offset="1" stopColor="#FFEFB3" />
      </RadialGradient>
      <RadialGradient id="cJuicy" cx="50%" cy="15%" r="95%">
        <Stop offset="0" stopColor="#FFF7C2" />
        <Stop offset="0.35" stopColor="#FFDF57" />
        <Stop offset="0.8" stopColor="#FFC81A" />
        <Stop offset="1" stopColor="#F2AE00" />
      </RadialGradient>
      <RadialGradient id="cDry" cx="50%" cy="15%" r="95%">
        <Stop offset="0" stopColor="#FCF7E4" />
        <Stop offset="1" stopColor="#EADFB6" />
      </RadialGradient>
      <RadialGradient id="cPink" cx="50%" cy="15%" r="95%">
        <Stop offset="0" stopColor="#FFE3DE" />
        <Stop offset="1" stopColor="#EE9488" />
      </RadialGradient>
      <RadialGradient id="cDrop" cx="36%" cy="64%" r="72%">
        <Stop offset="0" stopColor="#FFF8C8" />
        <Stop offset="0.4" stopColor="#FFD74A" />
        <Stop offset="0.85" stopColor="#F0B200" />
        <Stop offset="1" stopColor="#D69A00" />
      </RadialGradient>
    </Defs>
  );
}

type Fill = 'dry' | 'juicy' | 'pink';
function Lemon({ fills, size }: { fills: Fill[]; size: number }) {
  const n = fills.length;
  const pores = useMemo(() => Array.from({ length: 40 }, (_, k) => P(89 + ((k * 7) % 6), k * 9 + ((k * 13) % 5))), []);
  return (
    <Svg width={size} height={size} viewBox="-110 -110 220 220">
      <LemonDefs />
      <Circle r={98} fill="url(#cRind)" />
      {pores.map((p, k) => (
        <Circle key={k} cx={p[0]} cy={p[1]} r={1.2} fill="#D49A06" opacity={0.5} />
      ))}
      <Circle r={87} fill="url(#cPith)" />
      {fills.map((f, i) => (
        <Path key={i} d={segPath(i, n, 9, 78)} fill={f === 'juicy' ? 'url(#cJuicy)' : f === 'pink' ? 'url(#cPink)' : 'url(#cDry)'} stroke="rgba(255,255,255,0.35)" strokeWidth={1.2} />
      ))}
      <Circle r={8} fill="#FFFCEF" />
      <Ellipse cx={-40} cy={-54} rx={28} ry={10} rotation={-36} originX={-40} originY={-54} fill="#FFFFFF" opacity={0.24} />
    </Svg>
  );
}

function Drop({ size }: { size: number }) {
  return (
    <Svg width={size} height={size * 1.3} viewBox="-10 -14 20 26">
      <LemonDefs />
      <Path d="M 0 -13 C 3.5 -6.5 9 -1.5 9 5 A 9 9 0 0 1 -9 5 C -9 -1.5 -3.5 -6.5 0 -13 Z" fill="url(#cDrop)" />
      <Path d="M -5 -1 C -6 2 -5 6 -2 8" stroke="#FFFFFF" strokeWidth={2} strokeLinecap="round" fill="none" opacity={0.75} />
      <Circle cx={3.5} cy={5.5} r={1.3} fill="#FFFFFF" opacity={0.55} />
    </Svg>
  );
}

// ---------- juice physics, precomputed so the animation runs on the native driver ----------
type Sample = { x: number; y: number; r: number; sx: number; sy: number; o: number };
type Track = { kind: 'drop' | 'stain' | 'crown'; size: number; samples: Sample[] };
const FPS = 30;
/** Phones with little memory (like the Galaxy A03) get half the drops, so the juice never stutters. */
const LIGHT = (Device.totalMemory ?? 4e9) < 3.5e9;
const DURATION = 1.8;

function simulate(spawns: { x: number; y: number; vx: number; vy: number; s: number; delay: number }[], floor: number): Track[] {
  const N = Math.round(DURATION * FPS);
  const dt = 1 / FPS;
  const tracks: Track[] = [];
  const queue = spawns.map((s) => ({ ...s, start: s.delay }));
  while (queue.length) {
    const d = queue.shift()!;
    const samples: Sample[] = [];
    let { x, y, vx, vy } = d;
    let landedAt = -1;
    const ph = Math.random() * 6.28;
    for (let i = 0; i <= N; i++) {
      const t = i * dt;
      if (t < d.start) {
        samples.push({ x, y, r: 0, sx: d.s, sy: d.s, o: 0 });
        continue;
      }
      const age = t - d.start;
      if (landedAt < 0) {
        const steps = 3;
        for (let k = 0; k < steps; k++) {
          const h = dt / steps;
          vy += 980 * h;
          vx *= 1 - 0.6 * h;
          vy *= 1 - 0.15 * h;
          x += vx * h;
          y += vy * h;
        }
        if (y >= floor) {
          y = floor;
          landedAt = t;
          tracks.push(splashTrack('stain', x, floor, d.s, t, N));
          tracks.push(splashTrack('crown', x, floor, d.s, t, N));
          if (d.s > 0.7) {
            const kids = 2 + Math.floor(Math.random() * 2);
            for (let c = 0; c < kids; c++)
              queue.push({ x, y: floor - 3, vx: (Math.random() - 0.5) * 280, vy: -160 - Math.random() * 100, s: d.s * (0.22 + Math.random() * 0.12), delay: 0, start: t });
          }
          samples.push({ x, y, r: 0, sx: d.s, sy: d.s, o: 0 });
          continue;
        }
        const speed = Math.hypot(vx, vy);
        const stretch = 1 + Math.min(0.55, speed / 1000);
        const wob = 1 + 0.09 * Math.sin(age * 26 + ph) * Math.exp(-age * 2);
        samples.push({ x, y, r: (Math.atan2(vy, vx) * 180) / Math.PI - 90, sx: (d.s * wob) / Math.sqrt(stretch), sy: (d.s * stretch) / wob, o: 1 });
      } else samples.push({ x, y, r: 0, sx: d.s, sy: d.s, o: 0 });
    }
    tracks.push({ kind: 'drop', size: 20, samples });
  }
  return tracks;
}
function splashTrack(kind: 'stain' | 'crown', x: number, y: number, s: number, at: number, N: number): Track {
  const samples: Sample[] = [];
  for (let i = 0; i <= N; i++) {
    const t = i / FPS - at;
    if (t < 0) {
      samples.push({ x, y, r: 0, sx: 0.01, sy: 0.01, o: 0 });
      continue;
    }
    if (kind === 'stain') {
      const k = Math.min(1, t / 0.25);
      const e = 1 - Math.pow(1 - k, 3);
      samples.push({ x, y: y + 3, r: 0, sx: Math.max(0.01, e * s), sy: Math.max(0.01, e * s * 0.28), o: Math.max(0, 1 - Math.max(0, t - 0.4) / 1.2) });
    } else {
      const k = Math.min(1, t / 0.35);
      const e = 1 - Math.pow(1 - k, 3);
      samples.push({ x, y: y + 2, r: 0, sx: 0.2 + e * s, sy: (0.2 + e * s) * 0.25, o: 1 - k });
    }
  }
  return { kind, size: kind === 'stain' ? 28 : 40, samples };
}

function Juice({ tracks, cx, cy, onLand, onEnd }: { tracks: Track[]; cx: number; cy: number; onLand?: () => void; onEnd?: () => void }) {
  const v = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(v, { toValue: 1, duration: DURATION * 1000, easing: Easing.linear, useNativeDriver: true }).start(() => onEnd?.());
    // A drop sound for each landing (the sound helper throttles bursts).
    const timers = tracks
      .filter((t) => t.kind === 'crown')
      .map((t) => setTimeout(() => (onLand ? onLand() : play('drop', 0.7)), (t.samples.findIndex((s) => s.o > 0) / FPS) * 1000));
    return () => timers.forEach(clearTimeout);
  }, [v, tracks, onLand]);
  const input = tracks[0]?.samples.map((_, i, a) => i / (a.length - 1)) ?? [0, 1];
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      {tracks.map((t, i) => {
        const pick = (f: (s: Sample) => number) => v.interpolate({ inputRange: input, outputRange: t.samples.map(f) });
        const style = {
          position: 'absolute' as const,
          left: cx - t.size / 2,
          top: cy - t.size / 2,
          opacity: pick((s) => s.o),
          transform: [
            { translateX: pick((s) => s.x) },
            { translateY: pick((s) => s.y) },
            { rotate: v.interpolate({ inputRange: input, outputRange: t.samples.map((s) => `${s.r.toFixed(1)}deg`) }) },
            { scaleX: pick((s) => s.sx) },
            { scaleY: pick((s) => s.sy) },
          ],
        };
        if (t.kind === 'drop')
          return (
            <Animated.View key={i} style={style}>
              <Drop size={t.size} />
            </Animated.View>
          );
        return (
          <Animated.View
            key={i}
            style={[
              style,
              { width: t.size, height: t.size, borderRadius: t.size / 2 },
              t.kind === 'stain' ? { backgroundColor: 'rgba(255,212,59,0.35)' } : { borderWidth: 1.4, borderColor: '#FFE27A' },
            ]}
          />
        );
      })}
    </View>
  );
}

function rimSpray(count: number, power: number, radius: number) {
  return Array.from({ length: count }, () => {
    const a = ((-160 + Math.random() * 140) * Math.PI) / 180;
    const sp = (0.55 + Math.random() * 0.55) * power;
    return { x: Math.cos(a) * radius, y: Math.sin(a) * radius, vx: Math.cos(a) * sp + (Math.random() - 0.5) * 60, vy: Math.sin(a) * sp, s: 0.45 + Math.random() * 0.7, delay: Math.random() * 0.08 };
  });
}

// ---------- scenes ----------
function useReveal(delay: number) {
  const v = useRef(new Animated.Value(0)).current;
  const go = useCallback(() => {
    Animated.parallel([
      Animated.timing(v, { toValue: 1, duration: 420, delay: delay * 1000, easing: Easing.out(Easing.cubic), useNativeDriver: true }),
    ]).start();
  }, [v, delay]);
  const style = { opacity: v, transform: [{ translateY: v.interpolate({ inputRange: [0, 1], outputRange: [14, 0] }) }] };
  return [style, go] as const;
}

function LemonScene({ c, onClose, reduce }: { c: Celebration; onClose: () => void; reduce: boolean }) {
  const { width } = useWindowDimensions();
  const size = Math.min(220, width * 0.58);
  const exam = c.exam;
  const n = c.kind === 'deck' ? 10 : 20;
  const order: Fill[] = useMemo(() => {
    if (c.kind === 'deck') return Array<Fill>(10).fill('juicy');
    const total = Math.max(1, (exam?.right ?? 0) + (exam?.wrong ?? 0) + (exam?.blank ?? 0));
    const right = Math.round(((exam?.right ?? 0) / total) * n);
    const wrong = Math.min(n - right, Math.round(((exam?.wrong ?? 0) / total) * n));
    return [...Array<Fill>(right).fill('juicy'), ...Array<Fill>(wrong).fill('pink')];
  }, [c.kind, exam, n]);
  const [filled, setFilled] = useState(reduce ? order.length : 0);
  const [shown, setShown] = useState(reduce ? exam?.score ?? 0 : 0);
  const [spray, setSpray] = useState<Track[] | null>(null);
  const sx = useRef(new Animated.Value(reduce ? 1 : 0.6)).current;
  const sy = useRef(new Animated.Value(reduce ? 1 : 0.6)).current;
  const ty = useRef(new Animated.Value(0)).current;
  const rot = useRef(new Animated.Value(0)).current;
  const glow = useRef(new Animated.Value(0)).current;
  const breath = useRef(new Animated.Value(1)).current;
  const [textStyle, revealText] = useReveal(c.kind === 'great' || c.kind === 'deck' ? 0.25 : 0.1);

  useEffect(() => {
    if (reduce) {
      revealText();
      return;
    }
    Animated.spring(sx, { toValue: 1, friction: 6, tension: 90, useNativeDriver: true }).start();
    Animated.spring(sy, { toValue: 1, friction: 6, tension: 90, useNativeDriver: true }).start();
    const timers: ReturnType<typeof setTimeout>[] = [];
    const step = c.kind === 'low' ? 75 : c.kind === 'deck' ? 85 : 55;
    order.forEach((_, i) =>
      timers.push(
        setTimeout(() => {
          setFilled(i + 1);
          setShown(Math.round(((exam?.score ?? 0) * (i + 1)) / order.length));
          if (i % 3 === 0) play('tick', 0.5);
        }, 400 + i * step * (1 + i / 60)),
      ),
    );
    const end = 400 + order.length * step * 1.15 + 60;
    timers.push(
      setTimeout(() => {
        if (c.kind === 'great') {
          // soft-body squeeze: sink and widen, juice out at the peak, spring back with overshoot
          Animated.parallel([
            Animated.timing(sx, { toValue: 1.1, duration: 160, easing: Easing.inOut(Easing.cubic), useNativeDriver: true }),
            Animated.timing(sy, { toValue: 0.86, duration: 160, easing: Easing.inOut(Easing.cubic), useNativeDriver: true }),
            Animated.timing(ty, { toValue: 4, duration: 160, useNativeDriver: true }),
          ]).start(() => {
            buzz('success');
            play('pop');
            setSpray(simulate(rimSpray(LIGHT ? 8 : 16, 420, size * 0.42), size * 0.78));
            Animated.sequence([Animated.timing(glow, { toValue: 1, duration: 450, useNativeDriver: true }), Animated.timing(glow, { toValue: 0, duration: 900, delay: 350, easing: Easing.out(Easing.quad), useNativeDriver: true })]).start();
            Animated.spring(sx, { toValue: 1, friction: 3.2, tension: 160, useNativeDriver: true }).start();
            Animated.spring(sy, { toValue: 1, friction: 3.2, tension: 160, useNativeDriver: true }).start();
            Animated.spring(ty, { toValue: 0, friction: 4, useNativeDriver: true }).start();
          });
        } else if (c.kind === 'deck') {
          buzz('success');
          Animated.sequence([Animated.timing(glow, { toValue: 1, duration: 450, useNativeDriver: true }), Animated.timing(glow, { toValue: 0, duration: 900, delay: 350, easing: Easing.out(Easing.quad), useNativeDriver: true })]).start();
          Animated.spring(rot, { toValue: 1, friction: 6, tension: 30, useNativeDriver: true }).start();
          timers.push(
            setTimeout(() => {
              play('pop');
              setSpray(simulate(rimSpray(LIGHT ? 6 : 12, 380, size * 0.42), size * 0.78));
            }, 350),
          );
        } else if (c.kind === 'good') {
          buzz();
          Animated.sequence([
            Animated.timing(ty, { toValue: -16, duration: 180, easing: Easing.out(Easing.quad), useNativeDriver: true }),
            Animated.spring(ty, { toValue: 0, friction: 3.5, tension: 140, useNativeDriver: true }),
          ]).start();
          timers.push(setTimeout(() => setSpray(simulate(rimSpray(4, 250, size * 0.42), size * 0.78)), 200));
        } else {
          // low: a calm breath, no juice
          const breathe = (to: number) => Animated.timing(breath, { toValue: to, duration: 800, easing: Easing.inOut(Easing.sin), useNativeDriver: true });
          Animated.sequence([breathe(1.03), breathe(1), breathe(1.03), breathe(1)]).start();
        }
        revealText();
      }, end),
    );
    return () => timers.forEach(clearTimeout);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const fills = Array.from({ length: n }, (_, i) => (i < filled ? order[i] : 'dry')) as Fill[];
  const spin = rot.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });
  return (
    <View style={styles.scene}>
      <View style={{ width: size, height: size }}>
        <Animated.View style={[styles.glow, { width: size * 1.5, height: size * 1.5, borderRadius: size, left: -size * 0.25, top: -size * 0.25, opacity: glow.interpolate({ inputRange: [0, 1], outputRange: [0, 0.45] }), transform: [{ scale: glow.interpolate({ inputRange: [0, 1], outputRange: [0.7, 1.1] }) }] }]} />
        <Animated.View style={{ transform: [{ translateY: ty }, { rotate: spin }, { scale: breath }, { scaleX: sx }, { scaleY: sy }] }}>
          <Lemon fills={fills} size={size} />
        </Animated.View>
        {spray && <Juice tracks={spray} cx={size / 2} cy={size / 2} onEnd={() => setSpray(null)} />}
      </View>
      {exam && (
        <Text style={styles.score}>
          {toPersianDigits(shown)}
          <Text style={styles.scorePct}>٪</Text>
        </Text>
      )}
      <Animated.View style={[styles.copy, textStyle]}>
        <Text style={styles.title}>{c.title}</Text>
        {!!c.text && <Text style={[styles.text, { textAlign: 'center' }]}>{c.text}</Text>}
        {exam && (
          <View style={styles.chips}>
            <Text style={[styles.chip, { color: '#9BE3B4' }]}>{toPersianDigits(exam.right)} درست</Text>
            <Text style={[styles.chip, { color: '#F7B1AA' }]}>{toPersianDigits(exam.wrong)} غلط</Text>
            <Text style={[styles.chip, { color: '#B9C4BC' }]}>{toPersianDigits(exam.blank)} نزده</Text>
          </View>
        )}
        <Buttons c={c} onClose={onClose} />
      </Animated.View>
    </View>
  );
}

function Buttons({ c, onClose }: { c: Celebration; onClose: () => void }) {
  return (
    <View style={styles.btns}>
      <Pressable onPress={onClose} style={styles.btnY} accessibilityRole="button">
        <Text style={styles.btnYText}>{c.primary ?? 'ادامه'}</Text>
      </Pressable>
      {c.secondary && (
        <Pressable
          onPress={() => {
            onClose();
            c.secondary!.onPress();
          }}
          style={styles.btnG}
          accessibilityRole="button"
        >
          <Text style={styles.btnGText}>{c.secondary.label}</Text>
        </Pressable>
      )}
    </View>
  );
}

function MiniSlice({ on }: { on: boolean }) {
  return (
    <Svg width={34} height={34} viewBox="-100 -100 200 200">
      <LemonDefs />
      <Circle r={96} fill={on ? 'url(#cRind)' : '#26332B'} />
      <Circle r={84} fill={on ? '#FFFCEF' : '#1F2A22'} />
      {Array.from({ length: 8 }, (_, i) => (
        <Path key={i} d={segPath(i, 8, 10, 74)} fill={on ? 'url(#cJuicy)' : '#2C3A31'} />
      ))}
    </Svg>
  );
}
function StreakDay({ on, delay }: { on: boolean; delay: number }) {
  const v = useRef(new Animated.Value(0)).current;
  const [lit, setLit] = useState(false);
  useEffect(() => {
    if (!on) return;
    const t = setTimeout(() => {
      setLit(true);
      play('tick', 0.6);
      Animated.spring(v, { toValue: 1, friction: 4, tension: 160, useNativeDriver: true }).start();
    }, delay);
    return () => clearTimeout(t);
  }, [on, delay, v]);
  return (
    <Animated.View style={lit ? { transform: [{ scale: v.interpolate({ inputRange: [0, 1], outputRange: [0.4, 1] }) }, { rotate: v.interpolate({ inputRange: [0, 1], outputRange: ['-90deg', '0deg'] }) }] } : undefined}>
      <MiniSlice on={lit} />
    </Animated.View>
  );
}
function StreakScene({ c, onClose }: { c: Celebration; onClose: () => void }) {
  const days = c.days ?? 7;
  const shownDays = Math.min(7, days);
  const [count, setCount] = useState(0);
  const pop = useRef(new Animated.Value(1)).current;
  const [textStyle, revealText] = useReveal(0.1);
  useEffect(() => {
    const timers = Array.from({ length: shownDays }, (_, i) =>
      setTimeout(() => {
        setCount(i + 1 === shownDays ? days : i + 1);
        pop.setValue(1.18);
        Animated.spring(pop, { toValue: 1, friction: 4, tension: 200, useNativeDriver: true }).start();
      }, 300 + i * 190),
    );
    timers.push(
      setTimeout(() => {
        buzz('success');
        play('pop');
        revealText();
      }, 300 + shownDays * 190),
    );
    return () => timers.forEach(clearTimeout);
  }, [shownDays, days, pop, revealText]);
  return (
    <View style={styles.scene}>
      <Animated.Text style={[styles.big, { transform: [{ scale: pop }] }]}>{toPersianDigits(count)}</Animated.Text>
      <Text style={styles.bigLabel}>روز پشت سر هم</Text>
      <View style={styles.week}>
        {Array.from({ length: 7 }, (_, i) => (
          <StreakDay key={i} on={i < shownDays} delay={300 + i * 190} />
        ))}
      </View>
      <Animated.View style={[styles.copy, textStyle]}>
        <Text style={styles.title}>{c.title}</Text>
        {!!c.text && <Text style={[styles.text, { textAlign: 'center' }]}>{c.text}</Text>}
        <Buttons c={c} onClose={onClose} />
      </Animated.View>
    </View>
  );
}

function PurchaseScene({ c, onClose }: { c: Celebration; onClose: () => void }) {
  const appear = useRef(new Animated.Value(0.8)).current;
  const jiggle = useRef(new Animated.Value(0)).current;
  const shackle = useRef(new Animated.Value(0)).current;
  const fall = useRef(new Animated.Value(0)).current;
  const halo = useRef(new Animated.Value(0)).current;
  const [textStyle, revealText] = useReveal(0.15);
  useEffect(() => {
    Animated.spring(appear, { toValue: 1, friction: 6, tension: 90, useNativeDriver: true }).start();
    const t1 = setTimeout(() => {
      play('tick');
      Animated.sequence([
        Animated.timing(jiggle, { toValue: 1, duration: 70, useNativeDriver: true }),
        Animated.timing(jiggle, { toValue: -1, duration: 90, useNativeDriver: true }),
        Animated.spring(jiggle, { toValue: 0, friction: 3, tension: 300, useNativeDriver: true }),
      ]).start();
    }, 350);
    const t2 = setTimeout(() => {
      play('unlock');
      buzz('success');
      Animated.spring(shackle, { toValue: 1, friction: 3.5, tension: 160, useNativeDriver: true }).start();
    }, 760);
    const t3 = setTimeout(() => {
      Animated.timing(fall, { toValue: 1, duration: 560, easing: Easing.in(Easing.quad), useNativeDriver: true }).start();
      Animated.sequence([
        Animated.timing(halo, { toValue: 1, duration: 600, easing: Easing.out(Easing.cubic), useNativeDriver: true }),
        Animated.timing(halo, { toValue: 0.35, duration: 900, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
      ]).start();
      revealText();
    }, 1110);
    return () => [t1, t2, t3].forEach(clearTimeout);
  }, [appear, jiggle, shackle, fall, halo, revealText]);
  return (
    <View style={styles.scene}>
      <Animated.View style={{ width: 150, height: 196, transform: [{ scale: appear }] }}>
        <Animated.View style={[styles.halo, { opacity: halo.interpolate({ inputRange: [0, 1], outputRange: [0, 0.5] }) }]} />
        <View style={styles.pages} />
        <View style={[styles.book, { borderColor: '#3A4A40' }]}>
          <Animated.View pointerEvents="none" style={[styles.bookLit, { opacity: halo.interpolate({ inputRange: [0, 0.35, 1], outputRange: [0, 1, 1] }) }]} />
          <View style={[styles.bookLine, { width: '70%', backgroundColor: colors.lemon }]} />
          <View style={[styles.bookLine, { width: '85%' }]} />
          <View style={[styles.bookLine, { width: '55%' }]} />
        </View>
        <Animated.View
          style={[
            styles.lock,
            {
              opacity: fall.interpolate({ inputRange: [0, 0.9, 1], outputRange: [1, 0.3, 0] }),
              transform: [
                { translateY: fall.interpolate({ inputRange: [0, 1], outputRange: [0, 80] }) },
                { rotate: jiggle.interpolate({ inputRange: [-1, 1], outputRange: ['-9deg', '9deg'] }) },
                { rotate: fall.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '25deg'] }) },
              ],
            },
          ]}
        >
          <Animated.View
            style={[
              styles.shackle,
              {
                transform: [
                  { translateX: 14 },
                  { translateY: shackle.interpolate({ inputRange: [0, 1], outputRange: [0, -9] }) },
                  { rotate: shackle.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '-40deg'] }) },
                  { translateX: -14 },
                ],
              },
            ]}
          />
          <View style={styles.hole} />
        </Animated.View>
      </Animated.View>
      <Animated.View style={[styles.copy, textStyle]}>
        <Text style={styles.title}>{c.title}</Text>
        {!!c.text && <Text style={[styles.text, { textAlign: 'center' }]}>{c.text}</Text>}
        <Buttons c={c} onClose={onClose} />
      </Animated.View>
    </View>
  );
}

function LoginBanner({ c, onDone }: { c: Celebration; onDone: () => void }) {
  const y = useRef(new Animated.Value(-160)).current;
  const wave = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.spring(y, { toValue: 0, friction: 7, tension: 70, useNativeDriver: true }).start();
    const t1 = setTimeout(() => {
      Animated.sequence([
        Animated.timing(wave, { toValue: -1, duration: 150, useNativeDriver: true }),
        Animated.spring(wave, { toValue: 0, friction: 2.2, tension: 120, useNativeDriver: true }),
      ]).start();
    }, 350);
    const t2 = setTimeout(() => Animated.timing(y, { toValue: -160, duration: 320, easing: Easing.in(Easing.cubic), useNativeDriver: true }).start(onDone), 2600);
    return () => [t1, t2].forEach(clearTimeout);
  }, [y, wave, onDone]);
  return (
    <SafeAreaView pointerEvents="box-none" style={styles.toastWrap}>
      <Animated.View style={[styles.toast, { transform: [{ translateY: y }] }]}>
        <Animated.View style={{ transform: [{ translateY: 14 }, { rotate: wave.interpolate({ inputRange: [-1, 0], outputRange: ['-24deg', '0deg'] }) }, { translateY: -14 }] }}>
          <MiniSlice on />
        </Animated.View>
        <View style={{ flex: 1 }}>
          <Text style={[styles.toastTitle, rtl]}>{c.title}</Text>
          <Text style={[styles.toastText, rtl]}>{c.text ?? 'از همان جایی که ماندی ادامه بده.'}</Text>
        </View>
      </Animated.View>
    </SafeAreaView>
  );
}

function Backdrop() {
  return (
    <Svg style={StyleSheet.absoluteFill} width="100%" height="100%">
      <Defs>
        <RadialGradient id="cBg" cx="50%" cy="26%" r="75%">
          <Stop offset="0" stopColor="#26342C" />
          <Stop offset="0.62" stopColor="#17201A" />
          <Stop offset="1" stopColor="#17201A" />
        </RadialGradient>
      </Defs>
      <Rect width="100%" height="100%" fill="url(#cBg)" />
    </Svg>
  );
}

export function CelebrationProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<Celebration | null>(null);
  const [reduce, setReduce] = useState(false);
  const fade = useRef(new Animated.Value(0)).current;
  const seq = useRef(0);

  useEffect(() => {
    preloadSounds();
    AccessibilityInfo.isReduceMotionEnabled().then(setReduce).catch(() => undefined);
  }, []);

  const celebrate = useCallback(
    (kind: CelebrationKind, o: CelebrationOptions) => {
      seq.current += 1;
      setCurrent({ kind, ...o, key: seq.current });
      if (kind !== 'login') {
        fade.setValue(0);
        Animated.timing(fade, { toValue: 1, duration: 260, useNativeDriver: true }).start();
      }
    },
    [fade],
  );
  const close = useCallback(() => {
    Animated.timing(fade, { toValue: 0, duration: 200, useNativeDriver: true }).start(() => setCurrent(null));
  }, [fade]);
  const done = useCallback(() => setCurrent(null), []);

  return (
    <Ctx.Provider value={celebrate}>
      {children}
      {current?.kind === 'login' && <LoginBanner key={current.key} c={current} onDone={done} />}
      {current && current.kind !== 'login' && (
        <Animated.View style={[StyleSheet.absoluteFill, styles.overlay, { opacity: fade }]}>
          <Backdrop />
          <SafeAreaView style={{ flex: 1 }}>
            {current.kind === 'purchase' ? (
              <PurchaseScene key={current.key} c={current} onClose={close} />
            ) : current.kind === 'streak' ? (
              <StreakScene key={current.key} c={current} onClose={close} />
            ) : (
              <LemonScene key={current.key} c={current} onClose={close} reduce={reduce} />
            )}
          </SafeAreaView>
        </Animated.View>
      )}
    </Ctx.Provider>
  );
}

const styles = StyleSheet.create({
  overlay: { zIndex: 1500, elevation: 15 },
  scene: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8 },
  glow: { position: 'absolute', backgroundColor: 'rgba(255,212,59,0.55)' },
  score: { fontSize: 46, fontWeight: '900', color: '#FFF7D6', marginTop: 6 },
  scorePct: { fontSize: 22, color: colors.lemon },
  copy: { alignItems: 'center', gap: 8, alignSelf: 'stretch' },
  title: { fontSize: 26, fontWeight: '900', color: colors.lemon, textAlign: 'center' },
  text: { fontSize: 14, color: '#B9C4BC', lineHeight: 26, maxWidth: 300 },
  chips: { flexDirection: 'row-reverse', gap: 6, flexWrap: 'wrap', justifyContent: 'center' },
  chip: { fontSize: 12, fontWeight: '700', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4, backgroundColor: 'rgba(255,255,255,0.06)', borderWidth: 1, borderColor: 'rgba(255,255,255,0.08)', overflow: 'hidden' },
  btns: { alignSelf: 'stretch', gap: 8, marginTop: 8 },
  btnY: { backgroundColor: colors.lemon, borderRadius: 16, paddingVertical: 13, alignItems: 'center' },
  btnYText: { fontSize: 15, fontWeight: '800', color: colors.ink },
  btnG: { borderRadius: 16, paddingVertical: 12, alignItems: 'center', borderWidth: 1.5, borderColor: '#3A4A40' },
  btnGText: { fontSize: 15, fontWeight: '800', color: '#F1F4EC' },
  big: { fontSize: 80, fontWeight: '900', color: '#FFF7D6' },
  bigLabel: { fontSize: 14, color: '#B9C4BC', marginTop: -4 },
  week: { flexDirection: 'row-reverse', gap: 6, marginTop: 6, marginBottom: 10 },
  halo: { position: 'absolute', left: -40, right: -40, top: -40, bottom: -40, borderRadius: 200, backgroundColor: 'rgba(245,197,24,0.6)' },
  pages: { position: 'absolute', top: 6, bottom: 6, left: -6, width: 8, borderTopLeftRadius: 3, borderBottomLeftRadius: 3, backgroundColor: '#EDE6D2' },
  bookLit: { position: 'absolute', left: -2, right: -2, top: -2, bottom: -2, borderWidth: 2, borderColor: '#F5C518', borderTopLeftRadius: 14, borderBottomLeftRadius: 14, borderTopRightRadius: 22, borderBottomRightRadius: 22 },
  book: { flex: 1, borderTopLeftRadius: 14, borderBottomLeftRadius: 14, borderTopRightRadius: 22, borderBottomRightRadius: 22, backgroundColor: '#1F2A22', borderWidth: 2, justifyContent: 'flex-end', padding: 16, gap: 6 },
  bookLine: { height: 8, borderRadius: 4, backgroundColor: '#3A4A40', alignSelf: 'flex-end' },
  lock: { position: 'absolute', left: 46, top: 78, width: 58, height: 48, borderRadius: 11, backgroundColor: colors.lemon, alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.35, shadowRadius: 10, shadowOffset: { width: 0, height: 6 }, elevation: 6 },
  shackle: { position: 'absolute', bottom: 46, left: 12, width: 34, height: 30, borderWidth: 6, borderBottomWidth: 0, borderColor: colors.lemon, borderTopLeftRadius: 18, borderTopRightRadius: 18 },
  hole: { width: 9, height: 15, borderRadius: 4, backgroundColor: '#6E4E00' },
  toastWrap: { position: 'absolute', top: 0, left: 0, right: 0, zIndex: 1600, elevation: 16 },
  toast: { marginHorizontal: 12, marginTop: 8, backgroundColor: colors.ink, borderRadius: 22, paddingVertical: 10, paddingHorizontal: 14, flexDirection: 'row-reverse', alignItems: 'center', gap: 12, shadowColor: '#000', shadowOpacity: 0.28, shadowRadius: 16, shadowOffset: { width: 0, height: 10 }, elevation: 10 },
  toastTitle: { fontSize: 16, fontWeight: '800', color: colors.lemon },
  toastText: { fontSize: 12.5, color: '#B9C4BC' },
});
