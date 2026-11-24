import { router } from 'expo-router';
import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { Text, TextInput } from '../components/Text';

import { ApiError } from '../api/client';
import { endpoints } from '../api/endpoints';
import { Button, Header, Screen } from '../components/ui';
import { APP_BUILD, APP_CHANNEL, getApiUrl, getDefaultApiUrl, normalizeServerUrl, setApiUrlOverride } from '../config';
import { useAuth } from '../lib/auth';
import { colors, radius, rtl, toPersianDigits } from '../theme';

/** Staff/test emergency override: point the app at another server (official builds strictly require https://). */
export default function Settings() {
  const { user } = useAuth();
  const [url, setUrl] = useState('');
  const [status, setStatus] = useState<{ ok: boolean; text: string } | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    getApiUrl().then(setUrl).catch(() => setUrl(getDefaultApiUrl()));
  }, []);

  if (APP_CHANNEL === 'official' && !user?.is_staff) {
    return (
      <Screen>
        <Header title="تنظیمات سرور" />
        <View style={styles.page}>
          <Text style={[styles.help, rtl]}>تنظیم آدرس سرور فقط برای مدیر در شرایط اضطراری مجاز است.</Text>
          <Button label="بازگشت" variant="outline" onPress={() => router.back()} />
        </View>
      </Screen>
    );
  }

  const clean = (value: string) => normalizeServerUrl(value, APP_CHANNEL);

  const test = async () => {
    setBusy(true);
    setStatus(null);
    try {
      await endpoints.health(clean(url));
      setStatus({ ok: true, text: 'سرور در دسترس است.' });
    } catch (e) {
      setStatus({ ok: false, text: e instanceof ApiError || e instanceof Error ? e.message : 'اتصال ممکن نشد.' });
    } finally {
      setBusy(false);
    }
  };

  const save = async () => {
    setStatus(null);
    try {
      await setApiUrlOverride(clean(url));
      router.replace('/');
    } catch (e) {
      setStatus({ ok: false, text: e instanceof Error ? e.message : 'آدرس نامعتبر است.' });
    }
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
          placeholder={getDefaultApiUrl() || (APP_CHANNEL === 'official' ? 'https://' : 'http://')}
          style={styles.input}
        />
        <Text style={[styles.help, rtl]}>
          نشانی سرور اپ. به‌طور پیش‌فرض سرور اصلی لیموخوان است ({getDefaultApiUrl() || '—'}) و لازم نیست چیزی را عوض کنید.
          {APP_CHANNEL === 'official' ? ' در نسخه‌ی رسمی فقط آدرس‌های https:// پذیرفته می‌شوند.' : ' فقط برای آزمایش یک سرور دیگر است.'}
        </Text>
        {status && <Text style={[styles.status, rtl, { color: status.ok ? colors.greenDark : colors.redDark }]}>{status.text}</Text>}
        <Button label="آزمایش اتصال" variant="outline" onPress={test} loading={busy} />
        <Button label="ذخیره" onPress={save} />
        <Button label="برگشت به آدرس پیش‌فرض" variant="outline" onPress={reset} />
        <Text style={[styles.help, { textAlign: 'center' }]}>
          نسخه‌ی برنامه: {APP_BUILD ? toPersianDigits(APP_BUILD) : 'توسعه'} ({APP_CHANNEL === 'official' ? 'رسمی' : 'آزمایشی'})
        </Text>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 12 },
  label: { fontSize: 15, fontWeight: '700', color: colors.ink },
  input: { backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line, borderRadius: radius.sm, padding: 14, fontSize: 15, textAlign: 'left', writingDirection: 'ltr' },
  help: { fontSize: 13, color: colors.muted, lineHeight: 24 },
  status: { fontSize: 15, fontWeight: '700' },
});
