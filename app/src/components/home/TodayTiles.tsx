/** «کارهای امروز»: one compact row per job (chapter reviews, then flashcards, then the notebook), in one card. Each row
 * has a lemon with a wedge per question or card (filled as they are done today), the job and its size, and a start
 * button. A job finished since the last look shows a full lemon and a tick for a moment, then leaves the list; when
 * none is left, one row says so. */
import { router } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { LayoutAnimation, Pressable, StyleSheet, View } from 'react-native';

import type { TodayTask } from '../../api/endpoints';
import { openReview } from '../../lib/reviews';
import { colors, radius, rtl, toPersianDigits } from '../../theme';
import { Icon } from '../Icon';
import { LemonProgress, type PartState } from '../LemonProgress';
import { Text } from '../Text';

const keyOf = (t: TodayTask) => (t.kind === 'review' ? `r-${t.review_kind}-${t.id}` : t.kind);
const FINISHED_MS = 1600;

export function TodayTiles({ tasks, onError }: { tasks: TodayTask[]; onError: () => void }) {
  // Jobs seen before and gone now were just finished: kept a moment, ticked.
  const seen = useRef<Map<string, TodayTask>>(new Map());
  const [finished, setFinished] = useState<TodayTask[]>([]);
  useEffect(() => {
    const now = new Set(tasks.map(keyOf));
    const gone = [...seen.current.values()].filter((t) => !now.has(keyOf(t)));
    seen.current = new Map(tasks.map((t) => [keyOf(t), t]));
    if (!gone.length) return;
    setFinished(gone);
    const timer = setTimeout(() => {
      LayoutAnimation.configureNext(LayoutAnimation.create(260, 'easeInEaseOut', 'opacity'));
      setFinished([]);
    }, FINISHED_MS);
    return () => clearTimeout(timer);
  }, [tasks]);

  if (!tasks.length && !finished.length) {
    return (
      <View style={[styles.card, styles.row]}>
        <LemonProgress parts={['done']} size={44} />
        <Text style={[styles.allDone, rtl]}>کارهای امروز تمام شد. آفرین!</Text>
      </View>
    );
  }
  const rows = [...tasks.map((t) => ({ t, ended: false })), ...finished.map((t) => ({ t, ended: true }))];
  return (
    <View style={styles.card}>
      {rows.map(({ t, ended }, i) => (
        <Row key={keyOf(t) + (ended ? '-end' : '')} t={t} ended={ended} first={i === 0} onError={onError} />
      ))}
    </View>
  );
}

const ACCENT = { review: colors.green, cards: '#2F6BD8', notebook: colors.red } as const;

function Row({ t, ended, first, onError }: { t: TodayTask; ended: boolean; first: boolean; onError: () => void }) {
  const fa = toPersianDigits;
  let title = '';
  let size = '';
  let total = 1;
  let open = () => {};
  const done = t.done ?? 0;
  if (t.kind === 'review') {
    title =
      t.review_kind === 'book'
        ? 'مرور ترکیبی کتاب'
        : `${t.is_exam ? 'آزمون یادآوری' : 'مرور'} فصل ${t.chapter_number ? fa(t.chapter_number) + ' ' : ''}«${t.chapter_title}»`;
    total = t.questions;
    const left = Math.max(0, t.questions - done);
    size = `${t.book_title}، ${fa(left)} تست، حدود ${fa(Math.max(1, Math.round((t.minutes * left) / Math.max(1, t.questions))))} دقیقه`;
    open = () => openReview({ ...t, kind: t.review_kind }).catch(onError);
  } else if (t.kind === 'cards') {
    title = t.comeback && t.total > t.count ? 'کارت‌های مهم‌تر' : 'مرور کارت‌ها';
    total = t.count + done;
    size = `${fa(t.count)} کارت، حدود ${fa(t.minutes)} دقیقه`;
    open = () => router.push(t.comeback ? { pathname: '/review', params: { limit: String(t.count) } } : '/review');
  } else {
    title = 'دفترچه‌ی اشتباهات';
    total = t.count + done;
    size = `${fa(t.count)} تست از ${fa(t.total)}، حدود ${fa(t.minutes)} دقیقه`;
    open = () => router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: 'mistakes' } });
  }
  const parts: PartState[] = Array.from({ length: Math.max(1, total) }, (_, i) => (ended || i < done ? 'done' : 'empty'));
  return (
    <Pressable
      onPress={ended ? undefined : open}
      disabled={ended}
      style={({ pressed }) => [styles.row, !first && styles.line, pressed && { backgroundColor: '#F7F8F3' }]}
      accessibilityRole="button"
      accessibilityLabel={ended ? `${title}، تمام شد` : `${title}، ${size}`}
    >
      <View style={[styles.accent, { backgroundColor: ACCENT[t.kind] }]} />
      <LemonProgress parts={parts} size={46} />
      <View style={{ flex: 1, gap: 2 }}>
        <Text style={[styles.title, rtl]} numberOfLines={1}>{title}</Text>
        <Text style={[styles.size, rtl]} numberOfLines={1}>{ended ? 'تمام شد' : size}</Text>
      </View>
      {ended ? (
        <View style={[styles.go, styles.goDone]}>
          <Icon name="check" size={18} color={colors.green} />
        </View>
      ) : (
        <View style={styles.go}>
          <Icon name="play" size={16} color={colors.ink} />
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  card: { backgroundColor: colors.surface, borderRadius: radius.md, borderWidth: 1, borderColor: colors.line, overflow: 'hidden' },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, paddingHorizontal: 14, paddingVertical: 12 },
  line: { borderTopWidth: 1, borderTopColor: colors.line },
  accent: { position: 'absolute', right: 0, top: 12, bottom: 12, width: 4, borderTopLeftRadius: 4, borderBottomLeftRadius: 4 },
  title: { fontSize: 15, fontWeight: '800', color: colors.ink },
  size: { fontSize: 12, color: colors.muted },
  go: { width: 38, height: 38, borderRadius: 19, backgroundColor: colors.lemon, alignItems: 'center', justifyContent: 'center' },
  goDone: { backgroundColor: '#E7F3EC' },
  allDone: { flex: 1, fontSize: 15, fontWeight: '800', color: colors.greenDark },
});
