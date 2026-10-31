/**
 * New versions of the app. On start (and when the app comes back to the front) the server is asked about this build:
 * - a newer build: a sheet offers it once per version («بعداً» hides it until the next one);
 * - a required build (or any API call answered with 426): a full screen that only offers the download.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useRef, useState } from 'react';
import { AppState, Linking, ScrollView, StyleSheet, View } from 'react-native';
import { SafeAreaView } from 'react-native-safe-area-context';

import { setUpdateRequiredHandler } from '../api/client';
import { endpoints, type AppReleaseInfo } from '../api/endpoints';
import { APP_BUILD, APP_PLATFORM } from '../config';
import { colors, rtl, toPersianDigits } from '../theme';
import { IconBadge } from './Icon';
import { LemonSlice } from './LemonSlice';
import { Text } from './Text';
import { Button, Sheet } from './ui';

const CHECK_EVERY_MS = 30 * 60 * 1000;
const dismissedKey = (build: number) => `limo.update.later.${build}`;

function Notes({ release }: { release: AppReleaseInfo | null }) {
  if (!release?.notes.length) return null;
  return (
    <View style={styles.notes}>
      {release.notes.map((n, i) => (
        <Text key={i} style={[styles.note, rtl]}>
          • {n}
        </Text>
      ))}
    </View>
  );
}

function versionLabel(r: AppReleaseInfo | null) {
  if (!r) return 'نسخه‌ی جدید';
  return `نسخه‌ی ${r.version_name || toPersianDigits(r.build)}`;
}

export function UpdateGate() {
  const [required, setRequired] = useState<AppReleaseInfo | null | false>(false);
  const [offer, setOffer] = useState<AppReleaseInfo | null>(null);
  const lastCheck = useRef(0);

  useEffect(() => {
    if (!APP_PLATFORM) return;
    setUpdateRequiredHandler((data) => setRequired((data.latest as AppReleaseInfo | null) ?? null));

    const check = async () => {
      if (Date.now() - lastCheck.current < CHECK_EVERY_MS) return;
      lastCheck.current = Date.now();
      try {
        const v = await endpoints.appVersion(APP_PLATFORM!, APP_BUILD);
        if (v.status === 'required') setRequired(v.latest);
        else if (v.status === 'optional' && v.latest) {
          const later = await AsyncStorage.getItem(dismissedKey(v.latest.build)).catch(() => null);
          if (!later) setOffer(v.latest);
        }
      } catch {
        lastCheck.current = 0; // server unreachable: try again next time
      }
    };
    check();
    const sub = AppState.addEventListener('change', (s) => s === 'active' && check());
    return () => {
      sub.remove();
      setUpdateRequiredHandler(null);
    };
  }, []);

  const download = (r: AppReleaseInfo | null) => {
    if (r?.download_url) Linking.openURL(r.download_url).catch(() => undefined);
  };

  if (required !== false) {
    return (
      <View style={StyleSheet.absoluteFill}>
        <SafeAreaView style={styles.wall}>
          <ScrollView contentContainerStyle={styles.wallInner}>
            <LemonSlice size={120} />
            <Text style={styles.wallTitle}>وقت به‌روزرسانی است</Text>
            <Text style={[styles.wallText]}>
              این نسخه‌ی لیمو پلاس دیگر پشتیبانی نمی‌شود. برای ادامه، {versionLabel(required)} را نصب کنید؛ کتاب‌ها، یادداشت‌ها و پیشرفت شما
              سر جایش می‌ماند.
            </Text>
            <Notes release={required} />
            {required?.download_url ? (
              <Button label={`دریافت ${versionLabel(required)}`} onPress={() => download(required)} style={{ alignSelf: 'stretch' }} />
            ) : (
              <Text style={styles.wallText}>لینک دریافت هنوز آماده نیست؛ کمی بعد دوباره برنامه را باز کنید.</Text>
            )}
          </ScrollView>
        </SafeAreaView>
      </View>
    );
  }

  return (
    <Sheet visible={!!offer} onClose={() => setOffer(null)} title="نسخه‌ی جدید لیمو پلاس">
      <View style={styles.offerHead}>
        <IconBadge name="sparkles" size={44} />
        <Text style={[styles.offerText, rtl]}>{versionLabel(offer)} آماده است. نصبش چند ثانیه طول می‌کشد و اطلاعات شما سر جایش می‌ماند.</Text>
      </View>
      <Notes release={offer} />
      <Button
        label="دریافت نسخه‌ی جدید"
        onPress={() => {
          download(offer);
          setOffer(null);
        }}
      />
      <Button
        label="بعداً"
        variant="outline"
        onPress={() => {
          if (offer) AsyncStorage.setItem(dismissedKey(offer.build), '1').catch(() => undefined);
          setOffer(null);
        }}
      />
    </Sheet>
  );
}

const styles = StyleSheet.create({
  wall: { flex: 1, backgroundColor: colors.ground },
  wallInner: { flexGrow: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 14 },
  wallTitle: { fontSize: 24, fontWeight: '800', color: colors.ink, textAlign: 'center' },
  wallText: { fontSize: 15, color: colors.muted, textAlign: 'center', lineHeight: 26 },
  notes: { alignSelf: 'stretch', backgroundColor: colors.surface, borderRadius: 16, padding: 14, gap: 4 },
  note: { fontSize: 14, color: colors.ink, lineHeight: 24 },
  offerHead: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12 },
  offerText: { flex: 1, fontSize: 14, color: colors.ink, lineHeight: 24 },
});
