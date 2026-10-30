import { router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useEffect, useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints, type Plan } from '../../api/endpoints';
import { Text } from '../../components/Text';
import { Button, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { storage } from '../../lib/storage';
import { useApi } from '../../lib/useApi';
import { colors, formatToman, radius, rtl, toPersianDigits } from '../../theme';

type Choice = { kind: 'book' } | { kind: 'plan'; plan: Plan };

/** Buying a book or a subscription. Prices are shown from the server and the server computes the amount again. */
export default function Buy() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { user } = useAuth();
  const { data, error, loading, retry } = useApi(() => endpoints.offers(String(slug)), [slug]);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [major, setMajor] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [pendingOrder, setPendingOrder] = useState<number | null>(null);

  // The subscription major defaults to the space the learner is in.
  useEffect(() => {
    if (!data) return;
    storage.getMajor().then((m) => m && data.majors.some((x) => x.slug === m.slug) && setMajor((cur) => cur ?? m.slug));
  }, [data]);

  if (loading) return <Screen><Header title="خرید" /><Loading /></Screen>;
  if (error || !data) return <Screen><Header title="خرید" /><ErrorState message={error?.message ?? ''} onRetry={retry} /></Screen>;

  const majorChoice = major ?? (data.majors.length === 1 ? data.majors[0].slug : null);
  const needsMajor = choice?.kind === 'plan' && choice.plan.scope === 'major';
  const ready = !!choice && (!needsMajor || !!majorChoice);

  const check = async (orderId: number) => {
    const order = await endpoints.order(orderId, true).catch(() => null);
    if (order?.status === 'paid') router.replace({ pathname: '/payment-result', params: { order: String(orderId) } });
    else if (order?.status === 'failed') setMessage('پرداخت انجام نشد. اگر مبلغی کم شده، تا ۷۲ ساعت برمی‌گردد.');
    else setMessage('پرداخت هنوز تأیید نشده است. اگر پرداخت کرده‌اید چند لحظه بعد دوباره بررسی کنید.');
  };

  const pay = async () => {
    if (!choice || !requireLogin(user, 'برای خرید وارد شوید؛ کتاب روی حساب شما ثبت می‌شود.')) return;
    setBusy(true);
    setMessage(null);
    try {
      const order = await endpoints.createOrder(choice.kind === 'book' ? { book: data.book.slug } : { plan: choice.plan.id, major: needsMajor ? majorChoice! : undefined });
      setPendingOrder(order.order_id);
      if (Platform.OS === 'web') {
        window.open(order.pay_url, '_blank');
        setMessage('بعد از پرداخت در صفحه‌ی باز‌شده، اینجا «بررسی پرداخت» را بزنید.');
      } else {
        await WebBrowser.openAuthSessionAsync(order.pay_url, 'limoplus://payment-result');
        await check(order.order_id);
      }
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : 'شروع پرداخت ممکن نشد.');
    } finally {
      setBusy(false);
    }
  };

  const Option = ({ on, title, price, sub, onPress }: { on: boolean; title: string; price: number; sub: string; onPress: () => void }) => (
    <Pressable onPress={onPress} style={[styles.option, on && styles.optionOn]} accessibilityRole="radio" accessibilityState={{ checked: on }}>
      <View style={{ flex: 1, gap: 4 }}>
        <Text style={[styles.optionTitle, rtl]}>{title}</Text>
        <Text style={[styles.sub, rtl]}>{sub}</Text>
      </View>
      <Text style={styles.price}>{formatToman(price)}</Text>
    </Pressable>
  );

  return (
    <Screen>
      <Header title="خرید" subtitle={data.book.title} />
      <ScrollView contentContainerStyle={styles.page}>
        {!!data.book.price && (
          <Option
            on={choice?.kind === 'book'}
            title={`خرید کتاب «${data.book.title}»`}
            sub="همیشگی؛ خلاصه، جزوه، تست‌ها و فلش‌کارت‌های کتاب"
            price={data.book.price}
            onPress={() => setChoice({ kind: 'book' })}
          />
        )}
        {data.plans.length > 0 && <Text style={[styles.group, rtl]}>یا اشتراک (همه‌ی کتاب‌های رشته)</Text>}
        {data.plans.map((plan) => (
          <Option
            key={plan.id}
            on={choice?.kind === 'plan' && choice.plan.id === plan.id}
            title={plan.title}
            sub={`${toPersianDigits(plan.months)} ماه · ${plan.scope === 'all' ? 'همه‌ی رشته‌ها' : 'همه‌ی کتاب‌های یک رشته'}`}
            price={plan.price}
            onPress={() => setChoice({ kind: 'plan', plan })}
          />
        ))}
        {needsMajor && data.majors.length > 1 && (
          <View style={{ gap: 8 }}>
            <Text style={[styles.group, rtl]}>اشتراک کدام رشته؟</Text>
            <View style={styles.majors}>
              {data.majors.map((m) => (
                <Pressable key={m.slug} onPress={() => setMajor(m.slug)} style={[styles.major, majorChoice === m.slug && styles.majorOn]}>
                  <Text style={{ fontWeight: '800', color: majorChoice === m.slug ? colors.lemon : colors.ink }}>{m.name}</Text>
                </Pressable>
              ))}
            </View>
          </View>
        )}
        <Text style={[styles.sub, rtl]}>پرداخت امن با درگاه زیبال. بعد از پرداخت، کتاب فوراً برایتان باز می‌شود.</Text>
        {!!message && <Text style={[styles.message, rtl]}>{message}</Text>}
      </ScrollView>
      <View style={styles.bar}>
        {pendingOrder && <Button label="بررسی پرداخت" variant="outline" onPress={() => check(pendingOrder)} />}
        <Button label={busy ? 'در حال اتصال به درگاه…' : 'پرداخت'} disabled={!ready || busy} onPress={pay} />
      </View>
    </Screen>
  );
}


const styles = StyleSheet.create({
  page: { padding: 16, gap: 12 },
  option: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, padding: 16, borderRadius: radius.md, borderWidth: 2, borderColor: colors.line, backgroundColor: colors.surface },
  optionOn: { borderColor: colors.ink, backgroundColor: colors.lemonSoft },
  optionTitle: { fontSize: 16, fontWeight: '800', color: colors.ink },
  sub: { fontSize: 13, color: colors.muted, lineHeight: 22 },
  price: { fontSize: 15, fontWeight: '900', color: colors.ink },
  group: { fontSize: 14, fontWeight: '800', color: colors.muted, marginTop: 8 },
  majors: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8 },
  major: { paddingHorizontal: 16, paddingVertical: 10, borderRadius: 999, borderWidth: 1.5, borderColor: colors.line, backgroundColor: colors.surface },
  majorOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  message: { backgroundColor: colors.lemonSoft, padding: 12, borderRadius: 12, color: '#6B5200', lineHeight: 24 },
  bar: { padding: 12, gap: 8, borderTopWidth: 1, borderTopColor: colors.line },
});
