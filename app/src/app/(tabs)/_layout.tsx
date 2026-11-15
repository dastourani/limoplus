import { router, Slot, usePathname } from 'expo-router';
import { useEffect, useRef } from 'react';
import { Animated, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { Icon, type IconName } from '../../components/Icon';
import { LemonSlice } from '../../components/LemonSlice';
import { Text } from '../../components/Text';
import { useRoomy, useWide } from '../../lib/layout';
import { colors } from '../../theme';

// Right to left: home is the rightmost tab.
const TABS: { href: '/home' | '/library' | '/stats' | '/profile'; label: string; icon: IconName }[] = [
  { href: '/home', label: 'خانه', icon: 'house' },
  { href: '/library', label: 'کتابخانه', icon: 'library-big' },
  { href: '/stats', label: 'آمار', icon: 'chart-column' },
  { href: '/profile', label: 'پروفایل', icon: 'circle-user-round' },
];

const BAR = 58;

/**
 * Bottom tabs. Inactive: a larger icon centred in the bar, no label. Active: the icon moves up into a lemon capsule
 * and its name fades in underneath. The bar height never changes, so the screen does not jump.
 */
function Tab({ tab, on }: { tab: (typeof TABS)[number]; on: boolean }) {
  const v = useRef(new Animated.Value(on ? 1 : 0)).current;
  useEffect(() => {
    Animated.timing(v, { toValue: on ? 1 : 0, duration: 200, useNativeDriver: true }).start();
  }, [on, v]);
  const iconY = v.interpolate({ inputRange: [0, 1], outputRange: [0, -9] });
  const iconScale = v.interpolate({ inputRange: [0, 1], outputRange: [1.12, 1] });
  const labelY = v.interpolate({ inputRange: [0, 1], outputRange: [6, 0] });
  return (
    <Pressable
      accessibilityRole="tab"
      accessibilityState={{ selected: on }}
      accessibilityLabel={tab.label}
      onPress={() => !on && router.replace(tab.href)}
      style={styles.tab}
    >
      <Animated.View style={[styles.capsuleWrap, { transform: [{ translateY: iconY }, { scale: iconScale }] }]}>
        <Animated.View style={[styles.capsule, { opacity: v }]} />
        <View style={styles.iconLayer}>
          <Icon name={tab.icon} size={24} color={on ? colors.ink : colors.muted} strokeWidth={on ? 2.3 : 1.8} />
        </View>
      </Animated.View>
      <Animated.Text maxFontSizeMultiplier={1.3} style={[styles.label, { opacity: v, transform: [{ translateY: labelY }] }]}>{tab.label}</Animated.Text>
    </Pressable>
  );
}

/**
 * On a computer: a narrow rail down the right side (the lemon on top, then each place as an icon with its name under
 * it), so the page keeps the width. The current place sits in a lemon capsule, as in the phone's bar.
 */
function SideNav({ path }: { path: string }) {
  // A large screen has room: the menu opens out, icon and name side by side, with the app's name on top.
  if (useRoomy()) return <SideMenu path={path} />;
  return (
    <View style={styles.side} accessibilityRole="tablist">
      <View style={styles.brand} accessibilityLabel="لیموخوان">
        <LemonSlice size={36} />
      </View>
      {TABS.map((tab) => {
        const on = path === tab.href || path.startsWith(`${tab.href}/`);
        return (
          <Pressable
            key={tab.href}
            accessibilityRole="tab"
            accessibilityLabel={tab.label}
            accessibilityState={{ selected: on }}
            onPress={() => !on && router.replace(tab.href)}
            style={styles.sideItem}
          >
            {({ hovered, pressed }: { hovered?: boolean; pressed: boolean }) => (
              <>
                <View style={[styles.sidePill, on ? styles.sideOn : (hovered || pressed) && styles.sideHover]}>
                  <Icon name={tab.icon} size={22} color={colors.ink} strokeWidth={on ? 2.3 : 1.8} />
                </View>
                <Text style={[styles.sideText, on && { fontFamily: 'Vazirmatn_700Bold', color: colors.ink }]} numberOfLines={1}>
                  {tab.label}
                </Text>
              </>
            )}
          </Pressable>
        );
      })}
    </View>
  );
}

function SideMenu({ path }: { path: string }) {
  return (
    <View style={styles.menu} accessibilityRole="tablist">
      <View style={styles.menuBrand}>
        <LemonSlice size={36} />
        <Text style={styles.menuBrandText}>لیموخوان</Text>
      </View>
      {TABS.map((tab) => {
        const on = path === tab.href || path.startsWith(`${tab.href}/`);
        return (
          <Pressable
            key={tab.href}
            accessibilityRole="tab"
            accessibilityState={{ selected: on }}
            onPress={() => !on && router.replace(tab.href)}
            style={({ hovered, pressed }: { hovered?: boolean; pressed: boolean }) => [
              styles.menuItem,
              on ? styles.sideOn : (hovered || pressed) && styles.sideHover,
            ]}
          >
            <Icon name={tab.icon} size={22} color={colors.ink} strokeWidth={on ? 2.3 : 1.8} />
            <Text style={[styles.menuText, on && { fontFamily: 'Vazirmatn_700Bold' }]}>{tab.label}</Text>
          </Pressable>
        );
      })}
    </View>
  );
}

export default function TabsLayout() {
  const path = usePathname();
  const insets = useSafeAreaInsets();
  const wide = useWide();
  if (wide)
    return (
      <View style={{ flex: 1, flexDirection: 'row-reverse', backgroundColor: colors.ground }}>
        <SideNav path={path} />
        <View style={{ flex: 1 }}>
          <Slot />
        </View>
      </View>
    );
  return (
    <View style={{ flex: 1, backgroundColor: colors.ground }}>
      <View style={{ flex: 1 }}>
        <Slot />
      </View>
      <View style={[styles.bar, { paddingBottom: Math.max(insets.bottom, 6) }]}>
        {TABS.map((tab) => (
          <Tab key={tab.href} tab={tab} on={path === tab.href || path.startsWith(`${tab.href}/`)} />
        ))}
      </View>
    </View>
  );
}

const styles = StyleSheet.create({
  side: { width: 84, backgroundColor: colors.surface, borderLeftWidth: 1, borderLeftColor: colors.line, paddingVertical: 18, gap: 10, alignItems: 'center' },
  brand: { marginBottom: 14 },
  sideItem: { alignItems: 'center', gap: 4, paddingVertical: 4, width: 76 },
  sidePill: { width: 56, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center' },
  sideOn: { backgroundColor: colors.lemon },
  sideHover: { backgroundColor: colors.ground },
  sideText: { fontSize: 12, color: colors.muted },
  menu: { width: 224, backgroundColor: colors.surface, borderLeftWidth: 1, borderLeftColor: colors.line, paddingHorizontal: 14, paddingVertical: 20, gap: 4 },
  menuBrand: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, marginBottom: 18, paddingHorizontal: 6 },
  menuBrandText: { fontSize: 20, fontFamily: 'Vazirmatn_800ExtraBold', color: colors.ink },
  menuItem: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 11, borderRadius: 12 },
  menuText: { fontSize: 15, color: colors.ink },
  bar: { flexDirection: 'row-reverse', backgroundColor: colors.surface, borderTopWidth: 1, borderTopColor: colors.line },
  tab: { flex: 1, height: BAR, alignItems: 'center', justifyContent: 'center' },
  capsuleWrap: { width: 58, height: 34, alignItems: 'center', justifyContent: 'center' },
  iconLayer: { position: 'relative', zIndex: 1 },
  capsule: { position: 'absolute', zIndex: 0, top: 0, left: 0, width: 58, height: 34, borderRadius: 17, backgroundColor: colors.lemon },
  label: { position: 'absolute', bottom: 4, fontSize: 12, color: colors.ink, fontFamily: 'Vazirmatn_700Bold' },
});
