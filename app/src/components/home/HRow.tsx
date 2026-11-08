/**
 * A horizontal row that starts at the right (Persian), drawn lazily: only the cards near the screen are made.
 * With a mouse (web) there is no swiping, so arrows at both ends move the row a page at a time.
 */
import { useRef, useState, type ReactElement } from 'react';
import { FlatList, Platform, Pressable, StyleSheet, View } from 'react-native';

import { colors } from '../../theme';
import { Icon } from '../Icon';

export function HRow<T>({ data, keyOf, render, gap = 12, initial = 3 }: { data: T[]; keyOf: (item: T) => string; render: (item: T) => ReactElement; gap?: number; initial?: number }) {
  const list = useRef<FlatList<T>>(null);
  const [at, setAt] = useState({ x: 0, width: 0, content: 0 });
  const web = Platform.OS === 'web';
  // The row is flipped: a larger offset shows cards further to the left (later in the list).
  const go = (dir: 1 | -1) => {
    const x = Math.max(0, Math.min(at.content - at.width, at.x + dir * Math.max(200, at.width * 0.8)));
    list.current?.scrollToOffset({ offset: x, animated: true });
  };
  const more = at.width > 0 && at.content - at.width - at.x > 24;
  const back = at.x > 4;
  return (
    <View>
      <FlatList
        ref={list}
        horizontal
        data={data}
        keyExtractor={keyOf}
        renderItem={({ item }) => <View style={styles.flip}>{render(item)}</View>}
        showsHorizontalScrollIndicator={false}
        style={styles.row}
        contentContainerStyle={{ gap, paddingHorizontal: 16 }}
        initialNumToRender={web ? data.length : initial}
        // A screen and a half on each side is made ahead, so swiping a shelf rarely meets a cover still being made.
        windowSize={5}
        maxToRenderPerBatch={2}
        removeClippedSubviews={!web}
        onLayout={web ? (e) => setAt((a) => ({ ...a, width: e.nativeEvent.layout.width - 32 })) : undefined}
        onContentSizeChange={web ? (w) => setAt((a) => ({ ...a, content: w - 32 })) : undefined}
        onScroll={web ? (e) => setAt((a) => ({ ...a, x: e.nativeEvent.contentOffset.x })) : undefined}
        scrollEventThrottle={web ? 50 : undefined}
      />
      {web && more && (
        <Pressable onPress={() => go(1)} style={[styles.arrow, { left: -6 }]} accessibilityRole="button" accessibilityLabel="بعدی‌ها">
          <Icon name="chevron-left" size={22} color={colors.ink} />
        </Pressable>
      )}
      {web && back && (
        <Pressable onPress={() => go(-1)} style={[styles.arrow, { right: -6 }]} accessibilityRole="button" accessibilityLabel="قبلی‌ها">
          <Icon name="chevron-right" size={22} color={colors.ink} />
        </Pressable>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  // Flipped so the first card is on the right; each card is flipped back.
  row: { marginHorizontal: -16, flexGrow: 0, transform: [{ scaleX: -1 }] },
  flip: { transform: [{ scaleX: -1 }] },
  arrow: {
    position: 'absolute', top: '40%', width: 40, height: 40, borderRadius: 20, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line,
    alignItems: 'center', justifyContent: 'center', shadowColor: '#000', shadowOpacity: 0.12, shadowRadius: 8, elevation: 3,
  },
});
