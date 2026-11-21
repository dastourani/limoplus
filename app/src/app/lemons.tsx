/** «لیموها چه می‌گویند؟»: what the wedges of the progress lemons mean, the same everywhere in the app. */
import { ScrollView, StyleSheet, View } from 'react-native';

import { LemonProgress, type PartState } from '../components/LemonProgress';
import { Text } from '../components/Text';
import { Card, Header, Screen } from '../components/ui';
import { colors, rtl } from '../theme';

const COLORS: [PartState, string, string][] = [
  ['empty', 'کرم', 'هنوز انجام نشده'],
  ['done', 'زرد پررنگ', 'تمام شد: بخش خوانده و تست‌هایش زده شد، یا تست درست'],
  ['soft', 'زرد ملایم', 'نیمه‌کاره: بخشی که شروع کرده‌ای، یا فلش‌کارتی که «سخت» بود'],
  ['wrong', 'صورتی', 'تست غلط، یا فلش‌کارت «دوباره»'],
  ['flag', 'نارنجی', 'فقط در آزمون: سؤالی که «شک‌دار» علامت زده‌ای'],
];

const PLACES: [string, PartState[], string][] = [
  ['کتاب و فصل', ['done', 'done', 'soft', 'empty', 'empty', 'empty'], 'هر قاچ یک بخش است.'],
  ['تست', ['done', 'wrong', 'done', 'empty', 'empty'], 'هر قاچ یک تست است. لیمو را بزن تا به هر تست بروی.'],
  ['آزمون', ['done', 'flag', 'done', 'empty', 'empty', 'empty', 'empty'], 'تا پایان آزمون درست و غلط معلوم نیست؛ جواب‌داده‌ها زرد می‌شوند.'],
  ['فلش‌کارت', ['done', 'soft', 'wrong', 'empty'], 'هر قاچ یک کارت است.'],
];

export default function Lemons() {
  return (
    <Screen>
      <Header title="لیموها چه می‌گویند؟" />
      <ScrollView contentContainerStyle={styles.page}>
        <Text style={[styles.lead, rtl]}>
          پیشرفت در همه‌جای اپ یک لیموی برش‌خورده است: هر قاچ یک مورد. قاچ‌ها از بالا شروع می‌شوند و در جهت عقربه‌های ساعت پر
          می‌شوند. اگر مورد‌ها بیشتر از ۲۴ تا باشند، چند مورد کنار هم یک قاچ را با هم پر می‌کنند؛ قاچی که فقط بخشی از آن انجام شده،
          زرد خیلی کم‌رنگ است.
        </Text>
        <Card>
          <Text style={[styles.h, rtl]}>رنگ قاچ‌ها</Text>
          {COLORS.map(([state, name, text]) => (
            <View key={state} style={styles.row}>
              <LemonProgress parts={[state]} size={34} />
              <View style={{ flex: 1 }}>
                <Text style={[styles.name, rtl]}>{name}</Text>
                <Text style={[styles.text, rtl]}>{text}</Text>
              </View>
            </View>
          ))}
        </Card>
        <Card>
          <Text style={[styles.h, rtl]}>کجا چه چیزی را نشان می‌دهد</Text>
          {PLACES.map(([name, parts, text]) => (
            <View key={name} style={styles.row}>
              <LemonProgress parts={parts} size={44} />
              <View style={{ flex: 1 }}>
                <Text style={[styles.name, rtl]}>{name}</Text>
                <Text style={[styles.text, rtl]}>{text}</Text>
              </View>
            </View>
          ))}
        </Card>
      </ScrollView>
    </Screen>
  );
}

const styles = StyleSheet.create({
  page: { padding: 16, gap: 12 },
  lead: { fontSize: 14, lineHeight: 26, color: colors.ink },
  h: { fontSize: 15, fontWeight: '900', color: colors.ink, marginBottom: 4 },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12, paddingVertical: 8 },
  name: { fontSize: 14, fontWeight: '800', color: colors.ink },
  text: { fontSize: 13, lineHeight: 22, color: colors.muted },
});
