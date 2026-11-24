/**
 * «زمان مطالعه»: counts the seconds a signed-in learner spends on a section (reading, tests, cards, a review or an
 * exam) while the screen is open and the app is in front. Two minutes without a touch or scroll stops the count until
 * the next one. Exact seconds are sent about once a minute (queued when offline, like other progress); the server adds
 * them up and only what is shown is rounded.
 */
import { useFocusEffect } from 'expo-router';
import { useCallback } from 'react';
import AsyncStorage from '@react-native-async-storage/async-storage';
import { AppState } from 'react-native';

import { sendOrQueue } from './network';

export type StudyKind = 'read' | 'quiz' | 'cards' | 'exam' | 'review';

const IDLE_MS = 2 * 60 * 1000;
const TICK_MS = 5000;
const SEND_MS = 60 * 1000;

let lastActive = Date.now();
/** Any touch, scroll or page turn: the learner is here. */
export function markActive() {
  lastActive = Date.now();
}

const pending = new Map<string, { node_id: number; kind: StudyKind; day: string; seconds: number }>();

function today(): string {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

function add(nodeId: number, kind: StudyKind, seconds: number) {
  if (owner == null) return;
  const day = today();
  const key = `${nodeId}|${kind}|${day}`;
  const row = pending.get(key) ?? { node_id: nodeId, kind, day, seconds: 0 };
  row.seconds += seconds;
  pending.set(key, row);
}

// What is counted but not sent yet is also kept on the phone, so closing the app suddenly loses at most a few seconds.
// It is kept per account: time counted by one account is never sent by another (a session that expired, then someone
// else signing in on the same phone). The account's own time waits until it signs in again.
type Entry = { node_id: number; kind: StudyKind; day: string; seconds: number };
type InflightBatch = { id: string; entries: Entry[] };
let owner: number | null = null;
let restored = false;
const keyOf = (id: number) => `limo.studytime.pending.${id}`;
const inflightKeyOf = (id: number) => `limo.studytime.inflight.${id}`;
// Version 25 kept it without an account: it cannot be told whose it was, so it is dropped.
AsyncStorage.removeItem('limo.studytime.pending').catch(() => undefined);

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
  if (!restored || owner == null) return; // not before what an earlier run kept has been read back
  AsyncStorage.setItem(keyOf(owner), JSON.stringify([...pending.values()])).catch(() => undefined);
}
async function restore(id: number) {
  try {
    const rawInflight = await AsyncStorage.getItem(inflightKeyOf(id));
    if (owner !== id) return;
    const inflight = rawInflight ? (JSON.parse(rawInflight) as InflightBatch[]) : [];
    for (const batch of inflight) {
      if (owner !== id) return;
      await sendOrQueue('me/time/', batch);
      await updateInflight(id, (all) => all.filter((b) => b.id !== batch.id));
    }
  } catch {
    // nothing inflight
  }
  try {
    const saved = JSON.parse((await AsyncStorage.getItem(keyOf(id))) ?? '[]') as Entry[];
    if (owner !== id) return; // the account changed meanwhile
    for (const e of saved) {
      const key = `${e.node_id}|${e.kind}|${e.day}`;
      const row = pending.get(key) ?? { ...e, seconds: 0 };
      row.seconds += e.seconds;
      pending.set(key, row);
    }
  } catch {
    // nothing kept
  }
  if (owner !== id) return;
  restored = true;
  await flushStudyTime();
}

/** Who is signed in (null: nobody). Called by the auth state together with the outbox's owner. */
export function setStudyOwner(id: number | null) {
  if (id === owner) return;
  // Time the leaving account counted stays on the phone under its own name.
  if (owner != null && restored && pending.size) {
    AsyncStorage.setItem(keyOf(owner), JSON.stringify([...pending.values()])).catch(() => undefined);
  }
  pending.clear();
  restored = false;
  owner = id;
  if (id != null) restore(id);
}

/** Records study seconds locally (exposed for tests and timer ticks). */
export function recordStudySeconds(nodeId: number, kind: StudyKind, seconds: number) {
  add(nodeId, kind, seconds);
  keep();
}

/** Sends what was counted, keeping sub-second remainders and persisting inflight batches until queued or sent. */
export async function flushStudyTime(): Promise<void> {
  const mine = owner;
  if (mine == null || !restored) return;
  const entries: Entry[] = [];
  for (const [key, entry] of [...pending.entries()]) {
    const whole = Math.floor(entry.seconds);
    if (whole >= 1) {
      entries.push({ ...entry, seconds: whole });
      const remainder = entry.seconds - whole;
      if (remainder > 0.001) {
        pending.set(key, { ...entry, seconds: remainder });
      } else {
        pending.delete(key);
      }
    }
  }
  if (!entries.length) {
    keep();
    return;
  }
  const id = `t${Date.now().toString(36)}${Math.random().toString(36).slice(2, 12)}`;
  const batch: InflightBatch = { id, entries };
  await updateInflight(mine, (all) => [...all, batch]);
  keep();
  await sendOrQueue('me/time/', batch).catch(() => undefined);
  await updateInflight(mine, (all) => all.filter((b) => b.id !== id));
}

/** On sign-out (after flushStudyTime): nothing of the leaving account stays on the phone. */
export function forgetStudyTime() {
  if (owner != null) {
    AsyncStorage.removeItem(keyOf(owner)).catch(() => undefined);
    AsyncStorage.removeItem(inflightKeyOf(owner)).catch(() => undefined);
  }
  pending.clear();
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
        flushStudyTime();
      };
    }, [nodeId, kind, enabled]),
  );
}
