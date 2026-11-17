/** A small «؟» (or any wrapped icon/lemon) that opens a bubble right next to it explaining a number, word or status on
 *  the screen; a tap anywhere (or moving the mouse away after hovering on the web) closes it. The bubble stays inside
 *  the window and above the phone's own buttons (it opens upwards when there is no room below). */
import { useRef, useState, type ReactNode } from 'react';
import { Modal, Platform, Pressable, StyleSheet, View, useWindowDimensions, type GestureResponderEvent } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, rtl } from '../theme';
import { Text } from './Text';

const ARROW = 7;

export function HelpTip({
  title,
  text,
  size = 22,
  action,
  children,
}: {
  title: string;
  text: string;
  size?: number;
  /** Optional link/button inside the bubble (e.g. «صفحه‌ی کتاب ←»). */
  action?: { label: string; onPress: () => void };
  /** Custom trigger (e.g. a lemon or the offline icon) instead of the default «؟» badge. */
  children?: ReactNode;
}) {
  const [at, setAt] = useState<{
    x: number;
    y: number;
    w: number;
    h: number;
  } | null>(null);
  const [bubbleH, setBubbleH] = useState(0);
  const byHover = useRef(false);
  const win = useWindowDimensions();
  const insets = useSafeAreaInsets();
  // Where the trigger is on the screen: the browser gives the button's box; a phone gives the touch point, from which
  // the spot inside the button is taken away.
  const open = (e: GestureResponderEvent, hover = false) => {
    byHover.current = hover;
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
    byHover.current = false;
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

  // On the web, if opened by hovering, moving the pointer away from both the trigger and the bubble closes it smoothly.
  const webBackdropProps =
    Platform.OS === 'web'
      ? ({
          onMouseMove: (e: { nativeEvent?: { clientX?: number; clientY?: number }; clientX?: number; clientY?: number }) => {
            if (!byHover.current || !at) return;
            const mx = e.nativeEvent?.clientX ?? e.clientX ?? 0;
            const my = e.nativeEvent?.clientY ?? e.clientY ?? 0;
            const pad = 24;
            const minX = Math.min(at.x, left) - pad;
            const maxX = Math.max(at.x + at.w, left + width) + pad;
            const minY = Math.min(at.y, top) - pad;
            const maxY = Math.max(at.y + at.h, top + (bubbleH || 120)) + pad;
            if (mx < minX || mx > maxX || my < minY || my > maxY) close();
          },
        } as Record<string, unknown>)
      : undefined;

  return (
    <>
      <Pressable
        onPress={(e) => open(e, false)}
        onHoverIn={Platform.OS === 'web' ? (e) => open(e as unknown as GestureResponderEvent, true) : undefined}
        hitSlop={children ? 6 : 10}
        accessibilityRole="button"
        accessibilityLabel={`${title} یعنی چه؟`}
        style={children ? undefined : [styles.q, { width: size, height: size, borderRadius: size / 2 }, !!at && styles.qOn]}
      >
        {children ? (
          <View pointerEvents="none">{children}</View>
        ) : (
          <Text style={[styles.qText, { fontSize: Math.round(size * 0.55) }, !!at && { color: colors.ink }]}>؟</Text>
        )}
      </Pressable>
      <Modal visible={!!at} transparent animationType="fade" onRequestClose={close} statusBarTranslucent>
        <Pressable style={StyleSheet.absoluteFill} onPress={close} accessibilityLabel="بستن" {...webBackdropProps} />
        {!!at && (
          <View
            style={[styles.bubble, { width, left, top, opacity: bubbleH ? 1 : 0 }]}
            onLayout={(e) => setBubbleH(e.nativeEvent.layout.height)}
            accessibilityViewIsModal
          >
            <View style={[styles.arrow, below ? styles.arrowUp : styles.arrowDown, { left: arrowLeft }]} />
            <Text style={[styles.title, rtl]}>{title}</Text>
            <Text style={[styles.text, rtl]}>{text}</Text>
            {!!action && (
              <Pressable
                onPress={() => {
                  close();
                  action.onPress();
                }}
                style={styles.action}
                accessibilityRole="button"
              >
                <Text style={[styles.actionText, rtl]}>{action.label}</Text>
              </Pressable>
            )}
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
  action: {
    alignSelf: 'flex-start',
    marginTop: 4,
    paddingHorizontal: 10,
    paddingVertical: 4,
    borderRadius: 999,
    backgroundColor: 'rgba(255, 212, 59, 0.16)',
  },
  actionText: { fontSize: 12, fontWeight: '800', color: colors.lemon },
});
