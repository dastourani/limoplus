import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { ApiError } from '../api/client';
import { endpoints } from '../api/endpoints';
import { LemonSlice } from '../components/LemonSlice';
import { Text, TextInput } from '../components/Text';
import { Button, Header, Screen } from '../components/ui';
import { colors, radius, rtl } from '../theme';

const toLatin = (s: string) => s.replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d))).replace(/[٠-٩]/g, (d) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)));

/** Step 1 of signing in: the phone number. No passwords — a code comes by SMS. */
export default function Login() {
  const { reason } = useLocalSearchParams<{ reason?: string }>();
  const [phone, setPhone] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const digits = toLatin(phone).replace(/\D/g, '');
  const valid = /^(0?9\d{9}|989\d{9})$/.test(digits);

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await endpoints.requestOtp(digits);
      router.push({ pathname: '/verify', params: { phone: digits } });
    } catch (e) {
      if (e instanceof ApiError && e.code === 'cooldown') router.push({ pathname: '/verify', params: { phone: digits } });
      else setError(e instanceof ApiError ? e.message : 'ارسال کد ممکن نشد.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <Header title="ورود یا ثبت‌نام" />
      <View style={styles.page}>
        <View style={{ alignItems: 'center', marginBottom: 8 }}>
          <LemonSlice size={96} />
        </View>
        {!!reason && <Text style={[styles.reason, rtl]}>{reason}</Text>}
        <Text style={[styles.label, rtl]}>شماره موبایل</Text>
        <TextInput
          value={phone}
          onChangeText={setPhone}
          keyboardType="phone-pad"
          placeholder="۰۹۱۲ ۳۴۵ ۶۷۸۹"
          maxLength={14}
          autoFocus
          style={styles.input}
          onSubmitEditing={() => valid && send()}
          accessibilityLabel="شماره موبایل"
        />
        <Text style={[styles.help, rtl]}>یک کد ۶ رقمی برایتان پیامک می‌شود. اگر حساب ندارید، همین‌جا ساخته می‌شود.</Text>
        {!!error && <Text style={[styles.error, rtl]}>{error}</Text>}
        <Button label={busy ? 'در حال ارسال…' : 'دریافت کد'} onPress={send} disabled={!valid || busy} />
        <Button label="فعلاً بدون ورود ادامه می‌دهم" variant="outline" onPress={() => (router.canGoBack() ? router.back() : router.replace('/home'))} />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 24, gap: 12 },
  reason: { backgroundColor: colors.lemonSoft, color: '#6B5200', borderRadius: radius.sm, padding: 12, fontSize: 14, lineHeight: 24 },
  label: { fontSize: 14, fontWeight: '800', color: colors.ink },
  input: { backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.line, borderRadius: radius.md, padding: 16, fontSize: 22, textAlign: 'center', letterSpacing: 2, writingDirection: 'ltr' },
  help: { fontSize: 13, color: colors.muted, lineHeight: 22 },
  error: { color: colors.redDark, fontSize: 14 },
});
