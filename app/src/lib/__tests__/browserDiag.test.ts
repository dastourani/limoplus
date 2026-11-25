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
  pathname?: string;
  onLine?: boolean;
  fetchImpl?: (input: unknown, init?: RequestInit) => Promise<unknown>;
}

function loadBrowserDiag(opts: HarnessOptions = {}) {
  const storage = new Map<string, string>();
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
});
