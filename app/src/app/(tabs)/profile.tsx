import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, Switch, View } from 'react-native';

import { endpoints, type Purchases } from '../../api/endpoints';
import { LemonSlice } from '../../components/LemonSlice';
import { Text } from '../../components/Text';
import { APP_BUILD } from '../../config';
import { useFeedback } from '../../components/Feedback';
import { Icon, IconBadge } from '../../components/Icon';
import { Button, Card, Screen, usePullRefresh } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { setViewAsLearner, useViewAsLearner } from '../../lib/viewAs';
import { jalaliDate } from '../../lib/jalali';
import { play, setSoundEnabled, soundEnabled } from '../../lib/sound';
import { setCoverTheme, useCoverTheme } from '../../lib/coverTheme';
import { colors, rtl, toPersianDigits } from '../../theme';

function Row({ label, value, onPress, danger }: { label: string; value?: string; onPress: () => void; danger?: boolean }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.row, pressed && { backgroundColor: colors.ground }]} accessibilityRole="button">
      <Text style={[styles.rowLabel, rtl, danger && { color: colors.redDark }]}>{label}</Text>
      {value ? <Text style={styles.rowValue}>{value}</Text> : <Icon name="chevron-left" size={20} color={colors.muted} />}
    </Pressable>
  );
}

export default function Profile() {
  const { user, signOut } = useAuth();
  const { confirm } = useFeedback();
  const [purchases, setPurchases] = useState<Purchases | null>(null);
  const [sound, setSound] = useState(true);
  const coverTheme = useCoverTheme();
  const asLearner = useViewAsLearner();
  useEffect(() => {
    soundEnabled().then(setSound);
  }, []);

  const [reloading, setReloading] = useState(false);
  const reload = useCallback(() => {
    if (!user) return;
    setReloading(true);
    Promise.all([
      endpoints.purchases().then(setPurchases).catch(() => undefined),
    ]).finally(() => setReloading(false));
  }, [user]);
  useFocusEffect(reload);
  const refresh = usePullRefresh(reloading, reload);

  const name = user ? [user.first_name, user.last_name].filter(Boolean).join(' ') || 'کاربر لیمو پلاس' : 'مهمان';

  return (
    <Screen tab>
      <ScrollView contentContainerStyle={styles.page} refreshControl={refresh}>
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
                  {p.ends_at ? `، تا ${jalaliDate(p.ends_at)}` : '، همیشگی'}
                </Text>
              ))}
            </Card>
          )
        )}

        <View style={styles.group}>
          {user && <Row label="ویرایش نام" onPress={() => router.push('/edit-profile')} />}
          {user && <Row label="دستگاه‌های من" onPress={() => router.push('/devices')} />}
          <Row label="کتاب‌های آفلاین" onPress={() => router.push('/offline')} />
          <View style={styles.row}>
            <Text style={[styles.rowLabel, rtl]}>صدای جشن‌ها</Text>
            <Switch
              value={sound}
              onValueChange={async (on) => {
                setSound(on);
                await setSoundEnabled(on);
                if (on) play('pop');
              }}
              trackColor={{ true: colors.green }}
              accessibilityLabel="صدای جشن‌ها"
            />
          </View>
          <View style={styles.row}>
            <Text style={[styles.rowLabel, rtl]}>جلد کتاب‌ها</Text>
            <View style={styles.segment} accessibilityRole="radiogroup">
              {(['dark', 'light'] as const).map((t) => (
                <Pressable
                  key={t}
                  onPress={() => setCoverTheme(t)}
                  style={[styles.segmentItem, coverTheme === t && styles.segmentOn]}
                  accessibilityRole="radio"
                  accessibilityState={{ checked: coverTheme === t }}
                >
                  <View style={[styles.swatch, { backgroundColor: t === 'dark' ? colors.ink : '#F4F0E3' }]} />
                  <Text style={[styles.segmentText, coverTheme === t && { color: colors.ink }]}>{t === 'dark' ? 'تیره' : 'روشن'}</Text>
                </Pressable>
              ))}
            </View>
          </View>
          <Row label="تنظیمات سرور" onPress={() => router.push('/settings')} />
          {user?.is_staff && (
            <View style={styles.row}>
              <View style={{ flex: 1 }}>
                <Text style={[styles.rowLabel, rtl]}>نمایش مثل کاربر عادی</Text>
                <Text style={[styles.rowHint, rtl]}>فقط برای مدیر: قفل‌ها، قیمت‌ها و برچسب‌ها را مثل کاربر بدون خرید ببینید. با بستن اپ خاموش می‌شود.</Text>
              </View>
              <Switch value={asLearner} onValueChange={setViewAsLearner} trackColor={{ true: colors.green }} accessibilityLabel="نمایش مثل کاربر عادی" />
            </View>
          )}
        </View>

        <View style={styles.soon}>
          <View style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 8, flex: 1 }}>
            <IconBadge name="sparkles" size={32} />
            <Text style={[styles.soonText, rtl, { flex: 1 }]}>دستیار هوش مصنوعی</Text>
          </View>
          <Text style={styles.soonBadge}>به‌زودی</Text>
        </View>

        {user && (
          <View style={styles.group}>
            <Row
              label="خروج از حساب"
              danger
              onPress={async () => {
                const ok = await confirm({
                  title: 'از حساب خارج می‌شوید؟',
                  message: 'کتاب‌های آفلاین این گوشی پاک می‌شوند. پیشرفت، یادداشت‌ها و خریدهای شما روی حساب می‌ماند.',
                  confirmLabel: 'خروج',
                  destructive: true,
                  icon: 'log-out',
                });
                if (ok) signOut().then(() => router.replace('/home'));
              }}
            />
          </View>
        )}
        <Text style={styles.version}>لیمو پلاس، نسخه‌ی {APP_BUILD ? toPersianDigits(APP_BUILD) : 'آزمایشی'}</Text>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  rowHint: { fontSize: 12, color: colors.muted, marginTop: 2 },
  page: { padding: 20, gap: 16 },
  hero: { flexDirection: 'row-reverse', alignItems: 'center', gap: 14, backgroundColor: colors.ink, borderRadius: 26, padding: 18 },
  avatar: { width: 72, height: 72, borderRadius: 36, overflow: 'hidden', alignItems: 'center', justifyContent: 'center', backgroundColor: '#24302A' },
  name: { fontSize: 20, fontWeight: '800', color: colors.lemon },
  phone: { fontSize: 14, color: '#C9D0C6' },
  cardTitle: { fontSize: 15, fontWeight: '800', color: colors.ink },
  line: { fontSize: 14, color: colors.muted },
  group: { backgroundColor: colors.surface, borderRadius: 20, borderWidth: 1, borderColor: colors.line, overflow: 'hidden' },
  row: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 15, borderBottomWidth: 1, borderBottomColor: colors.line },
  rowLabel: { fontSize: 15, fontWeight: '700', color: colors.ink },
  rowValue: { fontSize: 14, color: colors.muted },
  soon: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', borderWidth: 1, borderStyle: 'dashed', borderColor: '#B9C4BC', borderRadius: 14, padding: 12 },
  soonText: { color: colors.muted, fontSize: 13 },
  soonBadge: { backgroundColor: colors.lemonSoft, color: '#6B5200', fontSize: 12, fontWeight: '700', borderRadius: 999, paddingHorizontal: 10, paddingVertical: 2, overflow: 'hidden' },
  segment: { flexDirection: 'row-reverse', backgroundColor: colors.ground, borderRadius: 12, padding: 3, gap: 3 },
  segmentItem: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 10 },
  segmentOn: { backgroundColor: colors.surface, shadowColor: '#17201A', shadowOpacity: 0.08, shadowRadius: 4, elevation: 1 },
  segmentText: { fontSize: 13, fontWeight: '700', color: colors.muted },
  swatch: { width: 12, height: 18, borderRadius: 3, borderWidth: 1, borderColor: colors.line },
  version: { textAlign: 'center', color: colors.muted, fontSize: 12 },
});
