/** One «راهنما» page, written in the panel («صفحه‌های راهنما») like a lesson. */
import { useLocalSearchParams } from 'expo-router';
import { ScrollView, StyleSheet } from 'react-native';

import { endpoints } from '../../api/endpoints';
import { MarkdownView } from '../../components/MarkdownView';
import { ErrorState, Header, Loading, Screen } from '../../components/ui';
import { useApi } from '../../lib/useApi';

export default function HelpPageScreen() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const { data, loading, error, retry } = useApi(() => endpoints.helpPage(Number(id)), [id]);
  return (
    <Screen>
      <Header title={data?.title ?? 'راهنما'} />
      {loading && !data ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error.message} onRetry={retry} />
      ) : (
        <ScrollView contentContainerStyle={styles.page}>
          <MarkdownView markdown={data!.body} compact sitePage />
        </ScrollView>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, paddingBottom: 40, width: '100%', maxWidth: 760, alignSelf: 'center' },
});
