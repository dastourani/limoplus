/**
 * «زمان مطالعه»: counts the seconds a learner spends on a section (reading, tests, cards, a review or an exam) while
 * the screen is open and the app is in front. Two minutes without a touch or scroll stops the count until the next one.
 * Signed-in accounts send exact seconds about once a minute (queued when offline, like other progress); guests keep
 * their study time locally until they sign in, scoped to the phone number so another phone number never inherits it.
 */
import { useFocusEffect } from 'expo-router';
import { useCallback, useEffect, useState } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { AppState } from 'react-native';

import { sendOrQueue } from './network';

export type StudyKind = 'read' | 'quiz' | 'cards' | 'exam' | 'review';

const IDLE_MS = 2 * 60 * 1000;
const TICK_MS = 5000;
const SEND_MS = 60 * 1000;
const MAX_CHUNK = 15 * 60;

let lastActive = Date.now();
/** Any touch, scroll or page turn: the learner is here. */
export function markActive() {
  lastActive = Date.now();
}

type Entry = { node_id: number; kind: StudyKind; day: string; seconds: number };
type InflightBatch = { id: string; entries: Entry[] };

const pending = new Map<string, Entry>();
const guestPending = new Map<string, Entry>();
const inflightByBatch = new Map<string, Entry[]>();

let owner: number | null = null;
let ownerPhone: string | null = null;
let restored = false;
let guestHydrated = false;
let guestRestored = false;
let restorePromise: Promise<void> | null = null;
let flushPromise: Promise<void> | null = null;

const keyOf = (id: number) => `limo.studytime.pending.${id}`;
const inflightKeyOf = (id: number) => `limo.studytime.inflight.${id}`;
const GUEST_KEY = 'limo.studytime.guest';
const LAST_PHONE_KEY = 'limo.studytime.last_phone';

// Version 25 kept signed-in time without an account: it cannot be told whose it was, so it is dropped.
AsyncStorage.removeItem('limo.studytime.pending').catch(() => undefined);

const listeners = new Set<() => void>();
function emit() {
  listeners.forEach((fn) => fn());
}

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function mergeInto(target: Map<string, Entry>, entries: Entry[]) {
  for (const e of entries) {
    if (!e || typeof e.node_id !== 'number' || typeof e.seconds !== 'number' || e.seconds <= 0) continue;
    const key = `${e.node_id}|${e.kind}|${e.day}`;
    const row = target.get(key) ?? { ...e, seconds: 0 };
    row.seconds += e.seconds;
    target.set(key, row);
  }
}

function add(nodeId: number, kind: StudyKind, seconds: number) {
  if (!nodeId || seconds <= 0) return;
  const day = today();
  const key = `${nodeId}|${kind}|${day}`;
  const target = owner == null ? guestPending : pending;
  const row = target.get(key) ?? { node_id: nodeId, kind, day, seconds: 0 };
  row.seconds += seconds;
  target.set(key, row);
  emit();
}

let inflightChain: Promise<unknown> = Promise.resolve();
function updateInflight(accountId: number, change: (batches: InflightBatch[]) => InflightBatch[]): Promise<void> {
  const next = inflightChain.then(async () => {
    let cur: InflightBatch[] = [];
    try {
      cur = JSON.parse((await AsyncStorage.getItem(inflightKeyOf(accountId))) ?? '[]') as InflightBatch[];
    } catch {
      cur = [];
    }
    const updated = change(cur);
    if (updated.length) {
      await AsyncStorage.setItem(inflightKeyOf(accountId), JSON.stringify(updated)).catch(() => undefined);
    } else {
      await AsyncStorage.removeItem(inflightKeyOf(accountId)).catch(() => undefined);
    }
  });
  inflightChain = next.catch(() => undefined);
  return next;
}

function keep() {
  if (owner == null) {
    if (!guestRestored) return;
    if (guestPending.size) {
      AsyncStorage.setItem(GUEST_KEY, JSON.stringify([...guestPending.values()])).catch(() => undefined);
    } else {
      AsyncStorage.removeItem(GUEST_KEY).catch(() => undefined);
    }
    return;
  }
  if (!restored) return; // not before what an earlier run kept has been read back
  if (pending.size) {
    AsyncStorage.setItem(keyOf(owner), JSON.stringify([...pending.values()])).catch(() => undefined);
  } else {
    AsyncStorage.removeItem(keyOf(owner)).catch(() => undefined);
  }
}

async function restoreGuest() {
  try {
    const saved = JSON.parse((await AsyncStorage.getItem(GUEST_KEY)) ?? '[]') as Entry[];
    if (owner != null) return;
    if (!guestHydrated && Array.isArray(saved) && saved.length) {
      mergeInto(guestPending, saved);
    }
    guestHydrated = true;
  } catch {
    guestHydrated = true;
  }
  if (owner != null) return;
  guestRestored = true;
  keep();
  emit();
}

restoreGuest();

async function restore(id: number, phone: string | null) {
  try {
    const lastPhone = (await AsyncStorage.getItem(LAST_PHONE_KEY))?.trim() || null;
    const rawGuest = await AsyncStorage.getItem(GUEST_KEY);
    if (owner !== id) return;
    if ((!guestHydrated || guestPending.size === 0) && rawGuest) {
      try {
        const parsed = JSON.parse(rawGuest) as Entry[];
        if (Array.isArray(parsed) && parsed.length) mergeInto(guestPending, parsed);
      } catch {
        // ignore corrupt guest cache
      }
    }
    const canAdoptGuest = !lastPhone || (phone != null && lastPhone === phone);
    if (canAdoptGuest && guestPending.size > 0) {
      mergeInto(pending, [...guestPending.values()]);
    }
    guestPending.clear();
    guestHydrated = false;
    guestRestored = false;
    await AsyncStorage.removeItem(GUEST_KEY).catch(() => undefined);
    if (phone) {
      await AsyncStorage.setItem(LAST_PHONE_KEY, phone).catch(() => undefined);
    }
  } catch {
    // ignore guest migration failure
  }

  try {
    const rawInflight = await AsyncStorage.getItem(inflightKeyOf(id));
    if (owner !== id) return;
    const inflight = rawInflight ? (JSON.parse(rawInflight) as InflightBatch[]) : [];
    for (const batch of inflight) {
      if (owner !== id) return;
      inflightByBatch.set(batch.id, batch.entries);
      emit();
      await sendOrQueue('me/time/', batch);
      inflightByBatch.delete(batch.id);
      await updateInflight(id, (all) => all.filter((b) => b.id !== batch.id));
    }
  } catch {
    // nothing inflight
  }
  try {
    const saved = JSON.parse((await AsyncStorage.getItem(keyOf(id))) ?? '[]') as Entry[];
    if (owner !== id) return; // the account changed meanwhile
    mergeInto(pending, saved);
  } catch {
    // nothing kept
  }
  if (owner !== id) return;
  restored = true;
  emit();
  await runFlush();
}

/** Who is signed in (null: nobody / guest). Called by the auth state together with the outbox's owner. */
export function setStudyOwner(id: number | null, phone?: string | null) {
  const cleanPhone = id != null ? phone?.trim() || null : null;
  if (id === owner && cleanPhone === ownerPhone) return;
  // Time the leaving account counted stays on the phone under its own name.
  if (owner != null && restored && pending.size) {
    AsyncStorage.setItem(keyOf(owner), JSON.stringify([...pending.values()])).catch(() => undefined);
  }
  pending.clear();
  inflightByBatch.clear();
  restored = false;
  owner = id;
  ownerPhone = cleanPhone;
  if (id != null) {
    guestRestored = false;
    restorePromise = restore(id, cleanPhone).finally(() => {
      restorePromise = null;
    });
  } else {
    restorePromise = null;
    guestPending.clear();
    guestHydrated = false;
    guestRestored = false;
    void restoreGuest();
    emit();
  }
}

/** Records study seconds locally (exposed for tests and timer ticks). */
export function recordStudySeconds(nodeId: number, kind: StudyKind, seconds: number) {
  add(nodeId, kind, seconds);
  keep();
}

async function runFlush(): Promise<void> {
  const mine = owner;
  if (mine == null || !restored) return;
  const entries: Entry[] = [];
  for (const [key, entry] of [...pending.entries()]) {
    const whole = Math.floor(entry.seconds);
    if (whole >= 1) {
      let left = whole;
      while (left > 0 && entries.length < 200) {
        const chunk = Math.min(left, MAX_CHUNK);
        entries.push({ ...entry, seconds: chunk });
        left -= chunk;
      }
      const remainder = entry.seconds - whole + left;
      if (remainder > 0.001) {
        pending.set(key, { ...entry, seconds: remainder });
      } else {
        pending.delete(key);
      }
    }
  }
  if (!entries.length) {
    keep();
    emit();
    return;
  }
  const id = `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
  const batch: InflightBatch = { id, entries };
  inflightByBatch.set(id, entries);
  await updateInflight(mine, (all) => [...all, batch]);
  keep();
  emit();
  await sendOrQueue('me/time/', batch).catch(() => undefined);
  inflightByBatch.delete(id);
  await updateInflight(mine, (all) => all.filter((b) => b.id !== id));
  emit();
}

/** Sends what was counted, keeping sub-second remainders and persisting inflight batches until queued or sent. */
export async function flushStudyTime(): Promise<void> {
  if (restorePromise) await restorePromise.catch(() => undefined);
  if (owner == null || !restored) return;
  if (!flushPromise) {
    flushPromise = runFlush().finally(() => {
      flushPromise = null;
    });
  }
  await flushPromise;
}

/** On sign-out (after flushStudyTime): nothing of the leaving account (or old guest buffer) stays on the phone. */
export function forgetStudyTime() {
  if (owner != null) {
    AsyncStorage.removeItem(keyOf(owner)).catch(() => undefined);
    AsyncStorage.removeItem(inflightKeyOf(owner)).catch(() => undefined);
  }
  pending.clear();
  inflightByBatch.clear();
  guestPending.clear();
  guestHydrated = false;
  guestRestored = false;
  AsyncStorage.removeItem(GUEST_KEY).catch(() => undefined);
  emit();
}

/** Local (unsent or guest) study seconds per node id, so book and chapter badges include them right away. */
export function getLocalStudySecondsByNode(): Record<number, number> {
  const out: Record<number, number> = {};
  if (owner == null) {
    for (const entry of guestPending.values()) {
      out[entry.node_id] = (out[entry.node_id] ?? 0) + entry.seconds;
    }
  } else {
    for (const entry of pending.values()) {
      out[entry.node_id] = (out[entry.node_id] ?? 0) + entry.seconds;
    }
    for (const entries of inflightByBatch.values()) {
      for (const entry of entries) {
        out[entry.node_id] = (out[entry.node_id] ?? 0) + entry.seconds;
      }
    }
  }
  for (const k of Object.keys(out)) {
    const id = Number(k);
    out[id] = Math.floor(out[id]);
  }
  return out;
}

/** Subscribes a screen to local/guest study seconds changes (e.g. after guest hydration on page reload). */
export function useLocalStudySeconds(): Record<number, number> {
  const [byNode, setByNode] = useState<Record<number, number>>(() => getLocalStudySecondsByNode());
  useEffect(() => {
    const sync = () => setByNode(getLocalStudySecondsByNode());
    listeners.add(sync);
    sync();
    return () => {
      listeners.delete(sync);
    };
  }, []);
  return byNode;
}

/** The app is in front (on the web: the tab is visible). */
function here() {
  if (typeof document !== 'undefined' && document.visibilityState) return document.visibilityState === 'visible';
  return AppState.currentState === 'active';
}

let sender: ReturnType<typeof setInterval> | null = null;
function startSender() {
  if (sender) return;
  sender = setInterval(flushStudyTime, SEND_MS);
  // Web (desktop browsers and the iPhone PWA): mouse, keys and the wheel count as being here too, and closing the tab
  // sends what was counted.
  if (typeof document !== 'undefined' && typeof document.addEventListener === 'function') {
    for (const e of ['pointerdown', 'keydown', 'wheel', 'scroll']) document.addEventListener(e, markActive, { passive: true, capture: true });
    document.addEventListener('visibilitychange', () => (document.visibilityState === 'hidden' ? flushStudyTime() : markActive()));
    window.addEventListener('pagehide', flushStudyTime);
  }
  AppState.addEventListener('change', (s) => {
    if (s !== 'active') flushStudyTime();
    else markActive();
  });
}

/** Counts time on this screen while it is focused. nodeId: the section (or the chapter, for an exam); null = nothing. */
export function useStudyTimer(nodeId: number | null | undefined, kind: StudyKind, enabled = true) {
  useFocusEffect(
    useCallback(() => {
      if (!nodeId || !enabled) return;
      startSender();
      markActive();
      let last = Date.now();
      const tick = setInterval(() => {
        const now = Date.now();
        const step = Math.min(now - last, TICK_MS * 2);
        last = now;
        if (here() && now - lastActive < IDLE_MS) {
          add(nodeId, kind, step / 1000);
          keep();
        }
      }, TICK_MS);
      return () => {
        clearInterval(tick);
        const now = Date.now();
        if (here() && now - lastActive < IDLE_MS) add(nodeId, kind, Math.min(now - last, TICK_MS * 2) / 1000);
        keep();
        flushStudyTime();
      };
    }, [nodeId, kind, enabled]),
  );
}
