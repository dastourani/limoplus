import { router } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { endpoints } from '../api/endpoints';
import { Text } from '../components/Text';
import { Empty, ErrorState, Header, Loading, Screen } from '../components/ui';
import { jalaliDateTime } from '../lib/jalali';
import { useApi } from '../lib/useApi';
import { colors, rtl, toPersianDigits } from '../theme';

export default function Exams() {
  const { data, error, loading, retry } = useApi(() => endpoints.myExams());
  return (
    <Screen>
      <Header title="سابقه‌ی آزمون‌ها" />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error.message} onRetry={retry} />
      ) : data!.length === 0 ? (
        <Empty icon="📝" title="هنوز آزمونی نداده‌ای" text="در صفحه‌ی کتاب، کنار هر فصل دکمه‌ی «آزمون» هست." />
      ) : (
        <ScrollView contentContainerStyle={styles.page}>
          {data!.map((e) => (
            <Pressable key={e.id} onPress={() => router.push(`/exam-result/${e.id}`)} style={styles.row}>
              <View style={{ flex: 1, gap: 4 }}>
                <Text style={[styles.title, rtl]}>{e.node_title}</Text>
                <Text style={[styles.muted, rtl]}>
                  {jalaliDateTime(e.started_at)} · {toPersianDigits(e.question_count)} سؤال
                </Text>
              </View>
              <Text style={styles.score}>{e.submitted_at ? `${toPersianDigits(e.score_percent ?? 0)}٪` : 'ناتمام'}</Text>
            </Pressable>
          ))}
        </ScrollView>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 10 },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 14 },
  title: { fontSize: 15, fontWeight: '800', color: colors.ink },
  muted: { fontSize: 12, color: colors.muted },
  score: { fontSize: 18, fontWeight: '900', color: colors.greenDark },
});
