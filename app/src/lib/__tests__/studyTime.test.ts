import { beforeEach, describe, expect, it, vi } from 'vitest';

const store = new Map<string, string>();
const sendOrQueueMock = vi.fn();

vi.mock('@react-native-async-storage/async-storage', () => ({
  default: {
    getItem: vi.fn(async (k: string) => store.get(k) ?? null),
    setItem: vi.fn(async (k: string, v: string) => {
      store.set(k, v);
    }),
    removeItem: vi.fn(async (k: string) => {
      store.delete(k);
    }),
  },
}));

vi.mock('expo-router', () => ({
  useFocusEffect: vi.fn(),
}));

vi.mock('react-native', () => ({
  AppState: { currentState: 'active', addEventListener: vi.fn() },
}));

vi.mock('../network', () => ({
  sendOrQueue: (...args: unknown[]) => sendOrQueueMock(...args),
}));

import {
  flushStudyTime,
  forgetStudyTime,
  getLocalStudySecondsByNode,
  recordStudySeconds,
  setStudyOwner,
} from '../studyTime';

describe('studyTime persistence, guest scoping & sub-second retention', () => {
  beforeEach(async () => {
    store.clear();
    sendOrQueueMock.mockReset().mockResolvedValue(undefined);
    setStudyOwner(null);
    forgetStudyTime();
    await new Promise((r) => setTimeout(r, 0));
  });

  it('retains sub-second remainders across flushes without losing seconds', async () => {
    setStudyOwner(12, '09120000012');
    await new Promise((r) => setTimeout(r, 0));

    recordStudySeconds(5, 'read', 1.4);
    await flushStudyTime();
    expect(sendOrQueueMock).toHaveBeenCalledTimes(1);
    expect(sendOrQueueMock.mock.calls[0][0]).toBe('me/time/');
    expect(sendOrQueueMock.mock.calls[0][1].entries[0].seconds).toBe(1);

    // Remaining 0.4 + another 0.7 -> 1.1 -> sends 1 more second
    recordStudySeconds(5, 'read', 0.7);
    await flushStudyTime();
    expect(sendOrQueueMock).toHaveBeenCalledTimes(2);
    expect(sendOrQueueMock.mock.calls[1][1].entries[0].seconds).toBe(1);
    forgetStudyTime();
  });

  it('re-sends leftover inflight batch with the exact same id after restart', async () => {
    const batch = { id: 't_crash_123', entries: [{ node_id: 9, kind: 'quiz', day: '2026-11-24', seconds: 42 }] };
    store.set('limo.studytime.inflight.19', JSON.stringify([batch]));

    setStudyOwner(19, '09120000019');
    await new Promise((r) => setTimeout(r, 10));

    expect(sendOrQueueMock).toHaveBeenCalledWith('me/time/', batch);
    expect(store.has('limo.studytime.inflight.19')).toBe(false);
    forgetStudyTime();
  });

  it('records guest study time locally and transfers it on first phone sign-in (splitting >900s chunks)', async () => {
    recordStudySeconds(101, 'read', 1200);
    recordStudySeconds(102, 'quiz', 75);

    expect(getLocalStudySecondsByNode()).toEqual({ 101: 1200, 102: 75 });
    expect(sendOrQueueMock).not.toHaveBeenCalled();

    setStudyOwner(21, '09120000021');
    await flushStudyTime();

    expect(sendOrQueueMock).toHaveBeenCalledTimes(1);
    const sentEntries = sendOrQueueMock.mock.calls[0][1].entries as { node_id: number; seconds: number }[];
    const total101 = sentEntries.filter((e) => e.node_id === 101).reduce((s, e) => s + e.seconds, 0);
    const total102 = sentEntries.filter((e) => e.node_id === 102).reduce((s, e) => s + e.seconds, 0);
    expect(total101).toBe(1200);
    expect(total102).toBe(75);
    expect(sentEntries.every((e) => e.seconds <= 900)).toBe(true);
    expect(store.get('limo.studytime.last_phone')).toBe('09120000021');
    expect(store.has('limo.studytime.guest')).toBe(false);
    forgetStudyTime();
  });

  it('adopts post-sign-out guest time only for the same phone number and drops it for a different phone', async () => {
    setStudyOwner(21, '09120000021');
    await flushStudyTime();
    forgetStudyTime();
    setStudyOwner(null);
    await new Promise((r) => setTimeout(r, 0));

    // Guest reads while logged out, then the same phone signs back in -> transferred
    recordStudySeconds(201, 'read', 90);
    expect(getLocalStudySecondsByNode()).toEqual({ 201: 90 });

    setStudyOwner(21, '09120000021');
    await flushStudyTime();
    expect(sendOrQueueMock).toHaveBeenCalledTimes(1);
    expect(sendOrQueueMock.mock.calls[0][1].entries[0]).toMatchObject({ node_id: 201, seconds: 90 });

    // Sign out again, read as guest, then a DIFFERENT phone signs in -> discarded
    sendOrQueueMock.mockReset().mockResolvedValue(undefined);
    forgetStudyTime();
    setStudyOwner(null);
    await new Promise((r) => setTimeout(r, 0));

    recordStudySeconds(202, 'read', 140);
    expect(getLocalStudySecondsByNode()).toEqual({ 202: 140 });

    setStudyOwner(99, '09129999999');
    await flushStudyTime();
    expect(sendOrQueueMock).not.toHaveBeenCalled();
    expect(store.get('limo.studytime.last_phone')).toBe('09129999999');
    expect(getLocalStudySecondsByNode()).toEqual({});
    forgetStudyTime();
  });
});
