/**
 * The app's loading indicators, drawn from the lemon slice:
 * - <LemonLoader />: a lemon slice tossed up, flipping in the air and landing, while its segments light up in turn.
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
  const t = useLoop(2000, Easing.linear, true);
  if (!show) return <View style={{ width: size * 1.6, height: size * 2.4 }} />;
  // Up and down (fast at the bottom, slow at the top), flipping like a tossed coin.
  const translateY = t.interpolate({ inputRange: [0, 0.45, 1], outputRange: [0, -size, 0], easing: Easing.out(Easing.quad) });
  // Half a turn per toss, like a coin flipped gently (a full turn looked too fast).
  const rotate = t.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '180deg'] });
  const scaleX = t.interpolate({ inputRange: [0, 0.5, 1], outputRange: [1, 0.35, 1] });
  const shadow = t.interpolate({ inputRange: [0, 0.45, 1], outputRange: [1, 0.45, 1] });
  return (
    <View style={{ width: size * 1.6, height: size * 2.4, alignItems: 'center', justifyContent: 'flex-end' }} accessibilityRole="progressbar" accessibilityLabel="در حال بارگذاری">
      <Animated.View style={{ transform: [{ translateY }, { rotate }, { scaleX }] }}>
        <Slice size={size} />
      </Animated.View>
      <Animated.View style={[styles.shadow, { width: size * 0.8, transform: [{ scale: shadow }] }]} />
    </View>
  );
}

const styles = StyleSheet.create({
  shadow: { height: 8, borderRadius: 999, backgroundColor: '#17201A22', marginTop: 6 },
});
