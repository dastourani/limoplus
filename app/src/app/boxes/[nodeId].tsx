import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { endpoints } from '../../api/endpoints';
import { MarkdownView, type ReaderEvent } from '../../components/MarkdownView';
import { Text } from '../../components/Text';
import { Empty, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { setLabels } from '../../lib/labels';
import { setNumbering } from '../../lib/numbering';
import { useApi } from '../../lib/useApi';
import { colors, toPersianDigits } from '../../theme';

/**
 * «کادرهای کتاب»: all boxes of one label (every definition, every trap…) of a book or chapter, in reading order,
 * each with its number and section, and a link to the same box in the notes.
 */
export default function Boxes() {
  const { nodeId, label: first } = useLocalSearchParams<{ nodeId: string; label?: string }>();
  const [label, setLabel] = useState(first ?? '');
  const { data, error, loading, retry } = useApi(() => endpoints.boxes(Number(nodeId), label || undefined), [nodeId, label]);

  // The titles are for this page only (a quiz or flashcard opened next must number its own boxes).
  useEffect(() => () => setNumbering(null), []);

  // No label asked for: the first one (the panel's order: definitions first).
  useEffect(() => {
    if (!label && data?.labels.length) setLabel(data.labels[0].name);
  }, [data, label]);

  const markdown = useMemo(() => {
    if (!data || !label) return '';
    const parts: string[] = [];
    let section = -1;
    for (const b of data.boxes) {
      if (b.section_id !== section) {
        section = b.section_id;
        parts.push(`### ${b.section_title}`);
      }
      // No {#name} here: a link to the name opens the box in its own section.
      parts.push(`:::${b.label}\n${b.body.trim()}\n:::`);
      if (b.name) parts.push(`[[#${b.name}|در درسنامه ←|${b.section_id}]]`);
    }
    return parts.join('\n\n');
  }, [data, label]);

  if (data) {
    setLabels(data.all_labels);
    setNumbering({ refs: data.refs, titles: data.boxes.map((b) => b.title) });
  }

  const onEvent = (e: ReaderEvent) => {
    if (e.type === 'ref' && e.node) router.push({ pathname: '/section/[id]', params: { id: String(e.node), find: '#' + e.name } });
  };

  if (loading && !data) return <Screen><Header title="کادرهای کتاب" /><Loading /></Screen>;
  if (error || !data) return <Screen><Header title="کادرهای کتاب" /><ErrorState message={error?.message ?? ''} status={error?.status} onRetry={retry} /></Screen>;

  return (
    <Screen>
      <Header title="کادرهای کتاب" subtitle={data.title} />
      {data.labels.length === 0 ? (
        <Empty icon="clipboard-list" title="هنوز کادری نیست" text="تعریف‌ها، قضیه‌ها، مثال‌ها و نکته‌های درسنامه اینجا دسته‌بندی می‌شوند." />
      ) : (
        <>
          <View style={styles.chips}>
              {data.labels.map((l) => {
                const on = l.name === label;
                return (
                  <Pressable
                    key={l.name}
                    onPress={() => setLabel(l.name)}
                    style={[styles.chip, on && styles.chipOn]}
                    accessibilityRole="button"
                    accessibilityState={{ selected: on }}
                  >
                    <Text style={[styles.chipText, on && styles.chipTextOn]}>
                      {l.name} ({toPersianDigits(l.count)})
                    </Text>
                  </Pressable>
                );
              })}
          </View>
          {!!data.locked_count && (
            <Text style={styles.locked}>{toPersianDigits(data.locked_count)} کادر دیگر در بخش‌هایی است که هنوز باز نشده‌اند.</Text>
          )}
          {loading ? <Loading /> : markdown ? <MarkdownView key={label} markdown={markdown} onEvent={onEvent} /> : null}
        </>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  chips: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 8, paddingHorizontal: 16, paddingVertical: 8 },
  chip: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface },
  chipOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  chipText: { fontSize: 14, color: colors.ink },
  chipTextOn: { color: '#fff', fontWeight: '700' },
  locked: { fontSize: 12, color: colors.muted, textAlign: 'right', paddingHorizontal: 16, paddingBottom: 4 },
});
