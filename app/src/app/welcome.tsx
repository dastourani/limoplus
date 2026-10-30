import { router } from 'expo-router';
import { useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { endpoints, type Major } from '../api/endpoints';
import { Button, ErrorState, Loading, Screen } from '../components/ui';
import { storage } from '../lib/storage';
import { useApi } from '../lib/useApi';
import { colors, radius, rtl } from '../theme';

export default function Welcome() {
  const { data, error, loading, retry } = useApi(() => endpoints.majors());
  const [picked, setPicked] = useState<Major | null>(null);

  const start = async () => {
    if (!picked || picked.is_coming_soon) return;
    await storage.setMajor({ slug: picked.slug, name: picked.name, color: picked.color });
    router.replace('/home');
  };

  return (
    <Screen>
      <View style={styles.hero}>
        <View style={styles.lemon}>
          <View style={styles.lemonInner} />
        </View>
        <Text style={styles.brand}>لیمو پلاس</Text>
        <Text style={[styles.tagline, rtl]}>درس‌هایی که زنده‌اند؛ بخوان، تست بزن، مرور کن.</Text>
      </View>

      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error.message} onRetry={retry} />
      ) : (
        <ScrollView contentContainerStyle={styles.body}>
          <Text style={[styles.question, rtl]}>رشته‌ات چیه؟</Text>
          <Text style={[styles.hint, rtl]}>بعداً هم می‌تونی عوضش کنی.</Text>
          <View style={styles.grid}>
            {data!.map((major) => {
              const on = picked?.slug === major.slug;
              return (
                <Pressable
                  key={major.slug}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: on }}
                  onPress={() => setPicked(major)}
                  style={[styles.major, { borderColor: on ? major.color : colors.line }, major.is_coming_soon && styles.soon]}
                >
                  <View style={styles.majorRow}>
                    <View style={[styles.dot, { backgroundColor: major.color }]} />
                    <Text style={[styles.majorName, rtl]}>{major.name}</Text>
                  </View>
                  <Text style={[styles.majorSub, rtl]}>{major.is_coming_soon ? 'به‌زودی' : 'آماده'}</Text>
                </Pressable>
              );
            })}
          </View>
        </ScrollView>
      )}

      <View style={styles.footer}>
        <Button
          label={!picked ? 'یک رشته انتخاب کن' : picked.is_coming_soon ? `${picked.name} به‌زودی آماده می‌شود` : `ورود به فضای ${picked.name}`}
          disabled={!picked || picked.is_coming_soon}
          onPress={start}
        />
        <Pressable onPress={() => router.push('/settings')} style={{ alignSelf: 'center', padding: 8 }}>
          <Text style={styles.settings}>تنظیمات سرور</Text>
        </Pressable>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  hero: { backgroundColor: colors.ink, padding: 24, paddingTop: 28, borderBottomLeftRadius: 32, borderBottomRightRadius: 32, gap: 6, overflow: 'hidden' },
  lemon: { position: 'absolute', left: -70, top: -70, width: 150, height: 150, borderRadius: 75, backgroundColor: colors.lemon, alignItems: 'center', justifyContent: 'center' },
  lemonInner: { width: 116, height: 116, borderRadius: 58, backgroundColor: '#FFE57A' },
  brand: { fontSize: 36, fontWeight: '900', color: colors.lemon, textAlign: 'right' },
  tagline: { fontSize: 16, color: colors.ground, fontWeight: '700', lineHeight: 28, maxWidth: 260, alignSelf: 'flex-end' },
  body: { padding: 20, gap: 6 },
  question: { fontSize: 20, fontWeight: '800', color: colors.ink },
  hint: { fontSize: 13, color: colors.muted, marginBottom: 8 },
  grid: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 10 },
  major: { flexBasis: '47%', flexGrow: 1, backgroundColor: colors.surface, borderWidth: 2, borderRadius: radius.md, padding: 14, gap: 6, minHeight: 76 },
  soon: { backgroundColor: '#EEF1EA' },
  majorRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  dot: { width: 12, height: 12, borderRadius: 6 },
  majorName: { fontSize: 16, fontWeight: '800', color: colors.ink },
  majorSub: { fontSize: 12, color: colors.muted },
  footer: { padding: 20, paddingTop: 8, gap: 6 },
  settings: { color: colors.muted, fontSize: 12 },
});
