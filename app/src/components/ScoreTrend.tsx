import { StyleSheet, View } from 'react-native';

import { colors, toPersianDigits } from '../theme';

/** Scores of the latest exams as small bars, oldest on the right (the reading direction). */
export function ScoreTrend({ scores, height = 54 }: { scores: number[]; height?: number }) {
  if (scores.length < 2) return null;
  return (
    <View style={[styles.trend, { height }]} accessibilityLabel={`روند نمره‌ها: ${scores.map((s) => toPersianDigits(Math.round(s))).join('، ')}`}>
      {scores.map((s, i) => (
        <View key={i} style={[styles.bar, { height: Math.max(3, (Math.max(0, s) / 100) * height), backgroundColor: i === scores.length - 1 ? '#E0B000' : colors.lemon, opacity: i === scores.length - 1 ? 1 : 0.6 }]} />
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  trend: { flexDirection: 'row-reverse', alignItems: 'flex-end', gap: 4 },
  bar: { flex: 1, borderRadius: 3, backgroundColor: colors.lemon },
});
