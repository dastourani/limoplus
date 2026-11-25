/** «برنامه‌ی امروز»: one compact row per job (chapter reviews, then flashcards, then the notebook), in one card. Each row
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

export function TodayTiles({
  tasks,
  onError,
  doneMessage = 'برنامه‌ی امروز تمام شد. آفرین!',
}: {
  tasks: TodayTask[];
  onError: () => void;
  doneMessage?: string;
}) {
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
      <View style={styles.row}>
        <LemonProgress parts={['done']} size={44} />
        <Text style={[styles.allDone, rtl]}>{doneMessage}</Text>
      </View>
    );
  }
  const rows = [...tasks.map((t) => ({ t, ended: false })), ...finished.map((t) => ({ t, ended: true }))];
  return (
    <View style={styles.list}>
      {rows.map(({ t, ended }, i) => (
        <Row key={keyOf(t) + (ended ? '-end' : '')} t={t} ended={ended} first={i === 0} onError={onError} />
      ))}
    </View>
  );
}

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
    const nextQ = t.next_question ?? done + 1;
    size =
      done > 0
        ? left > 0
          ? `${t.book_title}؛ ${fa(done)} از ${fa(total)} پاسخ داده‌ای، ادامه از سؤال ${fa(nextQ)}`
          : `${t.book_title}؛ برای ثبت مرور باز کن`
        : `${t.book_title}، ${fa(left)} تست، حدود ${fa(Math.max(1, Math.round((t.minutes * left) / Math.max(1, t.questions))))} دقیقه`;
    open = () => openReview({ ...t, kind: t.review_kind }).catch(onError);
  } else if (t.kind === 'cards') {
    title = t.comeback && t.total > t.count ? 'کارت‌های مهم‌تر' : 'مرور کارت‌ها';
    total = t.count + done;
    size = `${fa(t.count)} کارت، حدود ${fa(t.minutes)} دقیقه`;
    open = () => router.push(t.comeback ? { pathname: '/review', params: { limit: String(t.count) } } : '/review');
  } else {
    title = 'اشتباهات من';
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
      <LemonProgress parts={parts} size={44} />
      <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
        <Text style={[styles.title, rtl]} numberOfLines={1}>{title}</Text>
        <Text style={[styles.size, rtl]} numberOfLines={1}>{ended ? 'تمام شد' : size}</Text>
      </View>
      {ended ? (
        <View style={[styles.pill, styles.pillDone]}>
          <Icon name="check" size={16} color={colors.greenDark} />
        </View>
      ) : (
        <View style={styles.pill}>
          <Text style={styles.pillText}>{done > 0 ? 'ادامه' : 'شروع'}</Text>
        </View>
      )}
    </Pressable>
  );
}

const styles = StyleSheet.create({
  list: { overflow: 'hidden' },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, paddingHorizontal: 4, paddingVertical: 10, borderRadius: radius.sm },
  line: { borderTopWidth: 1, borderTopColor: colors.line },
  title: { fontSize: 15, fontWeight: '800', color: colors.ink },
  size: { fontSize: 12, color: colors.muted },
  pill: { backgroundColor: colors.lemon, borderRadius: 10, paddingHorizontal: 12, paddingVertical: 6, alignItems: 'center', justifyContent: 'center' },
  pillDone: { backgroundColor: '#E7F3EC', paddingHorizontal: 10 },
  pillText: { fontSize: 12, fontWeight: '800', color: colors.ink },
  allDone: { flex: 1, fontSize: 15, fontWeight: '800', color: colors.greenDark },
});
