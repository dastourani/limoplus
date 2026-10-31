import { Pressable, StyleSheet, View } from 'react-native';

import { colors, toPersianDigits } from '../theme';
import type { PartState } from './LemonProgress';
import { Text } from './Text';
import { Sheet } from './ui';

const LOOK: Record<PartState, { bg: string; fg: string; border: string }> = {
  empty: { bg: colors.surface, fg: colors.muted, border: colors.line },
  done: { bg: '#FFD43B', fg: colors.ink, border: '#FFD43B' },
  soft: { bg: '#FFF1B8', fg: colors.ink, border: '#FFE070' },
  wrong: { bg: '#FBE7E6', fg: '#9E2F2A', border: '#F49B93' },
};

/** Numbered grid of all questions; tap one to jump to it. Opened from the lemon progress. */
export function QuestionPicker({
  visible,
  onClose,
  parts,
  current,
  onPick,
  legend,
}: {
  visible: boolean;
  onClose: () => void;
  parts: PartState[];
  current: number;
  onPick: (i: number) => void;
  legend?: string;
}) {
  return (
    <Sheet visible={visible} onClose={onClose} title="رفتن به سؤال">
      {!!legend && <Text style={styles.legend}>{legend}</Text>}
      <View style={styles.grid}>
        {parts.map((p, i) => {
          const look = LOOK[p];
          const now = i === current;
          return (
            <Pressable
              key={i}
              onPress={() => {
                onClose();
                onPick(i);
              }}
              style={[styles.cell, { backgroundColor: look.bg, borderColor: now ? colors.ink : look.border }, now && styles.now]}
              accessibilityRole="button"
              accessibilityLabel={`سؤال ${i + 1}`}
            >
              <Text style={[styles.num, { color: look.fg }]}>{toPersianDigits(i + 1)}</Text>
            </Pressable>
          );
        })}
      </View>
    </Sheet>
  );
}

const styles = StyleSheet.create({
  legend: { fontSize: 12, color: colors.muted, textAlign: 'right', marginBottom: 10 },
  grid: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8, paddingBottom: 8 },
  cell: { width: 44, height: 44, borderRadius: 14, borderWidth: 1.5, alignItems: 'center', justifyContent: 'center' },
  now: { borderWidth: 2.5 },
  num: { fontSize: 14, fontWeight: '800' },
});
