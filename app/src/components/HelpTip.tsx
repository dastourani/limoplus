/** A small «؟» that opens a bubble right next to it explaining a number or a word on the screen; a tap anywhere
 *  closes it. The bubble stays inside the window and above the phone's own buttons (it opens upwards when there is
 *  no room below). */
import { useState } from 'react';
import { Modal, Platform, Pressable, StyleSheet, View, useWindowDimensions, type GestureResponderEvent } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, rtl } from '../theme';
import { Text } from './Text';

const ARROW = 7;

export function HelpTip({ title, text, size = 22 }: { title: string; text: string; size?: number }) {
  const [at, setAt] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);
  const [bubbleH, setBubbleH] = useState(0);
  const win = useWindowDimensions();
  const insets = useSafeAreaInsets();
  // Where the «؟» is on the screen: the browser gives the button's box; a phone gives the touch point, from which
  // the spot inside the button is taken away.
  const open = (e: GestureResponderEvent) => {
    const el = e.currentTarget as unknown as { getBoundingClientRect?: () => { left: number; top: number; width: number; height: number } };
    if (Platform.OS === 'web' && el?.getBoundingClientRect) {
      const r = el.getBoundingClientRect();
      setAt({ x: r.left, y: r.top, w: r.width, h: r.height });
      return;
    }
    const { pageX, pageY, locationX, locationY } = e.nativeEvent;
    setAt({ x: pageX - locationX, y: pageY - locationY, w: size, h: size });
  };
  const close = () => {
    setAt(null);
    setBubbleH(0);
  };

  const width = Math.min(320, win.width - 24);
  let left = 0;
  let top = 0;
  let below = true;
  if (at) {
    const cx = at.x + at.w / 2;
    left = Math.max(12, Math.min(win.width - width - 12, cx - width / 2));
    const room = win.height - insets.bottom - (at.y + at.h) - 12;
    below = !bubbleH || bubbleH + ARROW <= room || at.y < room;
    top = below ? at.y + at.h + ARROW : at.y - ARROW - bubbleH;
  }
  const arrowLeft = at ? Math.max(14, Math.min(width - 14, at.x + at.w / 2 - left)) - ARROW : 0;

  return (
    <>
      <Pressable
        onPress={open}
        hitSlop={10}
        accessibilityRole="button"
        accessibilityLabel={`${title} یعنی چه؟`}
        style={[styles.q, { width: size, height: size, borderRadius: size / 2 }, !!at && styles.qOn]}
      >
        <Text style={[styles.qText, { fontSize: Math.round(size * 0.55) }, !!at && { color: colors.ink }]}>؟</Text>
      </Pressable>
      <Modal visible={!!at} transparent animationType="fade" onRequestClose={close} statusBarTranslucent>
        <Pressable style={StyleSheet.absoluteFill} onPress={close} accessibilityLabel="بستن" />
        {!!at && (
          <View
            style={[styles.bubble, { width, left, top, opacity: bubbleH ? 1 : 0 }]}
            onLayout={(e) => setBubbleH(e.nativeEvent.layout.height)}
            accessibilityViewIsModal
          >
            <View style={[styles.arrow, below ? styles.arrowUp : styles.arrowDown, { left: arrowLeft }]} />
            <Text style={[styles.title, rtl]}>{title}</Text>
            <Text style={[styles.text, rtl]}>{text}</Text>
          </View>
        )}
      </Modal>
    </>
  );
}

const styles = StyleSheet.create({
  q: {
    borderWidth: 1,
    borderColor: colors.line,
    alignItems: 'center',
    justifyContent: 'center',
    backgroundColor: colors.surface,
  },
  qOn: { backgroundColor: colors.lemon, borderColor: colors.lemon },
  qText: { fontWeight: '800', color: colors.muted },
  bubble: {
    position: 'absolute',
    backgroundColor: colors.ink,
    borderRadius: 14,
    paddingHorizontal: 14,
    paddingVertical: 12,
    gap: 4,
    shadowColor: '#000',
    shadowOpacity: 0.18,
    shadowRadius: 12,
    shadowOffset: { width: 0, height: 4 },
    elevation: 8,
  },
  arrow: {
    position: 'absolute',
    width: 0,
    height: 0,
    borderLeftWidth: ARROW,
    borderRightWidth: ARROW,
    borderLeftColor: 'transparent',
    borderRightColor: 'transparent',
  },
  arrowUp: {
    top: -ARROW,
    borderBottomWidth: ARROW,
    borderBottomColor: colors.ink,
  },
  arrowDown: {
    bottom: -ARROW,
    borderTopWidth: ARROW,
    borderTopColor: colors.ink,
  },
  title: { fontSize: 13, fontWeight: '800', color: colors.lemon },
  text: { fontSize: 13, lineHeight: 22, color: '#FFFFFF' },
});
