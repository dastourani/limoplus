/** «تغییرات کتاب»: the important updates of a book (the panel's «مطلب تازه»), newest first, with their dates. */
import { router, useLocalSearchParams } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { endpoints } from '../../api/endpoints';
import { Icon } from '../../components/Icon';
import { Text } from '../../components/Text';
import { Empty, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { jalaliDate } from '../../lib/jalali';
import { useApi } from '../../lib/useApi';
import { colors, rtl } from '../../theme';

export default function BookChangesScreen() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { data, error, loading, retry } = useApi(() => endpoints.bookChanges(slug), [slug]);
  return (
    <Screen>
      <Header title="تغییرات کتاب" subtitle={data?.title} />
      {loading && !data ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error.message} onRetry={retry} />
      ) : !data?.changes.length ? (
        <Empty icon="sparkles" title="هنوز تغییری ثبت نشده" text="هر وقت نکته‌ی تازه‌ای به کتاب اضافه شود، این‌جا با تاریخش می‌آید." />
      ) : (
        <ScrollView contentContainerStyle={styles.page}>
          {data.changes.map((c) => {
            const body = (
              <>
                <Text style={[styles.date, rtl]}>{jalaliDate(c.at)}{c.place ? `، ${c.place}` : ''}</Text>
                <Text style={[styles.text, rtl]}>{c.text}</Text>
              </>
            );
            return c.node_id ? (
              <Pressable key={c.id} onPress={() => router.push(`/section/${c.node_id}`)} style={styles.row} accessibilityRole="button">
                <View style={{ flex: 1, gap: 2 }}>{body}</View>
                <Icon name="chevron-left" size={18} color={colors.muted} />
              </Pressable>
            ) : (
              <View key={c.id} style={styles.row}>
                <View style={{ flex: 1, gap: 2 }}>{body}</View>
              </View>
            );
          })}
        </ScrollView>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 10 },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.line, padding: 14 },
  date: { fontSize: 12, color: colors.muted },
  text: { fontSize: 15, lineHeight: 26, color: colors.ink },
});
