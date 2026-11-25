import { beforeEach, describe, expect, it, vi } from 'vitest';

const storage = new Map<string, string>();
const files = new Map<string, Uint8Array>();
const sec = new Map<string, string>();
let randomSeed = 1;

vi.mock('@react-native-async-storage/async-storage', () => ({
  default: {
    getItem: vi.fn(async (k: string) => storage.get(k) ?? null),
    setItem: vi.fn(async (k: string, v: string) => {
      storage.set(k, v);
    }),
    removeItem: vi.fn(async (k: string) => {
      storage.delete(k);
    }),
  },
}));

vi.mock('expo-crypto', () => ({
  getRandomBytes: (n: number) => new Uint8Array(n).fill(randomSeed++),
}));

vi.mock('expo-device', () => ({
  isRootedExperimentalAsync: vi.fn(async () => false),
}));

vi.mock('../secure', () => ({
  secure: {
    get: vi.fn(async (k: string) => sec.get(k) ?? null),
    set: vi.fn(async (k: string, v: string | null) => {
      if (v === null) sec.delete(k);
      else sec.set(k, v);
    }),
  },
}));

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {
    constructor(
      public status: number,
      public code: string,
      message: string,
    ) {
      super(message);
    }
  },
}));

vi.mock('expo-file-system', () => {
  class MockDirectory {
    constructor(
      public parent: unknown,
      public name: string,
    ) {}
    get exists() {
      return true;
    }
    create() {}
    delete() {
      files.clear();
    }
  }
  class MockFile {
    public uri: string;
    constructor(
      dir: MockDirectory,
      public name: string,
    ) {
      this.uri = `${dir.name}/${name}`;
    }
    get exists() {
      return files.has(this.uri);
    }
    create() {
      if (!files.has(this.uri)) files.set(this.uri, new Uint8Array());
    }
    async write(data: Uint8Array) {
      files.set(this.uri, new Uint8Array(data));
    }
    async bytes() {
      const d = files.get(this.uri);
      if (!d) throw new Error('missing');
      return d;
    }
    async move(dest: MockFile) {
      const d = files.get(this.uri);
      if (!d) throw new Error('missing src');
      files.set(dest.uri, d);
      files.delete(this.uri);
      this.uri = dest.uri;
    }
    delete() {
      files.delete(this.uri);
    }
  }
  return { Directory: MockDirectory, File: MockFile, Paths: { document: 'doc' } };
});

import type { OfflineBundle } from '../../api/endpoints';

function sampleBundle(slug = 'math-1'): OfflineBundle {
  const future = new Date(Date.now() + 7 * 86400 * 1000).toISOString();
  return {
    book: { slug, title: 'ریاضی ۱', updated_on: '2026-11-24T10:00:00Z' },
    labels: [],
    macros: {},
    sections: [
      {
        id: 101,
        kind: 'section',
        title: 'بخش اول',
        summary: 'خلاصه',
        full: 'متن درس با ![شکل](media:content/fig1.png)',
        chapter_number: 1,
        chapter_title: 'فصل اول',
      },
    ],
    media: [{ id: 'fig1', ref: 'media:content/fig1.png', mime: 'image/png', url: 'https://cdn.example/fig1.png?sig=secret123' }],
    downloaded_at: '2026-11-24T10:00:00Z',
    valid_until: future,
  };
}

describe('client diagnostics queue & offline failure reporting', () => {
  beforeEach(() => {
    storage.clear();
    files.clear();
    sec.clear();
    randomSeed = 1;
    vi.resetModules();
    vi.unstubAllGlobals();
  });

  it('queues offline corrupt bundle once with stable event_id across app restart and network retry', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        arrayBuffer: async () => new Uint8Array([1, 2, 3, 4]).buffer,
      })),
    );

    const diag1 = await import('../diagnostics');
    const offline1 = await import('../offline');
    diag1._resetDiagnosticsForTests();
    diag1.setDiagnosticsMeta({ platform: 'android', channel: 'official', appBuild: '116', webCommit: '' });

    await offline1.saveOfflineBook(sampleBundle('math-1'));
    // Go offline and corrupt the encrypted bundle file on disk.
    diag1.setDiagnosticsOnline(false);
    files.set('offline/math-1.bin', new Uint8Array([9, 8, 7, 6, 5]));

    const secResult = await offline1.offlineSection(101);
    expect(secResult).toBeNull();
    expect(await diag1.pendingDiagnosticCount()).toBe(1);

    const queuedBeforeRestart = JSON.parse(storage.get('limo.diagOutbox')!);
    expect(queuedBeforeRestart).toHaveLength(1);
    const savedEventId = queuedBeforeRestart[0].event_id;
    expect(queuedBeforeRestart[0].code).toBe('offline_corrupt');
    expect(queuedBeforeRestart[0].app_build).toBe('116');
    expect(queuedBeforeRestart[0].channel).toBe('official');
    expect(queuedBeforeRestart[0].is_offline).toBe(true);
    expect(queuedBeforeRestart[0].install_id).toMatch(/^inst_/);

    // Simulate app restart (fresh module state; AsyncStorage persists).
    vi.resetModules();
    const diag2 = await import('../diagnostics');
    diag2._resetDiagnosticsForTests();
    diag2.setDiagnosticsMeta({ platform: 'android', channel: 'official', appBuild: '116', webCommit: '' });
    expect(await diag2.pendingDiagnosticCount()).toBe(1);

    // First reconnect attempt drops response on the wire (status 0) -> stays queued with SAME event_id.
    const sentBatches: any[][] = [];
    let failFirst = true;
    diag2.setDiagnosticsTransport(async (events) => {
      sentBatches.push(events);
      if (failFirst) {
        failFirst = false;
        const err = new Error('network lost') as Error & { status?: number };
        err.status = 0;
        throw err;
      }
    });
    diag2.setDiagnosticsOnline(true);
    await diag2.flushDiagnostics();
    expect(await diag2.pendingDiagnosticCount()).toBe(1);

    // Second flush succeeds and clears queue without generating another error report.
    await diag2.flushDiagnostics();
    expect(await diag2.pendingDiagnosticCount()).toBe(0);
    expect(sentBatches).toHaveLength(2);
    expect(sentBatches[0][0].event_id).toBe(savedEventId);
    expect(sentBatches[1][0].event_id).toBe(savedEventId);
  });

  it('distinguishes missing bundle, missing media, and failed update with intact previous bundle', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: true,
        status: 200,
        arrayBuffer: async () => new Uint8Array([1, 2, 3, 4]).buffer,
      })),
    );
    const diag = await import('../diagnostics');
    const offline = await import('../offline');
    diag._resetDiagnosticsForTests();
    diag.setDiagnosticsOnline(false);

    // 1. Save valid v1 book, then fail v2 media download -> previous intact warning
    await offline.saveOfflineBook(sampleBundle('phys-1'));
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => ({
        ok: false,
        status: 502,
      })),
    );
    await expect(offline.saveOfflineBook(sampleBundle('phys-1'))).rejects.toThrow();
    let events = JSON.parse(storage.get('limo.diagOutbox')!);
    expect(events.some((e: any) => e.code === 'offline_update_failed_prev_intact' && e.context?.previous_intact === true)).toBe(true);

    // 2. Delete one media asset file -> section still opens, reports offline_media_missing without signed URL
    for (const key of files.keys()) {
      if (key.endsWith('.media')) files.delete(key);
    }
    const secWithMissingMedia = await offline.offlineSection(101);
    expect(secWithMissingMedia).not.toBeNull();
    events = JSON.parse(storage.get('limo.diagOutbox')!);
    const mediaEvt = events.find((e: any) => e.code === 'offline_media_missing');
    expect(mediaEvt).toBeTruthy();
    expect(JSON.stringify(mediaEvt)).not.toContain('secret123');

    // 3. Delete main .bin while index still lists book -> reports offline_missing
    files.delete('offline/phys-1.bin');
    expect(await offline.offlineBookDetail('phys-1')).toBeNull();
    events = JSON.parse(storage.get('limo.diagOutbox')!);
    expect(events.some((e: any) => e.code === 'offline_missing')).toBe(true);
  });

  it('strips unquoted English textbook text, unallowlisted context keys, emails, and Persian text from local queue while keeping file/line/version/requestId', async () => {
    const diag = await import('../diagnostics');
    diag._resetDiagnosticsForTests();
    diag.setDiagnosticsMeta({ platform: 'android', channel: 'official', appBuild: '118', webCommit: '' });
    diag.setDiagnosticsRoute('/quiz/42');
    diag.setDiagnosticsOnline(false);
    diag.addBreadcrumb('api', 'GET /search/?q=مشتق', 'student@example.com عبارت خصوصی درس');

    await diag.reportDiagnostic({
      kind: 'client_error',
      code: 'js_error',
      title: 'The passive voice expresses an action done to the subject',
      request_id: 'req_diag_123',
      observed: 'TypeError: The passive voice expresses an action done to the subject for student@example.com — عبارت خصوصی دانش‌آموز',
      context: {
        error_name: 'TypeError',
        error_message: 'The passive voice expresses an action done to the subject',
        extra_note: 'یادداشت آزمایشی خصوصی دانش‌آموز',
        stack: 'TypeError: The passive voice expresses an action done to the subject\n    at renderQuiz (quiz.tsx:42:9)',
        book_slug: 'english-1',
      },
      deferFlush: true,
    });

    const raw = storage.get('limo.diagOutbox')!;
    expect(raw).not.toContain('passive voice');
    expect(raw).not.toContain('extra_note');
    expect(raw).not.toContain('یادداشت آزمایشی');
    expect(raw).not.toContain('student@example.com');
    expect(raw).not.toContain('عبارت خصوصی دانش‌آموز');
    expect(raw).not.toContain('مشتق');

    const queued = JSON.parse(raw);
    expect(queued[0].context.error_name).toBe('TypeError');
    expect(queued[0].context.extra_note).toBeUndefined();
    expect(queued[0].context.error_message).toBeUndefined();
    expect(queued[0].route).toBe('/quiz/42');
    expect(queued[0].app_build).toBe('118');
    expect(queued[0].request_id).toBe('req_diag_123');
    expect(queued[0].context.stack).toContain('quiz.tsx:42:9');
  });

  it('scrubs phones and signed tokens on the client before storing', async () => {
    const diag = await import('../diagnostics');
    diag._resetDiagnosticsForTests();
    diag.setDiagnosticsOnline(false);
    diag.addBreadcrumb('api', 'GET /nodes/10/', '09123456789');

    await diag.reportDiagnostic({
      kind: 'client_error',
      code: 'js_error',
      title: 'خطا برای 09121112233',
      observed: 'Bearer secretToken987654 on ?sig=verysecret1',
      context: { error_message: 'phone 09121112233', book_slug: 'math-1' },
      deferFlush: true,
    });

    const raw = storage.get('limo.diagOutbox')!;
    expect(raw).not.toContain('09121112233');
    expect(raw).not.toContain('09123456789');
    expect(raw).not.toContain('secretToken987654');
    expect(raw).not.toContain('verysecret1');
  });
});
