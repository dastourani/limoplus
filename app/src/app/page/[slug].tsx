/** «قوانین»، «حریم خصوصی» and other site pages ticked «نمایش در اپ», with the date of the last change. */
import { useLocalSearchParams } from 'expo-router';
import { useEffect } from 'react';
import { ScrollView, StyleSheet } from 'react-native';

import { endpoints } from '../../api/endpoints';
import { MarkdownView } from '../../components/MarkdownView';
import { Text } from '../../components/Text';
import { ErrorState, Header, Loading, Screen } from '../../components/ui';
import { jalaliDate } from '../../lib/jalali';
import { markPageSeen } from '../../lib/pages';
import { useApi } from '../../lib/useApi';
import { colors, rtl } from '../../theme';

export default function SitePageScreen() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { data, loading, error, retry } = useApi(() => endpoints.sitePage(slug), [slug]);
  useEffect(() => {
    if (data) markPageSeen(data.slug);
  }, [data]);
  return (
    <Screen>
      <Header title={data?.title ?? ''} />
      {loading && !data ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error.message} onRetry={retry} />
      ) : (
        <ScrollView contentContainerStyle={styles.page}>
          <Text style={[styles.date, rtl]}>
            آخرین به‌روزرسانی: {jalaliDate(data!.updated_at)}
            {data!.important_at ? `؛ آخرین تغییر مهم: ${jalaliDate(data!.important_at)}` : ''}
          </Text>
          <MarkdownView markdown={data!.body} compact sitePage />
        </ScrollView>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, paddingBottom: 40, width: '100%', maxWidth: 760, alignSelf: 'center', gap: 10 },
  date: { fontSize: 12, color: colors.muted },
});
