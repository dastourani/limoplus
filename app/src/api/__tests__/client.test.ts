import { beforeEach, describe, expect, it, vi } from 'vitest';

const store = new Map<string, string>();
const reportMock = vi.fn(async (_input?: unknown) => 'evt_1');
const getApiUrlMock = vi.fn(async () => 'https://limookhan.ir');

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
  getApiUrl: () => getApiUrlMock(),
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
import { endpoints } from '../endpoints';

function jsonResponse(status: number, body: Record<string, unknown> = {}) {
  return new Response(JSON.stringify(body), {
    status,
    headers: { 'Content-Type': 'application/json', 'X-Request-Id': 'srv_req' },
  });
}

describe('api transient gateway retries and shared deadline', () => {
  beforeEach(() => {
    store.clear();
    reportMock.mockClear();
    getApiUrlMock.mockReset();
    getApiUrlMock.mockResolvedValue('https://limookhan.ir');
    _setRetryDelaysForTests([0, 0]);
  });

  it('retries transient 502/503 on endpoints.node and endpoints.book and skips api_5xx when retry succeeds', async () => {
    const nodeFetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(502))
      .mockResolvedValueOnce(jsonResponse(503))
      .mockResolvedValueOnce(jsonResponse(200, { id: 12, title: 'مشتق' }));
    vi.stubGlobal('fetch', nodeFetch);

    const node = await endpoints.node(12);
    expect(node).toMatchObject({ id: 12, title: 'مشتق' });
    expect(nodeFetch).toHaveBeenCalledTimes(3);
    expect(reportMock).not.toHaveBeenCalled();

    const bookFetch = vi
      .fn()
      .mockResolvedValueOnce(jsonResponse(503))
      .mockResolvedValueOnce(jsonResponse(200, { slug: 'math-1', title: 'ریاضی ۱' }));
    vi.stubGlobal('fetch', bookFetch);

    const book = await endpoints.book('math-1');
    expect(book).toMatchObject({ slug: 'math-1', title: 'ریاضی ۱' });
    expect(bookFetch).toHaveBeenCalledTimes(2);
    expect(reportMock).not.toHaveBeenCalled();
  });

  it('never retries payment-check GET (orders/<id>/?check=1) or other non-opted-in GETs on 503', async () => {
    const orderFetch = vi.fn().mockResolvedValueOnce(jsonResponse(503));
    vi.stubGlobal('fetch', orderFetch);

    await expect(endpoints.order(5, true)).rejects.toMatchObject({ status: 503 });
    expect(orderFetch).toHaveBeenCalledTimes(1);
    expect(reportMock).toHaveBeenCalledTimes(1);

    reportMock.mockClear();
    const otherGetFetch = vi.fn().mockResolvedValueOnce(jsonResponse(502));
    vi.stubGlobal('fetch', otherGetFetch);

    await expect(api('shelves/')).rejects.toMatchObject({ status: 502 });
    expect(otherGetFetch).toHaveBeenCalledTimes(1);
    expect(reportMock).toHaveBeenCalledTimes(1);
  });

  it('reports api_5xx once and throws ApiError when endpoints.node 503 persists across retries', async () => {
    const fetchMock = vi.fn().mockImplementation(async () => jsonResponse(503));
    vi.stubGlobal('fetch', fetchMock);

    await expect(endpoints.node(12)).rejects.toMatchObject({ status: 503 });
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

  it('enforces a single shared deadline across retries so slow gateway errors reach offline fallback on time', async () => {
    _setRetryDelaysForTests([50, 50]);
    const slowFetch = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          setTimeout(() => resolve(jsonResponse(502)), 45);
        }),
    );
    vi.stubGlobal('fetch', slowFetch);

    const t0 = Date.now();
    await expect(api('nodes/12/', { timeoutMs: 70, retryOnGatewayError: true })).rejects.toMatchObject({ status: 502 });
    const elapsed = Date.now() - t0;

    // 45ms first attempt leaves ~25ms (< 50ms retry backoff), so it stops cleanly inside the single 70ms budget.
    expect(slowFetch).toHaveBeenCalledTimes(1);
    expect(elapsed).toBeLessThan(120);
    expect(reportMock).toHaveBeenCalledTimes(1);
  });

  it('converts getApiUrl failure into ApiError(0, network) so screens can fall back offline', async () => {
    getApiUrlMock.mockRejectedValueOnce(new Error('secure storage error'));
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);

    await expect(endpoints.book('math-1')).rejects.toMatchObject({ status: 0, code: 'network' });
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('never retries POST mutations or non-gateway 500/404 responses', async () => {
    const post502 = vi.fn().mockResolvedValueOnce(jsonResponse(502));
    vi.stubGlobal('fetch', post502);
    await expect(api('nodes/12/progress/', { body: { percent: 50 } })).rejects.toBeInstanceOf(ApiError);
    expect(post502).toHaveBeenCalledTimes(1);
    expect(reportMock).toHaveBeenCalledTimes(1);

    reportMock.mockClear();
    const get500 = vi.fn().mockResolvedValueOnce(jsonResponse(500));
    vi.stubGlobal('fetch', get500);
    await expect(endpoints.node(12)).rejects.toMatchObject({ status: 500 });
    expect(get500).toHaveBeenCalledTimes(1);
    expect(reportMock).toHaveBeenCalledTimes(1);

    reportMock.mockClear();
    const get404 = vi.fn().mockResolvedValueOnce(jsonResponse(404));
    vi.stubGlobal('fetch', get404);
    await expect(endpoints.node(12)).rejects.toMatchObject({ status: 404 });
    expect(get404).toHaveBeenCalledTimes(1);
    expect(reportMock).not.toHaveBeenCalled();
  });
});
