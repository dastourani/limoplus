import AsyncStorage from '@react-native-async-storage/async-storage';

const DIAG_OUTBOX_KEY = 'limo.diagOutbox';
const INSTALL_ID_KEY = 'limo.installId';
export const MAX_DIAG_QUEUE = 25;
const MAX_DIAG_AGE_MS = 30 * 24 * 3600 * 1000;
const MAX_BREADCRUMBS = 15;

export type DiagnosticKind = 'client_error' | 'offline' | 'network' | 'invariant';
export type DiagnosticSeverity = 'critical' | 'error' | 'warning';

export type DiagnosticBreadcrumb = {
  at: string;
  type: string;
  name: string;
  detail?: string;
};

export type DiagnosticEventPayload = {
  event_id: string;
  kind: DiagnosticKind;
  severity: DiagnosticSeverity;
  code: string;
  title: string;
  route?: string;
  operation?: string;
  expected?: string;
  observed?: string;
  request_id?: string;
  op_id?: string;
  install_id?: string;
  platform?: string;
  channel?: string;
  app_build?: string;
  web_commit?: string;
  is_offline?: boolean;
  breadcrumbs?: DiagnosticBreadcrumb[];
  context?: Record<string, string | number | boolean | undefined>;
  created_at_ms: number;
};

export type ReportDiagnosticInput = {
  event_id?: string;
  kind: DiagnosticKind;
  severity?: DiagnosticSeverity;
  code: string;
  title: string;
  route?: string;
  operation?: string;
  expected?: string;
  observed?: string;
  request_id?: string;
  op_id?: string;
  is_offline?: boolean;
  context?: Record<string, string | number | boolean | undefined>;
  deferFlush?: boolean;
};

export type DiagnosticsMeta = {
  platform: string;
  channel: string;
  appBuild: string;
  webCommit: string;
};

type TransportFn = (events: DiagnosticEventPayload[]) => Promise<void>;

let meta: DiagnosticsMeta = {
  platform: '',
  channel: process.env.EXPO_PUBLIC_APP_CHANNEL ?? '',
  appBuild: process.env.EXPO_PUBLIC_APP_BUILD ?? '',
  webCommit: process.env.EXPO_PUBLIC_WEB_COMMIT ?? '',
};
let transport: TransportFn | null = null;
let isOnlineFlag = true;
let installIdCache: string | null = null;
let installIdPromise: Promise<string> | null = null;
let currentRoute = '';
const breadcrumbs: DiagnosticBreadcrumb[] = [];
const recentDedupe = new Map<string, number>();

export function setDiagnosticsMeta(next: Partial<DiagnosticsMeta>) {
  meta = { ...meta, ...next };
}

export function setDiagnosticsTransport(fn: TransportFn | null) {
  transport = fn;
}

export function setDiagnosticsOnline(online: boolean) {
  isOnlineFlag = online;
}

export function setDiagnosticsRoute(route: string) {
  currentRoute = cleanString(route, 200);
}

function randomToken(len = 12): string {
  const bytes = new Uint8Array(len);
  const g = typeof globalThis !== 'undefined' ? (globalThis as { crypto?: { getRandomValues?: (a: Uint8Array) => void } }) : undefined;
  if (g?.crypto?.getRandomValues) {
    g.crypto.getRandomValues(bytes);
    return Array.from(bytes, (b) => (b % 36).toString(36)).join('');
  }
  let out = '';
  while (out.length < len) out += Math.random().toString(36).slice(2);
  return out.slice(0, len);
}

export function newEventId(): string {
  return `evt_${Date.now().toString(36)}_${randomToken(10)}`;
}

export function newRequestId(): string {
  return `req_${Date.now().toString(36)}_${randomToken(8)}`;
}

export function newOpId(): string {
  return `op_${Date.now().toString(36)}_${randomToken(8)}`;
}

const PERSIAN_ARABIC_RE =
  /[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+(?:[\s\u200c\u200d،؛؟!«»\-–—.\d]+[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF\uFB50-\uFDFF\uFE70-\uFEFF]+)*/g;

function cleanString(value: unknown, maxLen = 400): string {
  if (value == null) return '';
  return String(value)
    .replace(/(?:\+?98|0)9\d{9}/g, '[PHONE]')
    .replace(/[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/g, '[EMAIL]')
    .replace(/(bearer\s+)[A-Za-z0-9._\-]{8,}/gi, '$1[REDACTED]')
    .replace(/\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{6,}\b/g, '[REDACTED]')
    .replace(/([?&](?:sig|signature|token|code|exp|expires|password|key|q|query|search)=)[^&\s]+/gi, '$1[REDACTED]')
    .replace(/\?[^\s"'<>#]+/g, '?[REDACTED]')
    .trim()
    .slice(0, maxLen);
}

export function sanitizeErrorText(value: unknown, maxLen = 300): string {
  const base = cleanString(value, maxLen * 2);
  if (!base) return '';
  return base
    .replace(PERSIAN_ARABIC_RE, '[TEXT]')
    .replace(/(["'«])(?:\\.|(?!\1).)*\1/g, (m) => (m.length > 22 || /\s/.test(m) || m.includes('[TEXT]') ? '"[REDACTED]"' : m))
    .replace(/(?:\[TEXT\]\s*){2,}/g, '[TEXT] ')
    .trim()
    .slice(0, maxLen);
}

export function sanitizeStack(value: unknown, maxLen = 1400): string {
  if (!value) return '';
  const lines = String(value).split(/\r?\n/).slice(-12);
  const out: string[] = [];
  for (const line of lines) {
    const trimmed = line.replace(/\s+$/, '');
    if (!trimmed) continue;
    if (/^\s*(?:at\s+|@\S+|File\s+")/.test(trimmed)) {
      out.push(cleanString(trimmed, 240));
    } else {
      out.push(sanitizeErrorText(trimmed, 240));
    }
  }
  return out.join('\n').slice(0, maxLen);
}

const SAFE_CLIENT_TITLE_PREFIXES = [
  'خطای اجرای جاوااسکریپت:',
  'خطای مرورگر:',
  'خطای نمایش صفحه:',
  'وعدهٔ مدیریت‌نشده',
];

function sanitizeClientTitle(title: string, fallback: string): string {
  const base = cleanString(title, 240);
  if (!base) return fallback;
  for (const prefix of SAFE_CLIENT_TITLE_PREFIXES) {
    if (base.startsWith(prefix)) {
      const rest = sanitizeErrorText(base.slice(prefix.length), 120);
      return `${prefix} ${rest}`.trim().slice(0, 240);
    }
  }
  return sanitizeErrorText(base, 240) || fallback;
}

function cleanContext(raw?: Record<string, string | number | boolean | undefined>): Record<string, string | number | boolean> | undefined {
  if (!raw) return undefined;
  const out: Record<string, string | number | boolean> = {};
  for (const [k, v] of Object.entries(raw)) {
    if (v === undefined) continue;
    if (typeof v === 'boolean' || typeof v === 'number') out[k] = v;
    else {
      const cleaned =
        k === 'stack' || k === 'component_stack'
          ? sanitizeStack(v, 1400)
          : k === 'error_message'
            ? sanitizeErrorText(v, 300)
            : cleanString(v, 300);
      if (cleaned) out[k] = cleaned;
    }
  }
  return Object.keys(out).length ? out : undefined;
}

export function getCachedInstallId(): string {
  return installIdCache ?? '';
}

export async function getInstallId(): Promise<string> {
  if (installIdCache) return installIdCache;
  if (!installIdPromise) {
    installIdPromise = (async () => {
      try {
        const stored = await AsyncStorage.getItem(INSTALL_ID_KEY);
        if (stored && stored.trim()) {
          installIdCache = stored.trim().slice(0, 64);
          return installIdCache;
        }
        const fresh = `inst_${Date.now().toString(36)}_${randomToken(12)}`;
        installIdCache = fresh;
        await AsyncStorage.setItem(INSTALL_ID_KEY, fresh).catch(() => undefined);
        return fresh;
      } catch {
        installIdCache = `inst_${Date.now().toString(36)}_${randomToken(12)}`;
        return installIdCache;
      } finally {
        installIdPromise = null;
      }
    })();
  }
  return installIdPromise;
}

export function addBreadcrumb(type: string, name: string, detail?: string) {
  breadcrumbs.push({
    at: new Date().toISOString(),
    type: cleanString(type, 30),
    name: cleanString(name, 80),
    ...(detail ? { detail: sanitizeErrorText(detail, 120) } : {}),
  });
  if (breadcrumbs.length > MAX_BREADCRUMBS) {
    breadcrumbs.splice(0, breadcrumbs.length - MAX_BREADCRUMBS);
  }
}

export function clearBreadcrumbs() {
  breadcrumbs.length = 0;
}

async function readQueue(): Promise<DiagnosticEventPayload[]> {
  try {
    const raw = await AsyncStorage.getItem(DIAG_OUTBOX_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw);
    return Array.isArray(parsed) ? (parsed as DiagnosticEventPayload[]) : [];
  } catch {
    return [];
  }
}

let queueChain: Promise<unknown> = Promise.resolve();
function updateQueue(change: (items: DiagnosticEventPayload[]) => DiagnosticEventPayload[]): Promise<void> {
  const next = queueChain.then(async () => {
    const now = Date.now();
    const items = await readQueue();
    const updated = change(items).filter((item) => now - (item.created_at_ms || now) <= MAX_DIAG_AGE_MS);
    const trimmed = updated.length > MAX_DIAG_QUEUE ? updated.slice(-MAX_DIAG_QUEUE) : updated;
    await AsyncStorage.setItem(DIAG_OUTBOX_KEY, JSON.stringify(trimmed)).catch(() => undefined);
  });
  queueChain = next.catch(() => undefined);
  return next;
}

export async function pendingDiagnosticCount(): Promise<number> {
  return (await readQueue()).length;
}

export async function reportDiagnostic(input: ReportDiagnosticInput): Promise<string | null> {
  try {
    const installId = await getInstallId();
    const eventId = cleanString(input.event_id || newEventId(), 64) || newEventId();
    const isClientError = input.kind === 'client_error';
    const cleanCode = cleanString(input.code, 80) || 'client_error';
    const payload: DiagnosticEventPayload = {
      event_id: eventId,
      kind: input.kind,
      severity: input.severity ?? 'error',
      code: cleanCode,
      title: isClientError ? sanitizeClientTitle(input.title, cleanCode) : cleanString(input.title, 240) || cleanCode,
      route: cleanString(input.route ?? currentRoute, 200),
      operation: cleanString(input.operation, 80),
      expected: cleanString(input.expected, 1000),
      observed: isClientError ? sanitizeErrorText(input.observed, 1000) : cleanString(input.observed, 1000),
      request_id: cleanString(input.request_id, 64),
      op_id: cleanString(input.op_id, 64),
      install_id: installId,
      platform: meta.platform || undefined,
      channel: meta.channel || undefined,
      app_build: meta.appBuild || meta.webCommit || undefined,
      web_commit: meta.webCommit || undefined,
      is_offline: input.is_offline ?? !isOnlineFlag,
      breadcrumbs: breadcrumbs.length ? [...breadcrumbs] : undefined,
      context: cleanContext(input.context),
      created_at_ms: Date.now(),
    };

    await updateQueue((items) => {
      if (items.some((x) => x.event_id === payload.event_id)) return items;
      return [...items, payload];
    });

    if (!input.deferFlush && isOnlineFlag && transport) {
      void flushDiagnostics();
    }
    return eventId;
  } catch {
    return null;
  }
}

let flushPromise: Promise<void> | null = null;
export function flushDiagnostics(): Promise<void> {
  if (!flushPromise) {
    flushPromise = doFlush().finally(() => {
      flushPromise = null;
    });
  }
  return flushPromise;
}

async function doFlush(): Promise<void> {
  if (!transport || !isOnlineFlag) return;
  const items = await readQueue();
  if (!items.length) return;
  const batch = items.slice(0, 20);
  const sentIds = new Set(batch.map((i) => i.event_id));
  try {
    await transport(batch);
    await updateQueue((all) => all.filter((item) => !sentIds.has(item.event_id)));
  } catch (e) {
    const status = typeof (e as { status?: unknown })?.status === 'number' ? (e as { status: number }).status : 0;
    // Permanent client payload rejections (400/403/404) are dropped so bad items never wedge the queue;
    // transient network/rate-limit/server errors (0, 429, 5xx) remain queued with their fixed event_ids.
    if (status >= 400 && status < 500 && status !== 429 && status !== 401 && status !== 408) {
      await updateQueue((all) => all.filter((item) => !sentIds.has(item.event_id)));
    }
  }
}

let handlersInstalled = false;
function shouldSkipDuplicate(key: string): boolean {
  const now = Date.now();
  const prev = recentDedupe.get(key);
  if (prev && now - prev < 5000) return true;
  recentDedupe.set(key, now);
  if (recentDedupe.size > 40) {
    for (const [k, ts] of recentDedupe) {
      if (now - ts >= 5000) recentDedupe.delete(k);
    }
  }
  return false;
}

export function installGlobalErrorHandlers() {
  if (handlersInstalled) return;
  handlersInstalled = true;

  const g = globalThis as {
    ErrorUtils?: {
      getGlobalHandler?: () => ((err: unknown, isFatal?: boolean) => void) | undefined;
      setGlobalHandler?: (fn: (err: unknown, isFatal?: boolean) => void) => void;
    };
    window?: {
      addEventListener?: (name: string, fn: (ev: any) => void) => void;
    };
  };

  if (g.ErrorUtils?.setGlobalHandler) {
    const prev = g.ErrorUtils.getGlobalHandler?.();
    g.ErrorUtils.setGlobalHandler((err: unknown, isFatal?: boolean) => {
      const e = err instanceof Error ? err : new Error(String(err ?? 'Unknown JS error'));
      const safeName = sanitizeErrorText(e.name, 60) || 'Error';
      const safeMsg = sanitizeErrorText(e.message, 240);
      const key = `rn:${safeName}:${safeMsg.slice(0, 80)}`;
      if (!shouldSkipDuplicate(key)) {
        void reportDiagnostic({
          kind: 'client_error',
          severity: isFatal ? 'critical' : 'error',
          code: 'js_error',
          title: `خطای اجرای جاوااسکریپت: ${safeName}`,
          expected: 'اجرای بدون استثنای مهارنشده در اپ.',
          observed: safeMsg ? `${safeName}: ${safeMsg}` : safeName,
          context: { error_name: safeName, error_message: safeMsg, stack: sanitizeStack(e.stack) },
          deferFlush: true,
        });
      }
      prev?.(err, isFatal);
    });
  }

  if (g.window?.addEventListener) {
    g.window.addEventListener('error', (ev: any) => {
      const err = ev?.error instanceof Error ? ev.error : null;
      const safeName = sanitizeErrorText(err?.name || 'Error', 60) || 'Error';
      const safeMsg = sanitizeErrorText(err?.message || String(ev?.message || 'Script error'), 240);
      const key = `web:${safeMsg.slice(0, 80)}`;
      if (shouldSkipDuplicate(key)) return;
      void reportDiagnostic({
        kind: 'client_error',
        severity: 'error',
        code: 'js_error',
        title: `خطای مرورگر: ${safeName}`,
        expected: 'اجرای بدون خطای رندر یا اسکریپت در وب‌اپ.',
        observed: safeMsg ? `${safeName}: ${safeMsg}` : safeName,
        context: {
          error_name: safeName,
          error_message: safeMsg,
          stack: sanitizeStack(err?.stack),
        },
      });
    });

    g.window.addEventListener('unhandledrejection', (ev: any) => {
      const reason = ev?.reason;
      const err = reason instanceof Error ? reason : null;
      const safeName = sanitizeErrorText(err?.name || 'PromiseRejection', 60) || 'PromiseRejection';
      const safeMsg = sanitizeErrorText(err?.message || String(reason ?? 'Unhandled promise rejection'), 240);
      const key = `rej:${safeMsg.slice(0, 80)}`;
      if (shouldSkipDuplicate(key)) return;
      void reportDiagnostic({
        kind: 'client_error',
        severity: 'error',
        code: 'unhandled_rejection',
        title: 'وعدهٔ مدیریت‌نشده (Unhandled Rejection)',
        expected: 'همهٔ عملیات ناهم‌زمان خطاها را مدیریت کنند.',
        observed: safeMsg ? `${safeName}: ${safeMsg}` : safeName,
        context: {
          error_name: safeName,
          error_message: safeMsg,
          stack: sanitizeStack(err?.stack),
        },
      });
    });
  }
}

export function _resetDiagnosticsForTests() {
  breadcrumbs.length = 0;
  recentDedupe.clear();
  installIdCache = null;
  installIdPromise = null;
  flushPromise = null;
  transport = null;
  isOnlineFlag = true;
  currentRoute = '';
  handlersInstalled = false;
}
