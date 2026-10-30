import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { StyleSheet, View } from 'react-native';

import { endpoints, type OrderStatus } from '../api/endpoints';
import { Text } from '../components/Text';
import { Button, Loading, Screen } from '../components/ui';
import { colors, formatToman, toPersianDigits } from '../theme';

/** Landing page after the gateway (deep link limoplus://payment-result?order=…). Asks the server, never trusts the link. */
export default function PaymentResult() {
  const { order } = useLocalSearchParams<{ order?: string }>();
  const [status, setStatus] = useState<OrderStatus | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    const id = Number(order);
    if (!id) {
      setFailed(true);
      return;
    }
    endpoints.order(id, true).then(setStatus).catch(() => setFailed(true));
  }, [order]);

  if (!status && !failed) return <Screen><Loading /></Screen>;
  const paid = status?.status === 'paid';
  return (
    <Screen>
      <View style={styles.page}>
        <Text style={[styles.icon, { color: paid ? colors.green : colors.red }]}>{paid ? '✓' : '✕'}</Text>
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
  title: { fontSize: 22, fontWeight: '900', color: colors.ink },
  text: { fontSize: 15, color: colors.muted, textAlign: 'center', lineHeight: 26 },
});
