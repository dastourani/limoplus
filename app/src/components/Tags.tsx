import { Pressable, StyleSheet, View } from 'react-native';

import type { Question } from '../api/endpoints';
import { colors, toPersianDigits } from '../theme';
import { Icon, type IconName } from './Icon';
import { Text } from './Text';

function Tag({ label, icon, color, background }: { label: string; icon: IconName; color: string; background: string }) {
  return (
    <View style={[styles.tag, { backgroundColor: background }]}>
      <Icon name={icon} size={14} color={color} strokeWidth={2.2} />
      <Text style={[styles.text, { color }]}>{label}</Text>
    </View>
  );
}

const DIFFICULTY: Record<string, { label: string; color: string; background: string }> = {
  easy: { label: 'آسان', color: '#1F5E3A', background: '#E3F3E9' },
  medium: { label: 'متوسط', color: '#6B5200', background: '#FFF1B8' },
  hard: { label: 'سخت', color: '#9E2F2A', background: '#FBE7E6' },
};
const KIND: Record<string, { label: string; icon: IconName }> = {
  recall: { label: 'حفظی', icon: 'book-open' },
  concept: { label: 'مفهومی', icon: 'brain' },
  calc: { label: 'محاسباتی', icon: 'calculator' },
  analysis: { label: 'تحلیلی', icon: 'search-check' },
};

/** A question's labels: exam sources (konkur) or «تألیفی», difficulty and kind of question (kept short on purpose). */
export function QuestionTags({ q }: { q: Question }) {
  const d = DIFFICULTY[q.difficulty];
  const kind = q.kind ? KIND[q.kind] : null;
  return (
    <View style={styles.row}>
      {q.sources.map((s) => (
        <Tag
          key={`${s.name}${s.year}`}
          icon="graduation-cap"
          label={`${s.name} ${toPersianDigits(s.year)}${s.number ? ` · سؤال ${toPersianDigits(s.number)}` : ''}`}
          color={colors.ink}
          background={colors.lemon}
        />
      ))}
      {q.is_original && <Tag icon="pen-line" label="تألیفی" color="#1F5E3A" background="#E3F3E9" />}
      {d && <Tag icon="gauge" label={d.label} color={d.color} background={d.background} />}
      {kind && <Tag icon={kind.icon} label={kind.label} color="#3B44B8" background="#EEF0FC" />}
    </View>
  );
}

/** «Report a mistake» as a small framed button; turns into a green «reported» mark afterwards. */
export function ReportButton({ reported, onPress, label = 'گزارش اشکال' }: { reported: boolean; onPress: () => void; label?: string }) {
  if (reported) {
    return (
      <View style={[styles.report, styles.reported]} accessibilityLabel="گزارش داده شد">
        <Icon name="circle-check" size={16} color="#1F5E3A" />
        <Text style={[styles.reportText, { color: '#1F5E3A' }]}>گزارش داده شد</Text>
      </View>
    );
  }
  return (
    <Pressable onPress={onPress} style={({ pressed }) => [styles.report, pressed && { opacity: 0.7 }]} accessibilityRole="button">
      <Icon name="flag" size={16} color="#9E2F2A" />
      <Text style={styles.reportText}>{label}</Text>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 6 },
  tag: { flexDirection: 'row-reverse', alignItems: 'center', gap: 4, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 4 },
  text: { fontSize: 12, fontWeight: '700' },
  report: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6, alignSelf: 'flex-end', borderRadius: 999, borderWidth: 1, borderColor: '#F2C7C4', backgroundColor: '#FFF6F5', paddingHorizontal: 12, paddingVertical: 7 },
  reported: { borderColor: '#BFE8CF', backgroundColor: '#E3F3E9' },
  reportText: { fontSize: 13, fontWeight: '700', color: '#9E2F2A' },
});
