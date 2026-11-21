import { useCallback, useRef } from 'react';
import { Animated, Easing, useWindowDimensions } from 'react-native';

/**
 * Page turn between questions: the page leaves to one side with a paper tilt and the next one swings in from the
 * other side. After a finger flick the page has already left (inside the web view), so only the arrival is played.
 */
export function usePageTurn() {
  const { width } = useWindowDimensions();
  const page = useRef(new Animated.Value(0)).current;
  const busy = useRef(false);

  const turn = useCallback(
    (forward: boolean, swap: () => void, alreadyOut = false) => {
      if (busy.current) return;
      busy.current = true;
      const arrive = () => {
        swap();
        page.setValue(forward ? -1 : 1);
        Animated.timing(page, { toValue: 0, duration: 280, easing: Easing.out(Easing.back(1.1)), useNativeDriver: true }).start(() => {
          busy.current = false;
        });
      };
      if (alreadyOut) arrive();
      else Animated.timing(page, { toValue: forward ? 1 : -1, duration: 170, easing: Easing.in(Easing.quad), useNativeDriver: true }).start(arrive);
    },
    [page],
  );

  // Forward = the page goes right (Persian book), the next comes from the left.
  const style = {
    opacity: page.interpolate({ inputRange: [-1, -0.6, 0, 0.6, 1], outputRange: [0, 0.6, 1, 0.6, 0] }),
    transform: [
      { perspective: 1000 },
      { translateX: page.interpolate({ inputRange: [-1, 0, 1], outputRange: [-width * 0.6, 0, width * 0.6] }) },
      { rotateY: page.interpolate({ inputRange: [-1, 0, 1], outputRange: ['-38deg', '0deg', '38deg'] }) },
      { scale: page.interpolate({ inputRange: [-1, 0, 1], outputRange: [0.9, 1, 0.9] }) },
    ],
  };
  return { style, turn };
}
