import { Pressable, StyleSheet, View, type StyleProp, type ViewStyle } from 'react-native';

import { colors, toPersianDigits, type } from '../theme';
import { Text } from './Text';

/**
 * A filter or a choice among a few: the same look on every page (library tabs, search, mistakes, exams, the quiz's
 * order, exam results). Chosen: dark with lemon text; the rest: white with a thin line. `small` for choices inside a
 * card (a mistake's reason, the quiz's order).
 */
export function Pill({
  label,
  count,
  selected,
  onPress,
  small = false,
  style,
  role = 'button',
}: {
  label: string;
  count?: number | string;
  selected: boolean;
  onPress: () => void;
  small?: boolean;
  style?: StyleProp<ViewStyle>;
  role?: 'button' | 'tab' | 'radio';
}) {
  return (
    <Pressable
      onPress={onPress}
      style={({ pressed }) => [styles.pill, small && styles.small, selected && styles.on, pressed && { opacity: 0.75 }, style]}
      accessibilityRole={role}
      accessibilityState={role === 'radio' ? { checked: selected } : { selected }}
    >
      <Text style={[styles.text, small && styles.smallText, selected && styles.textOn]} numberOfLines={1}>
        {label}
      </Text>
      {count !== undefined && count !== null && (
        <View style={[styles.badge, selected ? styles.badgeOn : styles.badgeOff]}>
          <Text style={[styles.badgeText, selected ? styles.badgeTextOn : styles.badgeTextOff]}>
            {typeof count === 'number' ? toPersianDigits(count) : count}
          </Text>
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  pill: {
    flexDirection: 'row-reverse',
    alignItems: 'center',
    justifyContent: 'center',
    gap: 8,
    paddingHorizontal: 14,
    paddingVertical: 7,
    borderRadius: 999,
    borderWidth: 1,
    borderColor: colors.line,
    backgroundColor: colors.surface,
  },
  small: { paddingHorizontal: 12, paddingVertical: 5, gap: 6 },
  on: { backgroundColor: colors.ink, borderColor: colors.ink },
  text: { fontSize: type.small, fontWeight: '700', color: colors.ink },
  smallText: { fontSize: type.caption },
  textOn: { color: colors.lemon },
  badge: {
    minWidth: 20,
    height: 20,
    borderRadius: 10,
    paddingHorizontal: 6,
    alignItems: 'center',
    justifyContent: 'center',
  },
  badgeOn: {
    backgroundColor: 'rgba(245, 197, 24, 0.22)',
    borderWidth: 1,
    borderColor: 'rgba(245, 197, 24, 0.45)',
  },
  badgeOff: {
    backgroundColor: colors.ground,
    borderWidth: 1,
    borderColor: colors.line,
  },
  badgeText: {
    fontSize: 11,
    fontWeight: '800',
    lineHeight: 15,
  },
  badgeTextOn: {
    color: colors.lemon,
  },
  badgeTextOff: {
    color: colors.muted,
  },
});
