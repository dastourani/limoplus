import { router, useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, Switch, View } from 'react-native';

import { endpoints, type AppPages, type Purchases } from '../../api/endpoints';
import { LemonSlice } from '../../components/LemonSlice';
import { Text } from '../../components/Text';
import { APP_BUILD, getApiUrl, getDefaultApiUrl } from '../../config';
import { useFeedback } from '../../components/Feedback';
import { Icon, IconBadge } from '../../components/Icon';
import { Button, Card, Screen, usePullRefresh, Chip } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { setViewAsLearner, useViewAsLearner } from '../../lib/viewAs';
import { jalaliDate } from '../../lib/jalali';
import { changedPages } from '../../lib/pages';
import { play, setSoundEnabled, soundEnabled } from '../../lib/sound';
import { setCoverTheme, useCoverTheme } from '../../lib/coverTheme';
import { storage } from '../../lib/storage';
import { colors, rtl, toPersianDigits } from '../../theme';

function Row({ label, value, onPress, danger, badge }: { label: string; value?: string; onPress: () => void; danger?: boolean; badge?: string }) {
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.row, pressed && { backgroundColor: colors.ground }]} accessibilityRole="button">
      <Text style={[styles.rowLabel, rtl, danger && { color: colors.redDark }]}>{label}</Text>
      {!!badge && <Chip label={badge} color="#6B5200" background={colors.lemonSoft} />}
      {value ? <Text style={styles.rowValue}>{value}</Text> : <Icon name="chevron-left" size={20} color={colors.muted} />}
    </Pressable>
  );
}

export default function Profile() {
  const { user, signOut } = useAuth();
  const { confirm } = useFeedback();
  const [purchases, setPurchases] = useState<Purchases | null>(null);
  const [showAll, setShowAll] = useState(false);
  const [sound, setSound] = useState(true);
  const [justify, setJustify] = useState(true);
  const coverTheme = useCoverTheme();
  const asLearner = useViewAsLearner();
  useEffect(() => {
    soundEnabled().then(setSound);
    storage.getReader().then((p) => setJustify(p?.justify ?? true));
  }, []);

  const [reloading, setReloading] = useState(false);
  const [versionTaps, setVersionTaps] = useState(0);
  // A test server set in «تنظیمات سرور» is said plainly, so the app is never quietly on another server.
  const [otherServer, setOtherServer] = useState<string | null>(null);
  useFocusEffect(
    useCallback(() => {
      if (Platform.OS === 'web') return;
      getApiUrl()
        .then((u) => setOtherServer(getDefaultApiUrl() && u !== getDefaultApiUrl() ? u : null))
        .catch(() => undefined);
    }, []),
  );
  const serverUnlocked = versionTaps >= 7;
  const [pages, setPages] = useState<AppPages | null>(null);
  const [changed, setChanged] = useState<Set<string>>(new Set());
  const reload = useCallback(() => {
    setReloading(true);
    Promise.all([
      user ? endpoints.purchases().then(setPurchases).catch(() => undefined) : null,
      endpoints
        .appPages()
        .then(async (p) => {
          setPages(p);
          setChanged(new Set((await changedPages(p.pages)).map((x) => x.slug)));
        })
        .catch(() => undefined),
    ]).finally(() => setReloading(false));
  }, [user]);
  useFocusEffect(reload);
  const refresh = usePullRefresh(reloading, reload);

  const name = user ? [user.first_name, user.last_name].filter(Boolean).join(' ') || 'کاربر لیموخوان' : 'مهمان';

  return (
    <Screen tab>
      <ScrollView contentContainerStyle={styles.page} refreshControl={refresh}>
        {!!otherServer && (
          <Pressable onPress={() => router.push('/settings')} style={styles.testServer} accessibilityRole="button">
            <Text style={[styles.testServerText, rtl]}>به سرور آزمایشی وصل است: {otherServer}. برای برگشت به سرور اصلی بزنید.</Text>
          </Pressable>
        )}
        <Text style={[styles.pageTitle, rtl]}>حساب من</Text>
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
              {/* Three at most; the rest behind «همه». A book opens its page. */}
              {(showAll ? purchases.active : purchases.active.slice(0, 3)).map((p) => (
                <Pressable
                  key={p.id}
                  onPress={() => (p.book_slug ? router.push(`/book/${p.book_slug}`) : router.push('/library'))}
                  style={styles.owned}
                  accessibilityRole="button"
                >
                  <IconBadge name={p.kind === 'subscription' ? 'badge-check' : 'book-open'} size={30} />
                  <View style={{ flex: 1 }}>
                    <Text style={[styles.ownedTitle, rtl]} numberOfLines={1}>{p.title}</Text>
                    <Text style={[styles.rowHint, rtl]}>{p.ends_at ? `تا ${jalaliDate(p.ends_at)}` : 'همیشگی'}</Text>
                  </View>
                  <Icon name="chevron-left" size={18} color={colors.muted} />
                </Pressable>
              ))}
              {purchases.active.length > 3 && (
                <Pressable onPress={() => setShowAll((v) => !v)} accessibilityRole="button" style={{ alignSelf: 'flex-start' }}>
                  <Text style={styles.more}>{showAll ? 'بستن ▴' : `همه (${toPersianDigits(purchases.active.length)}) ▾`}</Text>
                </Pressable>
              )}
            </Card>
          )
        )}

        <View style={styles.group}>
          {user && <Row label="ویرایش نام" onPress={() => router.push('/edit-profile')} />}
          {user && <Row label="دستگاه‌های من" onPress={() => router.push('/devices')} />}
          <Row label="کتاب‌های آفلاین" onPress={() => router.push('/offline')} />
          <View style={styles.row}>
            <Text style={[styles.rowLabel, rtl]}>صدای آفرین</Text>
            <Switch
              value={sound}
              onValueChange={async (on) => {
                setSound(on);
                await setSoundEnabled(on);
                if (on) play('pop');
              }}
              trackColor={{ true: colors.green }}
              accessibilityLabel="صدای آفرین"
            />
          </View>
          <View style={styles.row}>
            <View style={{ flex: 1 }}>
              <Text style={[styles.rowLabel, rtl]}>متن درس تراز باشد</Text>
              <Text style={[styles.rowHint, rtl]}>پاراگراف‌ها از دو طرف صاف، مثل کتاب چاپی. خاموش: راست‌چین.</Text>
            </View>
            <Switch
              value={justify}
              onValueChange={async (on) => {
                setJustify(on);
                const p = await storage.getReader();
                await storage.setReader({ ...(p ?? { fontSize: 17 }), justify: on });
              }}
              trackColor={{ true: colors.green }}
              accessibilityLabel="متن درس تراز باشد"
            />
          </View>
          {/* «ظاهر اپ»: two little covers; the chosen one has a lemon border and a tick. */}
          <View style={[styles.row, { flexDirection: 'column', alignItems: 'stretch', gap: 10 }]}>
            <View>
              <Text style={[styles.rowLabel, rtl]}>ظاهر اپ</Text>
              <Text style={[styles.rowHint, rtl]}>جلد کتاب‌ها، کارت‌های صفحه‌ی اول و بالای صفحه‌ی کتاب</Text>
            </View>
            <View style={styles.looks} accessibilityRole="radiogroup">
              {(['dark', 'light'] as const).map((t) => {
                const on = coverTheme === t;
                return (
                  <Pressable
                    key={t}
                    onPress={() => setCoverTheme(t)}
                    style={[styles.look, on && styles.lookOn]}
                    accessibilityRole="radio"
                    accessibilityState={{ checked: on }}
                    accessibilityLabel={t === 'dark' ? 'ظاهر تیره' : 'ظاهر روشن'}
                  >
                    <View style={[styles.mini, t === 'light' ? styles.miniLight : styles.miniDark]}>
                      <View style={styles.miniTop} />
                      <View style={[styles.miniRing, { borderColor: t === 'light' ? '#C9A400' : colors.lemon }]} />
                      <View style={[styles.miniLine, { backgroundColor: t === 'light' ? colors.ink : '#FFFFFF' }]} />
                      <View style={[styles.miniDash, { backgroundColor: t === 'light' ? '#C9A400' : colors.lemon }]} />
                    </View>
                    <View style={styles.lookLabel}>
                      <Icon name={t === 'dark' ? 'moon' : 'sun'} size={16} color={colors.ink} />
                      <Text style={styles.lookText}>{t === 'dark' ? 'تیره' : 'روشن'}</Text>
                    </View>
                    {on && (
                      <View style={styles.lookTick}>
                        <Icon name="check" size={14} color={colors.ink} />
                      </View>
                    )}
                  </Pressable>
                );
              })}
            </View>
          </View>
          {/* Only for the owner, while testing: hidden on the web (always its own server) and, in the Android app,
              until the version line below is tapped seven times. */}
          {Platform.OS !== 'web' && serverUnlocked && <Row label="تنظیمات سرور" onPress={() => router.push('/settings')} />}
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

        {/* «راهنما»: the lemons guide, then the pages written in the panel; «قوانین»: site pages ticked «نمایش در اپ». */}
        <Text style={[styles.groupTitle, rtl]}>راهنما</Text>
        <View style={styles.group}>
          <Row label="لیموها چه می‌گویند؟" onPress={() => router.push('/lemons')} />
          {pages?.help.map((h) => (
            <Row key={h.id} label={h.title} onPress={() => router.push({ pathname: '/help/[id]', params: { id: String(h.id) } })} />
          ))}
        </View>
        {!!pages?.pages.length && (
          <>
            <Text style={[styles.groupTitle, rtl]}>قوانین</Text>
            <View style={styles.group}>
              {pages.pages.map((p) => (
                <Row
                  key={p.slug}
                  label={p.title}
                  badge={changed.has(p.slug) ? 'به‌روز شد' : undefined}
                  onPress={() => router.push({ pathname: '/page/[slug]', params: { slug: p.slug } })}
                />
              ))}
            </View>
          </>
        )}

        <View style={styles.soon}>
          <View style={{ flexDirection: 'row-reverse', alignItems: 'center', gap: 8, flex: 1 }}>
            <IconBadge name="sparkles" size={32} />
            <Text style={[styles.soonText, rtl, { flex: 1 }]}>دستیار هوش مصنوعی</Text>
          </View>
          <Chip label="به‌زودی" color="#6B5200" background={colors.lemonSoft} />
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
        <Text style={styles.version} onPress={() => setVersionTaps((n) => n + 1)} suppressHighlighting>
          لیموخوان، نسخه‌ی {APP_BUILD ? toPersianDigits(APP_BUILD) : 'آزمایشی'}
        </Text>
        {Platform.OS !== 'web' && versionTaps >= 4 && (
          <Text style={[styles.version, { marginTop: -8 }]}>
            {serverUnlocked ? '«تنظیمات سرور» باز شد: بالاتر، پیش از «نمایش مثل کاربر عادی».' : `${toPersianDigits(7 - versionTaps)} ضربه‌ی دیگر`}
          </Text>
        )}
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  testServer: { backgroundColor: colors.lemonSoft, borderRadius: 12, padding: 10, borderWidth: 1, borderColor: colors.lemon },
  testServerText: { fontSize: 13, color: colors.ink },
  pageTitle: { fontSize: 22, fontWeight: '800', color: colors.ink, marginTop: -4, marginBottom: -4 },
  rowHint: { fontSize: 12, color: colors.muted, marginTop: 2 },
  page: { padding: 16, gap: 16 },
  hero: { flexDirection: 'row-reverse', alignItems: 'center', gap: 14, backgroundColor: colors.ink, borderRadius: 26, padding: 18 },
  avatar: { width: 72, height: 72, borderRadius: 36, overflow: 'hidden', alignItems: 'center', justifyContent: 'center', backgroundColor: '#24302A' },
  name: { fontSize: 22, fontWeight: '800', color: colors.lemon },
  phone: { fontSize: 15, color: '#C9D0C6' },
  cardTitle: { fontSize: 15, fontWeight: '800', color: colors.ink },
  line: { fontSize: 15, color: colors.muted },
  owned: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, paddingVertical: 4 },
  ownedTitle: { fontSize: 14, fontWeight: '700', color: colors.ink },
  more: { fontSize: 13, fontWeight: '800', color: colors.greenDark },
  groupTitle: { fontSize: 13, fontWeight: '800', color: colors.muted, marginBottom: -8, paddingHorizontal: 4 },
  group: { backgroundColor: colors.surface, borderRadius: 20, borderWidth: 1, borderColor: colors.line, overflow: 'hidden' },
  row: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', paddingHorizontal: 16, paddingVertical: 15, borderBottomWidth: 1, borderBottomColor: colors.line },
  rowLabel: { fontSize: 15, fontWeight: '700', color: colors.ink },
  rowValue: { fontSize: 15, color: colors.muted },
  soon: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center', borderWidth: 1, borderStyle: 'dashed', borderColor: '#B9C4BC', borderRadius: 14, padding: 12 },
  soonText: { color: colors.muted, fontSize: 13 },
  looks: { flexDirection: 'row-reverse', gap: 12 },
  look: { flex: 1, alignItems: 'center', gap: 8, paddingVertical: 12, borderRadius: 16, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface },
  lookOn: { borderWidth: 3, borderColor: colors.lemon, paddingVertical: 10 },
  lookLabel: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
  lookText: { fontSize: 14, fontWeight: '900', color: colors.ink },
  lookTick: { position: 'absolute', top: -9, left: -9, width: 24, height: 24, borderRadius: 12, backgroundColor: colors.lemon, alignItems: 'center', justifyContent: 'center' },
  mini: { width: 48, height: 70, borderTopLeftRadius: 7, borderBottomLeftRadius: 7, borderTopRightRadius: 3, borderBottomRightRadius: 3, overflow: 'hidden', alignItems: 'center' },
  miniDark: { backgroundColor: '#1E2A23' },
  miniLight: { backgroundColor: '#FBF8EC', borderWidth: 1, borderColor: '#E6DFC4' },
  miniTop: { alignSelf: 'stretch', height: 3, backgroundColor: '#3B44B8' },
  miniRing: { width: 22, height: 22, borderRadius: 11, borderWidth: 1.5, marginTop: 10 },
  miniLine: { width: 28, height: 4, borderRadius: 2, marginTop: 10, opacity: 0.85 },
  miniDash: { width: 12, height: 2, marginTop: 5 },
  segment: { flexDirection: 'row-reverse', backgroundColor: colors.ground, borderRadius: 12, padding: 3, gap: 3 },
  segmentItem: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, paddingHorizontal: 12, paddingVertical: 7, borderRadius: 10 },
  segmentOn: { backgroundColor: colors.surface, shadowColor: '#17201A', shadowOpacity: 0.08, shadowRadius: 4, elevation: 1 },
  segmentText: { fontSize: 13, fontWeight: '700', color: colors.muted },
  swatch: { width: 12, height: 18, borderRadius: 3, borderWidth: 1, borderColor: colors.line },
  version: { textAlign: 'center', color: colors.muted, fontSize: 12 },
});
