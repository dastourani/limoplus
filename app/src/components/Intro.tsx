/**
 * Opening animation (cold start only): the lemon from the splash screen grows until it fills the screen and the app
 * appears from inside it. Not shown when returning from another app, and only a quick fade with «reduce motion».
 */
import { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, StyleSheet, useWindowDimensions } from 'react-native';

import { colors } from '../theme';
import { LemonSlice } from './LemonSlice';

let played = false;
const SIZE = 160;

export function Intro() {
  const [show, setShow] = useState(!played);
  const t = useRef(new Animated.Value(0)).current;
  const { width, height } = useWindowDimensions();

  useEffect(() => {
    if (played) return;
    played = true;
    AccessibilityInfo.isReduceMotionEnabled()
      .catch(() => false)
      .then((reduce) => {
        Animated.timing(t, {
          toValue: 1,
          duration: reduce ? 200 : 800,
          easing: Easing.in(Easing.cubic),
          useNativeDriver: true,
        }).start(() => setShow(false));
      });
  }, [t]);

  if (!show) return null;
  const cover = (Math.hypot(width, height) / SIZE) * 1.15;
  const scale = t.interpolate({ inputRange: [0, 0.15, 1], outputRange: [1, 0.9, cover] });
  const opacity = t.interpolate({ inputRange: [0, 0.75, 1], outputRange: [1, 1, 0] });
  const groundOpacity = t.interpolate({ inputRange: [0, 0.55, 0.7], outputRange: [1, 1, 0] });
  return (
    <Animated.View pointerEvents="none" style={[StyleSheet.absoluteFill, styles.wrap, { opacity }]}>
      <Animated.View style={[StyleSheet.absoluteFill, { backgroundColor: colors.ink, opacity: groundOpacity }]} />
      <Animated.View style={{ transform: [{ scale }] }}>
        <LemonSlice size={SIZE} />
      </Animated.View>
    </Animated.View>
  );
}

const styles = StyleSheet.create({
  wrap: { alignItems: 'center', justifyContent: 'center', zIndex: 2000, elevation: 20 },
});
