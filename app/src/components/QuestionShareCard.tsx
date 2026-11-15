/**
 * Sample questions as one picture to share: the lemon, where they come from, each question with its choices, and an
 * invitation to see the answers in the app. The answers themselves are never on the picture. One to five questions.
 */
import { forwardRef } from 'react';
import { StyleSheet, View, type HostInstance } from 'react-native';

import type { Question } from '../api/endpoints';
import { colors, rtl, toPersianDigits } from '../theme';
import { LemonSlice } from './LemonSlice';
import { RichText } from './RichText';
import { Text } from './Text';

const KEYS = ['الف', 'ب', 'ج', 'د', 'ه', 'و'];

function placeLine(q: Question): string {
  const place = q.share_place;
  const source = q.sources[0];
  return [
    place?.chapter ? `فصل ${place.chapter_number ? toPersianDigits(place.chapter_number) + ' ' : ''}«${place.chapter}»` : '',
    source ? `${source.name}${source.year ? ' ' + toPersianDigits(source.year) : ''}` : q.is_original ? 'تألیفی' : '',
  ]
    .filter(Boolean)
    .join('، ');
}

export const QuestionShareCard = forwardRef<HostInstance, { questions: Question[] }>(function QuestionShareCard({ questions }, ref) {
  const book = questions[0]?.share_place?.book;
  const many = questions.length > 1;
  return (
    <View ref={ref} collapsable={false} style={styles.card}>
      <View style={styles.head}>
        <LemonSlice size={30} />
        <Text style={styles.brand}>لیموخوان</Text>
        {!!book && <Text style={[styles.book, rtl]} numberOfLines={1}>{book}</Text>}
      </View>
      {questions.map((q, n) => (
        <View key={q.id} style={[styles.question, n > 0 && styles.divider]}>
          <Text style={[styles.place, rtl]}>
            {many ? `تست ${toPersianDigits(n + 1)}${placeLine(q) ? '، ' : ''}` : ''}
            {placeLine(q)}
          </Text>
          <RichText text={q.stem} size={16} />
          <View style={{ gap: 8 }}>
            {q.choices.map((c, i) => (
              <View key={c.id} style={styles.choice}>
                <Text style={styles.key}>{KEYS[i] ?? i + 1}</Text>
                <View style={{ flex: 1 }}>
                  <RichText text={c.text} size={15} />
                </View>
              </View>
            ))}
          </View>
        </View>
      ))}
      <Text style={[styles.cta, rtl]}>{many ? 'جواب‌ها را با پاسخ تشریحی در لیموخوان ببین' : 'جوابش را با پاسخ تشریحی در لیموخوان ببین'}</Text>
    </View>
  );
});

const styles = StyleSheet.create({
  card: { width: 360, padding: 20, gap: 14, backgroundColor: '#FFFDF6', borderRadius: 24 },
  head: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  brand: { fontSize: 15, fontWeight: '900', color: colors.ink },
  book: { flex: 1, fontSize: 12, color: colors.muted },
  question: { gap: 10 },
  divider: { borderTopWidth: 1, borderTopColor: '#E3E8DE', paddingTop: 14 },
  place: { fontSize: 12, fontWeight: '700', color: colors.greenDark },
  choice: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, borderWidth: 1.5, borderColor: '#E3E8DE', borderRadius: 14, padding: 10, backgroundColor: '#FFFFFF' },
  key: { width: 30, textAlign: 'center', fontWeight: '800', color: colors.ink },
  cta: { fontSize: 13, fontWeight: '800', color: colors.greenDark, textAlign: 'center' },
});
