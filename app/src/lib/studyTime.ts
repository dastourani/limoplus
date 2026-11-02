/**
 * «زمان مطالعه»: counts the seconds a signed-in learner spends on a section (reading, tests, cards, a review or an
 * exam) while the screen is open and the app is in front. Two minutes without a touch or scroll stops the count until
 * the next one. Exact seconds are sent about once a minute (queued when offline, like other progress); the server adds
 * them up and only what is shown is rounded.
 */
import { useFocusEffect } from 'expo-router';
import { useCallback } from 'react';
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
  const day = today();
  const key = `${nodeId}|${kind}|${day}`;
  const row = pending.get(key) ?? { node_id: nodeId, kind, day, seconds: 0 };
  row.seconds += seconds;
  pending.set(key, row);
}

/** Sends what was counted (kept exactly; a failed send is queued and retried by the outbox). */
export function flushStudyTime() {
  const entries = [...pending.values()].filter((e) => e.seconds >= 1).map((e) => ({ ...e, seconds: Math.round(e.seconds) }));
  pending.clear();
  if (entries.length) sendOrQueue('me/time/', { entries }).catch(() => undefined);
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
        if (here() && now - lastActive < IDLE_MS) add(nodeId, kind, step / 1000);
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
