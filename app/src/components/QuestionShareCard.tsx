/**
 * A sample question as a picture to share: the question and its choices, the lemon, and an invitation to see the
 * answer in the app. The answer itself is never on the picture.
 */
import { forwardRef } from 'react';
import { StyleSheet, View, type HostInstance } from 'react-native';

import type { Question } from '../api/endpoints';
import { colors, rtl } from '../theme';
import { LemonSlice } from './LemonSlice';
import { RichText } from './RichText';
import { Text } from './Text';

const KEYS = ['الف', 'ب', 'ج', 'د', 'ه', 'و'];

export const QuestionShareCard = forwardRef<HostInstance, { question: Question; bookTitle?: string }>(function QuestionShareCard({ question, bookTitle }, ref) {
  return (
    <View ref={ref} collapsable={false} style={styles.card}>
      <View style={styles.head}>
        <LemonSlice size={30} />
        <Text style={styles.brand}>لیمو پلاس</Text>
        {!!bookTitle && <Text style={[styles.book, rtl]} numberOfLines={1}>{bookTitle}</Text>}
      </View>
      <RichText text={question.stem} size={16} />
      <View style={{ gap: 8 }}>
        {question.choices.map((c, i) => (
          <View key={c.id} style={styles.choice}>
            <Text style={styles.key}>{KEYS[i] ?? i + 1}</Text>
            <View style={{ flex: 1 }}>
              <RichText text={c.text} size={15} />
            </View>
          </View>
        ))}
      </View>
      <Text style={[styles.cta, rtl]}>جوابش را با پاسخ تشریحی در لیمو پلاس ببین</Text>
    </View>
  );
});

const styles = StyleSheet.create({
  card: { width: 360, padding: 20, gap: 14, backgroundColor: '#FFFDF6', borderRadius: 24 },
  head: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  brand: { fontSize: 15, fontWeight: '900', color: colors.ink },
  book: { flex: 1, fontSize: 12, color: colors.muted },
  choice: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, borderWidth: 1.5, borderColor: '#E3E8DE', borderRadius: 14, padding: 10, backgroundColor: '#FFFFFF' },
  key: { width: 30, textAlign: 'center', fontWeight: '800', color: colors.ink },
  cta: { fontSize: 13, fontWeight: '800', color: colors.greenDark, textAlign: 'center' },
});
