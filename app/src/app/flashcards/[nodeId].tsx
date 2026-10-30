import * as Sharing from 'expo-sharing';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Platform, Pressable, StyleSheet, View, type HostInstance } from 'react-native';
import { captureRef } from 'react-native-view-shot';

import { endpoints, type Flashcard } from '../../api/endpoints';
import { LemonSlice } from '../../components/LemonSlice';
import { MarkdownView } from '../../components/MarkdownView';
import { ReportSheet } from '../../components/ReportSheet';
import { Text } from '../../components/Text';
import { Icon } from '../../components/Icon';
import { Button, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { requireLogin, useAuth } from '../../lib/auth';
import { sendOrQueue } from '../../lib/network';
import { useApi } from '../../lib/useApi';
import { colors, rtl, toPersianDigits } from '../../theme';

const BOX_LABEL = ['', 'جعبه‌ی ۱', 'جعبه‌ی ۲', 'جعبه‌ی ۳', 'جعبه‌ی ۴', 'مسلط'];

/**
 * Flashcards are key points (not questions). Signed-in learners get a Leitner box per card on the server: known cards
 * move up and come back later, missed cards return to box 1. Due cards come first.
 */
export default function Flashcards() {
  const { nodeId } = useLocalSearchParams<{ nodeId: string }>();
  const { user } = useAuth();
  const { data, error, loading, retry } = useApi(() => endpoints.flashcards(Number(nodeId)), [nodeId]);
  const [boxes, setBoxes] = useState<Record<string, { box: number; due: boolean }>>({});
  const [reported, setReported] = useState<number[]>([]);
  const [order, setOrder] = useState<Flashcard[] | null>(null);
  const [index, setIndex] = useState(0);
  const [flipped, setFlipped] = useState(false);
  const [again, setAgain] = useState<number[]>([]);
  const [reportOpen, setReportOpen] = useState(false);
  const cardRef = useRef<HostInstance>(null);

  useEffect(() => {
    if (!data) return;
    if (!user) {
      setOrder(data.flashcards);
      return;
    }
    endpoints
      .flashcardState(Number(nodeId))
      .then((s) => {
        setBoxes(s.cards);
        setReported(s.reported);
        // Due and new cards first, then by box (weakest first).
        const rank = (f: Flashcard) => {
          const st = s.cards[f.id];
          return st ? (st.due ? 0 : 10) + st.box : 0;
        };
        setOrder([...data.flashcards].sort((a, b) => rank(a) - rank(b)));
      })
      .catch(() => setOrder(data.flashcards));
  }, [data, user, nodeId]);

  const dueCount = useMemo(() => (order ?? []).filter((f) => !boxes[f.id] || boxes[f.id].due).length, [order, boxes]);

  if (loading || (data && !order)) return <Screen><Header title="فلش‌کارت" /><Loading /></Screen>;
  if (error) return <Screen><Header title="فلش‌کارت" /><ErrorState message={error.message} onRetry={retry} /></Screen>;

  const cards = order!;
  if (cards.length === 0) {
    return (
      <Screen>
        <Header title="فلش‌کارت" />
        <ErrorState message={data!.locked_count ? 'فلش‌کارت‌های این بخش در نسخه‌ی کامل کتاب است.' : 'برای این بخش هنوز فلش‌کارتی نیست.'} />
      </Screen>
    );
  }

  if (index >= cards.length) {
    const mastered = Object.values(boxes).filter((b) => b.box >= 4).length;
    return (
      <Screen>
        <View style={styles.done}>
          <LemonSlice size={90} />
          <Text style={styles.doneTitle}>مرور تمام شد</Text>
          <Text style={[styles.doneText, rtl]}>
            {again.length ? `${toPersianDigits(again.length)} کارت را دوباره ببین.` : 'همه را بلد بودی!'}
            {user ? `\n${toPersianDigits(mastered)} کارت در جعبه‌های آخر است.` : ''}
          </Text>
          {again.length > 0 && (
            <Button
              label="مرور کارت‌های سخت"
              onPress={() => {
                setOrder(cards.filter((c) => again.includes(c.id)));
                setAgain([]);
                setIndex(0);
                setFlipped(false);
              }}
              style={{ alignSelf: 'stretch' }}
            />
          )}
          <Button label="بازگشت" variant="outline" onPress={() => router.back()} style={{ alignSelf: 'stretch' }} />
        </View>
      </Screen>
    );
  }

  const card = cards[index];
  const state = boxes[card.id];

  const advance = (known: boolean) => {
    setAgain((list) => (known ? list.filter((id) => id !== card.id) : list.includes(card.id) ? list : [...list, card.id]));
    if (user) {
      // Sent later if offline, so no review is lost; the box shown here is the expected one.
      const box = known ? Math.min(5, (boxes[card.id]?.box ?? 1) + 1) : 1;
      setBoxes((b) => ({ ...b, [card.id]: { box, due: false } }));
      sendOrQueue(`flashcards/${card.id}/review/`, { known });
    }
    setFlipped(false);
    setIndex((i) => i + 1);
  };

  const share = async () => {
    try {
      if (Platform.OS === 'web' || !(await Sharing.isAvailableAsync())) return;
      const uri = await captureRef(cardRef, { format: 'png', quality: 1 });
      await Sharing.shareAsync(uri, { mimeType: 'image/png', dialogTitle: card.title });
    } catch {
      // sharing cancelled
    }
  };

  return (
    <Screen>
      <Header
        title="فلش‌کارت"
        subtitle={`${toPersianDigits(index + 1)} از ${toPersianDigits(cards.length)}${user ? ` · ${toPersianDigits(dueCount)} برای مرور` : ''}`}
        right={
          Platform.OS !== 'web' ? (
            <Pressable onPress={share} style={{ padding: 10 }} accessibilityLabel="اشتراک‌گذاری کارت">
              <Icon name="share-2" size={22} />
            </Pressable>
          ) : undefined
        }
      />
      <View style={styles.stage}>
        <View style={[styles.shadowCard, { top: 16, left: 28, right: 28 }]} />
        <View style={[styles.shadowCard, { top: 8, left: 18, right: 18, backgroundColor: '#ECEFE7' }]} />
        <Pressable onPress={() => setFlipped((f) => !f)} accessibilityRole="button" accessibilityLabel={flipped ? 'برگرداندن به رو' : 'دیدن نکته'}>
          <View ref={cardRef} collapsable={false} style={[styles.card, flipped && styles.cardBack]}>
            <Text style={[styles.chip, flipped ? styles.chipBack : null]}>{flipped ? 'نکته' : 'مفهوم'}</Text>
            {!!state && <Text style={[styles.box, flipped && { color: '#B9C4BC' }]}>{BOX_LABEL[state.box]}</Text>}
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
          </View>
        </Pressable>
        <Pressable
          onPress={() => requireLogin(user, 'برای گزارش اشکال وارد شوید.') && !reported.includes(card.id) && setReportOpen(true)}
          style={{ alignSelf: 'center', marginTop: 14 }}
        >
          <Text style={styles.report}>{reported.includes(card.id) ? 'گزارش داده شد' : 'گزارش اشکال در این کارت'}</Text>
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
      <ReportSheet
        visible={reportOpen}
        onClose={() => setReportOpen(false)}
        onSend={(reason, note) => endpoints.reportFlashcard(card.id, reason, note)}
        onDone={() => setReported((r) => [...r, card.id])}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  stage: { flex: 1, padding: 24, justifyContent: 'center' },
  shadowCard: { position: 'absolute', bottom: 70, borderRadius: 30, backgroundColor: colors.line },
  card: { minHeight: 380, borderRadius: 30, backgroundColor: colors.surface, padding: 26, alignItems: 'center', justifyContent: 'center', gap: 16, shadowColor: '#17201A', shadowOpacity: 0.16, shadowRadius: 30, shadowOffset: { width: 0, height: 14 }, elevation: 6 },
  cardBack: { backgroundColor: colors.ink },
  chip: { position: 'absolute', top: 18, right: 18, fontSize: 12, fontWeight: '700', backgroundColor: '#EEF0FC', color: '#3B44B8', paddingHorizontal: 12, paddingVertical: 4, borderRadius: 999, overflow: 'hidden' },
  chipBack: { backgroundColor: colors.lemon, color: colors.ink },
  box: { position: 'absolute', top: 20, left: 20, fontSize: 12, color: colors.muted },
  title: { fontSize: 30, fontWeight: '900', color: colors.ink, textAlign: 'center', lineHeight: 44 },
  hint: { fontSize: 13, color: colors.muted },
  point: { fontSize: 19, fontWeight: '800', color: colors.ground, textAlign: 'center', lineHeight: 34, writingDirection: 'rtl' },
  formula: { backgroundColor: colors.surface, borderRadius: 14, padding: 4 },
  watermark: { position: 'absolute', bottom: 14, fontSize: 10, color: '#C9D0C6' },
  report: { fontSize: 12, color: colors.muted, textDecorationLine: 'underline' },
  bar: { flexDirection: 'row-reverse', gap: 10, padding: 16 },
  done: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  doneTitle: { fontSize: 26, fontWeight: '900', color: colors.ink },
  doneText: { fontSize: 16, color: colors.muted, marginBottom: 10, textAlign: 'center', lineHeight: 28 },
});
