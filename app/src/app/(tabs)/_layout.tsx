import { router, Slot, usePathname } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Icon, type IconName } from '../../components/Icon';
import { Text } from '../../components/Text';
import { colors } from '../../theme';

// Right to left: home is the rightmost tab.
const TABS: { href: '/home' | '/library' | '/stats' | '/profile'; label: string; icon: IconName }[] = [
  { href: '/home', label: 'خانه', icon: 'house' },
  { href: '/library', label: 'کتابخانه', icon: 'library-big' },
  { href: '/stats', label: 'آمار', icon: 'chart-column' },
  { href: '/profile', label: 'پروفایل', icon: 'circle-user-round' },
];

/** Bottom tabs: icons only; the active one sits in a lemon capsule with its name underneath. */
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
              <View style={[styles.capsule, on && styles.capsuleOn]}>
                <Icon name={tab.icon} size={24} color={on ? colors.ink : colors.muted} strokeWidth={on ? 2.3 : 1.7} />
              </View>
              <Text style={[styles.label, !on && styles.hidden]}>{tab.label}</Text>
            </Pressable>
          );
        })}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: 'row-reverse', backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 8 },
  tab: { flex: 1, alignItems: 'center', gap: 3 },
  capsule: { width: 58, height: 34, borderRadius: 999, alignItems: 'center', justifyContent: 'center' },
  capsuleOn: { backgroundColor: colors.lemon },
  label: { fontSize: 12, fontWeight: '700', color: colors.ink, height: 18 },
  hidden: { opacity: 0 },
});
