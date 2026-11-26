import { useSafeAreaInsets } from 'react-native-safe-area-context';
import { router } from 'expo-router';
import { useEffect, useRef, useState, type ReactNode } from 'react';
import { KeyboardAvoidingView, Modal, Platform, Pressable, RefreshControl, ScrollView, StyleSheet, useWindowDimensions, View, type StyleProp, type ViewStyle } from 'react-native';
import { WIDE } from '../lib/layout';
import { offlineSupported } from '../lib/offline';

import { Text } from './Text';
import { Icon, IconBadge, type IconName } from './Icon';
import { LemonLoader, LemonSpinner } from './LemonLoader';
import { LemonSlice } from './LemonSlice';
import { SafeAreaView } from 'react-native-safe-area-context';

import { colors, radius, rtl } from '../theme';
import { errorPresentation } from '../lib/errors';
import { refreshAll } from '../lib/useApi';

export function Screen({
  children,
  background = colors.ground,
  tab = false,
  wide = false,
  wideMax,
  desktopMax,
}: {
  children: ReactNode;
  background?: string;
  tab?: boolean;
  wide?: boolean;
  /** «wide» only: the most it may grow to; it then sits next to the right-hand menu, not in the middle. */
  wideMax?: number;
  /** A tab screen on a computer that may be wider than reading width (e.g. the library's shelves). */
  desktopMax?: number;
}) {
  // Tab screens leave the bottom edge to the tab bar. «wide»: a screen with its own columns on a computer.
  // On a computer, tab screens start right next to the side menu (any room left over goes to the far side).
  const desktop = useWindowDimensions().width >= WIDE;
  const place = wide
    ? { maxWidth: wideMax ?? 1320, alignSelf: 'flex-end' as const }
    : tab && desktop
      ? { maxWidth: desktopMax ?? 900, alignSelf: 'flex-end' as const, paddingRight: 16 }
      : null;
  return (
    <SafeAreaView style={[styles.screen, { backgroundColor: background }]} edges={tab ? ['top', 'left', 'right'] : ['top', 'bottom', 'left', 'right']}>
      <View style={[styles.inner, place]}>{children}</View>
    </SafeAreaView>
  );
}

export function Header({ title, subtitle, right }: { title?: string; subtitle?: string; right?: ReactNode }) {
  return (
    <View style={styles.header}>
      <Pressable accessibilityRole="button" accessibilityLabel="بازگشت" onPress={() => (router.canGoBack() ? router.back() : router.replace('/home'))} style={styles.iconButton}>
        <Icon name="arrow-right" size={24} />
      </Pressable>
      <View style={styles.headerText}>
        {!!subtitle && <Text style={[styles.subtitle, rtl]} numberOfLines={1}>{subtitle}</Text>}
        {!!title && <Text style={[styles.title, rtl]} numberOfLines={1}>{title}</Text>}
      </View>
      <View style={styles.headerRight}>{right}</View>
    </View>
  );
}

export function Button({
  label,
  onPress,
  variant = 'primary',
  disabled,
  loading,
  style,
}: {
  label: string;
  onPress: () => void;
  variant?: 'primary' | 'dark' | 'outline' | 'danger';
  disabled?: boolean;
  /** Shows the lemon spinner and blocks taps until the work is done. */
  loading?: boolean;
  style?: StyleProp<ViewStyle>;
}) {
  const look = variant === 'primary' ? styles.primary : variant === 'dark' ? styles.dark : variant === 'danger' ? styles.danger : styles.outline;
  const text = variant === 'dark' ? styles.darkText : variant === 'danger' ? styles.dangerText : styles.primaryText;
  return (
    <Pressable
      accessibilityRole="button"
      disabled={disabled || loading}
      accessibilityState={{ disabled: !!(disabled || loading), busy: !!loading }}
      onPress={onPress}
      style={({ pressed }) => [styles.button, look, disabled && styles.disabled, pressed && { opacity: 0.85 }, style]}
    >
      <View style={styles.buttonInner}>
        {loading && <LemonSpinner size={20} />}
        <Text numberOfLines={1} adjustsFontSizeToFit minimumFontScale={0.8} style={[styles.buttonText, text, disabled && !loading && { color: colors.muted }]}>
          {label}
        </Text>
      </View>
    </Pressable>
  );
}

let retrySpinUntil = 0;
function markRetrySpin() {
  retrySpinUntil = Date.now() + 800;
}

export function Loading() {
  const immediate = Date.now() < retrySpinUntil;
  return (
    <View style={styles.center}>
      <LemonLoader delay={immediate ? 0 : 300} />
    </View>
  );
}

export function ErrorState({
  message,
  onRetry,
  icon,
  title,
  status,
}: {
  message: string;
  onRetry?: () => void;
  icon?: IconName;
  title?: string;
  status?: number;
}) {
  const [retrying, setRetrying] = useState(false);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);
  useEffect(
    () => () => {
      if (timer.current) clearTimeout(timer.current);
    },
    [],
  );

  // Without onRetry it is an informational/locked state; with onRetry it is a connection or server failure with brand presence.
  if (!onRetry) {
    return (
      <View style={styles.center}>
        <IconBadge name={icon ?? 'book-open'} size={56} />
        <Text style={[styles.errorText, { marginTop: 14 }]}>{message}</Text>
      </View>
    );
  }

  const handleRetry = () => {
    markRetrySpin();
    setRetrying(true);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => setRetrying(false), 600);
    onRetry();
  };

  const presentation = errorPresentation(status);
  const resolvedIcon = icon ?? presentation.icon;
  const resolvedTitle = title ?? presentation.title;

  return (
    <View style={styles.center}>
      <View style={styles.errorCard}>
        <View style={styles.errorEmblem}>
          <LemonSlice size={68} />
          <View style={styles.errorBadge}>
            <Icon name={resolvedIcon} size={15} color={colors.ink} strokeWidth={2.2} />
          </View>
        </View>
        <Text style={[styles.errorTitle, rtl]}>{resolvedTitle}</Text>
        <Text style={[styles.errorText, rtl]}>{message}</Text>
        <Button label="تلاش دوباره" variant="outline" onPress={handleRetry} loading={retrying} style={{ marginTop: 8, minWidth: 170 }} />
        {offlineSupported && (
          <Pressable onPress={() => router.push('/offline')} style={{ marginTop: 6 }} accessibilityRole="link">
            <Text style={styles.link}>کتاب‌های آفلاین</Text>
          </Pressable>
        )}
        <View style={styles.brandFoot}>
          <View style={styles.brandRule} />
          <Text style={styles.brandName}>لیموخوان</Text>
        </View>
      </View>
    </View>
  );
}

/** A panel that slides up from the bottom: reports, notes, choices. */
export function Sheet({ visible, onClose, title, children }: { visible: boolean; onClose: () => void; title: string; children: ReactNode }) {
  // The panel stops above the phone's own buttons (back, home), which newer Android draws over the app.
  const insets = useSafeAreaInsets();
  return (
    <Modal visible={visible} transparent animationType="slide" onRequestClose={onClose} statusBarTranslucent navigationBarTranslucent>
      <KeyboardAvoidingView behavior={Platform.OS === 'ios' ? 'padding' : undefined} style={styles.sheetWrap}>
        <Pressable style={StyleSheet.absoluteFill} onPress={onClose} accessibilityLabel="بستن" />
        <View style={[styles.sheet, { paddingBottom: 20 + insets.bottom }]}>
          <View style={styles.sheetHandle} />
          <Text style={[styles.sheetTitle, rtl]}>{title}</Text>
          <ScrollView keyboardShouldPersistTaps="handled" contentContainerStyle={{ gap: 10, paddingBottom: 8 }}>
            {children}
          </ScrollView>
        </View>
      </KeyboardAvoidingView>
    </Modal>
  );
}

export function Card({ children, style }: { children: ReactNode; style?: StyleProp<ViewStyle> }) {
  return <View style={[styles.card, style]}>{children}</View>;
}

export function Empty({ icon = 'book-open', title, text, action }: { icon?: IconName; title: string; text?: string; action?: ReactNode }) {
  return (
    <View style={styles.empty}>
      <IconBadge name={icon} size={64} />
      <Text style={styles.emptyTitle}>{title}</Text>
      {!!text && <Text style={styles.emptyText}>{text}</Text>}
      {!!action && <View style={{ alignSelf: 'stretch', alignItems: 'center' }}><View style={{ width: '100%', maxWidth: 420 }}>{action}</View></View>}
    </View>
  );
}

export function Chip({ label, color = colors.muted, background = colors.surface, icon }: { label: string; color?: string; background?: string; icon?: IconName }) {
  return (
    <View style={[styles.chip, { backgroundColor: background }]}>
      {icon && <Icon name={icon} size={14} color={color} strokeWidth={2.2} />}
      <Text style={[styles.chipText, { color }]}>{label}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  screen: { flex: 1 },
  inner: { flex: 1, width: '100%', maxWidth: 900, alignSelf: 'center' },
  header: { flexDirection: 'row-reverse', alignItems: 'center', paddingHorizontal: 8, paddingVertical: 6, gap: 4 },
  iconButton: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  back: { fontSize: 22, color: colors.ink },
  headerText: { flex: 1 },
  headerRight: { minWidth: 44, alignItems: 'flex-start' },
  title: { fontSize: 18, fontWeight: '800', color: colors.ink },
  subtitle: { fontSize: 12, color: colors.muted },
  // No button wider than about 420 px, even in a wide column on a computer.
  button: { minHeight: 52, maxWidth: 420, borderRadius: radius.md, alignItems: 'center', justifyContent: 'center', paddingHorizontal: 18 },
  primary: { backgroundColor: colors.lemon },
  dark: { backgroundColor: colors.ink },
  danger: { backgroundColor: colors.redDark },
  dangerText: { color: '#FFFFFF' },
  outline: { borderWidth: 1.5, borderColor: colors.ink, backgroundColor: 'transparent' },
  disabled: { backgroundColor: colors.disabled, borderColor: colors.disabled },
  buttonInner: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10 },
  buttonText: { fontSize: 15, fontWeight: '700' },
  primaryText: { color: colors.ink },
  darkText: { color: colors.lemon },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 },
  errorCard: {
    width: '100%',
    maxWidth: 400,
    backgroundColor: colors.surface,
    borderRadius: 24,
    borderWidth: 1,
    borderColor: colors.line,
    paddingVertical: 26,
    paddingHorizontal: 22,
    alignItems: 'center',
    gap: 8,
  },
  errorEmblem: { position: 'relative', marginBottom: 6 },
  errorBadge: {
    position: 'absolute',
    bottom: -2,
    left: -4,
    width: 28,
    height: 28,
    borderRadius: 14,
    backgroundColor: colors.lemon,
    borderWidth: 2,
    borderColor: colors.surface,
    alignItems: 'center',
    justifyContent: 'center',
  },
  errorTitle: { fontSize: 17, fontWeight: '900', color: colors.ink, textAlign: 'center' },
  errorText: { fontSize: 14.5, color: colors.muted, textAlign: 'center', lineHeight: 24 },
  brandFoot: { alignItems: 'center', gap: 6, marginTop: 10 },
  brandRule: { width: 42, height: 3, borderRadius: 2, backgroundColor: colors.line },
  brandName: { fontSize: 12, fontWeight: '800', color: '#8FA095' },
  link: { color: colors.greenDark, fontWeight: '700', fontSize: 13 },
  // Every status label (رایگان، به‌زودی، نسخه‌ی کامل، a question's tags) has this height and shape; its colour says what it means.
  chip: { borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4, flexDirection: 'row-reverse', alignItems: 'center', gap: 4 },
  sheetWrap: { flex: 1, justifyContent: 'flex-end', backgroundColor: '#17201A66' },
  sheet: { backgroundColor: colors.surface, borderTopLeftRadius: 28, borderTopRightRadius: 28, padding: 20, paddingTop: 10, maxHeight: '85%', gap: 12 },
  sheetHandle: { alignSelf: 'center', width: 44, height: 5, borderRadius: 3, backgroundColor: colors.line, marginBottom: 6 },
  sheetTitle: { fontSize: 18, fontWeight: '800', color: colors.ink },
  card: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, padding: 16, gap: 10 },
  // An empty or guest message: a small frame in the middle of its own column, not spread over a wide page.
  empty: {
    alignItems: 'center', justifyContent: 'center', padding: 24, gap: 8, width: '100%', maxWidth: 480, alignSelf: 'center',
    marginVertical: 24, backgroundColor: colors.surface, borderRadius: 20, borderWidth: 1, borderColor: colors.line,
  },
  emptyTitle: { fontSize: 18, fontWeight: '800', color: colors.ink, textAlign: 'center' },
  emptyText: { fontSize: 15, color: colors.muted, textAlign: 'center', lineHeight: 24, marginBottom: 8 },
  chipText: { fontSize: 12, fontWeight: '700' },
});

/**
 * Pull-to-refresh that spins only after the learner actually pulled. (A spinner tied to every background load showed
 * a second loader at the top of the screen next to the lemon.)
 */
export function usePullRefresh(loading: boolean, reload: () => void) {
  const [pulled, setPulled] = useState(false);
  useEffect(() => {
    if (!loading) setPulled(false);
  }, [loading]);
  return (
    <RefreshControl
      refreshing={pulled}
      onRefresh={() => {
        setPulled(true);
        reload();
        refreshAll();
      }}
      colors={[colors.ink]}
      progressBackgroundColor={colors.lemon}
      tintColor={colors.ink}
    />
  );
}
