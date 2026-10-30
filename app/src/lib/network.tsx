/**
 * Internet status: a banner when the phone is offline, and an outbox so learner data (reading progress, flashcard
 * reviews) saved while offline is sent when the connection returns instead of being lost.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import NetInfo from '@react-native-community/netinfo';
import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
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

export function NetworkProvider({ children }: { children: ReactNode }) {
  const [online, setState] = useState(true);
  const insets = useSafeAreaInsets();
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
      {!online && (
        <View style={[styles.banner, { paddingTop: insets.top + 6 }]} pointerEvents="none">
          <Icon name="wifi-off" size={16} color={colors.ink} />
          <Text style={styles.text}>اینترنت قطع است؛ کارهایتان بعداً ارسال می‌شود.</Text>
        </View>
      )}
    </OnlineContext.Provider>
  );
}

const styles = StyleSheet.create({
  banner: { position: 'absolute', zIndex: 1000, elevation: 10, top: 0, left: 0, right: 0, paddingBottom: 8, paddingHorizontal: 16, backgroundColor: colors.lemon, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
  text: { fontSize: 13, fontWeight: '700', color: colors.ink, textAlign: 'right', flexShrink: 1 },
});
