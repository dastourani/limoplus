/**
 * A page turning over, as in a Persian book: the spine is on the right, the page lifts from its left edge and
 * rolls to the right, showing its paper back, while the new page appears underneath.
 *   kind="cover": the book's dark cover with the lemon (entering a book)
 *   kind="paper": a page of the section just finished (going to the next section)
 * Drawn with transforms only (native driver), so it stays smooth on low-end phones. Tapping skips it.
 */
import { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, Pressable, StyleSheet, View, useWindowDimensions } from 'react-native';
import Svg, { Defs, LinearGradient, Rect, Stop } from 'react-native-svg';

import { colors, rtl } from '../theme';
import { LemonSlice } from './LemonSlice';
import { Text } from './Text';

function Face({ kind, title, w, h }: { kind: 'cover' | 'paper'; title?: string; w: number; h: number }) {
  if (kind === 'cover') {
    return (
      <View style={[styles.cover, { width: w, height: h }]}>
        <LemonSlice size={Math.min(140, w * 0.38)} />
        {!!title && <Text style={styles.coverTitle}>{title}</Text>}
        <View style={styles.coverRule} />
        <Text style={styles.coverBrand}>لیمو پلاس</Text>
      </View>
    );
  }
  return (
    <View style={[styles.paper, { width: w, height: h }]}>
      {!!title && <Text style={[styles.paperTitle, rtl]}>{title}</Text>}
      {[92, 84, 96, 70, 88, 94, 66, 90, 80, 95, 72, 86].map((p, i) => (
        <View key={i} style={[styles.line, { width: `${p}%` }]} />
      ))}
    </View>
  );
}

function Shade({ w, h, from, to, id }: { w: number; h: number; from: string; to: string; id: string }) {
  return (
    <Svg width={w} height={h}>
      <Defs>
        <LinearGradient id={id} x1="0" y1="0" x2="1" y2="0">
          <Stop offset="0" stopColor={from} />
          <Stop offset="1" stopColor={to} />
        </LinearGradient>
      </Defs>
      <Rect width={w} height={h} fill={`url(#${id})`} />
    </Svg>
  );
}

export function PageTurn({
  kind,
  title,
  delay = 120,
  duration = 760,
  hold = false,
  onDone,
}: {
  kind: 'cover' | 'paper';
  title?: string;
  delay?: number;
  duration?: number;
  /** Show the page still (while the next screen loads). */
  hold?: boolean;
  onDone?: () => void;
}) {
  const { width: W, height: H } = useWindowDimensions();
  const p = useRef(new Animated.Value(0)).current;
  const [done, setDone] = useState(false);

  useEffect(() => {
    if (hold) return;
    let cancelled = false;
    AccessibilityInfo.isReduceMotionEnabled()
      .catch(() => false)
      .then((reduce) => {
        if (cancelled) return;
        Animated.timing(p, { toValue: 1, duration: reduce ? 1 : duration, delay: reduce ? 0 : delay, easing: Easing.inOut(Easing.cubic), useNativeDriver: true }).start(() => {
          setDone(true);
          onDone?.();
        });
      });
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hold]);

  if (done) return null;

  // x = how far the fold has travelled from the left edge.
  const x = p.interpolate({ inputRange: [0, 1], outputRange: [0, W] });
  const negX = p.interpolate({ inputRange: [0, 1], outputRange: [0, -W] });
  // The lifted part lies over the page as its back side, mirrored: from the fold to twice the fold.
  const flapScale = p.interpolate({ inputRange: [0, 1], outputRange: [0.0001, 1] });
  const flapX = p.interpolate({ inputRange: [0, 1], outputRange: [-W / 2, W] });
  const shadow = p.interpolate({ inputRange: [0, 0.15, 0.85, 1], outputRange: [0, 1, 1, 0] });

  return (
    <Pressable style={StyleSheet.absoluteFill} onPress={() => p.stopAnimation(() => (setDone(true), onDone?.()))} accessibilityLabel="رد کردن">
      <View style={[StyleSheet.absoluteFill, { overflow: 'hidden' }]} pointerEvents="none">
        {/* the old page, still flat to the right of the fold */}
        <Animated.View style={[StyleSheet.absoluteFill, { overflow: 'hidden', transform: [{ translateX: x }] }]}>
          <Animated.View style={{ transform: [{ translateX: negX }] }}>
            <Face kind={kind} title={title} w={W} h={H} />
          </Animated.View>
        </Animated.View>
        {/* soft shadow the rolling page casts on the new page */}
        <Animated.View style={{ position: 'absolute', top: 0, left: -40, opacity: shadow, transform: [{ translateX: x }] }}>
          <Shade w={40} h={H} from="rgba(23,32,26,0)" to="rgba(23,32,26,0.28)" id="pt-s" />
        </Animated.View>
        {/* the paper back of the lifted part, its fold edge rounded by a highlight */}
        <Animated.View style={{ position: 'absolute', top: 0, left: 0, width: W, height: H, opacity: shadow, transform: [{ translateX: flapX }, { scaleX: flapScale }] }}>
          <View style={[StyleSheet.absoluteFill, { backgroundColor: kind === 'cover' ? '#1F2A22' : '#F1EAD6' }]} />
          <View style={[StyleSheet.absoluteFill, { flexDirection: 'row' }]}>
            <Shade w={W * 0.5} h={H} from="rgba(255,255,255,0.35)" to="rgba(255,255,255,0)" id="pt-h" />
            <Shade w={W * 0.5} h={H} from="rgba(23,32,26,0)" to="rgba(23,32,26,0.18)" id="pt-d" />
          </View>
        </Animated.View>
      </View>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  cover: { backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center', gap: 18, padding: 32 },
  coverTitle: { color: colors.lemon, fontSize: 24, fontWeight: '900', textAlign: 'center', lineHeight: 38 },
  coverRule: { width: 60, height: 4, borderRadius: 2, backgroundColor: '#3A4A40' },
  coverBrand: { color: '#8FA095', fontSize: 13 },
  paper: { backgroundColor: '#FFFDF6', paddingTop: 120, paddingHorizontal: 24, gap: 14 },
  paperTitle: { fontSize: 20, fontWeight: '800', color: colors.ink, marginBottom: 10 },
  line: { height: 8, borderRadius: 4, backgroundColor: '#E2E5DA', alignSelf: 'flex-end' },
});
