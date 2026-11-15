/**
 * The calm top of the practice pages (tests, exam, flashcards, mistakes notebook): back, an icon in a lemon circle,
 * the page's name with a short status line under it, then extras (a timer, a flag) and the progress lemon at the far end.
 */
import { router } from 'expo-router';
import type { ReactNode } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { colors, rtl } from '../theme';
import { Icon, type IconName } from './Icon';
import { Text } from './Text';

export function PageHeader({
  icon,
  title,
  status,
  extra,
  lemon,
}: {
  icon: IconName;
  title: string;
  /** «تست ۳ از ۴۸» */
  status?: string;
  /** Beside the title: a timer, a flag, a share button. */
  extra?: ReactNode;
  /** The progress lemon (tap it to jump to any item). */
  lemon?: ReactNode;
}) {
  return (
    <View style={styles.row}>
      <Pressable
        accessibilityRole="button"
        accessibilityLabel="بازگشت"
        onPress={() => (router.canGoBack() ? router.back() : router.replace('/home'))}
        style={styles.back}
        hitSlop={6}
      >
        <Icon name="arrow-right" size={20} />
      </Pressable>
      <View style={styles.circle}>
        <Icon name={icon} size={19} />
      </View>
      <View style={styles.text}>
        <Text style={[styles.title, rtl]} numberOfLines={1}>{title}</Text>
        {!!status && <Text style={[styles.status, rtl]} numberOfLines={1}>{status}</Text>}
      </View>
      {extra}
      {lemon}
    </View>
  );
}

/** The timer of an exam, as a dark chip («۱۲:۴۰»); red in the last minute. */
export function TimerChip({ text, urgent }: { text: string; urgent?: boolean }) {
  return (
    <View style={[styles.chip, urgent && { backgroundColor: colors.red }]} accessibilityLabel={`زمان مانده ${text}`}>
      <Text style={[styles.chipText, urgent && { color: '#fff' }]}>{text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, paddingHorizontal: 14, paddingTop: 10, paddingBottom: 8 },
  back: { width: 40, height: 40, borderRadius: 12, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line, alignItems: 'center', justifyContent: 'center' },
  circle: { width: 38, height: 38, borderRadius: 19, backgroundColor: colors.lemonSoft, borderWidth: 1.5, borderColor: colors.lemon, alignItems: 'center', justifyContent: 'center' },
  text: { flex: 1, minWidth: 0 },
  title: { fontSize: 15, fontWeight: '900', color: colors.ink },
  status: { fontSize: 12, color: colors.muted },
  chip: { backgroundColor: colors.ink, borderRadius: 10, paddingHorizontal: 10, paddingVertical: 4 },
  chipText: { fontSize: 15, fontWeight: '900', color: colors.lemon, fontVariant: ['tabular-nums'] },
});
