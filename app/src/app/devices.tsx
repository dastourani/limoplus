import { ScrollView, StyleSheet } from 'react-native';

import { endpoints } from '../api/endpoints';
import { Text } from '../components/Text';
import { useFeedback } from '../components/Feedback';
import { Button, Card, ErrorState, Header, Loading, Screen, usePullRefresh } from '../components/ui';
import { jalaliDate, relativeDay } from '../lib/jalali';
import { useApi } from '../lib/useApi';
import { colors, rtl } from '../theme';

/** Signed-in devices (at most two). The user can sign out any other device from here. */
export default function Devices() {
  const { data, error, loading, retry } = useApi(() => endpoints.sessions());
  const refresh = usePullRefresh(loading, retry);
  const { confirm } = useFeedback();
  return (
    <Screen>
      <Header title="دستگاه‌های من" />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error.message} onRetry={retry} />
      ) : (
        <ScrollView contentContainerStyle={styles.page} refreshControl={refresh}>
          <Text style={[styles.help, rtl]}>هر حساب حداکثر روی دو دستگاه هم‌زمان باز است؛ مثلاً گوشی و لپ‌تاپ.</Text>
          {data!.map((s) => (
            <Card key={s.id}>
              <Text style={[styles.name, rtl]}>
                {s.device_name}
                {s.is_current ? '  (همین دستگاه)' : ''}
              </Text>
              <Text style={[styles.help, rtl]}>ورود: {jalaliDate(s.created_at)}، آخرین استفاده: {relativeDay(s.last_seen_at)}</Text>
              {!s.is_current && <Button label="خروج این دستگاه" variant="outline" onPress={async () => {
                    const ok = await confirm({ title: `«${s.device_name}» خارج شود؟`, message: 'روی آن دستگاه باید دوباره با کد پیامکی وارد شد.', confirmLabel: 'خروج دستگاه', destructive: true, icon: 'monitor-smartphone' });
                    if (ok) endpoints.revokeSession(s.id).then(retry);
                  }} />}
            </Card>
          ))}
        </ScrollView>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 12 },
  help: { fontSize: 13, color: colors.muted, lineHeight: 22 },
  name: { fontSize: 15, fontWeight: '800', color: colors.ink },
});
