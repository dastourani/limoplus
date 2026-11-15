import { Pressable, StyleSheet, type StyleProp, type ViewStyle } from 'react-native';

import { colors, type } from '../theme';
import { Text } from './Text';

/**
 * A filter or a choice among a few: the same look on every page (library tabs, search, mistakes, exams, the quiz's
 * order, exam results). Chosen: dark with lemon text; the rest: white with a thin line. `small` for choices inside a
 * card (a mistake's reason, the quiz's order).
 */
export function Pill({
  label,
  selected,
  onPress,
  small = false,
  style,
  role = 'button',
}: {
  label: string;
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
    </Pressable>
  );
}

const styles = StyleSheet.create({
  pill: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface },
  small: { paddingHorizontal: 12, paddingVertical: 5 },
  on: { backgroundColor: colors.ink, borderColor: colors.ink },
  text: { fontSize: type.small, fontWeight: '700', color: colors.ink },
  smallText: { fontSize: type.caption },
  textOn: { color: colors.lemon },
});
