/**
 * A deck of flashcards: tap to flip (3D), then grade with four buttons — again / hard / good / easy — each showing
 * when the card comes back. Swipe right = good, swipe left = again. «Again» cards return later in the same session.
 * Signed-in learners' grades go to the server (queued when offline); guests just practise.
 */
import * as Sharing from 'expo-sharing';
import { router } from 'expo-router';
import { useMemo, useRef, useState } from 'react';
import { Animated, Easing, PanResponder, Platform, Pressable, StyleSheet, View, type HostInstance } from 'react-native';
import { captureRef } from 'react-native-view-shot';

import { endpoints, type Flashcard, type Grade, type GradeHints } from '../api/endpoints';
import { requireLogin, useAuth } from '../lib/auth';
import { sendOrQueue } from '../lib/network';
import { colors, rtl, toPersianDigits } from '../theme';
import { useCelebrate } from './Celebrate';
import { Icon } from './Icon';
import { LemonProgress, type PartState } from './LemonProgress';
import { MarkdownView } from './MarkdownView';
import { ReportSheet } from './ReportSheet';
import { ReportButton } from './Tags';
import { Text } from './Text';
import { Button, Header, Screen } from './ui';
import { Watermark } from './Watermark';

const DEFAULT_HINTS: GradeHints = { again: 0, hard: 1, good: 1, easy: 3 };
const GRADES: { grade: Grade; label: string; color: string; soft: string }[] = [
  { grade: 'again', label: 'دوباره', color: '#B3261E', soft: '#FBE7E6' },
  { grade: 'hard', label: 'سخت', color: '#B26A00', soft: '#FFF0D6' },
  { grade: 'good', label: 'خوب', color: '#1F5E3A', soft: '#E3F3E9' },
  { grade: 'easy', label: 'آسان', color: '#3B44B8', soft: '#EEF0FC' },
];

function nextBox(box: number, grade: Grade) {
  if (grade === 'again') return 1;
  if (grade === 'hard') return box;
  return Math.min(6, box + (grade === 'easy' ? 2 : 1));
}

function whenLabel(days: number) {
  if (days <= 0) return 'همین الان';
  if (days === 1) return 'فردا';
  if (days >= 30) return `${toPersianDigits(Math.round(days / 30))} ماه`;
  return `${toPersianDigits(days)} روز`;
}

export type DeckState = Record<string, { box: number; hints: GradeHints }>;

export function FlashcardDeck({
  title,
  cards,
  state,
  newHints = DEFAULT_HINTS,
  masteredBox = 4,
  reported: initialReported = [],
  puzzle = true,
}: {
  title: string;
  cards: Flashcard[];
  state: DeckState;
  newHints?: GradeHints;
  masteredBox?: number;
  reported?: number[];
  puzzle?: boolean;
}) {
  const { user } = useAuth();
  const celebrate = useCelebrate();
  const [queue, setQueue] = useState<number[]>(() => cards.map((c) => c.id));
  const [pos, setPos] = useState(0);
  const [boxes, setBoxes] = useState<DeckState>(state);
  const [flipped, setFlipped] = useState(false);
  const [againIds, setAgainIds] = useState<Set<number>>(new Set());
  const [reported, setReported] = useState<number[]>(initialReported);
  const [reportOpen, setReportOpen] = useState(false);
  // Last grade given to each card in this session: fills its wedge of the lemon.
  const [graded, setGraded] = useState<Record<number, Grade>>({});
  const flip = useRef(new Animated.Value(0)).current;
  const drag = useRef(new Animated.ValueXY()).current;
  const cardRef = useRef<HostInstance>(null);
  const byId = useMemo(() => new Map(cards.map((c) => [c.id, c])), [cards]);
  const masteredIdx = useMemo(
    () => new Set(cards.map((c, i) => ((boxes[c.id]?.box ?? 0) >= masteredBox ? i : -1)).filter((i) => i >= 0)),
    [cards, boxes, masteredBox],
  );

  const done = pos >= queue.length;
  const parts: PartState[] = cards.map((c) => {
    const g = graded[c.id];
    return !g ? 'empty' : g === 'again' ? 'wrong' : g === 'hard' ? 'soft' : 'done';
  });
  const gradedCount = Object.keys(graded).length;
  const card = done ? null : byId.get(queue[pos])!;
  const hints = card ? (boxes[card.id]?.hints ?? newHints) : newHints;

  const turn = (to: 0 | 1) => {
    setFlipped(to === 1);
    Animated.timing(flip, { toValue: to, duration: 380, easing: Easing.out(Easing.cubic), useNativeDriver: true }).start();
  };

  const grade = (g: Grade) => {
    if (!card) return;
    const box = boxes[card.id]?.box ?? 1;
    const nb = nextBox(box, g);
    setBoxes((b) => ({ ...b, [card.id]: { box: nb, hints: b[card.id]?.hints ?? newHints } }));
    setGraded((m) => ({ ...m, [card.id]: g }));
    if (user) sendOrQueue(`flashcards/${card.id}/review/`, { grade: g });
    if (g === 'again') {
      setAgainIds((s) => new Set(s).add(card.id));
      // Comes back three cards later in this session.
      setQueue((q) => {
        const copy = [...q];
        copy.splice(Math.min(copy.length, pos + 4), 0, card.id);
        return copy;
      });
    }
    flip.setValue(0);
    setFlipped(false);
    drag.setValue({ x: 0, y: 0 });
    const next = pos + 1;
    setPos(next);
    if (g !== 'again' && next >= queue.length) {
      celebrate('deck', {
        title: 'مرور تمام شد!',
        text: againIds.size ? `${toPersianDigits(queue.length - againIds.size)} کارت مرور شد. ${toPersianDigits(againIds.size)} کارت سخت بود و دوباره می‌آید.` : 'همه‌ی کارت‌ها را بلد بودی!',
        primary: 'بازگشت',
      });
    }
  };

  const responder = useMemo(
    () =>
      PanResponder.create({
        onMoveShouldSetPanResponder: (_, g) => flipped && Math.abs(g.dx) > 8 && Math.abs(g.dx) > Math.abs(g.dy),
        onPanResponderMove: Animated.event([null, { dx: drag.x }], { useNativeDriver: false }),
        onPanResponderRelease: (_, g) => {
          if (Math.abs(g.dx) > 80 || (Math.abs(g.vx) > 0.5 && Math.abs(g.dx) > 30)) {
            const right = g.dx > 0;
            Animated.timing(drag, { toValue: { x: right ? 500 : -500, y: 0 }, duration: 180, useNativeDriver: false }).start(() =>
              grade(right ? 'good' : 'again'),
            );
          } else {
            Animated.spring(drag, { toValue: { x: 0, y: 0 }, friction: 6, useNativeDriver: false }).start();
          }
        },
      }),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [flipped, pos, queue, boxes],
  );

  const share = async () => {
    try {
      if (Platform.OS === 'web' || !(await Sharing.isAvailableAsync())) return;
      const uri = await captureRef(cardRef, { format: 'png', quality: 1 });
      await Sharing.shareAsync(uri, { mimeType: 'image/png', dialogTitle: card?.title });
    } catch {
      // cancelled
    }
  };

  if (done) {
    return (
      <Screen>
        <Header title={title} />
        <View style={styles.done}>
          <LemonProgress parts={parts} size={150} />
          {puzzle && user && (
            <Text style={[styles.doneText, rtl]}>
              {toPersianDigits(masteredIdx.size)} از {toPersianDigits(cards.length)} کارت این بخش را دیگر کامل بلدی
            </Text>
          )}
          <Text style={styles.doneTitle}>مرور تمام شد</Text>
          <Text style={[styles.doneText, rtl]}>{againIds.size ? `${toPersianDigits(againIds.size)} کارت سخت بود؛ به‌زودی دوباره می‌بینی‌شان.` : 'همه را بلد بودی!'}</Text>
          {!user && (
            <Button label="ورود برای ذخیره‌ی مرورها" onPress={() => requireLogin(user, 'تا مرورها ذخیره شود و کارت‌ها سر وقتش برگردند، وارد شوید.')} style={{ alignSelf: 'stretch' }} />
          )}
          <Button label="بازگشت" variant="outline" onPress={() => router.back()} style={{ alignSelf: 'stretch' }} />
        </View>
      </Screen>
    );
  }

  const frontRotate = flip.interpolate({ inputRange: [0, 1], outputRange: ['0deg', '180deg'] });
  const backRotate = flip.interpolate({ inputRange: [0, 1], outputRange: ['180deg', '360deg'] });
  const frontOpacity = flip.interpolate({ inputRange: [0, 0.5, 0.51, 1], outputRange: [1, 1, 0, 0] });
  const backOpacity = flip.interpolate({ inputRange: [0, 0.5, 0.51, 1], outputRange: [0, 0, 1, 1] });
  const tilt = drag.x.interpolate({ inputRange: [-300, 0, 300], outputRange: ['-14deg', '0deg', '14deg'] });
  const goodTint = drag.x.interpolate({ inputRange: [0, 120], outputRange: [0, 0.85], extrapolate: 'clamp' });
  const againTint = drag.x.interpolate({ inputRange: [-120, 0], outputRange: [0.85, 0], extrapolate: 'clamp' });
  const box = boxes[card!.id]?.box;

  return (
    <Screen>
      <Header
        title={title}
        subtitle={`${toPersianDigits(Math.min(pos + 1, queue.length))} از ${toPersianDigits(queue.length)}`}
        right={
          Platform.OS !== 'web' ? (
            <Pressable onPress={share} style={{ padding: 10 }} accessibilityLabel="اشتراک‌گذاری کارت">
              <Icon name="share-2" size={22} />
            </Pressable>
          ) : undefined
        }
      />
      <View style={styles.puzzleRow}>
        <LemonProgress parts={parts} current={cards.findIndex((c) => c.id === card!.id)} size={50} />
        <Text style={[styles.puzzleText, rtl]}>
          {toPersianDigits(gradedCount)} از {toPersianDigits(cards.length)} کارت مرور شد
          {puzzle && user && masteredIdx.size ? `، ${toPersianDigits(masteredIdx.size)} کارت کاملاً بلدی` : ''}
        </Text>
      </View>
      <View style={styles.stage}>
        <View style={[styles.stack, { top: 34, left: 34, right: 34 }]} />
        <View style={[styles.stack, { top: 26, left: 26, right: 26, backgroundColor: '#ECEFE7' }]} />
        <Animated.View {...responder.panHandlers} style={{ transform: [{ translateX: drag.x }, { rotate: tilt }] }}>
          <Pressable onPress={() => turn(flipped ? 0 : 1)} accessibilityRole="button" accessibilityLabel={flipped ? 'برگرداندن به رو' : 'دیدن نکته'}>
            <View style={styles.cardBox}>
              <Animated.View style={[styles.card, { opacity: frontOpacity, transform: [{ perspective: 1000 }, { rotateY: frontRotate }] }]}>
                <Text style={styles.chip}>مفهوم</Text>
                {!!box && <Text style={styles.boxLabel}>جعبه‌ی {toPersianDigits(box)}</Text>}
                <Text style={styles.cardTitle}>{card!.title}</Text>
                <Text style={styles.hint}>بزن تا نکته را ببینی</Text>
                <Text style={styles.brand}>لیمو پلاس</Text>
              </Animated.View>
              <Animated.View
                ref={cardRef}
                collapsable={false}
                style={[styles.card, styles.cardBack, styles.face, { opacity: backOpacity, transform: [{ perspective: 1000 }, { rotateY: backRotate }] }]}
              >
                <Text style={[styles.chip, styles.chipBack]}>نکته</Text>
                <View style={{ alignSelf: 'stretch', gap: 14 }}>
                  <Text style={styles.point}>{card!.point}</Text>
                  {!!card!.formula && (
                    <View pointerEvents="none" style={styles.formula}>
                      <MarkdownView markdown={`$$${card!.formula}$$`} compact fontSize={16} />
                    </View>
                  )}
                </View>
                <Text style={[styles.brand, { color: '#56655B' }]}>لیمو پلاس</Text>
              </Animated.View>
              <Animated.View pointerEvents="none" style={[styles.tint, { backgroundColor: '#2F7D4F', opacity: goodTint }]}>
                <Text style={styles.tintText}>خوب</Text>
              </Animated.View>
              <Animated.View pointerEvents="none" style={[styles.tint, { backgroundColor: '#B3261E', opacity: againTint }]}>
                <Text style={styles.tintText}>دوباره</Text>
              </Animated.View>
            </View>
          </Pressable>
        </Animated.View>
        {/* On screen only: the shared image carries just the brand, never the reader's phone number. */}
        <Watermark text={user?.phone || 'لیمو پلاس'} />
        <View style={{ alignSelf: 'center', marginTop: 12 }}>
          <ReportButton
            reported={reported.includes(card!.id)}
            label="گزارش اشکال در این کارت"
            onPress={() => requireLogin(user, 'برای گزارش اشکال وارد شوید.') && setReportOpen(true)}
          />
        </View>
      </View>
      <View style={styles.bar}>
        {flipped ? (
          GRADES.map((g) => (
            <Pressable key={g.grade} onPress={() => grade(g.grade)} style={[styles.grade, { backgroundColor: g.soft }]} accessibilityRole="button">
              <Text style={[styles.gradeLabel, { color: g.color }]}>{g.label}</Text>
              <Text style={[styles.gradeWhen, { color: g.color }]}>{whenLabel(hints[g.grade])}</Text>
            </Pressable>
          ))
        ) : (
          <Button label="برگرداندن کارت" variant="dark" onPress={() => turn(1)} style={{ flex: 1 }} />
        )}
      </View>
      {flipped && <Text style={[styles.swipeHint]}>یا بکش: راست = خوب، چپ = دوباره</Text>}
      <ReportSheet
        visible={reportOpen}
        onClose={() => setReportOpen(false)}
        onSend={(reason, note) => endpoints.reportFlashcard(card!.id, reason, note)}
        onDone={() => setReported((r) => [...r, card!.id])}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  puzzleRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, paddingHorizontal: 20 },
  puzzleText: { flex: 1, fontSize: 13, color: colors.muted },
  stage: { flex: 1, padding: 22, justifyContent: 'center' },
  stack: { position: 'absolute', bottom: 90, borderRadius: 30, backgroundColor: colors.line },
  cardBox: { minHeight: 360 },
  card: { minHeight: 360, borderRadius: 30, backgroundColor: colors.surface, padding: 26, alignItems: 'center', justifyContent: 'center', gap: 16, backfaceVisibility: 'hidden', shadowColor: '#17201A', shadowOpacity: 0.16, shadowRadius: 30, shadowOffset: { width: 0, height: 14 }, elevation: 6 },
  face: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0 },
  cardBack: { backgroundColor: colors.ink },
  chip: { position: 'absolute', top: 18, right: 18, fontSize: 12, fontWeight: '700', backgroundColor: '#EEF0FC', color: '#3B44B8', paddingHorizontal: 12, paddingVertical: 4, borderRadius: 999, overflow: 'hidden' },
  chipBack: { backgroundColor: colors.lemon, color: colors.ink },
  boxLabel: { position: 'absolute', top: 20, left: 20, fontSize: 12, color: colors.muted },
  cardTitle: { fontSize: 28, fontWeight: '800', color: colors.ink, textAlign: 'center', lineHeight: 42 },
  hint: { fontSize: 13, color: colors.muted },
  point: { fontSize: 19, fontWeight: '700', color: colors.ground, textAlign: 'center', lineHeight: 34, writingDirection: 'rtl' },
  formula: { backgroundColor: colors.surface, borderRadius: 14, padding: 4 },
  brand: { position: 'absolute', bottom: 14, fontSize: 11, color: '#B9C4BC' },
  tint: { position: 'absolute', top: 0, left: 0, right: 0, bottom: 0, borderRadius: 30, alignItems: 'center', justifyContent: 'center' },
  tintText: { color: '#fff', fontSize: 28, fontWeight: '800' },
  bar: { flexDirection: 'row-reverse', gap: 8, paddingHorizontal: 12, paddingTop: 8, paddingBottom: 4 },
  grade: { flex: 1, borderRadius: 16, paddingVertical: 10, alignItems: 'center', gap: 2 },
  gradeLabel: { fontSize: 15, fontWeight: '800' },
  gradeWhen: { fontSize: 12, opacity: 0.85 },
  swipeHint: { textAlign: 'center', fontSize: 12, color: colors.muted, paddingBottom: 8 },
  done: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  doneTitle: { fontSize: 26, fontWeight: '800', color: colors.ink },
  doneText: { fontSize: 15, color: colors.muted, textAlign: 'center', lineHeight: 26 },
});
