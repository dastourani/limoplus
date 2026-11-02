/** A horizontal row that starts at the right (Persian), drawn lazily: only the cards near the screen are made. */
import { FlatList, StyleSheet, View } from 'react-native';
import type { ReactElement } from 'react';

export function HRow<T>({ data, keyOf, render, gap = 12, initial = 3 }: { data: T[]; keyOf: (item: T) => string; render: (item: T) => ReactElement; gap?: number; initial?: number }) {
  return (
    <FlatList
      horizontal
      data={data}
      keyExtractor={keyOf}
      renderItem={({ item }) => <View style={styles.flip}>{render(item)}</View>}
      showsHorizontalScrollIndicator={false}
      style={styles.row}
      contentContainerStyle={{ gap, paddingHorizontal: 20 }}
      initialNumToRender={initial}
      // A screen and a half on each side is made ahead, so swiping a shelf rarely meets a cover still being made.
      windowSize={5}
      maxToRenderPerBatch={2}
      removeClippedSubviews
    />
  );
}

const styles = StyleSheet.create({
  // Flipped so the first card is on the right; each card is flipped back.
  row: { marginHorizontal: -20, flexGrow: 0, transform: [{ scaleX: -1 }] },
  flip: { transform: [{ scaleX: -1 }] },
});
