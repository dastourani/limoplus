import { beforeEach, describe, expect, it, vi } from 'vitest';

const store = new Map<string, string>();
const apiMock = vi.fn();
let failNextSetItem = false;

vi.mock('@react-native-async-storage/async-storage', () => ({
  default: {
    getItem: vi.fn(async (k: string) => store.get(k) ?? null),
    setItem: vi.fn(async (k: string, v: string) => {
      if (failNextSetItem) {
        failNextSetItem = false;
        throw new Error('disk full');
      }
      store.set(k, v);
    }),
    removeItem: vi.fn(async (k: string) => {
      store.delete(k);
    }),
  },
}));

vi.mock('@react-native-community/netinfo', () => ({
  default: { configure: vi.fn(), addEventListener: vi.fn(() => () => undefined) },
}));

vi.mock('react-native', () => ({
  Platform: { OS: 'web' },
  StyleSheet: { create: (x: unknown) => x },
  View: 'View',
}));

vi.mock('react-native-safe-area-context', () => ({
  useSafeAreaInsets: () => ({ top: 0, bottom: 0, left: 0, right: 0 }),
}));

vi.mock('../../components/HelpTip', () => ({ HelpTip: 'HelpTip' }));
vi.mock('../../components/Icon', () => ({ Icon: 'Icon' }));
vi.mock('../../components/Text', () => ({ Text: 'Text' }));
vi.mock('../../theme', () => ({ colors: {} }));

vi.mock('../../api/client', () => {
  class ApiError extends Error {
    constructor(
      public readonly status: number,
      public readonly code: string,
      message: string,
      public readonly data: Record<string, unknown> = {},
    ) {
      super(message);
    }
  }
  return {
    ApiError,
    api: (...args: unknown[]) => apiMock(...args),
    setOnline: vi.fn(),
  };
});

import { ApiError } from '../../api/client';
import { flushOutbox, isRetryableStatus, sendOrQueue, setOutboxOwner, subscribeOutboxWarning } from '../network';

describe('network outbox resilience', () => {
  beforeEach(() => {
    store.clear();
    apiMock.mockReset();
    failNextSetItem = false;
    setOutboxOwner(null);
  });

  it('classifies transient statuses as retryable', () => {
    expect(isRetryableStatus(0)).toBe(true);
    expect(isRetryableStatus(429)).toBe(true);
    expect(isRetryableStatus(500)).toBe(true);
    expect(isRetryableStatus(502)).toBe(true);
    expect(isRetryableStatus(503)).toBe(true);
    expect(isRetryableStatus(504)).toBe(true);
    expect(isRetryableStatus(400)).toBe(false);
    expect(isRetryableStatus(401)).toBe(false);
    expect(isRetryableStatus(403)).toBe(false);
    expect(isRetryableStatus(404)).toBe(false);
  });

  it('queues requests on 503 and 429 and flushes them once server recovers', async () => {
    setOutboxOwner(7);
    apiMock.mockRejectedValueOnce(new ApiError(503, 'unavailable', 'deploy'));
    await sendOrQueue('nodes/1/progress/', { percent: 50 });

    apiMock.mockRejectedValueOnce(new ApiError(429, 'rate_limited', 'slow down'));
    await sendOrQueue('nodes/1/progress/', { percent: 90 });

    const queued = JSON.parse(store.get('limo.outbox') ?? '[]');
    expect(queued).toHaveLength(2);

    // Still 503 during flush: must keep both jobs in outbox and stop flushing
    apiMock.mockRejectedValueOnce(new ApiError(503, 'unavailable', 'still deploying'));
    await flushOutbox();
    expect(JSON.parse(store.get('limo.outbox') ?? '[]')).toHaveLength(2);
    expect(apiMock).toHaveBeenCalledTimes(3);

    // Server recovers -> both jobs drain cleanly
    apiMock.mockResolvedValue({ ok: true });
    await flushOutbox();
    expect(JSON.parse(store.get('limo.outbox') ?? '[]')).toHaveLength(0);
    expect(apiMock).toHaveBeenCalledTimes(5);
  });

  it('drops permanent 4xx errors on flush without dropping later retryable jobs', async () => {
    setOutboxOwner(7);
    apiMock.mockRejectedValueOnce(new ApiError(0, 'offline', 'offline'));
    await sendOrQueue('nodes/1/progress/', { percent: 20 });

    apiMock.mockRejectedValueOnce(new ApiError(0, 'offline', 'offline'));
    await sendOrQueue('nodes/2/progress/', { percent: 40 });

    apiMock
      .mockRejectedValueOnce(new ApiError(400, 'invalid', 'bad payload'))
      .mockRejectedValueOnce(new ApiError(502, 'bad_gateway', 'gateway restarting'));

    await flushOutbox();
    const remaining = JSON.parse(store.get('limo.outbox') ?? '[]');
    expect(remaining).toHaveLength(1);
    expect(remaining[0].path).toBe('nodes/2/progress/');
  });

  it('reports failed (never silent queued) and warns UI if AsyncStorage.setItem fails', async () => {
    setOutboxOwner(7);
    await flushOutbox();
    const warnings: (string | null)[] = [];
    const unsub = subscribeOutboxWarning((m) => warnings.push(m));
    try {
      apiMock.mockRejectedValueOnce(new ApiError(503, 'unavailable', 'deploy'));
      failNextSetItem = true;
      const outcome = await sendOrQueue('me/time/', { entries: [{ node_id: 1, seconds: 10 }] });
      expect(outcome).toBe('failed');
      expect(warnings[warnings.length - 1]).toContain('ممکن نشد');

      // Subsequent successful queue clears the warning.
      apiMock.mockRejectedValueOnce(new ApiError(503, 'unavailable', 'deploy'));
      const okOutcome = await sendOrQueue('me/time/', { entries: [{ node_id: 1, seconds: 10 }] });
      expect(okOutcome).toBe('queued');
      expect(warnings[warnings.length - 1]).toBeNull();
    } finally {
      unsub();
    }
  });
});
