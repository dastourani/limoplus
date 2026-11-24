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

import { flushStudyTime, forgetStudyTime, recordStudySeconds, setStudyOwner } from '../studyTime';

describe('studyTime persistence & sub-second retention', () => {
  beforeEach(() => {
    store.clear();
    sendOrQueueMock.mockReset().mockResolvedValue(undefined);
    setStudyOwner(null);
  });

  it('retains sub-second remainders across flushes without losing seconds', async () => {
    setStudyOwner(12);
    // Let initial restore finish
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

    setStudyOwner(19);
    await new Promise((r) => setTimeout(r, 10));

    expect(sendOrQueueMock).toHaveBeenCalledWith('me/time/', batch);
    expect(store.has('limo.studytime.inflight.19')).toBe(false);
    forgetStudyTime();
  });
});
