/**
 * Flashcard puzzle: each card of a chapter is one piece of a lemon picture. A piece falls into place when its card
 * is mastered (Leitner box 4+); when every piece is in, the picture is complete.
 */
import { useEffect, useRef } from 'react';
import { Animated, StyleSheet, View } from 'react-native';

import { colors } from '../theme';
import { LemonSlice } from './LemonSlice';

function Piece({ filled, size, row, col, cols, rows }: { filled: boolean; size: number; row: number; col: number; cols: number; rows: number }) {
  const v = useRef(new Animated.Value(filled ? 1 : 0)).current;
  const first = useRef(true);
  useEffect(() => {
    if (first.current) {
      first.current = false;
      return;
    }
    // A newly mastered card: the piece drops in and settles.
    v.setValue(0);
    Animated.spring(v, { toValue: filled ? 1 : 0, friction: 4, tension: 120, useNativeDriver: true }).start();
  }, [filled, v]);
  const full = Math.max(cols, rows) * size;
  return (
    <View style={[styles.slot, { width: size, height: size }]}>
      <Animated.View
        style={{
          width: size,
          height: size,
          overflow: 'hidden',
          borderRadius: size * 0.18,
          opacity: v,
          transform: [{ scale: v.interpolate({ inputRange: [0, 1], outputRange: [1.6, 1] }) }],
        }}
      >
        <View style={{ position: 'absolute', left: -col * size, top: -row * size }}>
          <LemonSlice size={full} />
        </View>
      </Animated.View>
    </View>
  );
}

export function Puzzle({ total, mastered, size = 140 }: { total: number; mastered: Set<number> | number[]; size?: number }) {
  const filledIndexes = Array.isArray(mastered) ? new Set(mastered) : mastered;
  const cols = Math.ceil(Math.sqrt(total));
  const rows = Math.ceil(total / cols);
  const piece = Math.floor(size / Math.max(cols, rows));
  return (
    <View style={[styles.board, { width: cols * piece + 12, padding: 5 }]} accessibilityLabel={`پازل: ${filledIndexes.size} از ${total}`}>
      {Array.from({ length: total }, (_, i) => (
        <Piece key={i} filled={filledIndexes.has(i)} size={piece} row={Math.floor(i / cols)} col={i % cols} cols={cols} rows={rows} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  board: { flexDirection: 'row', flexWrap: 'wrap', backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.line, alignSelf: 'center' },
  slot: { borderWidth: 0.5, borderColor: '#E3E8DE', borderStyle: 'dashed', borderRadius: 6 },
});
