/**
 * Moments worth marking, each with its own small animation and message:
 *   great (exam ≥ 80%), good (50–80%), low (< 50%, gentle), login, purchase, deck (flashcards done), streak.
 * celebrate('great', { title, text }). Tapping anywhere closes it; it also closes by itself.
 */
import * as Haptics from 'expo-haptics';
import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { AccessibilityInfo, Animated, Easing, Platform, Pressable, StyleSheet, View, useWindowDimensions } from 'react-native';

import { colors, radius, rtl } from '../theme';
import { Icon } from './Icon';
import { LemonSlice } from './LemonSlice';
import { Text } from './Text';

export type CelebrationKind = 'great' | 'good' | 'low' | 'login' | 'purchase' | 'deck' | 'streak';
type Celebration = { kind: CelebrationKind; title: string; text?: string };

const Ctx = createContext<(kind: CelebrationKind, o: { title: string; text?: string }) => void>(() => undefined);
export const useCelebrate = () => useContext(Ctx);

const CONFETTI: CelebrationKind[] = ['great', 'purchase', 'deck', 'streak'];

function Confetti() {
  const { width, height } = useWindowDimensions();
  const pieces = useRef(
    Array.from({ length: 16 }, () => ({
      x: Math.random() * width,
      size: 18 + Math.random() * 18,
      delay: Math.random() * 400,
      spin: (Math.random() > 0.5 ? 1 : -1) * (180 + Math.random() * 360),
      v: new Animated.Value(0),
    })),
  ).current;
  useEffect(() => {
    pieces.forEach((p) =>
      Animated.timing(p.v, { toValue: 1, duration: 1600, delay: p.delay, easing: Easing.in(Easing.quad), useNativeDriver: true }).start(),
    );
  }, [pieces]);
  return (
    <View pointerEvents="none" style={StyleSheet.absoluteFill}>
      {pieces.map((p, i) => (
        <Animated.View
          key={i}
          style={{
            position: 'absolute',
            left: p.x,
            top: -40,
            transform: [
              { translateY: p.v.interpolate({ inputRange: [0, 1], outputRange: [0, height + 80] }) },
              { rotate: p.v.interpolate({ inputRange: [0, 1], outputRange: ['0deg', `${p.spin}deg`] }) },
            ],
          }}
        >
          <LemonSlice size={p.size} />
        </Animated.View>
      ))}
    </View>
  );
}

function Hero({ kind }: { kind: CelebrationKind }) {
  const v = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    Animated.timing(v, { toValue: 1, duration: kind === 'low' ? 1200 : 900, easing: Easing.out(Easing.back(1.6)), useNativeDriver: true }).start();
  }, [v, kind]);
  if (kind === 'purchase') {
    return (
      <Animated.View style={{ transform: [{ scale: v }] }}>
        <View style={styles.check}>
          <Icon name="circle-check" size={64} color={colors.green} strokeWidth={2} />
        </View>
      </Animated.View>
    );
  }
  const jump = v.interpolate({ inputRange: [0, 0.5, 1], outputRange: [40, -30, 0] });
  const turn = v.interpolate({ inputRange: [0, 1], outputRange: ['0deg', kind === 'good' || kind === 'great' ? '360deg' : '0deg'] });
  const wave = v.interpolate({ inputRange: [0, 0.25, 0.5, 0.75, 1], outputRange: ['0deg', '-14deg', '12deg', '-8deg', '0deg'] });
  const drop = v.interpolate({ inputRange: [0, 0.6, 1], outputRange: [0, 0, 50] });
  const dropOpacity = v.interpolate({ inputRange: [0, 0.55, 0.65, 0.95, 1], outputRange: [0, 0, 1, 1, 0] });
  return (
    <View style={{ alignItems: 'center', height: 150 }}>
      <Animated.View
        style={{
          transform: [
            { translateY: kind === 'low' ? v.interpolate({ inputRange: [0, 1], outputRange: [-30, 0] }) : jump },
            { rotate: kind === 'login' ? wave : turn },
          ],
        }}
      >
        <LemonSlice size={96} />
      </Animated.View>
      {kind === 'low' && <Animated.View style={[styles.drop, { opacity: dropOpacity, transform: [{ translateY: drop }] }]} />}
    </View>
  );
}

export function CelebrationProvider({ children }: { children: ReactNode }) {
  const [current, setCurrent] = useState<Celebration | null>(null);
  const [reduce, setReduce] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    AccessibilityInfo.isReduceMotionEnabled().then(setReduce).catch(() => undefined);
  }, []);

  const celebrate = useCallback((kind: CelebrationKind, o: { title: string; text?: string }) => {
    if (timer.current) clearTimeout(timer.current);
    setCurrent({ kind, ...o });
    if (Platform.OS !== 'web' && kind !== 'low') Haptics.notificationAsync(Haptics.NotificationFeedbackType.Success).catch(() => undefined);
    timer.current = setTimeout(() => setCurrent(null), kind === 'login' ? 1800 : 2800);
  }, []);

  return (
    <Ctx.Provider value={celebrate}>
      {children}
      {current && (
        <Pressable style={[StyleSheet.absoluteFill, styles.backdrop]} onPress={() => setCurrent(null)} accessibilityLabel="بستن">
          {!reduce && CONFETTI.includes(current.kind) && <Confetti />}
          <View style={styles.card}>
            {!reduce && <Hero kind={current.kind} />}
            <Text style={[styles.title, { textAlign: 'center' }]}>{current.title}</Text>
            {!!current.text && <Text style={[styles.text, rtl, { textAlign: 'center' }]}>{current.text}</Text>}
          </View>
        </Pressable>
      )}
    </Ctx.Provider>
  );
}

const styles = StyleSheet.create({
  backdrop: { backgroundColor: '#17201A99', alignItems: 'center', justifyContent: 'center', padding: 24, zIndex: 1500, elevation: 15 },
  card: { backgroundColor: colors.surface, borderRadius: radius.lg, paddingVertical: 24, paddingHorizontal: 22, alignItems: 'center', gap: 8, width: '100%', maxWidth: 360 },
  title: { fontSize: 22, fontWeight: '800', color: colors.ink },
  text: { fontSize: 15, color: colors.muted, lineHeight: 26 },
  check: { width: 110, height: 110, borderRadius: 55, backgroundColor: colors.greenSoft, alignItems: 'center', justifyContent: 'center', marginBottom: 8 },
  drop: { position: 'absolute', top: 96, width: 12, height: 16, borderRadius: 8, backgroundColor: colors.lemon },
});
