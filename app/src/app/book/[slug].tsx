import { router, useLocalSearchParams } from 'expo-router';
import { Pressable, ScrollView, StyleSheet, Text, View } from 'react-native';

import { endpoints, type NodeSummary } from '../../api/endpoints';
import { Chip, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { useApi } from '../../lib/useApi';
import { colors, formatToman, radius, rtl, toPersianDigits } from '../../theme';

export default function Book() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { data, error, loading, retry } = useApi(() => endpoints.book(String(slug)), [slug]);

  return (
    <Screen>
      <Header title={data?.title ?? ''} subtitle="کتاب" />
      {loading ? (
        <Loading />
      ) : error ? (
        <ErrorState message={error.message} onRetry={retry} />
      ) : (
        <ScrollView contentContainerStyle={styles.page}>
          {data!.price ? <Text style={[styles.price, rtl]}>نسخه‌ی کامل: {formatToman(data!.price)} · خرید به‌زودی</Text> : null}
          {data!.chapters.map((chapter, index) => (
            <View key={chapter.id} style={styles.chapter}>
              <View style={styles.chapterHead}>
                <Text style={[styles.chapterTitle, rtl]}>
                  فصل {toPersianDigits(index + 1)} · {chapter.title}
                </Text>
                {chapter.is_locked ? <Chip label="🔒 نسخه‌ی کامل" /> : <Chip label="رایگان" color={colors.greenDark} background={colors.greenSoft} />}
              </View>
              {chapter.sections.map((section) => (
                <SectionRow key={section.id} section={section} />
              ))}
              {!chapter.is_locked && (
                <View style={styles.actions}>
                  <Pressable style={styles.action} onPress={() => router.push(`/quiz/${chapter.id}`)}>
                    <Text style={styles.actionText}>تست‌های فصل</Text>
                  </Pressable>
                  <Pressable style={styles.action} onPress={() => router.push(`/flashcards/${chapter.id}`)}>
                    <Text style={styles.actionText}>فلش‌کارت‌های فصل</Text>
                  </Pressable>
                </View>
              )}
            </View>
          ))}
        </ScrollView>
      )}
    </Screen>
  );
}

function SectionRow({ section }: { section: NodeSummary }) {
  return (
    <Pressable
      onPress={() => router.push(`/section/${section.id}`)}
      style={({ pressed }) => [styles.section, pressed && { backgroundColor: colors.ground }]}
      accessibilityRole="button"
    >
      <Text style={[styles.sectionTitle, rtl, section.is_locked && { color: colors.muted }]}>{section.title}</Text>
      <Text style={styles.sectionMeta}>
        {section.is_locked ? '🔒' : `${toPersianDigits(section.question_count ?? 0)} تست · ${toPersianDigits(section.flashcard_count ?? 0)} کارت`}
      </Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 14 },
  price: { fontSize: 13, color: colors.muted },
  chapter: { backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.line, overflow: 'hidden' },
  chapterHead: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', padding: 16, gap: 8 },
  chapterTitle: { flex: 1, fontSize: 17, fontWeight: '900', color: colors.ink },
  section: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingVertical: 14, borderTopWidth: 1, borderTopColor: colors.line, gap: 8 },
  sectionTitle: { flex: 1, fontSize: 15, fontWeight: '700', color: colors.ink },
  sectionMeta: { fontSize: 12, color: colors.muted },
  actions: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: colors.line },
  action: { flex: 1, backgroundColor: colors.ground, borderRadius: 14, paddingVertical: 12, alignItems: 'center' },
  actionText: { fontWeight: '800', color: colors.ink, fontSize: 14 },
});
