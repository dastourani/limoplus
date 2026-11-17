/**
 * The app's loading indicators, harmonized with LemonProgress (8 wedges, white pith, crisp wedges):
 * - <LemonLoader />: a lemon slice that crouches, leaps up with a smooth 360° wheel spin, lands with a soft squash,
 *   bounce and golden ripple — 100% on the native driver (60 fps on phones and web).
 * - <LemonSpinner />: a smoothly turning 8-wedge lemon slice for buttons.
 * Shown only after a short delay, so fast answers never flash a spinner.
 */
import { useEffect, useRef, useState } from 'react';
import { Animated, Easing, StyleSheet, View } from 'react-native';
import Svg, { Circle, G, Path } from 'react-native-svg';

const SEGMENTS = 8;

function point(r: number, deg: number) {
  const a = ((deg - 90) * Math.PI) / 180;
  return `${(r * Math.cos(a)).toFixed(2)} ${(r * Math.sin(a)).toFixed(2)}`;
}

function wedgePath(i: number) {
  const step = 360 / SEGMENTS;
  const a0 = i * step;
  const a1 = (i + 1) * step;
  const outer = 76;
  return `M 0 0 L ${point(outer, a0)} A ${outer} ${outer} 0 0 1 ${point(outer, a1)} Z`;
}

const WEDGE_FILL = ['#FFC414', '#FFD43B', '#FFE27A', '#FFD43B', '#FFC414', '#FFD43B', '#FFE27A', '#EAA800'];

function useLoop(duration: number, easing = Easing.linear) {
  const value = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    const loop = Animated.loop(Animated.timing(value, { toValue: 1, duration, easing, useNativeDriver: true }));
    loop.start();
    return () => loop.stop();
  }, [value, duration, easing]);
  return value;
}

function StaticLemon({ size }: { size: number }) {
  return (
    <Svg width={size} height={size} viewBox="-100 -100 200 200">
      <Circle r={98} fill="#F5C518" />
      <Circle r={98} fill="none" stroke="#E0AE0B" strokeWidth={3} />
      <Circle r={87} fill="#FFFFFF" />
      <G>
        {Array.from({ length: SEGMENTS }, (_, i) => (
          <Path key={i} d={wedgePath(i)} fill={WEDGE_FILL[i]} stroke="#FFFFFF" strokeWidth={6} strokeLinejoin="round" />
        ))}
      </G>
      <Circle r={9} fill="#FFFFFF" />
    </Svg>
  );
}

function useDelayed(ms: number) {
  const [show, setShow] = useState(ms === 0);
  useEffect(() => {
    if (ms === 0) return;
    const t = setTimeout(() => setShow(true), ms);
    return () => clearTimeout(t);
  }, [ms]);
  return show;
}

export function LemonSpinner({ size = 20 }: { size?: number }) {
  const t = useLoop(1100);
  const spin = t.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '360deg'] });
  return (
    <Animated.View style={{ width: size, height: size, transform: [{ rotate: spin }] }}>
      <StaticLemon size={size} />
    </Animated.View>
  );
}

export function LemonLoader({ size = 64, delay = 300 }: { size?: number; delay?: number }) {
  const show = useDelayed(delay);
  const t = useLoop(1900, Easing.linear);
  if (!show) return <View style={{ width: size * 1.6, height: size * 2.2 }} />;
  const ip = (input: number[], output: number[]) => t.interpolate({ inputRange: input, outputRange: output });
  const keys = [0, 0.1, 0.2, 0.42, 0.5, 0.68, 0.73, 0.82, 0.9, 1];
  const lift = ip(keys, [0, 0, -0.18, -0.46, -0.44, -0.03, 0, -0.05, 0, 0].map((v) => v * size * 1.8));
  const sx = ip(keys, [1, 1.13, 0.92, 1, 1, 0.95, 1.14, 0.97, 1.02, 1]);
  const sy = ip(keys, [1, 0.85, 1.1, 1, 1, 1.06, 0.84, 1.04, 0.98, 1]);
  const translateY = Animated.add(lift, Animated.multiply(Animated.subtract(1, sy), size / 2));
  const spin = t.interpolate({ inputRange: [0, 0.12, 0.45, 0.72, 1], outputRange: ['0deg', '0deg', '190deg', '360deg', '360deg'] });
  const shadowScale = ip([0, 0.1, 0.42, 0.5, 0.73, 1], [1.05, 1.08, 0.52, 0.55, 1.14, 1]);
  const shadowOpacity = ip([0, 0.1, 0.42, 0.5, 0.73, 1], [0.95, 1, 0.32, 0.35, 1, 0.95]);
  const ripple = ip([0, 0.7, 0.73, 0.94, 1], [0, 0, 0.85, 0, 0]);
  const rippleScale = ip([0, 0.7, 0.73, 0.94, 1], [0.65, 0.65, 0.75, 1.48, 1.48]);
  return (
    <View style={{ width: size * 1.6, height: size * 2.2, alignItems: 'center', justifyContent: 'flex-end' }} accessibilityRole="progressbar" accessibilityLabel="در حال بارگذاری">
      <Animated.View style={[styles.ripple, { width: size * 0.9, height: size * 0.2, bottom: size * 0.02, opacity: ripple, transform: [{ scale: rippleScale }] }]} />
      <Animated.View style={{ transform: [{ translateY }, { scaleX: sx }, { scaleY: sy }, { rotate: spin }] }}>
        <StaticLemon size={size} />
      </Animated.View>
      <Animated.View style={[styles.shadow, { width: size * 0.78, opacity: shadowOpacity, transform: [{ scaleX: shadowScale }] }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  shadow: { height: 7, borderRadius: 999, backgroundColor: '#17201A20', marginTop: 6 },
  ripple: { position: 'absolute', borderRadius: 999, borderWidth: 2, borderColor: '#F5C518' },
});
