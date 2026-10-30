import { useState } from 'react';
import { Pressable, StyleSheet } from 'react-native';

import { ApiError } from '../api/client';
import type { ReportReason } from '../api/endpoints';
import { colors, radius, rtl } from '../theme';
import { Text, TextInput } from './Text';
import { Button, Sheet } from './ui';

const REASONS: [ReportReason, string][] = [
  ['wrong_answer', 'جواب یا نکته غلط است'],
  ['formula', 'فرمول درست نمایش داده نمی‌شود'],
  ['unclear', 'مبهم است'],
  ['typo', 'غلط تایپی'],
  ['other', 'سایر'],
];

/** "Report a mistake": the learner then sees «گزارش داده شد», and the report waits in the admin panel. */
export function ReportSheet({
  visible,
  onClose,
  onSend,
  onDone,
}: {
  visible: boolean;
  onClose: () => void;
  onSend: (reason: ReportReason, note: string) => Promise<unknown>;
  onDone: () => void;
}) {
  const [reason, setReason] = useState<ReportReason>('wrong_answer');
  const [note, setNote] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const send = async () => {
    setBusy(true);
    setError(null);
    try {
      await onSend(reason, note.trim());
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
      {REASONS.map(([key, label]) => (
        <Pressable key={key} onPress={() => setReason(key)} style={[styles.reason, reason === key && styles.reasonOn]} accessibilityRole="radio">
          <Text style={[styles.reasonText, rtl, reason === key && { color: colors.ink, fontWeight: '800' }]}>{label}</Text>
        </Pressable>
      ))}
      <TextInput value={note} onChangeText={setNote} placeholder="توضیح (اختیاری)" multiline style={styles.input} maxLength={1000} />
      {!!error && <Text style={{ color: colors.redDark }}>{error}</Text>}
      <Button label={busy ? '…' : 'ارسال گزارش'} onPress={send} disabled={busy} />
    </Sheet>
  );
}

const styles = StyleSheet.create({
  reason: { padding: 14, borderRadius: radius.sm, borderWidth: 1.5, borderColor: colors.line },
  reasonOn: { borderColor: colors.ink, backgroundColor: colors.lemonSoft },
  reasonText: { color: colors.muted, fontSize: 15 },
  input: { minHeight: 80, borderWidth: 1.5, borderColor: colors.line, borderRadius: radius.sm, padding: 12, textAlign: 'right', textAlignVertical: 'top', writingDirection: 'rtl' },
});
