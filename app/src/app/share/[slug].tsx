/** «تست‌های نمونه»: pick up to five of the book's shareable questions and send them as one picture (without answers). */
import * as Sharing from 'expo-sharing';
import { useLocalSearchParams } from 'expo-router';
import { useRef, useState } from 'react';
import { Platform, Pressable, ScrollView, StyleSheet, View, type HostInstance } from 'react-native';
import { captureRef } from 'react-native-view-shot';

import { endpoints } from '../../api/endpoints';
import { useFeedback } from '../../components/Feedback';
import { Icon } from '../../components/Icon';
import { QuestionShareCard } from '../../components/QuestionShareCard';
import { RichText } from '../../components/RichText';
import { Text } from '../../components/Text';
import { Button, Empty, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { useApi } from '../../lib/useApi';
import { colors, rtl, toPersianDigits } from '../../theme';

const MAX = 5;

export default function ShareSamples() {
  const { slug } = useLocalSearchParams<{ slug: string }>();
  const { data, error, loading, retry } = useApi(() => endpoints.bookSamples(String(slug)), [slug]);
  const { toast } = useFeedback();
  const [picked, setPicked] = useState<number[]>([]);
  const [busy, setBusy] = useState(false);
  const ref = useRef<HostInstance>(null);

  if (loading && !data) return <Screen><Header title="تست‌های نمونه" /><Loading /></Screen>;
  if (error || !data) return <Screen><Header title="تست‌های نمونه" /><ErrorState message={error?.message ?? ''} onRetry={retry} /></Screen>;

  const toggle = (id: number) =>
    setPicked((p) => (p.includes(id) ? p.filter((x) => x !== id) : p.length >= MAX ? (toast(`حداکثر ${toPersianDigits(MAX)} تست با هم.`), p) : [...p, id]));
  const chosen = data.questions.filter((q) => picked.includes(q.id));

  const share = async () => {
    if (!chosen.length) return;
    if (Platform.OS === 'web' || !(await Sharing.isAvailableAsync())) {
      toast('فرستادن تصویر فقط در اپ گوشی ممکن است.');
      return;
    }
    setBusy(true);
    try {
      await new Promise((r) => setTimeout(r, 900 + 300 * chosen.length)); // let the formulas draw
      const uri = await captureRef(ref, { format: 'png', quality: 1 });
      await Sharing.shareAsync(uri, { mimeType: 'image/png', dialogTitle: 'تست‌های لیموخوان' });
    } catch {
      // cancelled
    } finally {
      setBusy(false);
    }
  };

  return (
    <Screen>
      <Header title="تست‌های نمونه" subtitle={data.book} />
      {data.questions.length === 0 ? (
        <Empty icon="share-2" title="هنوز تست نمونه‌ای نیست" text="تست‌هایی که برای اشتراک انتخاب شده‌اند این‌جا می‌آیند." />
      ) : (
        <>
          <ScrollView contentContainerStyle={styles.page}>
            <Text style={[styles.hint, rtl]}>
              تا {toPersianDigits(MAX)} تست را انتخاب کن تا با هم در یک تصویر، بدون جواب، برای دوستانت بفرستی.
            </Text>
            {data.questions.map((q) => {
              const on = picked.includes(q.id);
              return (
                <Pressable key={q.id} onPress={() => toggle(q.id)} style={[styles.row, on && styles.rowOn]} accessibilityRole="checkbox" accessibilityState={{ checked: on }}>
                  <View style={[styles.check, on && styles.checkOn]}>{on && <Icon name="check" size={14} color="#fff" strokeWidth={3} />}</View>
                  <View style={{ flex: 1, gap: 4 }}>
                    {!!q.share_place?.chapter && <Text style={[styles.place, rtl]}>{q.share_place.chapter}</Text>}
                    <RichText text={q.stem} size={14} />
                  </View>
                </Pressable>
              );
            })}
          </ScrollView>
          <View style={styles.bar}>
            <Button
              label={busy ? 'در حال آماده کردن…' : chosen.length ? `فرستادن ${toPersianDigits(chosen.length)} تست` : 'تست‌ها را انتخاب کن'}
              onPress={share}
              disabled={!chosen.length || busy}
            />
          </View>
        </>
      )}
      {busy && (
        <View style={styles.offscreen} pointerEvents="none">
          <QuestionShareCard ref={ref} questions={chosen} />
        </View>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 10, paddingBottom: 100 },
  hint: { fontSize: 13, color: colors.muted, lineHeight: 22 },
  row: { flexDirection: 'row-reverse', gap: 12, alignItems: 'flex-start', backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1.5, borderColor: colors.line, padding: 12 },
  rowOn: { borderColor: colors.ink },
  check: { width: 24, height: 24, borderRadius: 8, borderWidth: 2, borderColor: colors.line, alignItems: 'center', justifyContent: 'center', marginTop: 2 },
  checkOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  place: { fontSize: 12, fontWeight: '700', color: colors.greenDark },
  bar: { position: 'absolute', left: 0, right: 0, bottom: 0, padding: 16, backgroundColor: colors.ground, borderTopWidth: 1, borderTopColor: colors.line },
  offscreen: { position: 'absolute', left: -2000, top: 0 },
});
