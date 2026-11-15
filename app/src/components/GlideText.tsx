/**
 * One line of text that, when it does not fit, glides once (slowly, a moment after it appears) to show its end, waits,
 * and comes back to its start; otherwise, and when the phone asks for less motion, it simply ends with «…».
 * Only a transform moves (on the native driver), so it costs nothing while still.
 */
import { useEffect, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, StyleSheet, View, type StyleProp, type TextStyle } from 'react-native';

import { Text } from './Text';

const START_DELAY = 1800;
const PAUSE = 1400;
const SPEED = 32; // px per second

export function GlideText({ children, style }: { children: string; style?: StyleProp<TextStyle> }) {
  const [box, setBox] = useState(0);
  const [full, setFull] = useState(0);
  const [gliding, setGliding] = useState(false);
  const x = useRef(new Animated.Value(0)).current;
  const overflow = full > 0 && box > 0 ? Math.ceil(full - box) : 0;

  useEffect(() => {
    if (overflow <= 2) return;
    let cancelled = false;
    let anim: Animated.CompositeAnimation | null = null;
    const timer = setTimeout(async () => {
      const reduce = await AccessibilityInfo.isReduceMotionEnabled().catch(() => false);
      if (cancelled || reduce) return;
      setGliding(true);
      const ms = (overflow / SPEED) * 1000;
      x.setValue(0);
      // Right-to-left text starts at the right; its hidden end is on the left, so the line moves right to show it.
      anim = Animated.sequence([
        Animated.timing(x, { toValue: overflow, duration: ms, easing: Easing.inOut(Easing.quad), useNativeDriver: true }),
        Animated.delay(PAUSE),
        Animated.timing(x, { toValue: 0, duration: Math.min(ms, 900), easing: Easing.out(Easing.quad), useNativeDriver: true }),
      ]);
      anim.start(() => !cancelled && setGliding(false));
    }, START_DELAY);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      anim?.stop();
    };
  }, [overflow, x]);

  return (
    <View style={styles.box} onLayout={(e) => setBox(e.nativeEvent.layout.width)}>
      {/* Measures the whole line without wrapping. */}
      <View style={styles.measure} pointerEvents="none" importantForAccessibility="no-hide-descendants" accessibilityElementsHidden>
        <Text style={[style, styles.hidden]} numberOfLines={1} onLayout={(e) => setFull(e.nativeEvent.layout.width)}>
          {children}
        </Text>
      </View>
      {gliding ? (
        <Animated.View style={{ width: full, alignSelf: 'flex-end', transform: [{ translateX: x }] }}>
          <Text style={style} numberOfLines={1}>
            {children}
          </Text>
        </Animated.View>
      ) : (
        <Text style={style} numberOfLines={1}>
          {children}
        </Text>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  box: { overflow: 'hidden', alignSelf: 'stretch' },
  measure: { position: 'absolute', right: 0, top: 0, width: 4000, alignItems: 'flex-end', opacity: 0 },
  hidden: { flexShrink: 0 },
});
