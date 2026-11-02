/** «کارهای امروز»: one upright tile per job (chapter reviews, then flashcards, then the notebook), side by side. A job
 * done today leaves; when none is left, one tile says so. */
import { router } from 'expo-router';
import { Pressable, StyleSheet, View } from 'react-native';

import type { TodayTask } from '../../api/endpoints';
import { openReview } from '../../lib/reviews';
import { colors, rtl, toPersianDigits } from '../../theme';
import { Icon, type IconName } from '../Icon';
import { Text } from '../Text';
import { HRow } from './HRow';

const W = 170; // wide enough for «مرور فصل ۱ «حد و پیوستگی»» in three lines

export function TodayTiles({ tasks, onError }: { tasks: TodayTask[]; onError: () => void }) {
  if (!tasks.length) {
    return (
      <View style={[styles.tile, styles.done, { width: '100%', minHeight: 0, flexDirection: 'row-reverse', alignItems: 'center' }]}>
        <Icon name="circle-check" size={22} color={colors.greenDark} />
        <Text style={[styles.doneText, rtl]}>کارهای امروز تمام شد. آفرین!</Text>
      </View>
    );
  }
  return <HRow data={tasks} keyOf={(t) => (t.kind === 'review' ? `r-${t.id}-${t.kind}` : t.kind)} render={(t) => <Tile t={t} onError={onError} />} gap={10} />;
}

function Tile({ t, onError }: { t: TodayTask; onError: () => void }) {
  const fa = toPersianDigits;
  let icon: IconName = 'layers';
  let title = '';
  let place = '';
  let size = '';
  let open = () => {};
  if (t.kind === 'review') {
    icon = 'rotate-ccw';
    title =
      t.review_kind === 'book'
        ? 'مرور ترکیبی کتاب'
        : `${t.is_exam ? 'آزمون یادآوری' : 'مرور'} فصل ${t.chapter_number ? fa(t.chapter_number) + ' ' : ''}«${t.chapter_title}»`;
    place = t.book_title;
    size = `${fa(t.questions)} تست، حدود ${fa(t.minutes)} دقیقه`;
    open = () => openReview({ ...t, kind: t.review_kind }).catch(onError);
  } else if (t.kind === 'cards') {
    icon = 'layers';
    title = t.comeback && t.total > t.count ? 'کارت‌های مهم‌تر' : 'مرور فلش‌کارت‌ها';
    size = `${fa(t.count)} کارت، حدود ${fa(t.minutes)} دقیقه`;
    open = () => router.push(t.comeback ? { pathname: '/review', params: { limit: String(t.count) } } : '/review');
  } else {
    icon = 'notebook-pen';
    title = 'دفترچه‌ی اشتباهات';
    size = `${fa(t.count)} تست از ${fa(t.total)}، حدود ${fa(t.minutes)} دقیقه`;
    open = () => router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: 'mistakes' } });
  }
  return (
    <Pressable onPress={open} style={[styles.tile, { width: W }]} accessibilityRole="button" accessibilityLabel={`${title}، ${size}`}>
      <View style={styles.icon}>
        <Icon name={icon} size={20} color={colors.ink} />
      </View>
      <Text style={[styles.title, rtl]} numberOfLines={3}>{title}</Text>
      {!!place && <Text style={[styles.place, rtl]} numberOfLines={1}>{place}</Text>}
      <View style={{ flex: 1 }} />
      <Text style={[styles.size, rtl]} numberOfLines={2}>{size}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  tile: { backgroundColor: colors.ink, borderRadius: 18, padding: 14, gap: 6, minHeight: 176 },
  icon: { width: 36, height: 36, borderRadius: 12, backgroundColor: colors.lemon, alignItems: 'center', justifyContent: 'center', alignSelf: 'flex-end' },
  title: { fontSize: 15, fontWeight: '900', color: '#FFFFFF', lineHeight: 22 },
  place: { fontSize: 11, color: '#A9B6AD' },
  size: { fontSize: 12, fontWeight: '700', color: colors.lemon, lineHeight: 19 },
  done: { backgroundColor: colors.greenSoft, minHeight: 0, gap: 10 },
  doneText: { flex: 1, fontSize: 15, fontWeight: '800', color: colors.greenDark },
});
