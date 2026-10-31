import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { Text } from '../components/Text';
import { useFeedback } from '../components/Feedback';
import { Empty, Header, Screen } from '../components/ui';
import { jalaliDate } from '../lib/jalali';
import { offlineBooks, offlineSupported, removeOfflineBook, type OfflineBook } from '../lib/offline';
import { colors, rtl, toPersianDigits } from '../theme';

export default function Offline() {
  const [books, setBooks] = useState<OfflineBook[]>([]);
  const { confirm } = useFeedback();
  useFocusEffect(useCallback(() => void offlineBooks().then(setBooks), []));

  return (
    <Screen>
      <Header title="کتاب‌های آفلاین" />
      {!offlineSupported ? (
        <Empty icon="smartphone" title="فقط در اپ گوشی" text="دانلود آفلاین رمزدار در اپ اندروید در دسترس است." />
      ) : books.length === 0 ? (
        <Empty icon="download" title="کتاب آفلاینی نداری" text="در صفحه‌ی هر کتاب، «دانلود برای مطالعه‌ی آفلاین» را بزن. فایل‌ها رمزگذاری‌شده‌اند و ۳۰ روز اعتبار دارند." />
      ) : (
        <ScrollView contentContainerStyle={styles.page}>
          {books.map((b) => (
            <View key={b.slug} style={styles.row}>
              <Pressable style={{ flex: 1, gap: 4 }} onPress={() => router.push(`/book/${b.slug}`)}>
                <Text style={[styles.title, rtl]}>{b.title}</Text>
                <Text style={[styles.muted, rtl]}>
                  {toPersianDigits(b.sectionIds.length)} بخش، معتبر تا {jalaliDate(b.validUntil)}
                </Text>
              </Pressable>
              <Pressable onPress={async () => (await confirm({ title: `نسخه‌ی آفلاین «${b.title}» حذف شود؟`, confirmLabel: 'حذف', destructive: true, icon: 'trash' })) && removeOfflineBook(b.slug).then(() => offlineBooks().then(setBooks))}>
                <Text style={{ color: colors.redDark, fontWeight: '800' }}>حذف</Text>
              </Pressable>
            </View>
          ))}
        </ScrollView>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 10 },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, backgroundColor: colors.surface, borderRadius: 18, borderWidth: 1, borderColor: colors.line, padding: 14 },
  title: { fontSize: 15, fontWeight: '800', color: colors.ink },
  muted: { fontSize: 12, color: colors.muted },
});
