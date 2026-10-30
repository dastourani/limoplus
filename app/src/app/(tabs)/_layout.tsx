import { router, Slot, usePathname } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Text } from '../../components/Text';
import { colors } from '../../theme';

const TABS = [
  { href: '/home', label: 'خانه', icon: '⌂' },
  { href: '/library', label: 'کتابخانه', icon: '▤' },
  { href: '/stats', label: 'آمار', icon: '▥' },
  { href: '/profile', label: 'پروفایل', icon: '◉' },
] as const;

/** The four main tabs, right to left, with the lemon highlight on the active one. */
export default function TabsLayout() {
  const path = usePathname();
  const insets = useSafeAreaInsets();
  return (
    <View style={{ flex: 1, backgroundColor: colors.ground }}>
      <View style={{ flex: 1 }}>
        <Slot />
      </View>
      <View style={[styles.bar, { paddingBottom: Math.max(insets.bottom, 8) }]}>
        {TABS.map((tab) => {
          const on = path === tab.href || path.startsWith(`${tab.href}/`);
          return (
            <Pressable
              key={tab.href}
              accessibilityRole="tab"
              accessibilityState={{ selected: on }}
              accessibilityLabel={tab.label}
              onPress={() => !on && router.replace(tab.href)}
              style={styles.tab}
            >
              <View style={[styles.iconWrap, on && styles.iconOn]}>
                <Text style={[styles.icon, on && { color: colors.ink }]}>{tab.icon}</Text>
              </View>
              <Text style={[styles.label, on && styles.labelOn]}>{tab.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: 'row-reverse', backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 6 },
  tab: { flex: 1, alignItems: 'center', gap: 2, paddingVertical: 2 },
  iconWrap: { width: 52, height: 30, borderRadius: 999, alignItems: 'center', justifyContent: 'center' },
  iconOn: { backgroundColor: colors.lemon },
  icon: { fontSize: 18, color: colors.muted },
  label: { fontSize: 11, color: colors.muted },
  labelOn: { color: colors.ink, fontWeight: '800' },
});
