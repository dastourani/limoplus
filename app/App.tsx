import { StatusBar } from 'expo-status-bar';
import { useEffect, useState } from 'react';
import { I18nManager, StyleSheet, Text, View } from 'react-native';

import { api, ApiError } from './src/api/client';

I18nManager.allowRTL(true);

type Status = { kind: 'checking' } | { kind: 'ok' } | { kind: 'error'; message: string };

export default function App() {
  const [status, setStatus] = useState<Status>({ kind: 'checking' });

  useEffect(() => {
    api<{ status: string }>('health/')
      .then(() => setStatus({ kind: 'ok' }))
      .catch((error: unknown) =>
        setStatus({ kind: 'error', message: error instanceof ApiError ? error.message : 'خطای ناشناخته' }),
      );
  }, []);

  return (
    <View style={styles.container}>
      <Text style={styles.title}>لیمو پلاس</Text>
      <Text style={styles.status}>
        {status.kind === 'checking' && 'در حال اتصال به سرور…'}
        {status.kind === 'ok' && 'سرور در دسترس است ✓'}
        {status.kind === 'error' && status.message}
      </Text>
      <StatusBar style="dark" />
    </View>
  );
}

const styles = StyleSheet.create({
  container: { flex: 1, backgroundColor: '#F6F7F2', alignItems: 'center', justifyContent: 'center', gap: 12 },
  title: { fontSize: 32, fontWeight: '800', color: '#17201A' },
  status: { fontSize: 16, color: '#56655B', writingDirection: 'rtl' },
});
