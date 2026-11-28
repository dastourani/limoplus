import { beforeEach, describe, expect, it, vi } from 'vitest';

const store = new Map<string, string>();
const reportMock = vi.fn(async (_input?: unknown) => 'evt_1');

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

vi.mock('../../lib/viewAs', () => ({
  viewAsLearner: () => false,
}));

vi.mock('../../config', () => ({
  APP_ABIS: '',
  APP_BUILD: 0,
  APP_CHANNEL: 'official',
  APP_PLATFORM: null,
  CLIENT_PLATFORM: 'web',
  WEB_COMMIT: 'deadbeef',
  getApiUrl: async () => 'https://limookhan.ir',
}));

vi.mock('../../lib/diagnostics', () => ({
  addBreadcrumb: vi.fn(),
  getInstallId: vi.fn(async () => 'inst_1'),
  newRequestId: vi.fn(() => 'req_test'),
  reportDiagnostic: (input: unknown) => reportMock(input),
  setDiagnosticsMeta: vi.fn(),
  setDiagnosticsOnline: vi.fn(),
  setDiagnosticsTransport: vi.fn(),
}));

import { _setRetryDelaysForTests, api, ApiError } from '../client';

function jsonResponse(status: number, body: Record<string, unknown> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'X-Request-Id': 'srv_req' },
  });
}

describe('api transient gateway retries', () => {
  beforeEach(() => {
    store.clear();
    reportMock.mockClear();
    _setRetryDelaysForTests([0, 0]);
  });

  it('retries transient 502/503 on GET and skips api_5xx when retry succeeds', async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(502))
      .mockResolvedValueOnce(jsonResponse(503))
      .mockResolvedValueOnce(jsonResponse(200, { id: 12, title: 'مشتق' }));
    vi.stubGlobal('fetch', fetchMock);

    const data = await api<{ id: number; title: string }>('nodes/12/');
    expect(data).toEqual({ id: 12, title: 'مشتق' });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(reportMock).not.toHaveBeenCalled();
  });

  it('reports api_5xx once and throws ApiError when GET 503 persists across retries', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => jsonResponse(503));
    vi.stubGlobal('fetch', fetchMock);

    await expect(api('nodes/12/')).rejects.toMatchObject({ status: 503 });
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(reportMock).toHaveBeenCalledTimes(1);
    expect(reportMock).toHaveBeenCalledWith(
      expect.objectContaining({
        code: 'api_5xx',
        route: '/api/v1/nodes/12/',
        context: { status_code: 503, method: 'GET' },
      }),
    );
  });

  it('never retries non-GET mutations or non-gateway 500/404 responses', async () => {
    const post502 = vi.fn().mockResolvedValueOnce(jsonResponse(502));
    vi.stubGlobal('fetch', post502);
    await expect(api('nodes/12/progress/', { body: { percent: 50 } })).rejects.toBeInstanceOf(ApiError);
    expect(post502).toHaveBeenCalledTimes(1);
    expect(reportMock).toHaveBeenCalledTimes(1);

    reportMock.mockClear();
    const get500 = vi.fn().mockResolvedValueOnce(jsonResponse(500));
    vi.stubGlobal('fetch', get500);
    await expect(api('nodes/12/')).rejects.toMatchObject({ status: 500 });
    expect(get500).toHaveBeenCalledTimes(1);
    expect(reportMock).toHaveBeenCalledTimes(1);

    reportMock.mockClear();
    const get404 = vi.fn().mockResolvedValueOnce(jsonResponse(404));
    vi.stubGlobal('fetch', get404);
    await expect(api('nodes/12/')).rejects.toMatchObject({ status: 404 });
    expect(get404).toHaveBeenCalledTimes(1);
    expect(reportMock).not.toHaveBeenCalled();
  });
});
