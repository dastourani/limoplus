/**
 * Internet status: a banner when the phone is offline, and an outbox so learner data (reading progress, flashcard
 * reviews) saved while offline is sent when the connection returns instead of being lost.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from 'react';
import { Platform, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { api, ApiError, setOnline } from '../api/client';
import { Icon } from '../components/Icon';
import { Text } from '../components/Text';
import { colors } from '../theme';

const OUTBOX = 'limo.outbox';
type Job = { path: string; body: unknown; at: number };

const OnlineContext = createContext(true);
export const useOnline = () => useContext(OnlineContext);

async function readOutbox(): Promise<Job[]> {
  try {
    return JSON.parse((await AsyncStorage.getItem(OUTBOX)) ?? '[]') as Job[];
  } catch {
    return [];
  }
}

/** POST that is retried later if there is no connection. Use only for requests that are safe to send late. */
export async function sendOrQueue(path: string, body: unknown): Promise<void> {
  try {
    await api(path, { body });
  } catch (e) {
    if (e instanceof ApiError && e.status === 0) {
      const jobs = await readOutbox();
      jobs.push({ path, body, at: Date.now() });
      await AsyncStorage.setItem(OUTBOX, JSON.stringify(jobs.slice(-500))).catch(() => undefined);
    }
  }
}

let flushing = false;
export async function flushOutbox() {
  if (flushing) return;
  flushing = true;
  try {
    const jobs = await readOutbox();
    const left: Job[] = [];
    for (const job of jobs) {
      try {
        await api(job.path, { body: job.body });
      } catch (e) {
        // Keep it only if we are still offline; a server refusal (e.g. signed out) drops it.
        if (e instanceof ApiError && e.status === 0) left.push(job);
      }
    }
    await AsyncStorage.setItem(OUTBOX, JSON.stringify(left)).catch(() => undefined);
  } finally {
    flushing = false;
  }
}

const BANNER_SECONDS = 4;

export function NetworkProvider({ children }: { children: ReactNode }) {
  const [online, setState] = useState(true);
  const [banner, setBanner] = useState<'offline' | 'back' | null>(null);
  const insets = useSafeAreaInsets();
  const wasOnline = useRef(true);

  // When the connection drops: a banner for a few seconds, then only a small icon in the corner (reading in peace).
  // When it comes back: a short «back online» note.
  useEffect(() => {
    if (online === wasOnline.current) return;
    wasOnline.current = online;
    setBanner(online ? 'back' : 'offline');
    const t = setTimeout(() => setBanner(null), (online ? 2.5 : BANNER_SECONDS) * 1000);
    return () => clearTimeout(t);
  }, [online]);
  useEffect(() => {
    flushOutbox();
    const update = (now: boolean) => {
      setState(now);
      setOnline(now);
      if (now) flushOutbox();
    };
    const unsubscribe = NetInfo.addEventListener((s) => update(s.isConnected !== false && s.isInternetReachable !== false));
    // Browsers: also follow the online/offline events (Chrome's NetInfo listens to another event).
    const web = Platform.OS === 'web' && typeof window !== 'undefined';
    const onWeb = () => update(navigator.onLine);
    if (web) {
      window.addEventListener('online', onWeb);
      window.addEventListener('offline', onWeb);
    }
    return () => {
      unsubscribe();
      if (web) {
        window.removeEventListener('online', onWeb);
        window.removeEventListener('offline', onWeb);
      }
    };
  }, []);
  return (
    <OnlineContext.Provider value={online}>
      {children}
      {banner && (
        <View style={[styles.banner, { paddingTop: insets.top + 6 }, banner === 'back' && { backgroundColor: colors.greenSoft }]} pointerEvents="none">
          <Icon name={banner === 'back' ? 'circle-check' : 'cloud-off'} size={16} color={banner === 'back' ? colors.greenDark : colors.ink} />
          <Text style={[styles.text, banner === 'back' && { color: colors.greenDark }]}>
            {banner === 'back' ? 'دوباره آنلاین شدید؛ کارهایتان ارسال شد.' : 'آفلاین هستید؛ کارهایتان ذخیره می‌شود.'}
          </Text>
        </View>
      )}
      {!online && !banner && (
        <View style={[styles.dot, { top: insets.top + 8 }]} pointerEvents="none" accessibilityLabel="آفلاین هستید">
          <Icon name="cloud-off" size={14} color={colors.ink} />
        </View>
      )}
    </OnlineContext.Provider>
  );
}

const styles = StyleSheet.create({
  banner: { position: 'absolute', zIndex: 1000, elevation: 10, top: 0, left: 0, right: 0, paddingBottom: 8, paddingHorizontal: 16, backgroundColor: colors.lemon, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
  dot: { position: 'absolute', zIndex: 1000, elevation: 10, left: 10, width: 26, height: 26, borderRadius: 13, backgroundColor: colors.lemon, alignItems: 'center', justifyContent: 'center', opacity: 0.9 },
  text: { fontSize: 13, fontWeight: '700', color: colors.ink, textAlign: 'right', flexShrink: 1 },
});
