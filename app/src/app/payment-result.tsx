import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { endpoints, type OrderStatus } from '../api/endpoints';
import { useCelebrate } from '../components/Celebrate';
import { Text } from '../components/Text';
import { Icon } from '../components/Icon';
import { Button, Loading, Screen } from '../components/ui';
import { jalaliDate } from '../lib/jalali';
import { colors, formatToman, toPersianDigits } from '../theme';

/** Landing page after the gateway (deep link limookhan://payment-result?order=…). Asks the server, never trusts the link. */
export default function PaymentResult() {
  const { order } = useLocalSearchParams<{ order?: string }>();
  const [status, setStatus] = useState<OrderStatus | null>(null);
  const [failed, setFailed] = useState(false);
  const celebrate = useCelebrate();

  useEffect(() => {
    const id = Number(order);
    if (!id) {
      setFailed(true);
      return;
    }
    endpoints
      .order(id, true)
      .then((s) => {
        setStatus(s);
        if (s.status === 'paid') celebrate('purchase', { once: `purchase.${id}`, title: s.book_slug ? 'کتاب باز شد!' : 'اشتراکت فعال شد!', text: s.book_slug ? 'نسخه‌ی کامل حالا در دسترس توست. مطالعه‌ی خوبی داشته باشی!' : 'همه‌ی کتاب‌های اشتراک برایت باز است.', primary: 'شروع مطالعه' });
      })
      .catch(() => setFailed(true));
  }, [order, celebrate]);

  if (!status && !failed) return <Screen><Loading /></Screen>;
  const paid = status?.status === 'paid';
  const accessLine = paid
    ? status?.starts_at && status?.ends_at
      ? `\nبازهٔ دسترسی: از ${jalaliDate(status.starts_at)} تا ${jalaliDate(status.ends_at)}`
      : status?.kind === 'book' || status?.book_slug
        ? '\nدسترسی شخصی به کتاب، بدون تاریخ انقضای اشتراک'
        : ''
    : '';
  return (
    <Screen>
      <View style={styles.page}>
        <Icon name={paid ? 'circle-check' : 'circle-x'} size={72} color={paid ? colors.green : colors.red} strokeWidth={1.6} />
        <Text style={styles.title}>{paid ? 'پرداخت موفق بود' : status?.status === 'pending' ? 'پرداخت هنوز تأیید نشده' : 'پرداخت انجام نشد'}</Text>
        {status && (
          <Text style={styles.text}>
            {status.title}
            {`\nشمارهٔ سفارش: #${toPersianDigits(status.id)}`}
            {'\n'}
            {status.regular_amount > status.amount
              ? `قیمت عادی: ${formatToman(status.regular_amount)}\n${status.campaign_title ? `${status.campaign_title} · ` : ''}تخفیف: ${formatToman(status.discount_amount)}\nمبلغ پرداخت‌شده: ${formatToman(status.amount)}`
              : `مبلغ: ${formatToman(status.amount)}`}
            {accessLine}
            {status.ref_number ? `\nشماره‌ی پیگیری: ${toPersianDigits(status.ref_number)}` : ''}
          </Text>
        )}
        {!paid && <Text style={styles.text}>اگر مبلغی از حسابتان کم شده، تا ۷۲ ساعت به حسابتان برمی‌گردد.</Text>}
        {paid && status?.book_slug ? (
          <Button label="رفتن به کتاب" onPress={() => router.replace(`/book/${status.book_slug}`)} style={{ alignSelf: 'stretch' }} />
        ) : null}
        <Button label="خانه" variant={paid && status?.book_slug ? 'outline' : 'primary'} onPress={() => router.replace('/home')} style={{ alignSelf: 'stretch' }} />
        <View style={styles.legalLinks}>
          <Pressable onPress={() => router.push('/page/terms')} accessibilityRole="link">
            <Text style={styles.legalLink}>شرایط انصراف و بازپرداخت</Text>
          </Pressable>
          <Text style={styles.legalDot}>·</Text>
          <Pressable onPress={() => router.push('/page/contact')} accessibilityRole="link">
            <Text style={styles.legalLink}>پیگیری سفارش</Text>
          </Pressable>
        </View>
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  icon: { fontSize: 64, fontWeight: '900' },
  title: { fontSize: 22, fontWeight: '800', color: colors.ink },
  text: { fontSize: 15, color: colors.muted, textAlign: 'center', lineHeight: 26 },
  legalLinks: { flexDirection: 'row-reverse', justifyContent: 'center', alignItems: 'center', gap: 10, marginTop: 4 },
  legalLink: { fontSize: 12.5, fontWeight: '700', color: colors.greenDark, textDecorationLine: 'underline' },
  legalDot: { fontSize: 12.5, color: colors.muted },
});
