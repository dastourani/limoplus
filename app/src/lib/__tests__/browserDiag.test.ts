import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';
import { describe, expect, it } from 'vitest';

const SCRIPT_PATH = path.resolve(
  __dirname,
  '../../../../backend/apps/diagnostics/static/diagnostics/browser-diag.js',
);

interface HarnessOptions {
  platform?: string;
  channel?: string;
  build?: string;
  sessionTag?: string;
  pathname?: string;
  onLine?: boolean;
  initialStorage?: Map<string, string>;
  fetchImpl?: (input: unknown, init?: RequestInit) => Promise<unknown>;
}

function loadBrowserDiag(opts: HarnessOptions = {}) {
  const storage = opts.initialStorage ?? new Map<string, string>();
  const listeners = new Map<string, Array<(ev: unknown) => void>>();
  const fetchCalls: Array<{ input: unknown; init?: RequestInit }> = [];

  const origFetch = async (input: unknown, init?: RequestInit) => {
    fetchCalls.push({ input, init });
    if (opts.fetchImpl) {
      return opts.fetchImpl(input, init);
    }
    return {
      ok: true,
      status: 200,
      headers: new Headers({ 'X-Request-Id': 'srv_req_1' }),
    };
  };

  const scriptAttrs: Record<string, string> = {
    'data-platform': opts.platform ?? 'panel',
    'data-channel': opts.channel ?? 'teacher',
    'data-build': opts.build ?? '1732500',
    'data-session-tag': opts.sessionTag ?? '',
  };

  const navigatorObj = { onLine: opts.onLine ?? true };
  const locationObj = {
    origin: 'https://panel.example.com',
    href: `https://panel.example.com${opts.pathname ?? '/admin/catalog/book/5/chapters/'}`,
    pathname: opts.pathname ?? '/admin/catalog/book/5/chapters/',
  };

  const win: Record<string, unknown> = {
    Error,
    URL,
    Headers,
    Request,
    fetch: origFetch,
    location: locationObj,
    navigator: navigatorObj,
    localStorage: {
      getItem: (k: string) => storage.get(k) ?? null,
      setItem: (k: string, v: string) => {
        storage.set(k, v);
      },
    },
    addEventListener: (name: string, fn: (ev: unknown) => void) => {
      const list = listeners.get(name) || [];
      list.push(fn);
      listeners.set(name, list);
    },
    setTimeout: (fn: () => void) => {
      fn();
      return 1;
    },
  };
  win.window = win;

  const doc = {
    readyState: 'complete',
    currentScript: {
      getAttribute: (k: string) => scriptAttrs[k] ?? null,
    },
    querySelector: () => null,
  };

  const context = vm.createContext({
    ...win,
    document: doc,
    Date,
    Math,
    JSON,
    Object,
    Array,
    String,
    Number,
    Boolean,
    RegExp,
    Uint8Array,
  });
  context.window = context;

  const code = fs.readFileSync(SCRIPT_PATH, 'utf8');
  vm.runInContext(code, context);

  const emit = (eventName: string, ev: unknown) => {
    for (const fn of listeners.get(eventName) || []) {
      fn(ev);
    }
  };

  return {
    win: context as Record<string, unknown> & {
      fetch: (input: unknown, init?: RequestInit) => Promise<{ ok: boolean; status: number }>;
      __limoBrowserDiag: { flush: () => void; pendingCount: () => number };
    },
    navigatorObj,
    storage,
    fetchCalls,
    emit,
  };
}

const flushAsync = () => new Promise((resolve) => setTimeout(resolve, 10));

describe('browser-diag.js', () => {
  it('captures JS errors without leaking Error.message or non-frame text', async () => {
    const h = loadBrowserDiag({ platform: 'panel', channel: 'teacher' });
    const err = new TypeError('Secret student phone 09123456789 at room temperature failed');
    err.stack = [
      'TypeError: Secret student phone 09123456789',
      '    at room temperature in other words',
      '    at renderNode (https://panel.example.com/static/catalog/panel.js?v=123:42:9)',
    ].join('\n');

    h.emit('error', { error: err });
    await flushAsync();

    const diagCall = h.fetchCalls.find((c) => c.input === '/api/v1/diagnostics/events/');
    expect(diagCall).toBeDefined();
    const payload = JSON.parse(String(diagCall!.init?.body));
    expect(payload.events).toHaveLength(1);
    const ev = payload.events[0];
    expect(ev.platform).toBe('panel');
    expect(ev.channel).toBe('teacher');
    expect(ev.code).toBe('js_error');
    expect(ev.title).toBe('خطای اجرای جاوااسکریپت: TypeError');
    expect(ev.context).toEqual({
      error_name: 'TypeError',
      stack: 'at renderNode (https://panel.example.com/static/catalog/panel.js:42:9)',
    });
    expect(JSON.stringify(ev)).not.toContain('09123456789');
    expect(JSON.stringify(ev)).not.toContain('Secret student');
    expect(JSON.stringify(ev)).not.toContain('room temperature');
    expect(JSON.stringify(ev)).not.toContain('v=123');
  });

  it('captures same-origin script/link asset load failures and ignores cross-origin assets', async () => {
    const h = loadBrowserDiag({ platform: 'website', channel: 'public', pathname: '/site/books/math/' });
    h.emit('error', {
      target: { tagName: 'SCRIPT', src: 'https://panel.example.com/static/website/site.js?v=19' },
    });
    h.emit('error', {
      target: { tagName: 'SCRIPT', src: 'https://cdn.other.example/widget.js' },
    });
    await flushAsync();

    const diagCall = h.fetchCalls.find((c) => c.input === '/api/v1/diagnostics/events/');
    expect(diagCall).toBeDefined();
    const payload = JSON.parse(String(diagCall!.init?.body));
    expect(payload.events).toHaveLength(1);
    expect(payload.events[0].code).toBe('asset_load_error');
    expect(payload.events[0].context).toEqual({
      error_name: 'SCRIPTLoadError',
      location: '/static/website/site.js',
    });
  });

  it('captures unhandledrejection with sanitized error_name and stack only', async () => {
    const h = loadBrowserDiag();
    const err = new ReferenceError('cannot read private note text اینجا فارسی است');
    err.stack = 'ReferenceError: cannot read\n    at saveDraft (https://panel.example.com/static/panel.js:10:2)';
    h.emit('unhandledrejection', { reason: err });
    await flushAsync();

    const diagCall = h.fetchCalls.find((c) => c.input === '/api/v1/diagnostics/events/');
    const ev = JSON.parse(String(diagCall!.init?.body)).events[0];
    expect(ev.code).toBe('unhandled_rejection');
    expect(ev.context.error_name).toBe('ReferenceError');
    expect(ev.context.stack).toBe('at saveDraft (https://panel.example.com/static/panel.js:10:2)');
    expect(JSON.stringify(ev)).not.toContain('private note');
    expect(JSON.stringify(ev)).not.toContain('اینجا');
  });

  it('wraps same-origin fetch with correlation headers, reports 5xx, and skips cross-origin and diagnostics URLs', async () => {
    const h = loadBrowserDiag({
      platform: 'panel',
      channel: 'superadmin',
      fetchImpl: async (input) => {
        if (input === '/admin/catalog/api/fail/?secret=1') {
          return { ok: false, status: 502, headers: new Headers({ 'X-Request-Id': 'srv_502_id' }) };
        }
        return { ok: true, status: 200, headers: new Headers() };
      },
    });

    await h.win.fetch('/admin/catalog/api/fail/?secret=1', { method: 'POST' });
    await h.win.fetch('https://external.example.com/hook', { method: 'POST' });
    await flushAsync();

    const apiCall = h.fetchCalls.find((c) => c.input === '/admin/catalog/api/fail/?secret=1');
    const apiHeaders = new Headers(apiCall!.init?.headers);
    expect(apiHeaders.get('X-App-Platform')).toBe('panel');
    expect(apiHeaders.get('X-App-Channel')).toBe('superadmin');
    expect(apiHeaders.get('X-Request-Id')).toMatch(/^req_/);
    expect(apiHeaders.get('X-App-Install-Id')).toMatch(/^inst_b_/);

    const extCall = h.fetchCalls.find((c) => c.input === 'https://external.example.com/hook');
    expect(extCall!.init?.headers).toBeUndefined();

    const diagCall = h.fetchCalls.find((c) => c.input === '/api/v1/diagnostics/events/');
    expect(diagCall).toBeDefined();
    const ev = JSON.parse(String(diagCall!.init?.body)).events[0];
    expect(ev.kind).toBe('network');
    expect(ev.code).toBe('api_5xx');
    expect(ev.route).toBe('/admin/catalog/api/fail/');
    expect(ev.request_id).toBe('srv_502_id');
    expect(ev.context).toEqual({ status_code: 502, method: 'POST' });
  });

  it('never loops when /api/v1/diagnostics/events/ fails and flushes queued events once online', async () => {
    let failDiag = true;
    const h = loadBrowserDiag({
      onLine: false,
      fetchImpl: async () => {
        if (failDiag) return { ok: false, status: 503, headers: new Headers() };
        return { ok: true, status: 200, headers: new Headers() };
      },
    });

    h.emit('error', { error: new TypeError('offline err') });
    expect(h.win.__limoBrowserDiag.pendingCount()).toBe(1);
    expect(h.fetchCalls).toHaveLength(0);

    // Come online while server returns 503 -> must keep queued and NOT generate a second 5xx report.
    h.navigatorObj.onLine = true;
    h.emit('online', {});
    await flushAsync();
    expect(h.fetchCalls).toHaveLength(1);
    expect(h.win.__limoBrowserDiag.pendingCount()).toBe(1);

    // Server recovers -> flush clears queue.
    failDiag = false;
    h.emit('online', {});
    await flushAsync();
    expect(h.fetchCalls).toHaveLength(2);
    expect(h.win.__limoBrowserDiag.pendingCount()).toBe(0);
  });

  it('scrubs invite and verify-email path tokens before writing route, operation, and breadcrumbs to localStorage', async () => {
    const h = loadBrowserDiag({
      platform: 'website',
      channel: 'public',
      pathname: '/join/SECRET_JOIN_TOKEN_99/',
      onLine: false,
      fetchImpl: async () => ({ ok: false, status: 500, headers: new Headers() }),
    });

    h.emit('error', { error: new TypeError('join page err') });
    await h.win.fetch('/site/verify-email/SECRET_EMAIL_TOKEN_42/?token=extra', { method: 'POST' });

    const rawOutbox = h.storage.get('limo.browserDiagOutbox') || '';
    expect(rawOutbox).not.toContain('SECRET_JOIN_TOKEN_99');
    expect(rawOutbox).not.toContain('SECRET_EMAIL_TOKEN_42');
    expect(rawOutbox).not.toContain('extra');

    const queued = JSON.parse(rawOutbox);
    expect(queued).toHaveLength(2);
    expect(queued[0].route).toBe('/join/<token>/');
    expect(queued[0].breadcrumbs[0].name).toBe('/join/<token>/');
    expect(queued[1].route).toBe('/site/verify-email/<token>/');
    expect(queued[1].operation).toBe('POST /site/verify-email/<token>/');
    expect(queued[1].breadcrumbs.some((b: { name: string }) => b.name === 'POST /site/verify-email/<token>/')).toBe(true);
  });

  it('uses credentials=omit when flushing queued events from a guest or different session', async () => {
    const sharedStorage = new Map<string, string>();
    // 1. Guest queues an event while offline.
    const guest = loadBrowserDiag({
      platform: 'website',
      channel: 'public',
      sessionTag: '',
      pathname: '/site/',
      onLine: false,
      initialStorage: sharedStorage,
    });
    guest.emit('error', { error: new TypeError('guest err') });
    expect(guest.win.__limoBrowserDiag.pendingCount()).toBe(1);

    // 2. Teacher A logs in -> guest event must flush with credentials='omit' so cookies are never sent.
    const teacherA = loadBrowserDiag({
      platform: 'panel',
      channel: 'teacher',
      sessionTag: 's-teacherA',
      pathname: '/admin/',
      onLine: true,
      initialStorage: sharedStorage,
    });
    await flushAsync();
    const guestFlush = teacherA.fetchCalls.find((c) => c.input === '/api/v1/diagnostics/events/');
    expect(guestFlush?.init?.credentials).toBe('omit');
    expect(JSON.parse(String(guestFlush?.init?.body)).events[0].session_tag).toBe('');

    // 3. Teacher A queues an offline event, then Teacher B opens the panel -> must flush with credentials='omit'.
    teacherA.navigatorObj.onLine = false;
    teacherA.emit('error', { error: new ReferenceError('teacherA offline err') });
    expect(teacherA.win.__limoBrowserDiag.pendingCount()).toBe(1);

    const teacherB = loadBrowserDiag({
      platform: 'panel',
      channel: 'teacher',
      sessionTag: 's-teacherB',
      pathname: '/admin/',
      onLine: true,
      initialStorage: sharedStorage,
    });
    await flushAsync();
    const crossFlush = teacherB.fetchCalls.find((c) => c.input === '/api/v1/diagnostics/events/');
    expect(crossFlush?.init?.credentials).toBe('omit');
    expect(JSON.parse(String(crossFlush?.init?.body)).events[0].session_tag).toBe('s-teacherA');

    // 4. Same-session event flushes with credentials='same-origin'.
    teacherB.emit('error', { error: new RangeError('teacherB online err') });
    await flushAsync();
    const sameFlush = teacherB.fetchCalls.filter((c) => c.input === '/api/v1/diagnostics/events/').pop();
    expect(sameFlush?.init?.credentials).toBe('same-origin');
    expect(JSON.parse(String(sameFlush?.init?.body)).events[0].session_tag).toBe('s-teacherB');
  });

  it('handles string, URL, and Request inputs with init.headers without stripping form headers or leaking to external URLs', async () => {
    const h = loadBrowserDiag({ platform: 'panel', channel: 'teacher' });

    // 1. string + init.headers
    await h.win.fetch('/admin/catalog/save/', {
      method: 'POST',
      headers: { 'X-CSRFToken': 'csrf_str', 'Content-Type': 'application/json' },
    });
    const strCall = h.fetchCalls.find((c) => c.input === '/admin/catalog/save/');
    const strHeaders = new Headers(strCall!.init?.headers);
    expect(strHeaders.get('X-CSRFToken')).toBe('csrf_str');
    expect(strHeaders.get('Content-Type')).toBe('application/json');
    expect(strHeaders.get('X-Request-Id')).toMatch(/^req_/);
    expect(strHeaders.get('X-App-Platform')).toBe('panel');

    // 2. URL same-origin + URL external
    await h.win.fetch(new URL('https://panel.example.com/admin/catalog/url-save/'), {
      method: 'POST',
      headers: { 'X-CSRFToken': 'csrf_url' },
    });
    const urlCall = h.fetchCalls.find((c) => c.input instanceof URL && c.input.pathname === '/admin/catalog/url-save/');
    expect(urlCall).toBeDefined();
    const urlHeaders = new Headers(urlCall!.init?.headers);
    expect(urlHeaders.get('X-CSRFToken')).toBe('csrf_url');
    expect(urlHeaders.get('X-Request-Id')).toMatch(/^req_/);
    expect(urlHeaders.get('X-App-Platform')).toBe('panel');

    await h.win.fetch(new URL('https://external.example.com/webhook'), {
      method: 'POST',
      headers: { 'X-External-Only': 'keep' },
    });
    const extUrlCall = h.fetchCalls.find((c) => c.input instanceof URL && c.input.origin === 'https://external.example.com');
    expect(extUrlCall).toBeDefined();
    const extUrlHeaders = new Headers(extUrlCall!.init?.headers);
    expect(extUrlHeaders.get('X-External-Only')).toBe('keep');
    expect(extUrlHeaders.get('X-App-Platform')).toBeNull();
    expect(extUrlHeaders.get('X-Request-Id')).toBeNull();

    // 3a. Request WITHOUT init.headers preserves Request's own headers + diagnostic headers
    const reqKeep = new Request('https://panel.example.com/admin/catalog/req-keep/', {
      method: 'POST',
      headers: { 'X-From-Request': 'req_val' },
    });
    await h.win.fetch(reqKeep);
    const keepCall = h.fetchCalls.find((c) => c.input instanceof Request && c.input.url.endsWith('/admin/catalog/req-keep/'));
    expect(keepCall).toBeDefined();
    const sentKeepReq = keepCall!.input as Request;
    expect(sentKeepReq.headers.get('X-From-Request')).toBe('req_val');
    expect(sentKeepReq.headers.get('X-Request-Id')).toMatch(/^req_/);
    expect(sentKeepReq.headers.get('X-App-Platform')).toBe('panel');

    // 3b. Request WITH init.headers replaces Request.headers with init.headers (standard Fetch behavior)
    const reqReplace = new Request('https://panel.example.com/admin/catalog/req-replace/', {
      method: 'POST',
      headers: { 'X-Old': 'should_be_dropped' },
    });
    await h.win.fetch(reqReplace, { headers: { 'X-CSRFToken': 'csrf_req', 'X-New': 'yes' } });
    const replaceCall = h.fetchCalls.find((c) => c.input instanceof Request && c.input.url.endsWith('/admin/catalog/req-replace/'));
    expect(replaceCall).toBeDefined();
    const sentReplaceReq = replaceCall!.input as Request;
    expect(sentReplaceReq.headers.get('X-Old')).toBeNull();
    expect(sentReplaceReq.headers.get('X-New')).toBe('yes');
    expect(sentReplaceReq.headers.get('X-CSRFToken')).toBe('csrf_req');
    expect(sentReplaceReq.headers.get('X-Request-Id')).toMatch(/^req_/);
    expect(sentReplaceReq.headers.get('X-App-Platform')).toBe('panel');
    expect(replaceCall!.init?.headers).toBeUndefined();

    // 3c. Request WITH headers: {} explicitly clears old Request headers while still attaching diagnostic headers
    const reqClear = new Request('https://panel.example.com/admin/catalog/req-clear/', {
      method: 'POST',
      headers: { 'X-Old': 'should_be_cleared' },
    });
    await h.win.fetch(reqClear, { headers: {} });
    const clearCall = h.fetchCalls.find((c) => c.input instanceof Request && c.input.url.endsWith('/admin/catalog/req-clear/'));
    expect(clearCall).toBeDefined();
    const sentClearReq = clearCall!.input as Request;
    expect(sentClearReq.headers.get('X-Old')).toBeNull();
    expect(sentClearReq.headers.get('X-Request-Id')).toMatch(/^req_/);
    expect(sentClearReq.headers.get('X-App-Platform')).toBe('panel');
    expect(clearCall!.init?.headers).toBeUndefined();
  });
});
