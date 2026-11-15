/**
 * The app's loading indicators, drawn from the lemon slice:
 * - <LemonLoader />: a lemon slice tossed up (squash and stretch, a pause at the top, a tilted flip), landing with a
 *   small bounce and a ripple, while its segments light up in turn.
 * - <LemonSpinner />: just the segments lighting up in turn, small enough for buttons.
 * Shown only after a short delay, so fast answers never flash a spinner.
 */
import { useEffect, useRef, useState } from 'react';
import { Animated, Easing, StyleSheet, View } from 'react-native';
import Svg, { Circle, Path } from 'react-native-svg';

const SEGMENTS = 9;
const AnimatedPath = Animated.createAnimatedComponent(Path);

function point(r: number, deg: number) {
  const a = ((deg - 90) * Math.PI) / 180;
  return `${(r * Math.cos(a)).toFixed(2)} ${(r * Math.sin(a)).toFixed(2)}`;
}

function segment(i: number) {
  const step = 360 / SEGMENTS;
  const a0 = i * step + 4.5;
  const a1 = (i + 1) * step - 4.5;
  const mid = (a0 + a1) / 2;
  return `M ${point(13, mid)} L ${point(72, a0)} A 72 72 0 0 1 ${point(72, a1)} Z`;
}

function useLoop(duration: number, easing = Easing.linear, nativeDriver = false) {
  const value = useRef(new Animated.Value(0)).current;
  useEffect(() => {
    const loop = Animated.loop(Animated.timing(value, { toValue: 1, duration, easing, useNativeDriver: nativeDriver }));
    loop.start();
    return () => loop.stop();
  }, [value, duration, easing, nativeDriver]);
  return value;
}

function Slice({ size }: { size: number }) {
  const t = useLoop(1500);
  return (
    <Svg width={size} height={size} viewBox="-100 -100 200 200">
      <Circle r={98} fill="#F5C518" />
      <Circle r={98} fill="none" stroke="#E0AE0B" strokeWidth={3} />
      <Circle r={86} fill="#FFF7D6" />
      {Array.from({ length: SEGMENTS }, (_, i) => (
        <Path key={`b${i}`} d={segment(i)} fill="#FFD43B" stroke="#FFD43B" strokeWidth={9} strokeLinejoin="round" />
      ))}
      {Array.from({ length: SEGMENTS }, (_, i) => {
        // Each segment glows darker as the wave passes it.
        const at = i / SEGMENTS;
        const opacity = t.interpolate({
          inputRange: [0, at, Math.min(1, at + 0.3), 1],
          outputRange: [i === 0 ? 1 : 0, 1, 0, i === 0 ? 1 : 0],
          extrapolate: 'clamp',
        });
        return <AnimatedPath key={`g${i}`} d={segment(i)} fill="#EAA800" stroke="#EAA800" strokeWidth={9} strokeLinejoin="round" opacity={opacity} />;
      })}
      <Circle r={9} fill="#FFF7D6" />
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
  return <Slice size={size} />;
}

export function LemonLoader({ size = 64, delay = 300 }: { size?: number; delay?: number }) {
  const show = useDelayed(delay);
  const t = useLoop(2200, Easing.linear, true);
  if (!show) return <View style={{ width: size * 1.6, height: size * 2.4 }} />;
  // Toss: crouch, stretch on the way up, hang at the top, a tilted one-and-a-half flip, squash on landing,
  // a small bounce, and a ripple on the ground.
  const ip = (input: number[], output: number[]) => t.interpolate({ inputRange: input, outputRange: output });
  const keys = [0, 0.1, 0.18, 0.36, 0.46, 0.66, 0.7, 0.78, 0.86, 0.92, 1];
  const lift = ip(keys, [0, 0, -0.14, -0.46, -0.48, -0.04, 0, -0.06, 0, 0, 0].map((v) => v * size * 1.9));
  const sx = ip(keys, [1, 1.14, 0.9, 1, 1, 0.94, 1.16, 0.96, 1.03, 1, 1]);
  const sy = ip(keys, [1, 0.82, 1.14, 1, 1, 1.08, 0.8, 1.05, 0.97, 1, 1]);
  // keep the bottom on the ground while squashing
  const translateY = Animated.add(lift, Animated.multiply(Animated.subtract(1, sy), size / 2));
  const flip = t.interpolate({ inputRange: [0, 0.12, 0.4, 0.68, 1], outputRange: ['0deg', '0deg', '300deg', '540deg', '540deg'] });
  const tilt = t.interpolate({ inputRange: [0, 0.12, 0.4, 0.68, 1], outputRange: ['0deg', '0deg', '14deg', '0deg', '0deg'] });
  const shadowScale = ip([0, 0.1, 0.4, 0.46, 0.7, 1], [1.05, 1.05, 0.5, 0.5, 1.15, 1]);
  const shadowOpacity = ip([0, 0.1, 0.4, 0.46, 0.7, 1], [1, 1, 0.3, 0.3, 1, 1]);
  const ripple = ip([0, 0.68, 0.7, 0.92, 1], [0, 0, 0.9, 0, 0]);
  const rippleScale = ip([0, 0.68, 0.7, 0.92, 1], [0.6, 0.6, 0.7, 1.5, 1.5]);
  return (
    <View style={{ width: size * 1.6, height: size * 2.4, alignItems: 'center', justifyContent: 'flex-end' }} accessibilityRole="progressbar" accessibilityLabel="در حال بارگذاری">
      <Animated.View style={[styles.ripple, { width: size * 0.9, height: size * 0.2, bottom: size * 0.02, opacity: ripple, transform: [{ scale: rippleScale }] }]} />
      <Animated.View style={{ transform: [{ perspective: 600 }, { translateY }, { rotateX: tilt }, { rotateY: flip }, { scaleX: sx }, { scaleY: sy }] }}>
        <Slice size={size} />
      </Animated.View>
      <Animated.View style={[styles.shadow, { width: size * 0.8, opacity: shadowOpacity, transform: [{ scaleX: shadowScale }] }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  shadow: { height: 8, borderRadius: 999, backgroundColor: '#17201A22', marginTop: 6 },
  ripple: { position: 'absolute', borderRadius: 999, borderWidth: 2, borderColor: '#F5C518' },
});
