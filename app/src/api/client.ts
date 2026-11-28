import { viewAsLearner } from '../lib/viewAs';
import {
  addBreadcrumb,
  getInstallId,
  newRequestId,
  reportDiagnostic,
  setDiagnosticsMeta,
  setDiagnosticsOnline,
  setDiagnosticsTransport,
} from '../lib/diagnostics';
import { APP_ABIS, APP_BUILD, APP_CHANNEL, APP_PLATFORM, CLIENT_PLATFORM, WEB_COMMIT, getApiUrl } from '../config';

setDiagnosticsMeta({
  platform: CLIENT_PLATFORM,
  channel: APP_CHANNEL,
  appBuild: APP_BUILD ? String(APP_BUILD) : '',
  webCommit: WEB_COMMIT,
});

/** Error returned by the server, with its machine code and a Persian message for the user. */
export class ApiError extends Error {
  constructor(
    public readonly status: number,
    public readonly code: string,
    message: string,
    public readonly data: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

let authToken: string | null = null;
let online = true;

/** Set by the network watcher, so a failed request can say "no internet" rather than "server unreachable". */
export function setOnline(value: boolean) {
  online = value;
  setDiagnosticsOnline(value);
}
let onUnauthorized: (() => void) | null = null;
let onUpdateRequired: ((data: Record<string, unknown>) => void) | null = null;

/** Called when the server refuses this (too old) build; the app then shows its update screen. */
export function setUpdateRequiredHandler(handler: ((data: Record<string, unknown>) => void) | null) {
  onUpdateRequired = handler;
}

export function setAuthToken(token: string | null) {
  authToken = token;
}

/** Called when the server says the session is no longer valid (sends the user to sign in). */
export function setUnauthorizedHandler(handler: (() => void) | null) {
  onUnauthorized = handler;
}

/** When the server's own Persian message did not arrive (a proxy in between answered with its own error page),
 *  at least the status says what kind of problem it was. */
export function statusMessage(status: number): string {
  if (status === 400) return 'درخواست پذیرفته نشد؛ اگر کد وارد می‌کنید، شاید اشتباه یا منقضی باشد. دوباره تلاش کنید.';
  if (status === 401) return 'نشست منقضی شده است. دوباره وارد شوید.';
  if (status === 403) return 'اجازه‌ی این کار را ندارید.';
  if (status === 404) return 'پیدا نشد.';
  if (status === 409) return 'با این حساب روی دو دستگاه دیگر وارد شده‌اید. از یکی از آن‌ها خارج شوید و دوباره امتحان کنید.';
  if (status === 429) return 'تلاش‌ها زیاد شد. کمی بعد دوباره امتحان کنید.';
  if (status >= 500) return 'سرور موقتاً مشکل دارد. کمی بعد دوباره تلاش کنید.';
  return 'خطایی رخ داد. دوباره تلاش کنید.';
}

/** No request waits longer than this; an unreachable server would otherwise hang for minutes on Android. */
const TIMEOUT_MS = 10_000;
const TRANSIENT_GATEWAY_STATUSES = new Set([502, 503, 504]);
let retryDelaysMs = [350, 850];

export function _setRetryDelaysForTests(delays: number[]) {
  retryDelaysMs = delays;
}

export async function api<T>(
  path: string,
  options: { method?: string; body?: unknown; baseUrl?: string; timeoutMs?: number; opId?: string; skipDiagnostics?: boolean } = {},
): Promise<T> {
  const cleanPath = path.replace(/^\//, '');
  const method = (options.method ?? (options.body === undefined ? 'GET' : 'POST')).toUpperCase();
  const reqId = newRequestId();
  const isDiag = Boolean(options.skipDiagnostics) || cleanPath.startsWith('diagnostics/');

  const headers: Record<string, string> = { Accept: 'application/json', 'X-Request-Id': reqId };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  if (authToken && viewAsLearner()) headers['X-View-As'] = 'learner';
  headers['X-App-Platform'] = CLIENT_PLATFORM;
  headers['X-App-Channel'] = APP_CHANNEL;
  if (APP_PLATFORM) {
    headers['X-App-Build'] = String(APP_BUILD);
    if (APP_ABIS) headers['X-App-Abi'] = APP_ABIS;
  } else if (WEB_COMMIT) {
    headers['X-App-Web-Commit'] = WEB_COMMIT;
  }
  if (options.opId) headers['X-App-Op-Id'] = options.opId;
  const installId = await getInstallId().catch(() => '');
  if (installId) headers['X-App-Install-Id'] = installId;

  const canRetryGateway = method === 'GET' && !isDiag;
  const maxAttempts = canRetryGateway ? 1 + retryDelaysMs.length : 1;
  const base = options.baseUrl ?? (await getApiUrl());

  let response!: Response;
  let data: Record<string, unknown> = {};

  for (let attempt = 1; attempt <= maxAttempts; attempt += 1) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? TIMEOUT_MS);
    try {
      response = await fetch(`${base}/api/v1/${cleanPath}`, {
        method,
        headers,
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
        signal: controller.signal,
      });
    } catch {
      clearTimeout(timer);
      if (!isDiag) addBreadcrumb('api', `${method} /api/v1/${cleanPath}`, online ? 'network_error' : 'offline');
      throw new ApiError(
        0,
        'network',
        online ? 'سرور در دسترس نیست. کمی بعد دوباره تلاش کنید.' : 'اینترنت قطع است. اتصال را بررسی کنید و دوباره تلاش کنید.',
      );
    }

    data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
    clearTimeout(timer);
    if (canRetryGateway && TRANSIENT_GATEWAY_STATUSES.has(response.status) && attempt < maxAttempts) {
      const waitMs = retryDelaysMs[attempt - 1] ?? 0;
      if (waitMs > 0) await new Promise((resolve) => setTimeout(resolve, waitMs));
      continue;
    }
    break;
  }

  if (!isDiag) addBreadcrumb('api', `${method} /api/v1/${cleanPath}`, String(response.status));
  if (!response.ok) {
    if (response.status === 401) onUnauthorized?.();
    if (response.status === 426) onUpdateRequired?.(data);
    if (!isDiag && response.status >= 500) {
      void reportDiagnostic({
        kind: 'network',
        severity: 'error',
        code: 'api_5xx',
        title: `پاسخ خطای سرور (${response.status})`,
        route: `/api/v1/${cleanPath}`,
        operation: `${method} /api/v1/${cleanPath}`,
        request_id: response.headers.get('X-Request-Id') || reqId,
        op_id: options.opId,
        expected: 'درخواست API بدون خطای ۵۰۰ پاسخ داده شود.',
        observed: `سرور وضعیت ${response.status} برگرداند.`,
        context: { status_code: response.status, method },
      });
    }
    throw new ApiError(
      response.status,
      typeof data.code === 'string' ? data.code : 'error',
      typeof data.message === 'string' ? data.message : statusMessage(response.status),
      data,
    );
  }
  return data as T;
}

setDiagnosticsTransport(async (events) => {
  await api('diagnostics/events/', { body: { events }, skipDiagnostics: true, timeoutMs: 12_000 });
});
