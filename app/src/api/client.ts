import { viewAsLearner } from '../lib/viewAs';
import { APP_BUILD, APP_PLATFORM, getApiUrl } from '../config';

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

export async function api<T>(path: string, options: { method?: string; body?: unknown; baseUrl?: string; timeoutMs?: number } = {}): Promise<T> {
  const headers: Record<string, string> = { Accept: 'application/json' };
  if (options.body !== undefined) headers['Content-Type'] = 'application/json';
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  if (authToken && viewAsLearner()) headers['X-View-As'] = 'learner';
  if (APP_PLATFORM) {
    headers['X-App-Platform'] = APP_PLATFORM;
    headers['X-App-Build'] = String(APP_BUILD);
  }

  let response: Response;
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeoutMs ?? TIMEOUT_MS);
  try {
    const base = options.baseUrl ?? (await getApiUrl());
    response = await fetch(`${base}/api/v1/${path.replace(/^\//, '')}`, {
      method: options.method ?? (options.body === undefined ? 'GET' : 'POST'),
      headers,
      body: options.body === undefined ? undefined : JSON.stringify(options.body),
      signal: controller.signal,
    });
  } catch {
    clearTimeout(timer);
    throw new ApiError(
      0,
      'network',
      online ? 'سرور در دسترس نیست. کمی بعد دوباره تلاش کنید.' : 'اینترنت قطع است. اتصال را بررسی کنید و دوباره تلاش کنید.',
    );
  }

  const data = (await response.json().catch(() => ({}))) as Record<string, unknown>;
  clearTimeout(timer);
  if (!response.ok) {
    if (response.status === 401) onUnauthorized?.();
    if (response.status === 426) onUpdateRequired?.(data);
    throw new ApiError(
      response.status,
      typeof data.code === 'string' ? data.code : 'error',
      typeof data.message === 'string' ? data.message : statusMessage(response.status),
      data,
    );
  }
  return data as T;
}
