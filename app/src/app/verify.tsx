import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { KeyboardAvoidingView, Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { ApiError } from '../api/client';
import { endpoints, type DeviceSessionInfo } from '../api/endpoints';
import { useCelebrate } from '../components/Celebrate';
import { Text, TextInput } from '../components/Text';
import { Button, Card, Header, Screen } from '../components/ui';
import { deviceName, useAuth } from '../lib/auth';
import { relativeDay } from '../lib/jalali';
import { listenForSmsCode, smsAppHash } from '../lib/smsCode';
import { colors, radius, rtl, toPersianDigits } from '../theme';

const RESEND_SECONDS = 60;
const toLatin = (s: string) => s.replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)));

/** Step 2: the SMS code. If two devices are already signed in, the user chooses one to sign out. */
export default function Verify() {
  const { phone } = useLocalSearchParams<{ phone: string }>();
  const { signIn } = useAuth();
  const celebrate = useCelebrate();
  const [code, setCode] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [wait, setWait] = useState(RESEND_SECONDS);
  const [limit, setLimit] = useState<DeviceSessionInfo[] | null>(null);

  // Android: the code is read from the SMS by itself and the user is signed in without typing.
  const verifyRef = useRef<(replace?: number, code?: string) => void>(() => undefined);
  useEffect(() => {
    if (limit) return;
    return listenForSmsCode((smsCode) => {
      setCode(smsCode);
      verifyRef.current(undefined, smsCode);
    });
  }, [limit]);

  useEffect(() => {
    if (wait <= 0) return;
    const t = setTimeout(() => setWait((w) => w - 1), 1000);
    return () => clearTimeout(t);
  }, [wait]);

  const clean = toLatin(code).replace(/\D/g, '');

  const verify = async (replace?: number, fromSms?: string) => {
    setBusy(true);
    setError(null);
    try {
      const r = await endpoints.verifyOtp({ phone: String(phone), code: fromSms ?? clean, device_name: deviceName(), platform: Platform.OS, replace_session_id: replace });
      await signIn(r.token, r.user);
      celebrate('login', { title: r.user.first_name ? `خوش آمدی ${r.user.first_name}!` : 'خوش آمدی!' });
      // Back to where the user was; first-timers are asked for their name.
      if (!r.user.first_name) router.replace('/edit-profile?first=1');
      else if (router.canDismiss()) router.dismissAll();
      else router.replace('/home');
    } catch (e) {
      if (e instanceof ApiError && e.code === 'session_limit') setLimit((e.data.sessions as DeviceSessionInfo[]) ?? []);
      else setError(e instanceof ApiError ? e.message : 'ورود ممکن نشد.');
    } finally {
      setBusy(false);
    }
  };

  verifyRef.current = verify;

  const resend = async () => {
    setError(null);
    try {
      await endpoints.requestOtp(String(phone), smsAppHash());
      setWait(RESEND_SECONDS);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'ارسال دوباره ممکن نشد.');
    }
  };

  if (limit) {
    return (
      <Screen>
        <Header title="حداکثر دو دستگاه" />
        <View style={styles.page}>
          <Text style={[styles.help, rtl]}>
            با این حساب روی دو دستگاه وارد شده‌اید. برای ورود روی این دستگاه، یکی از آن‌ها را خارج کنید.
          </Text>
          {limit.map((s) => (
            <Card key={s.id}>
              <Text style={[styles.device, rtl]}>{s.device_name}</Text>
              <Text style={[styles.help, rtl]}>آخرین استفاده: {relativeDay(s.last_seen_at)}</Text>
              <Button label="خروج این دستگاه و ورود" variant="dark" loading={busy} onPress={() => verify(s.id)} />
            </Card>
          ))}
          {!!error && <Text style={[styles.error, rtl]}>{error}</Text>}
        </View>
      </Screen>
    );
  }

  return (
    <Screen>
      <Header title="کد تأیید" />
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
      <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
        <Text style={[styles.help, rtl]}>کد ۶ رقمی پیامک‌شده به {toPersianDigits(String(phone))} را وارد کنید.</Text>
        <TextInput
          value={code}
          onChangeText={(v) => {
            setCode(v);
            if (toLatin(v).replace(/\D/g, '').length === 6) setError(null);
          }}
          keyboardType="number-pad"
          textContentType="oneTimeCode"
          autoComplete="sms-otp"
          maxLength={6}
          autoFocus
          style={styles.input}
          accessibilityLabel="کد تأیید"
          onSubmitEditing={() => clean.length === 6 && verify()}
        />
        {!!error && <Text style={[styles.error, rtl]}>{error}</Text>}
        <Button label="ورود" onPress={() => verify()} disabled={clean.length !== 6} loading={busy} />
        <Pressable onPress={resend} disabled={wait > 0} style={{ alignSelf: 'center', padding: 10 }}>
          <Text style={{ color: wait > 0 ? colors.muted : colors.greenDark, fontWeight: '700' }}>
            {wait > 0 ? `ارسال دوباره تا ${toPersianDigits(wait)} ثانیه‌ی دیگر` : 'ارسال دوباره‌ی کد'}
          </Text>
        </Pressable>
        <Pressable onPress={() => router.back()} style={{ alignSelf: 'center', padding: 6 }}>
          <Text style={{ color: colors.muted }}>شماره را اشتباه زده‌ام</Text>
        </Pressable>
      </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 24, gap: 12 },
  help: { fontSize: 15, color: colors.muted, lineHeight: 24 },
  input: { backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.line, borderRadius: radius.md, paddingHorizontal: 16, height: 64, fontSize: 28, textAlign: 'center', letterSpacing: 8 },
  error: { color: colors.redDark, fontSize: 15 },
  device: { fontSize: 15, fontWeight: '800', color: colors.ink },
});
