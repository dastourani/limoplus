import { router, useLocalSearchParams } from 'expo-router';
import { useMemo, useState } from 'react';
import { FlatList, Pressable, StyleSheet, View } from 'react-native';

import { endpoints } from '../../api/endpoints';
import { Icon } from '../../components/Icon';
import { Text, TextInput } from '../../components/Text';
import { Empty, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { useApi } from '../../lib/useApi';
import { colors, radius, rtl, toPersianDigits } from '../../theme';

/** Every term from the book's review cards, searchable in Persian or English; tap one to open its section. */
export default function Glossary() {
  const { slug, chapter } = useLocalSearchParams<{ slug: string; chapter?: string }>();
  const { data, error, loading, retry } = useApi(() => endpoints.glossary(String(slug), chapter), [slug, chapter]);
  const [q, setQ] = useState('');
  const list = useMemo(() => {
    const terms = data?.terms ?? [];
    const s = q.trim().toLowerCase();
    return s ? terms.filter((t) => t.fa.includes(s) || t.en.toLowerCase().includes(s) || t.meaning.includes(s)) : terms;
  }, [data, q]);

  if (loading && !data) return <Screen><Header title="واژه‌نامه" /><Loading /></Screen>;
  if (error || !data) return <Screen><Header title="واژه‌نامه" /><ErrorState message={error?.message ?? ''} onRetry={retry} /></Screen>;

  return (
    <Screen>
      <Header title={data.chapter ? 'واژه‌های این فصل' : 'واژه‌نامه'} subtitle={data.chapter ? `${data.chapter}، ${data.book}` : data.book} />
      <View style={styles.search}>
        <Icon name="search-check" size={18} color={colors.muted} />
        <TextInput value={q} onChangeText={setQ} placeholder="جست‌وجوی فارسی یا انگلیسی" style={[styles.input, rtl]} autoCorrect={false} />
      </View>
      {data.terms.length === 0 ? (
        <Empty icon="languages" title="هنوز واژه‌ای نیست" text="واژه‌های تخصصی از کارت مرور بخش‌ها اینجا جمع می‌شوند." />
      ) : (
        <FlatList
          data={list}
          keyExtractor={(t) => t.fa}
          contentContainerStyle={styles.list}
          ListHeaderComponent={<Text style={[styles.count, rtl]}>{toPersianDigits(list.length)} واژه</Text>}
          renderItem={({ item }) => (
            <Pressable onPress={() => router.push(`/section/${item.section_id}`)} style={styles.item} accessibilityRole="button">
              <View style={styles.head}>
                <Text style={styles.fa}>{item.fa}</Text>
                {!!item.en && <Text style={styles.en}>{item.en}</Text>}
              </View>
              {!!item.meaning && <Text style={[styles.mean, rtl]}>{item.meaning}</Text>}
              <Text style={[styles.where, rtl]}>{item.section_title}</Text>
            </Pressable>
          )}
        />
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  search: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, marginHorizontal: 16, marginBottom: 8, paddingHorizontal: 12, borderRadius: 14, backgroundColor: colors.surface, borderWidth: 1, borderColor: colors.line },
  input: { flex: 1, paddingVertical: 10, fontSize: 15, color: colors.ink },
  list: { padding: 16, paddingTop: 4, gap: 8 },
  count: { fontSize: 12, color: colors.muted, marginBottom: 4 },
  item: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, padding: 12, gap: 4 },
  head: { flexDirection: 'row-reverse', alignItems: 'baseline', gap: 10, flexWrap: 'wrap' },
  fa: { fontSize: 16, fontWeight: '800', color: colors.ink },
  en: { fontSize: 14, color: '#3B44B8', writingDirection: 'ltr' },
  mean: { fontSize: 14, color: colors.ink, lineHeight: 24 },
  where: { fontSize: 12, color: colors.muted },
});
