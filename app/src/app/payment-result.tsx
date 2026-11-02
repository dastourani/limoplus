import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { endpoints, type OrderStatus } from '../api/endpoints';
import { useCelebrate } from '../components/Celebrate';
import { Text } from '../components/Text';
import { Icon } from '../components/Icon';
import { Button, Loading, Screen } from '../components/ui';
import { colors, formatToman, toPersianDigits } from '../theme';

/** Landing page after the gateway (deep link limokhan://payment-result?order=…). Asks the server, never trusts the link. */
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
  return (
    <Screen>
      <View style={styles.page}>
        <Icon name={paid ? 'circle-check' : 'circle-x'} size={72} color={paid ? colors.green : colors.red} strokeWidth={1.6} />
        <Text style={styles.title}>{paid ? 'پرداخت موفق بود' : status?.status === 'pending' ? 'پرداخت هنوز تأیید نشده' : 'پرداخت انجام نشد'}</Text>
        {status && (
          <Text style={styles.text}>
            {status.title}
            {'\n'}
            {formatToman(status.amount)}
            {status.ref_number ? `\nشماره‌ی پیگیری: ${toPersianDigits(status.ref_number)}` : ''}
          </Text>
        )}
        {!paid && <Text style={styles.text}>اگر مبلغی از حسابتان کم شده، تا ۷۲ ساعت به حسابتان برمی‌گردد.</Text>}
        {paid && status?.book_slug ? (
          <Button label="رفتن به کتاب" onPress={() => router.replace(`/book/${status.book_slug}`)} style={{ alignSelf: 'stretch' }} />
        ) : null}
        <Button label="خانه" variant={paid && status?.book_slug ? 'outline' : 'primary'} onPress={() => router.replace('/home')} style={{ alignSelf: 'stretch' }} />
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  icon: { fontSize: 64, fontWeight: '900' },
  title: { fontSize: 22, fontWeight: '800', color: colors.ink },
  text: { fontSize: 15, color: colors.muted, textAlign: 'center', lineHeight: 26 },
});
