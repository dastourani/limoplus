import { router, useLocalSearchParams } from 'expo-router';
import { useState } from 'react';
import { Pressable, StyleSheet, Text, View } from 'react-native';

import { endpoints } from '../../api/endpoints';
import { MarkdownView } from '../../components/MarkdownView';
import { Button, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { useApi } from '../../lib/useApi';
import { colors, rtl, toPersianDigits } from '../../theme';

export default function Flashcards() {
  const { nodeId } = useLocalSearchParams<{ nodeId: string }>();
  const { data, error, loading, retry } = useApi(() => endpoints.flashcards(Number(nodeId)), [nodeId]);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [again, setAgain] = useState<number[]>([]);

  if (loading) return <Screen><Header title="فلش‌کارت" /><Loading /></Screen>;
  if (error) return <Screen><Header title="فلش‌کارت" /><ErrorState message={error.message} onRetry={retry} /></Screen>;

  const cards = data!.flashcards;
  if (cards.length === 0) {
    return (
      <Screen>
        <Header title="فلش‌کارت" />
        <ErrorState message={data!.locked_count ? 'فلش‌کارت‌های این بخش در نسخه‌ی کامل کتاب است.' : 'برای این بخش هنوز فلش‌کارتی نیست.'} />
      </Screen>
    );
  }

  if (index >= cards.length) {
    return (
      <Screen>
        <View style={styles.done}>
          <Text style={styles.doneTitle}>مرور تمام شد</Text>
          <Text style={[styles.doneText, rtl]}>
            {again.length ? `${toPersianDigits(again.length)} کارت را دوباره ببین.` : 'همه را بلد بودی!'}
          </Text>
          {again.length > 0 && (
            <Button label="مرور کارت‌های سخت" onPress={() => { setIndex(0); setFlipped(false); }} style={{ alignSelf: 'stretch' }} />
          )}
          <Button label="بازگشت" variant="outline" onPress={() => router.back()} style={{ alignSelf: 'stretch' }} />
        </View>
      </Screen>
    );
  }

  const card = cards[index];
  const advance = (known: boolean) => {
    setAgain((list) => (known ? list.filter((id) => id !== card.id) : list.includes(card.id) ? list : [...list, card.id]));
    setFlipped(false);
    setIndex((i) => i + 1);
  };

  return (
    <Screen>
      <Header title="فلش‌کارت" subtitle={`${toPersianDigits(index + 1)} از ${toPersianDigits(cards.length)}`} />
      <View style={styles.stage}>
        <View style={[styles.shadowCard, { top: 16, left: 28, right: 28 }]} />
        <View style={[styles.shadowCard, { top: 8, left: 18, right: 18, backgroundColor: '#ECEFE7' }]} />
        <Pressable
          onPress={() => setFlipped((f) => !f)}
          accessibilityRole="button"
          accessibilityLabel={flipped ? 'برگرداندن به رو' : 'دیدن نکته'}
          style={[styles.card, flipped && styles.cardBack]}
        >
          <Text style={[styles.chip, flipped ? styles.chipBack : null]}>{flipped ? 'نکته' : 'مفهوم'}</Text>
          {!flipped ? (
            <>
              <Text style={styles.title}>{card.title}</Text>
              <Text style={styles.hint}>بزن تا نکته را ببینی</Text>
            </>
          ) : (
            <View style={{ alignSelf: 'stretch', gap: 14 }}>
              <Text style={[styles.point]}>{card.point}</Text>
              {!!card.formula && (
                <View pointerEvents="none" style={styles.formula}>
                  <MarkdownView markdown={`$$${card.formula}$$`} compact fontSize={16} />
                </View>
              )}
            </View>
          )}
          <Text style={[styles.watermark, flipped && { color: '#3E4C44' }]}>لیمو پلاس</Text>
        </Pressable>
      </View>
      <View style={styles.bar}>
        {flipped ? (
          <>
            <Button label="دوباره نشانم بده" variant="outline" onPress={() => advance(false)} style={{ flex: 1 }} />
            <Button label="بلد بودم" onPress={() => advance(true)} style={{ flex: 1 }} />
          </>
        ) : (
          <Button label="اول کارت را برگردان" disabled onPress={() => undefined} style={{ flex: 1 }} />
        )}
      </View>
    </Screen>
  );
}

const styles = StyleSheet.create({
  stage: { flex: 1, padding: 24, justifyContent: 'center' },
  shadowCard: { position: 'absolute', bottom: 40, borderRadius: 30, backgroundColor: colors.line },
  card: { minHeight: 380, borderRadius: 30, backgroundColor: colors.surface, padding: 26, alignItems: 'center', justifyContent: 'center', gap: 16, shadowColor: '#17201A', shadowOpacity: 0.16, shadowRadius: 30, shadowOffset: { width: 0, height: 14 }, elevation: 6 },
  cardBack: { backgroundColor: colors.ink },
  chip: { position: 'absolute', top: 18, right: 18, fontSize: 11, fontWeight: '800', backgroundColor: '#EEF0FC', color: '#3B44B8', paddingHorizontal: 12, paddingVertical: 4, borderRadius: 999, overflow: 'hidden' },
  chipBack: { backgroundColor: colors.lemon, color: colors.ink },
  title: { fontSize: 30, fontWeight: '900', color: colors.ink, textAlign: 'center', lineHeight: 44 },
  hint: { fontSize: 13, color: colors.muted },
  point: { fontSize: 19, fontWeight: '800', color: colors.ground, textAlign: 'center', lineHeight: 34, writingDirection: 'rtl' },
  formula: { backgroundColor: colors.surface, borderRadius: 14, padding: 4 },
  watermark: { position: 'absolute', bottom: 14, fontSize: 10, color: '#C9D0C6' },
  bar: { flexDirection: 'row-reverse', gap: 10, padding: 16 },
  done: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  doneTitle: { fontSize: 26, fontWeight: '900', color: colors.ink },
  doneText: { fontSize: 16, color: colors.muted, marginBottom: 10 },
});
