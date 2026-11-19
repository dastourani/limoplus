import { router, useLocalSearchParams } from 'expo-router';
import * as WebBrowser from 'expo-web-browser';
import { useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints, type Plan, type PriceDiscount } from '../../api/endpoints';
import { BookCover } from '../../components/BookCover';
import { Text } from '../../components/Text';
import { Button, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { coverByline } from '../../lib/cover';
import { currentPrice, percentLabel } from '../../lib/pricing';
import { useApi } from '../../lib/useApi';
import { colors, formatToman, radius, rtl, toPersianDigits } from '../../theme';

type Choice = { kind: 'book' } | { kind: 'plan'; plan: Plan };

/** Buying a book or a subscription. Prices are shown from the server and the server computes the amount again. */
export default function Buy() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { user } = useAuth();
  const { data, error, loading, retry } = useApi(() => endpoints.offers(String(slug)), [slug]);
  const [choice, setChoice] = useState<Choice | null>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState<string | null>(null);
  const [pendingOrder, setPendingOrder] = useState<number | null>(null);
  const book = useApi(() => endpoints.book(String(slug)), [slug]);

  if (loading) return <Screen><Header title="باز کردن کتاب" /><Loading /></Screen>;
  if (error || !data) return <Screen><Header title="باز کردن کتاب" /><ErrorState message={error?.message ?? ''} onRetry={retry} /></Screen>;

  const ready = !!choice;

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
      const order = await endpoints.createOrder(choice.kind === 'book' ? { book: data.book.slug } : { plan: choice.plan.id });
      if (order.amount !== amount) {
        // Campaigns can start/end between rendering this quote and creating the order. Never silently send a learner
        // to the bank for a different amount; refresh the server quote and ask them to choose again.
        setChoice(null);
        setMessage(`قیمت زمان سفارش به‌روز شد؛ مبلغ فعلی ${formatToman(order.amount)} است. گزینه‌ها تازه می‌شوند؛ لطفاً دوباره انتخاب کنید.`);
        retry();
        return;
      }
      setPendingOrder(order.order_id);
      if (Platform.OS === 'web') {
        window.open(order.pay_url, '_blank');
        setMessage('بعد از پرداخت در صفحه‌ی باز‌شده، اینجا «بررسی پرداخت» را بزنید.');
      } else {
        await WebBrowser.openAuthSessionAsync(order.pay_url, 'limookhan://payment-result');
        await check(order.order_id);
      }
    } catch (e) {
      setMessage(e instanceof ApiError ? e.message : 'شروع پرداخت ممکن نشد.');
    } finally {
      setBusy(false);
    }
  };

  const Option = ({ on, title, price, regularPrice, discount, unit, sub, badge, onPress }: {
    on: boolean;
    title: string;
    price: number | null;
    regularPrice: number | null;
    discount: PriceDiscount | null;
    unit?: string;
    sub: string;
    badge?: string;
    onPress: () => void;
  }) => {
    const shown = currentPrice({ price, regular_price: regularPrice, discount });
    return (
      <Pressable onPress={onPress} style={[styles.option, on && styles.optionOn]} accessibilityRole="radio" accessibilityState={{ checked: on }}>
        <View style={[styles.radio, on && styles.radioOn]}>{on && <View style={styles.radioDot} />}</View>
        <View style={{ flex: 1, gap: 4 }}>
          <View style={styles.optionTop}>
            <Text style={[styles.optionTitle, rtl, { flex: 1 }]}>{title}</Text>
            <View style={styles.priceColumn}>
              <Text style={styles.price}>
                {formatToman(shown.price ?? 0).replace(' تومان', '')} <Text style={styles.unit}>{unit ?? 'تومان'}</Text>
              </Text>
              {shown.discount && (
                <View style={styles.priceDeal}>
                  <Text style={styles.oldPrice}>{formatToman(shown.regularPrice ?? 0)}</Text>
                  <Text style={styles.priceBadge}>{percentLabel(shown.discount.percent)}٪ تخفیف</Text>
                </View>
              )}
            </View>
          </View>
          <Text style={[styles.sub, rtl]}>{sub}</Text>
        </View>
        {!!badge && <Text style={styles.badge}>{badge}</Text>}
      </Pressable>
    );
  };

  const bookPrice = currentPrice(data.book);
  const selectedPrice = choice?.kind === 'book' ? bookPrice : choice?.kind === 'plan' ? currentPrice(choice.plan) : null;
  const amount = selectedPrice?.price ?? 0;

  return (
    <Screen>
      <Header title="باز کردن کتاب" />
      <ScrollView contentContainerStyle={styles.page}>
        <View style={styles.bookCard}>
          {book.data ? <BookCover book={book.data} major={book.data?.major ?? null} width={64} /> : <View style={styles.coverSpace} />}
          <View style={{ flex: 1, gap: 3 }}>
            <Text style={[styles.bookTitle, rtl]}>{data.book.title}</Text>
            {!!book.data && !!coverByline(book.data.author, book.data.edition) && <Text style={[styles.sub, rtl]}>{coverByline(book.data.author, book.data.edition)}</Text>}
            {!!book.data && (
              <Text style={[styles.sub, rtl]}>
                {toPersianDigits(book.data.chapter_count)} فصل، {toPersianDigits(book.data.section_count)} بخش
              </Text>
            )}
          </View>
        </View>

        <Text style={[styles.group, rtl]}>یکی را انتخاب کن</Text>
        {!!bookPrice.price && (
          <Option
            on={choice?.kind === 'book'}
            title="فقط همین کتاب"
            sub="یک‌بار پرداخت، همیشه مال تو؛ همه‌ی فصل‌های فعلی و فصل‌هایی که بعداً اضافه می‌شوند."
            price={data.book.price}
            regularPrice={data.book.regular_price}
            discount={data.book.discount}
            onPress={() => setChoice({ kind: 'book' })}
          />
        )}
        {data.plans.map((plan, i) => (
          <Option
            key={plan.id}
            on={choice?.kind === 'plan' && choice.plan.id === plan.id}
            title={plan.title}
            sub={`همه‌ی کتاب‌های لیموخوان تا وقتی اشتراک داری (${toPersianDigits(plan.months)} ماه)؛ کتاب‌های تازه هم خودکار اضافه می‌شوند.`}
            price={plan.price}
            regularPrice={plan.regular_price}
            discount={plan.discount}
            unit={plan.months === 1 ? 'تومان برای یک ماه' : `تومان برای ${toPersianDigits(plan.months)} ماه`}
            badge={i === 0 ? 'برای چند کتاب به‌صرفه‌تر' : undefined}
            onPress={() => setChoice({ kind: 'plan', plan })}
          />
        ))}
        {!!choice && (
          <View style={styles.summary}>
            {selectedPrice?.discount && (
              <>
                <View style={styles.summaryRow}>
                  <Text style={[styles.sub, rtl]}>قیمت عادی</Text>
                  <Text style={styles.oldPrice}>{formatToman(selectedPrice.regularPrice ?? amount)}</Text>
                </View>
                <View style={styles.summaryRow}>
                  <Text style={[styles.sub, rtl]}>صرفه‌جویی کمپین</Text>
                  <Text style={styles.saving}>−{formatToman(selectedPrice.discount.amount)}</Text>
                </View>
              </>
            )}
            <View style={styles.rule} />
            <View style={styles.summaryRow}>
              <Text style={[styles.summaryTotal, rtl]}>قابل پرداخت</Text>
              <Text style={styles.summaryTotal}>{formatToman(amount)}</Text>
            </View>
          </View>
        )}
        <Text style={[styles.sub, rtl, { textAlign: 'center' }]}>
          به درگاه بانکی زیبال می‌روی و بعد از پرداخت خودکار به اپ برمی‌گردی؛ قفل باز می‌شود و از همان‌جا ادامه می‌دهی.
        </Text>
        {!!message && <Text style={[styles.message, rtl]}>{message}</Text>}
      </ScrollView>
      <View style={styles.bar}>
        {pendingOrder && <Button label="بررسی پرداخت" variant="outline" onPress={() => check(pendingOrder)} />}
        <Button label={busy ? 'اتصال به درگاه' : 'پرداخت امن با زیبال'} variant="primary" disabled={!ready} loading={busy} onPress={pay} />
      </View>
    </Screen>
  );
}


const styles = StyleSheet.create({
  page: { padding: 16, gap: 12, maxWidth: 760, width: '100%', alignSelf: 'center' },
  bookCard: { flexDirection: 'row-reverse', alignItems: 'center', gap: 14, backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, padding: 12 },
  coverSpace: { width: 64, height: 96, borderRadius: 8, backgroundColor: colors.ink },
  bookTitle: { fontSize: 15, fontWeight: '900', color: colors.ink },
  option: { flexDirection: 'row-reverse', alignItems: 'flex-start', gap: 12, padding: 16, borderRadius: 18, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface },
  optionOn: { borderWidth: 2, borderColor: colors.ink, shadowColor: '#17201A', shadowOpacity: 0.1, shadowRadius: 12, shadowOffset: { width: 0, height: 6 }, elevation: 3 },
  optionTop: { flexDirection: 'row-reverse', alignItems: 'flex-start', gap: 8 },
  radio: { width: 22, height: 22, borderRadius: 11, borderWidth: 2, borderColor: '#CBD3C6', alignItems: 'center', justifyContent: 'center', marginTop: 2 },
  radioOn: { borderColor: colors.ink },
  radioDot: { width: 11, height: 11, borderRadius: 6, backgroundColor: colors.ink },
  optionTitle: { fontSize: 15, fontWeight: '900', color: colors.ink },
  sub: { fontSize: 12.5, color: colors.muted, lineHeight: 22 },
  priceColumn: { alignItems: 'flex-end', gap: 2 },
  price: { fontSize: 15, fontWeight: '900', color: colors.ink },
  priceDeal: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
  oldPrice: { fontSize: 12, color: colors.muted, textDecorationLine: 'line-through' },
  priceBadge: { fontSize: 10, fontWeight: '900', color: colors.redDark, backgroundColor: colors.redSoft, borderRadius: 6, paddingHorizontal: 5, paddingVertical: 1, overflow: 'hidden' },
  saving: { fontSize: 13, fontWeight: '800', color: colors.redDark },
  unit: { fontSize: 11, fontWeight: '400', color: colors.muted },
  badge: { position: 'absolute', top: -10, left: 16, backgroundColor: '#3FB8A9', color: '#FFFFFF', fontSize: 11, fontWeight: '800', paddingHorizontal: 9, paddingVertical: 2, borderRadius: 8, overflow: 'hidden' },
  group: { fontSize: 15, fontWeight: '900', color: colors.ink, marginTop: 6 },
  summary: { backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, paddingHorizontal: 16, paddingVertical: 12, gap: 8 },
  summaryRow: { flexDirection: 'row-reverse', justifyContent: 'space-between', alignItems: 'center' },
  summaryValue: { fontSize: 13, color: colors.ink },
  summaryTotal: { fontSize: 15, fontWeight: '900', color: colors.ink },
  rule: { height: 1, backgroundColor: colors.line },
  message: { backgroundColor: colors.lemonSoft, padding: 12, borderRadius: 12, color: '#6B5200', lineHeight: 24 },
  bar: { padding: 12, gap: 8, borderTopWidth: 1, borderTopColor: colors.line },
});
