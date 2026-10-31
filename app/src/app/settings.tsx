import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Text, TextInput } from '../components/Text';

import { ApiError } from '../api/client';
import { endpoints } from '../api/endpoints';
import { Button, Header, Screen } from '../components/ui';
import { APP_BUILD, getApiUrl, getDefaultApiUrl, setApiUrlOverride } from '../config';
import { colors, radius, rtl, toPersianDigits } from '../theme';

/** Test builds: point the app at a server, e.g. the laptop running the backend on the same Wi-Fi. */
export default function Settings() {
  const [url, setUrl] = useState('');
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getApiUrl().then(setUrl).catch(() => setUrl(getDefaultApiUrl()));
  }, []);

  const clean = (value: string) => {
    const trimmed = value.trim().replace(/\/+$/, '');
    return /^https?:\/\//.test(trimmed) ? trimmed : `http://${trimmed}`;
  };

  const test = async () => {
    setBusy(true);
    setStatus(null);
    try {
      await endpoints.health(clean(url));
      setStatus({ ok: true, text: 'سرور در دسترس است.' });
    } catch (e) {
      setStatus({ ok: false, text: e instanceof ApiError ? e.message : 'اتصال ممکن نشد.' });
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    await setApiUrlOverride(clean(url));
    router.replace('/');
  };

  const reset = async () => {
    await setApiUrlOverride(null);
    setUrl(getDefaultApiUrl());
    setStatus(null);
  };

  return (
    <Screen>
      <Header title="تنظیمات سرور" />
      <View style={styles.page}>
        <Text style={[styles.label, rtl]}>آدرس سرور</Text>
        <TextInput
          value={url}
          onChangeText={setUrl}
          autoCapitalize="none"
          autoCorrect={false}
          keyboardType="url"
          placeholder="http://192.168.1.20:8000"
          style={styles.input}
        />
        <Text style={[styles.help, rtl]}>
          برای تست روی گوشی: سرور را روی لپ‌تاپ اجرا کنید، گوشی و لپ‌تاپ در یک Wi‑Fi باشند، و آدرس IP لپ‌تاپ را با پورت ۸۰۰۰ وارد کنید.
        </Text>
        {status && <Text style={[styles.status, rtl, { color: status.ok ? colors.greenDark : colors.redDark }]}>{status.text}</Text>}
        <Button label="آزمایش اتصال" variant="outline" onPress={test} loading={busy} />
        <Button label="ذخیره" onPress={save} />
        <Button label="برگشت به آدرس پیش‌فرض" variant="outline" onPress={reset} />
        <Text style={[styles.help, { textAlign: 'center' }]}>نسخه‌ی برنامه: {APP_BUILD ? toPersianDigits(APP_BUILD) : 'آزمایشی'}</Text>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 20, gap: 12 },
  label: { fontSize: 14, fontWeight: '700', color: colors.ink },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line, borderRadius: radius.sm, padding: 14, fontSize: 16, textAlign: 'left', writingDirection: 'ltr' },
  help: { fontSize: 13, color: colors.muted, lineHeight: 24 },
  status: { fontSize: 14, fontWeight: '700' },
});
