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
import { HelpTip } from '../components/HelpTip';
import { Icon } from '../components/Icon';
import { Text } from '../components/Text';
import { colors } from '../theme';

const OUTBOX = 'limo.outbox';
export const MAX_OUTBOX_JOBS = 500;
/** A queued request, with the account it belongs to: it is only ever sent for that account. */
type Job = { id: string; path: string; body: unknown; at: number; owner?: number };
export type OutboxOutcome = 'sent' | 'queued' | 'dropped' | 'failed';
const MAX_AGE_MS = 30 * 24 * 3600 * 1000;

let outboxWarning: string | null = null;
const outboxWarningListeners = new Set<(msg: string | null) => void>();
function emitOutboxWarning(msg: string | null) {
  outboxWarning = msg;
  for (const fn of outboxWarningListeners) fn(msg);
}
export function subscribeOutboxWarning(fn: (msg: string | null) => void): () => void {
  outboxWarningListeners.add(fn);
  fn(outboxWarning);
  return () => {
    outboxWarningListeners.delete(fn);
  };
}

let owner: number | null = null;
/** Called by the auth provider whenever the signed-in account changes. */
export function setOutboxOwner(id: number | null) {
  owner = id;
  if (id != null) flushOutbox().catch(() => undefined);
}

let onReconnect: (() => void) | null = null;
/** Called whenever the device transitions from offline to online. */
export function setReconnectHandler(handler: (() => void) | null) {
  onReconnect = handler;
}

/** Network failures, 429 rate-limits, and 5xx server/proxy errors are transient and stay in the outbox. */
export function isRetryableStatus(status: number): boolean {
  return status === 0 || status === 429 || status >= 500;
}

const OnlineContext = createContext(true);
export const useOnline = () => useContext(OnlineContext);

async function readOutbox(): Promise<Job[]> {
  try {
    return JSON.parse((await AsyncStorage.getItem(OUTBOX)) ?? '[]') as Job[];
  } catch {
    return [];
  }
}

// Every change to the stored outbox goes through this one chain, so a flush and a new job never overwrite each other.
let chain: Promise<unknown> = Promise.resolve();
function update(change: (jobs: Job[]) => Job[]): Promise<void> {
  const next = chain.then(async () => {
    const jobs = await readOutbox();
    const now = Date.now();
    const fresh = change(jobs).filter((j) => now - j.at <= MAX_AGE_MS);
    const trimmed = fresh.length > MAX_OUTBOX_JOBS ? fresh.slice(-MAX_OUTBOX_JOBS) : fresh;
    try {
      await AsyncStorage.setItem(OUTBOX, JSON.stringify(trimmed));
      if (fresh.length > MAX_OUTBOX_JOBS) {
        emitOutboxWarning('صف ذخیرهٔ آفلاین پر شده است؛ قدیمی‌ترین موارد کنار گذاشته شدند.');
      } else {
        emitOutboxWarning(null);
      }
    } catch (err) {
      emitOutboxWarning('ذخیرهٔ آفلاین پیشرفت روی حافظهٔ دستگاه ممکن نشد.');
      throw err;
    }
  });
  chain = next.catch(() => undefined);
  return next;
}

/** POST that is retried later if there is no connection or a transient server error (429 / 5xx). */
export async function sendOrQueue(path: string, body: unknown): Promise<OutboxOutcome> {
  if (owner == null) return 'dropped';
  const mine = owner;
  try {
    await api(path, { body });
    return 'sent';
  } catch (e) {
    if (e instanceof ApiError && (isRetryableStatus(e.status) || e.status === 401)) {
      const job: Job = { id: `${Date.now()}-${Math.random().toString(36).slice(2)}`, path, body, at: Date.now(), owner: mine };
      try {
        await update((jobs) => [...jobs, job]);
        return 'queued';
      } catch {
        return 'failed';
      }
    }
    return 'dropped';
  }
}

let running: Promise<void> | null = null;
/** Sends this account's waiting jobs. Callers share one run, so awaiting it (e.g. before signing out) really waits. */
export function flushOutbox(): Promise<void> {
  if (!running) running = flush().finally(() => (running = null));
  return running;
}

async function flush() {
  const me = owner;
  if (me == null) return;
  const now = Date.now();
  // Jobs saved by an older app version have no account: they belong to whoever is signed in first after the update.
  await update((jobs) => jobs.map((j) => (j.owner == null ? { ...j, owner: me, id: j.id ?? `${j.at}-${Math.random()}` } : j)));
  const jobs = (await readOutbox()).filter((j) => j.owner === me);
  const done = new Set<string>();
  for (const job of jobs) {
    if (now - job.at > MAX_AGE_MS) {
      done.add(job.id);
      continue;
    }
    try {
      await api(job.path, { body: job.body });
      done.add(job.id);
    } catch (e) {
      if (!(e instanceof ApiError)) break;
      // Transient (offline, 429, 5xx) or expired session (401): keep in outbox and stop flushing for now.
      // Permanent 4xx refusals (400, 403, 404, 409, ...) are dropped.
      if (isRetryableStatus(e.status) || e.status === 401) break;
      done.add(job.id);
    }
  }
  // Remove only what was handled; anything queued meanwhile stays.
  await update((all) => all.filter((j) => !done.has(j.id)));
}

const BANNER_SECONDS = 4;

export function NetworkProvider({ children }: { children: ReactNode }) {
  const [online, setState] = useState(true);
  const [banner, setBanner] = useState<'offline' | 'back' | null>(null);
  const [queueWarn, setQueueWarn] = useState<string | null>(null);
  const insets = useSafeAreaInsets();
  const wasOnline = useRef(true);

  useEffect(() => subscribeOutboxWarning(setQueueWarn), []);

  // When the connection drops: a banner for a few seconds, then only a small icon in the corner (reading in peace).
  // When it comes back: a short «back online» note.
  useEffect(() => {
    if (online === wasOnline.current) return;
    wasOnline.current = online;
    setBanner(online ? 'back' : 'offline');
    if (online) onReconnect?.();
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
    // In a browser the reachability check is a request to our own server every few seconds, per open tab: only
    // the tab in front checks, and not more than once a minute when all is well.
    if (Platform.OS === 'web' && typeof document !== 'undefined') {
      NetInfo.configure({
        reachabilityShouldRun: () => document.visibilityState === 'visible',
        reachabilityLongTimeout: 60 * 1000,
        reachabilityShortTimeout: 15 * 1000,
      });
    }
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
      {queueWarn && (
        <View style={[styles.banner, { paddingTop: insets.top + 6, backgroundColor: colors.redSoft }]}>
          <Icon name="circle-alert" size={16} color={colors.redDark} />
          <Text style={[styles.text, { color: colors.redDark }]}>{queueWarn}</Text>
        </View>
      )}
      {!queueWarn && banner && (
        <View style={[styles.banner, { paddingTop: insets.top + 6 }, banner === 'back' && { backgroundColor: colors.greenSoft }]} pointerEvents="none">
          <Icon name={banner === 'back' ? 'circle-check' : 'cloud-off'} size={16} color={banner === 'back' ? colors.greenDark : colors.ink} />
          <Text style={[styles.text, banner === 'back' && { color: colors.greenDark }]}>
            {banner === 'back' ? 'دوباره آنلاین شدید؛ کارهایتان ارسال شد.' : 'آفلاین هستید؛ کارهایتان ذخیره می‌شود.'}
          </Text>
        </View>
      )}
      {!online && !banner && (
        <View style={[styles.dotWrap, { top: insets.top + 8 }]}>
          <HelpTip
            size={26}
            title="آفلاین هستید"
            text="ارتباط با سرور برقرار نیست. پیشرفت مطالعه و مرور فلش‌کارت‌ها روی دستگاه شما ذخیره می‌شود و به محض وصل شدن اینترنت، خودکار ارسال خواهد شد."
          >
            <View style={styles.dot}>
              <Icon name="cloud-off" size={14} color={colors.ink} />
            </View>
          </HelpTip>
        </View>
      )}
    </OnlineContext.Provider>
  );
}

const styles = StyleSheet.create({
  banner: { position: 'absolute', zIndex: 1000, elevation: 10, top: 0, left: 0, right: 0, paddingBottom: 8, paddingHorizontal: 16, backgroundColor: colors.lemon, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 8 },
  dotWrap: { position: 'absolute', zIndex: 1000, elevation: 10, left: 10 },
  dot: { width: 26, height: 26, borderRadius: 13, backgroundColor: colors.lemon, alignItems: 'center', justifyContent: 'center', opacity: 0.9 },
  text: { fontSize: 13, fontWeight: '700', color: colors.ink, textAlign: 'right', flexShrink: 1 },
});
