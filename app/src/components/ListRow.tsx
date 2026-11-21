import type { ReactNode } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { colors, radius, rtl, type } from '../theme';
import { Icon, IconBadge, type IconName } from './Icon';
import { Text } from './Text';

/**
 * One row of a list (library, mistakes notebook, exam history…): the same frame everywhere. Icon and title on the
 * right, a short line under the title, a value or action on the left, and a chevron when the row opens something.
 */
export function ListRow({
  title,
  subtitle,
  icon,
  value,
  onPress,
  chevron = false,
  accessibilityLabel,
}: {
  title: string;
  subtitle?: string | null;
  icon?: IconName;
  /** A number, a short state or a small button, on the left. */
  value?: ReactNode;
  onPress?: () => void;
  chevron?: boolean;
  accessibilityLabel?: string;
}) {
  // A button on the left (e.g. «ادامه») goes beside the row's own button, not inside it (no button within a button).
  if (onPress && value != null && typeof value !== 'string') {
    return (
      <View style={styles.row}>
        <Pressable
          onPress={onPress}
          style={({ pressed }) => [styles.main, pressed && { opacity: 0.8 }]}
          accessibilityRole="button"
          accessibilityLabel={accessibilityLabel}
        >
          {!!icon && <IconBadge name={icon} size={38} />}
          <View style={styles.text}>
            <Text style={[styles.title, rtl]} numberOfLines={2}>{title}</Text>
            {!!subtitle && <Text style={[styles.subtitle, rtl]} numberOfLines={2}>{subtitle}</Text>}
          </View>
        </Pressable>
        {value}
        {chevron && <Icon name="chevron-left" size={20} color={colors.muted} />}
      </View>
    );
  }
  return (
    <Pressable
      onPress={onPress}
      disabled={!onPress}
      style={({ pressed }) => [styles.row, pressed && { opacity: 0.8 }]}
      accessibilityRole={onPress ? 'button' : undefined}
      accessibilityLabel={accessibilityLabel}
    >
      {!!icon && <IconBadge name={icon} size={38} />}
      <View style={styles.text}>
        <Text style={[styles.title, rtl]} numberOfLines={2}>{title}</Text>
        {!!subtitle && <Text style={[styles.subtitle, rtl]} numberOfLines={2}>{subtitle}</Text>}
      </View>
      {typeof value === 'string' ? <Text style={styles.value}>{value}</Text> : value}
      {chevron && <Icon name="chevron-left" size={20} color={colors.muted} />}
    </Pressable>
  );
}

/** A count on the left of a row: a small lemon pill. */
export function RowCount({ n, label }: { n: string; label?: string }) {
  return <Text style={styles.count} accessibilityLabel={label}>{n}</Text>;
}

const styles = StyleSheet.create({
  main: { flex: 1, flexDirection: 'row-reverse', alignItems: 'center', gap: 12, alignSelf: 'stretch' },
  row: {
    flexDirection: 'row-reverse',
    alignItems: 'center',
    gap: 12,
    minHeight: 68,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line,
    paddingHorizontal: 14,
    paddingVertical: 12,
  },
  text: { flex: 1, gap: 3 },
  title: { fontSize: type.body, fontWeight: '800', color: colors.ink },
  subtitle: { fontSize: type.caption, color: colors.muted, lineHeight: 19 },
  value: { fontSize: type.title, fontWeight: '800', color: colors.greenDark },
  count: { minWidth: 26, textAlign: 'center', paddingHorizontal: 8, paddingVertical: 2, borderRadius: 999, backgroundColor: colors.lemon, color: colors.ink, fontWeight: '800', fontSize: type.small, overflow: 'hidden' },
});
