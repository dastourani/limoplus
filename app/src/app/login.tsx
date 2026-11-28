import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { KeyboardAvoidingView, Platform, ScrollView, StyleSheet, View } from 'react-native';

import { ApiError } from '../api/client';
import { endpoints } from '../api/endpoints';
import { LemonSlice } from '../components/LemonSlice';
import { Text, TextInput } from '../components/Text';
import { Button, Header, Screen } from '../components/ui';
import { smsAppHash } from '../lib/smsCode';
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
      await endpoints.requestOtp(digits, smsAppHash());
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
      <KeyboardAvoidingView style={{ flex: 1 }} behavior={Platform.OS === 'ios' ? 'padding' : 'height'}>
      <ScrollView contentContainerStyle={styles.page} keyboardShouldPersistTaps="handled">
        <View style={{ alignItems: 'center', marginBottom: 8 }}>
          <LemonSlice size={96} />
        </View>
        {!!reason && <Text style={[styles.reason, rtl]}>{reason}</Text>}
        <Text style={[styles.label, rtl]}>شماره موبایل</Text>
        <TextInput
          value={phone}
          onChangeText={setPhone}
          keyboardType="phone-pad"
          placeholder="09123456789"
          placeholderTextColor="#A8B3AB"
          maxLength={13}
          autoFocus
          style={styles.input}
          onSubmitEditing={() => valid && send()}
          accessibilityLabel="شماره موبایل"
        />
        <Text style={[styles.help, rtl]}>یک کد ۶ رقمی برایتان پیامک می‌شود. اگر حساب ندارید، همین‌جا ساخته می‌شود.</Text>
        {!!error && <Text style={[styles.error, rtl]}>{error}</Text>}
        <Button label="دریافت کد" onPress={send} disabled={!valid} loading={busy} />
        <Text style={[styles.terms, rtl]}>
          با ورود،{' '}
          <Text style={styles.termsLink} onPress={() => router.push('/page/terms')} accessibilityRole="link">شرایط استفاده و خرید</Text>
          {' و '}
          <Text style={styles.termsLink} onPress={() => router.push('/page/privacy')} accessibilityRole="link">حریم خصوصی</Text>
          {' را می‌پذیرید.'}
        </Text>
        <Button label="فعلاً بدون ورود ادامه می‌دهم" variant="outline" onPress={() => (router.canGoBack() ? router.back() : router.replace('/home'))} />
      </ScrollView>
      </KeyboardAvoidingView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  terms: { fontSize: 12, color: colors.muted, textAlign: 'center' },
  termsLink: { color: colors.greenDark, textDecorationLine: 'underline' },
  page: { padding: 24, gap: 12 },
  reason: { backgroundColor: colors.lemonSoft, color: '#6B5200', borderRadius: radius.sm, padding: 12, fontSize: 15, lineHeight: 24 },
  label: { fontSize: 15, fontWeight: '700', color: colors.ink },
  input: { backgroundColor: colors.surface, borderWidth: 1.5, borderColor: colors.line, borderRadius: radius.md, paddingHorizontal: 16, height: 60, fontSize: 22, textAlign: 'center' },
  help: { fontSize: 13, color: colors.muted, lineHeight: 22 },
  error: { color: colors.redDark, fontSize: 15 },
});
