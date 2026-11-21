import { useEffect, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { ApiError } from '../api/client';
import type { ReportReason } from '../api/endpoints';
import { colors, radius, rtl, toPersianDigits } from '../theme';
import { Text, TextInput } from './Text';
import { Button, Sheet } from './ui';

/** What is being reported decides the reasons offered. */
export type ReportKind = 'text' | 'latin' | 'media' | 'question' | 'flashcard';

const REASONS: Record<ReportKind, [ReportReason, string][]> = {
  text: [
    ['typo', 'غلط تایپی یا نگارشی'],
    ['wrong_answer', 'مطلب نادرست است'],
    ['formula', 'فرمول یا علامت نادرست است'],
    ['unclear', 'مبهم یا ناقص است'],
    ['other', 'سایر'],
  ],
  latin: [
    ['translation', 'ترجمه‌ی نادرست'],
    ['typo', 'غلط تایپی یا املایی'],
    ['wrong_answer', 'مطلب نادرست است'],
    ['unclear', 'مبهم یا ناقص است'],
    ['other', 'سایر'],
  ],
  media: [
    ['image', 'عکس یا نمودار نادرست است'],
    ['unclear', 'ناخوانا یا نامفهوم است'],
    ['formula', 'فرمول یا عدد آن نادرست است'],
    ['other', 'سایر'],
  ],
  question: [
    ['wrong_answer', 'گزینه‌ی درست اشتباه است'],
    ['explanation', 'پاسخ تشریحی ایراد دارد'],
    ['formula', 'فرمول درست نمایش داده نمی‌شود'],
    ['typo', 'غلط تایپی'],
    ['unclear', 'صورت سؤال مبهم است'],
    ['other', 'سایر'],
  ],
  flashcard: [
    ['wrong_answer', 'نکته نادرست است'],
    ['formula', 'فرمول درست نمایش داده نمی‌شود'],
    ['typo', 'غلط تایپی'],
    ['unclear', 'مبهم است'],
    ['other', 'سایر'],
  ],
};

const NOTE_MAX = 200;
const COUNT_FROM = 150;
const NOTE_MIN = 10;

/** «گزارش اشکال»: a reason (by what is reported), a short note (10–200 characters, required so accidental or empty
 *  taps do not flood the panel), and — for the lesson text — the selected words shown on top. The learner then sees
 *  «گزارش داده شد»; the report waits in the panel, and when it is fixed the app says «اصلاح شد، ممنون». */
export function ReportSheet({
  visible,
  onClose,
  onSend,
  onDone,
  kind = 'text',
  quote,
  where,
}: {
  visible: boolean;
  onClose: () => void;
  onSend: (reason: ReportReason, note: string) => Promise<unknown>;
  onDone: () => void;
  kind?: ReportKind;
  quote?: string;
  /** «چکیده، تعریف»: where the quote is. */
  where?: string;
}) {
  const reasons = REASONS[kind];
  const [reason, setReason] = useState<ReportReason>(reasons[0][0]);
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    if (visible) {
      setReason(REASONS[kind][0][0]);
      setError(null);
    }
  }, [visible, kind]);

  const trimmed = note.trim();
  const distinctChars = new Set(trimmed.replace(/\s+/g, '')).size;
  const needsNote = trimmed.length < NOTE_MIN || distinctChars < 3;
  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSend(reason, trimmed);
      setNote('');
      onDone();
      onClose();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'ارسال ممکن نشد.');
    } finally {
      setBusy(false);
    }
  };

  return (
    <Sheet visible={visible} onClose={onClose} title="گزارش اشکال">
      {!!quote && (
        <View style={styles.quote}>
          {!!where && <Text style={[styles.where, rtl]}>{where}</Text>}
          <Text style={[styles.quoteText, rtl]} numberOfLines={4}>
            {quote}
          </Text>
        </View>
      )}
      {reasons.map(([key, label]) => (
        <Pressable
          key={key}
          onPress={() => setReason(key)}
          style={[styles.reason, reason === key && styles.reasonOn]}
          accessibilityRole="radio"
          accessibilityState={{ checked: reason === key }}
        >
          <Text style={[styles.reasonText, rtl, reason === key && { color: colors.ink, fontWeight: '800' }]}>{label}</Text>
        </Pressable>
      ))}
      <TextInput
        value={note}
        onChangeText={(t) => setNote(t.slice(0, NOTE_MAX))}
        placeholder="در یک جمله‌ی کوتاه بنویس اشکال کجاست (دست‌کم ۱۰ نویسه)…"
        multiline
        style={styles.input}
        maxLength={NOTE_MAX}
      />
      {(note.length >= COUNT_FROM || needsNote) && (
        <Text style={[styles.count, rtl, note.length >= NOTE_MAX && { color: colors.redDark }]}>
          {needsNote ? `برای ارسال گزارش، دست‌کم ${toPersianDigits(NOTE_MIN)} نویسه بنویس چه اشکالی دیدی.` : `${toPersianDigits(note.length)} از ${toPersianDigits(NOTE_MAX)}`}
        </Text>
      )}
      {!!error && <Text style={{ color: colors.redDark }}>{error}</Text>}
      <Button label={busy ? '…' : 'ارسال گزارش'} onPress={send} disabled={busy || needsNote} />
    </Sheet>
  );
}

const styles = StyleSheet.create({
  quote: { borderRightWidth: 3, borderRightColor: colors.lemon, backgroundColor: colors.lemonSoft, borderRadius: radius.sm, padding: 10, gap: 4 },
  where: { fontSize: 11, color: colors.muted, fontWeight: '700' },
  quoteText: { fontSize: 14, color: colors.ink, lineHeight: 22 },
  reason: { padding: 14, borderRadius: radius.sm, borderWidth: 1.5, borderColor: colors.line },
  reasonOn: { borderColor: colors.ink, backgroundColor: colors.lemonSoft },
  reasonText: { color: colors.muted, fontSize: 15 },
  input: { minHeight: 80, borderWidth: 1.5, borderColor: colors.line, borderRadius: radius.sm, padding: 12, textAlign: 'right', textAlignVertical: 'top', writingDirection: 'rtl' },
  count: { fontSize: 12, color: colors.muted },
});
