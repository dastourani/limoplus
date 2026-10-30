import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { endpoints } from '../../api/endpoints';
import { MarkdownView } from '../../components/MarkdownView';
import { Button, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { storage } from '../../lib/storage';
import { useApi } from '../../lib/useApi';
import { colors, formatToman, rtl } from '../../theme';

export default function Section() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const nodeId = Number(id);
  const { data, error, loading, retry } = useApi(() => endpoints.node(nodeId), [nodeId]);
  const [mode, setMode] = useState<'full' | 'summary'>('full');
  const [fontSize, setFontSize] = useState(17);

  useEffect(() => {
    if (!data) return;
    const book = data.breadcrumb[0];
    storage.setLastSection({ id: data.id, title: data.title, bookTitle: book?.title ?? '', bookSlug: book?.slug ?? '' });
    if (!data.summary) setMode('full');
  }, [data]);

  if (loading) return <Screen><Header /><Loading /></Screen>;

  if (error?.code === 'locked') {
    const book = error.data.book as { title: string; price: number | null; slug: string } | undefined;
    return (
      <Screen>
        <Header title={book?.title} />
        <View style={styles.locked}>
          <Text style={styles.lockIcon}>🔒</Text>
          <Text style={[styles.lockTitle]}>این بخش در نسخه‌ی کامل کتاب است</Text>
          {book?.price ? <Text style={styles.lockPrice}>{formatToman(book.price)}</Text> : null}
          <Button label="خرید به‌زودی فعال می‌شود" disabled onPress={() => undefined} style={{ alignSelf: 'stretch' }} />
          <Button label="بازگشت به کتاب" variant="outline" onPress={() => router.back()} style={{ alignSelf: 'stretch' }} />
        </View>
      </Screen>
    );
  }
  if (error) return <Screen><Header /><ErrorState message={error.message} onRetry={retry} /></Screen>;

  const node = data!;
  const chapter = node.breadcrumb[node.breadcrumb.length - 1];
  const body = mode === 'summary' && node.summary ? node.summary : node.full;

  return (
    <Screen background={colors.paper}>
      <Header
        title={node.title}
        subtitle={chapter?.title}
        right={
          <Pressable onPress={() => setFontSize((s) => (s >= 21 ? 15 : s + 2))} accessibilityLabel="اندازه‌ی متن" style={styles.font}>
            <Text style={styles.fontText}>آ</Text>
          </Pressable>
        }
      />
      {!!node.summary && (
        <View style={styles.toggle}>
          {(['full', 'summary'] as const).map((m) => (
            <Pressable key={m} onPress={() => setMode(m)} style={[styles.toggleItem, mode === m && styles.toggleOn]} accessibilityRole="tab" accessibilityState={{ selected: mode === m }}>
              <Text style={[styles.toggleText, mode === m && styles.toggleTextOn]}>{m === 'full' ? 'جزوه' : 'خلاصه'}</Text>
            </Pressable>
          ))}
        </View>
      )}
      <MarkdownView markdown={body} fontSize={fontSize} />
      <View style={styles.bar}>
        <Button label="تست‌ها" variant="outline" onPress={() => router.push(`/quiz/${node.id}`)} style={{ flex: 1 }} />
        <Button label="فلش‌کارت" variant="outline" onPress={() => router.push(`/flashcards/${node.id}`)} style={{ flex: 1 }} />
        {node.next_id ? (
          <Button label="بخش بعد" variant="dark" onPress={() => router.replace(`/section/${node.next_id}`)} style={{ flex: 1.2 }} />
        ) : null}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  font: { width: 44, height: 44, alignItems: 'center', justifyContent: 'center' },
  fontText: { fontSize: 18, fontWeight: '800', color: colors.ink },
  toggle: { flexDirection: 'row-reverse', alignSelf: 'center', backgroundColor: colors.disabled, borderRadius: 999, padding: 3, marginBottom: 6 },
  toggleItem: { paddingHorizontal: 22, paddingVertical: 7, borderRadius: 999 },
  toggleOn: { backgroundColor: colors.ink },
  toggleText: { fontWeight: '700', color: colors.muted },
  toggleTextOn: { color: colors.lemon },
  bar: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1, borderTopColor: '#ECEFE6', backgroundColor: colors.paper },
  locked: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  lockIcon: { fontSize: 44 },
  lockTitle: { fontSize: 18, fontWeight: '800', color: colors.ink, textAlign: 'center', writingDirection: 'rtl' },
  lockPrice: { fontSize: 16, color: colors.muted, marginBottom: 8 },
});
