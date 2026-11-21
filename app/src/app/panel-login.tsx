import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Platform, StyleSheet, View } from 'react-native';

import { ApiError } from '../api/client';
import { endpoints, type DeviceSessionInfo } from '../api/endpoints';
import { Text } from '../components/Text';
import { Button, Card, Header, Loading, Screen } from '../components/ui';
import { deviceName, useAuth } from '../lib/auth';
import { relativeDay } from '../lib/jalali';
import { colors, rtl } from '../theme';

/**
 * The panel's «باز کردن وب اپ با حساب من» lands here with a one-time code after «#». The code is taken out of the
 * address at once, exchanged for a session (staff only, once, within a minute), and the app opens on the home page.
 * With two devices already signed in, one is chosen to sign out, as after an SMS code.
 */
export default function PanelLogin() {
  const { signIn } = useAuth();
  const code = useRef<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [limit, setLimit] = useState<DeviceSessionInfo[] | null>(null);
  const [busy, setBusy] = useState(false);

  const go = async (replace?: number) => {
    if (!code.current) return;
    setBusy(true);
    setError(null);
    try {
      const r = await endpoints.panelLogin({ code: code.current, device_name: deviceName(), platform: Platform.OS, replace_session_id: replace });
      code.current = null;
      await signIn(r.token, r.user);
      router.replace('/home');
    } catch (e) {
      if (e instanceof ApiError && e.code === 'session_limit') setLimit((e.data.sessions as DeviceSessionInfo[]) ?? []);
      else setError(e instanceof ApiError ? e.message : 'ورود ممکن نشد.');
    } finally {
      setBusy(false);
    }
  };

  useEffect(() => {
    if (Platform.OS !== 'web' || typeof window === 'undefined') {
      setError('این پیوند فقط در مرورگر کار می‌کند.');
      return;
    }
    const fromHash = window.location.hash.replace(/^#/, '').trim();
    // Out of the address bar and the history at once: the code must not be bookmarked, shared or reused.
    window.history.replaceState(null, '', window.location.pathname);
    if (!fromHash) {
      setError('پیوند ورود ناقص است. از پنل دوباره «باز کردن وب اپ با حساب من» را بزنید.');
      return;
    }
    code.current = fromHash;
    go();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  if (limit) {
    return (
      <Screen>
        <Header title="حداکثر دو دستگاه" />
        <View style={styles.page}>
          <Text style={[styles.help, rtl]}>با این حساب روی دو دستگاه وارد شده‌اید. برای ورود در این مرورگر، یکی را خارج کنید.</Text>
          {limit.map((s) => (
            <Card key={s.id}>
              <Text style={[styles.device, rtl]}>{s.device_name}</Text>
              <Text style={[styles.help, rtl]}>آخرین استفاده: {relativeDay(s.last_seen_at)}</Text>
              <Button label="خروج این دستگاه و ورود" variant="dark" loading={busy} onPress={() => go(s.id)} />
            </Card>
          ))}
          {!!error && <Text style={[styles.error, rtl]}>{error}</Text>}
        </View>
      </Screen>
    );
  }

  return (
    <Screen>
      <Header title="ورود از پنل" />
      <View style={styles.page}>
        {error ? (
          <>
            <Text style={[styles.error, rtl]}>{error}</Text>
            <Button label="رفتن به صفحه‌ی اول" onPress={() => router.replace('/home')} />
          </>
        ) : (
          <Loading />
        )}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 24, gap: 12 },
  help: { fontSize: 15, color: colors.muted, lineHeight: 24 },
  device: { fontSize: 16, fontWeight: '800', color: colors.ink },
  error: { color: colors.redDark, fontSize: 15, lineHeight: 24 },
});
