import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { endpoints, type Purchases } from '../../api/endpoints';
import { LemonSlice } from '../../components/LemonSlice';
import { Text } from '../../components/Text';
import { Button, Card, Screen } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { jalaliDate } from '../../lib/jalali';
import { storage } from '../../lib/storage';
import { colors, rtl, toPersianDigits } from '../../theme';

function Row({ label, value, onPress, danger }: { label: string; value?: string; onPress: () => void; danger?: boolean }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.row, pressed && { backgroundColor: colors.ground }]} accessibilityRole="button">
      <Text style={[styles.rowLabel, rtl, danger && { color: colors.redDark }]}>{label}</Text>
      <Text style={styles.rowValue}>{value ?? '‹'}</Text>
    </Pressable>
  );
}

export default function Profile() {
  const { user, signOut } = useAuth();
  const [major, setMajor] = useState<{ name: string } | null>(null);
  const [purchases, setPurchases] = useState<Purchases | null>(null);

  useFocusEffect(
    useCallback(() => {
      storage.getMajor().then(setMajor);
      if (user) endpoints.purchases().then(setPurchases).catch(() => undefined);
    }, [user]),
  );

  const name = user ? [user.first_name, user.last_name].filter(Boolean).join(' ') || 'کاربر لیمو پلاس' : 'مهمان';

  return (
    <Screen tab>
      <ScrollView contentContainerStyle={styles.page}>
        <View style={styles.hero}>
          <View style={styles.avatar}>
            <LemonSlice size={64} />
          </View>
          <View style={{ flex: 1, gap: 4 }}>
            <Text style={[styles.name, rtl]}>{name}</Text>
            <Text style={[styles.phone, rtl]}>{user ? toPersianDigits(user.phone) : 'برای ذخیره‌ی پیشرفت وارد شوید'}</Text>
          </View>
        </View>

        {!user ? (
          <Button label="ورود یا ثبت‌نام" onPress={() => router.push('/login')} />
        ) : (
          purchases && purchases.active.length > 0 && (
            <Card>
              <Text style={[styles.cardTitle, rtl]}>اشتراک‌ها و کتاب‌های من</Text>
              {purchases.active.map((p) => (
                <Text key={p.id} style={[styles.line, rtl]}>
                  {p.title}
                  {p.ends_at ? ` · تا ${jalaliDate(p.ends_at)}` : ' · همیشگی'}
                </Text>
              ))}
            </Card>
          )
        )}

        <View style={styles.group}>
          {user && <Row label="ویرایش نام" onPress={() => router.push('/edit-profile')} />}
          <Row label="رشته" value={major?.name ?? '—'} onPress={() => router.push('/welcome')} />
          {user && <Row label="دستگاه‌های من" onPress={() => router.push('/devices')} />}
          {user && <Row label="سابقه‌ی آزمون‌ها" onPress={() => router.push('/exams')} />}
          <Row label="کتاب‌های آفلاین" onPress={() => router.push('/offline')} />
          <Row label="تنظیمات سرور" onPress={() => router.push('/settings')} />
        </View>

        <View style={styles.soon}>
          <Text style={[styles.soonText, rtl]}>✦ دستیار هوش مصنوعی</Text>
          <Text style={styles.soonBadge}>به‌زودی</Text>
        </View>

        {user && (
          <View style={styles.group}>
            <Row label="خروج از حساب" danger onPress={() => signOut().then(() => router.replace('/home'))} />
          </View>
        )}
        <Text style={styles.version}>لیمو پلاس · نسخه‌ی آزمایشی</Text>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 20, gap: 16 },
  hero: { flexDirection: 'row-reverse', alignItems: 'center', gap: 14, backgroundColor: colors.ink, borderRadius: 26, padding: 18 },
  avatar: { width: 72, height: 72, borderRadius: 36, overflow: 'hidden', alignItems: 'center', justifyContent: 'center', backgroundColor: '#24302A' },
  name: { fontSize: 20, fontWeight: '900', color: colors.lemon },
  phone: { fontSize: 14, color: '#C9D0C6' },
  cardTitle: { fontSize: 15, fontWeight: '800', color: colors.ink },
  line: { fontSize: 14, color: colors.muted },
  group: { backgroundColor: colors.surface, borderRadius: 20, borderWidth: 1, borderColor: colors.line, overflow: 'hidden' },
  row: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 15, borderBottomWidth: 1, borderBottomColor: colors.line },
  rowLabel: { fontSize: 15, fontWeight: '700', color: colors.ink },
  rowValue: { fontSize: 14, color: colors.muted },
  soon: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', borderWidth: 1, borderStyle: 'dashed', borderColor: '#B9C4BC', borderRadius: 14, padding: 12 },
  soonText: { color: colors.muted, fontSize: 13 },
  soonBadge: { backgroundColor: colors.lemonSoft, color: '#6B5200', fontSize: 11, fontWeight: '800', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 2, overflow: 'hidden' },
  version: { textAlign: 'center', color: colors.muted, fontSize: 11 },
});
