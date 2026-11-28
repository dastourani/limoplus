import { beforeEach, describe, expect, it, vi } from 'vitest';

const storage = new Map<string, string>();
const files = new Map<string, Uint8Array>();
const sec = new Map<string, string>();
let failNextTempWrite = false;
let failNextIndexWrite = false;
let failNextIndexRead = false;
let failNextDeleteUri: string | null = null;
let randomSeed = 1;
let writeBarrier: (() => void) | null = null;
let activeWrites = 0;
let maxConcurrentWrites = 0;
let onSecondWriteStarted: (() => void) | null = null;

vi.mock('@react-native-async-storage/async-storage', () => ({
  default: {
    getItem: vi.fn(async (k: string) => {
      await Promise.resolve();
      if (failNextIndexRead && k === 'limo.offlineIndex') {
        failNextIndexRead = false;
        throw new Error('storage read failed');
      }
      return storage.get(k) ?? null;
    }),
    setItem: vi.fn(async (k: string, v: string) => {
      await Promise.resolve();
      if (failNextIndexWrite && k === 'limo.offlineIndex') {
        failNextIndexWrite = false;
        throw new Error('storage write failed');
      }
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
    get: vi.fn(async (k: string) => {
      await Promise.resolve();
      return sec.get(k) ?? null;
    }),
    set: vi.fn(async (k: string, v: string | null) => {
      await Promise.resolve();
      if (v === null) sec.delete(k);
      else sec.set(k, v);
    }),
  },
}));

vi.mock('../../api/client', () => ({
  ApiError: class ApiError extends Error {
    constructor(public status: number, public code: string, message: string) {
      super(message);
    }
  },
}));

vi.mock('expo-file-system', () => {
  class MockDirectory {
    constructor(public parent: unknown, public name: string) {}
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
    constructor(dir: MockDirectory, public name: string) {
      this.uri = `${dir.name}/${name}`;
    }
    get exists() {
      return files.has(this.uri);
    }
    create() {
      if (!files.has(this.uri)) files.set(this.uri, new Uint8Array());
    }
    async write(data: Uint8Array) {
      if (failNextTempWrite && this.uri.endsWith('.tmp')) {
        failNextTempWrite = false;
        throw new Error('disk full');
      }
      activeWrites += 1;
      maxConcurrentWrites = Math.max(maxConcurrentWrites, activeWrites);
      try {
        if (writeBarrier && activeWrites === 1) {
          await new Promise<void>((resolve) => {
            onSecondWriteStarted = resolve;
          });
        } else if (onSecondWriteStarted) {
          const release = onSecondWriteStarted;
          onSecondWriteStarted = null;
          writeBarrier = null;
          release();
        }
        files.set(this.uri, new Uint8Array(data));
      } finally {
        activeWrites -= 1;
      }
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
      if (failNextDeleteUri === this.uri) {
        failNextDeleteUri = null;
        throw new Error('delete failed');
      }
      files.delete(this.uri);
    }
  }
  return { Directory: MockDirectory, File: MockFile, Paths: { document: 'doc' } };
});

import type { OfflineBundle } from '../../api/endpoints';
import { offlineBooks, offlineSection, reconcileOfflineRevocations, removeOfflineBook, saveOfflineBook } from '../offline';

const sampleBundle = (slug: string, downloadedAt: string, validUntil: string, sectionTitle = 'بخش اول', sectionId = 101): OfflineBundle => ({
  book: { slug, title: `کتاب ${slug}` },
  sections: [{ id: sectionId, title: sectionTitle, summary: 'خلاصه', full: 'متن کامل' }],
  downloaded_at: downloadedAt,
  valid_until: validUntil,
});

describe('offline atomic writes & hybrid revocation sync', () => {
  beforeEach(() => {
    storage.clear();
    files.clear();
    sec.clear();
    failNextTempWrite = false;
    failNextIndexWrite = false;
    failNextIndexRead = false;
    failNextDeleteUri = null;
    randomSeed = 1;
    writeBarrier = null;
    activeWrites = 0;
    maxConcurrentWrites = 0;
    onSecondWriteStarted = null;
  });

  it('preserves existing .bin and cleans up .tmp if temp write fails', async () => {
    const future = new Date(Date.now() + 10 * 86400 * 1000).toISOString();
    await saveOfflineBook(sampleBundle('math-1', '2026-11-20T10:00:00Z', future));
    expect(files.has('offline/math-1.bin')).toBe(true);

    failNextTempWrite = true;
    await expect(saveOfflineBook(sampleBundle('math-1', '2026-11-24T10:00:00Z', future))).rejects.toThrow('disk full');

    expect(files.has('offline/math-1.bin')).toBe(true);
    expect(files.has('offline/math-1.bin.tmp')).toBe(false);
    expect(files.has('offline/math-1.bin.bak')).toBe(false);
    const sec = await offlineSection(101);
    expect(sec?.title).toBe('بخش اول');
  });

  it('rejects and leaves no orphan .bin when saving the offline index fails on a new download', async () => {
    const future = new Date(Date.now() + 10 * 86400 * 1000).toISOString();
    failNextIndexWrite = true;

    await expect(saveOfflineBook(sampleBundle('bio-1', '2026-11-24T10:00:00Z', future))).rejects.toThrow('storage write failed');

    expect(files.has('offline/bio-1.bin')).toBe(false);
    expect(files.has('offline/bio-1.bin.tmp')).toBe(false);
    expect(files.has('offline/bio-1.bin.bak')).toBe(false);
    expect(await offlineBooks()).toEqual([]);
    expect(await offlineSection(101)).toBeNull();
  });

  it('restores previous .bin and index entry when saving the offline index fails on a re-download', async () => {
    const future = new Date(Date.now() + 10 * 86400 * 1000).toISOString();
    await saveOfflineBook(sampleBundle('math-1', '2026-11-20T10:00:00Z', future, 'نسخه‌ی اول'));

    failNextIndexWrite = true;
    await expect(saveOfflineBook(sampleBundle('math-1', '2026-11-24T10:00:00Z', future, 'نسخه‌ی جدید'))).rejects.toThrow('storage write failed');

    expect(files.has('offline/math-1.bin')).toBe(true);
    expect(files.has('offline/math-1.bin.tmp')).toBe(false);
    expect(files.has('offline/math-1.bin.bak')).toBe(false);
    const list = await offlineBooks();
    expect(list.map((b) => b.downloadedAt)).toEqual(['2026-11-20T10:00:00Z']);
    expect((await offlineSection(101))?.title).toBe('نسخه‌ی اول');
  });

  it('rejects without wiping existing books or leaving files if reading the index fails', async () => {
    const future = new Date(Date.now() + 10 * 86400 * 1000).toISOString();
    await saveOfflineBook(sampleBundle('math-1', '2026-11-20T10:00:00Z', future));

    failNextIndexRead = true;
    await expect(saveOfflineBook(sampleBundle('chem-1', '2026-11-24T10:00:00Z', future))).rejects.toThrow('storage read failed');

    expect(files.has('offline/chem-1.bin')).toBe(false);
    expect((await offlineBooks()).map((b) => b.slug)).toEqual(['math-1']);
  });

  it('keeps .bin intact when removeOfflineBook fails to update the index', async () => {
    const future = new Date(Date.now() + 10 * 86400 * 1000).toISOString();
    await saveOfflineBook(sampleBundle('math-1', '2026-11-20T10:00:00Z', future));

    failNextIndexWrite = true;
    await expect(removeOfflineBook('math-1')).rejects.toThrow('storage write failed');

    expect(files.has('offline/math-1.bin')).toBe(true);
    expect((await offlineBooks()).map((b) => b.slug)).toEqual(['math-1']);
  });

  it('wipes revoked offline books only when revoked_at >= downloadedAt', async () => {
    const future = new Date(Date.now() + 10 * 86400 * 1000).toISOString();
    await saveOfflineBook(sampleBundle('math-1', '2026-11-20T10:00:00Z', future));
    await saveOfflineBook(sampleBundle('phys-1', '2026-11-24T12:00:00Z', future));

    await reconcileOfflineRevocations([
      { slug: 'math-1', revoked_at: '2026-11-24T11:00:00Z' }, // revoked after download -> wipe
      { slug: 'phys-1', revoked_at: '2026-11-24T10:00:00Z' }, // re-downloaded after revocation -> keep
    ]);

    const remaining = await offlineBooks();
    expect(remaining.map((b) => b.slug)).toEqual(['phys-1']);
    expect(files.has('offline/math-1.bin')).toBe(false);
    expect(files.has('offline/phys-1.bin')).toBe(true);
  });

  it('continues wiping remaining books when deleting one fails and retries the failed book on next sync', async () => {
    const future = new Date(Date.now() + 10 * 86400 * 1000).toISOString();
    await saveOfflineBook(sampleBundle('book-1', '2026-11-20T10:00:00Z', future));
    await saveOfflineBook(sampleBundle('book-2', '2026-11-20T10:00:00Z', future));

    failNextDeleteUri = 'offline/book-1.bin';
    const revocations = [
      { slug: 'book-1', revoked_at: '2026-11-24T11:00:00Z' },
      { slug: 'book-2', revoked_at: '2026-11-24T11:00:00Z' },
    ];
    await reconcileOfflineRevocations(revocations);

    // book-2 was wiped despite book-1 failing, and book-1 stayed indexed so the next sync retries it.
    expect(files.has('offline/book-2.bin')).toBe(false);
    expect(files.has('offline/book-1.bin')).toBe(true);
    expect((await offlineBooks()).map((b) => b.slug)).toEqual(['book-1']);

    await reconcileOfflineRevocations(revocations);
    expect(files.has('offline/book-1.bin')).toBe(false);
    expect(await offlineBooks()).toEqual([]);
  });

  it('keeps both concurrently downloaded books in the index and readable after app restart while writing files in parallel', async () => {
    const future = new Date(Date.now() + 10 * 86400 * 1000).toISOString();
    writeBarrier = () => undefined;

    const [entryA, entryB] = await Promise.all([
      saveOfflineBook(sampleBundle('math-1', '2026-11-24T10:00:00Z', future, 'فصل اول ریاضی', 101)),
      saveOfflineBook(sampleBundle('phys-1', '2026-11-24T10:00:00Z', future, 'فصل اول فیزیک', 202)),
    ]);

    expect(entryA.slug).toBe('math-1');
    expect(entryB.slug).toBe('phys-1');
    expect(maxConcurrentWrites).toBe(2);
    expect(files.has('offline/math-1.bin')).toBe(true);
    expect(files.has('offline/phys-1.bin')).toBe(true);

    const { secure } = await import('../secure');
    expect(secure.set).toHaveBeenCalledTimes(1);

    // Simulate closing and reopening the app (fresh module state, persisted storage + files + keystore).
    vi.resetModules();
    const reopened = await import('../offline');
    const list = await reopened.offlineBooks();
    expect(list.map((b) => b.slug).sort()).toEqual(['math-1', 'phys-1']);
    expect((await reopened.offlineSection(101))?.title).toBe('فصل اول ریاضی');
    expect((await reopened.offlineSection(202))?.title).toBe('فصل اول فیزیک');
  });

  it('does not lose a concurrent save when removeOfflineBook runs or rolls back on failure', async () => {
    const future = new Date(Date.now() + 10 * 86400 * 1000).toISOString();
    await saveOfflineBook(sampleBundle('book-a', '2026-11-20T10:00:00Z', future, 'الف', 101));

    failNextDeleteUri = 'offline/book-a.bin';
    const removePromise = removeOfflineBook('book-a').catch((e) => e);
    const savePromise = saveOfflineBook(sampleBundle('book-b', '2026-11-24T10:00:00Z', future, 'ب', 202));

    const [removeResult] = await Promise.all([removePromise, savePromise]);
    expect(removeResult).toBeInstanceOf(Error);
    expect((await offlineBooks()).map((b) => b.slug).sort()).toEqual(['book-a', 'book-b']);
    expect((await offlineSection(101))?.title).toBe('الف');
    expect((await offlineSection(202))?.title).toBe('ب');
  });

  it('downloads deduplicated media once, serves data: URIs after signed URL expiry, and keeps previous version if media fails on update', async () => {
    const future = new Date(Date.now() + 10 * 86400 * 1000).toISOString();
    const svgBytes = new TextEncoder().encode('<svg><circle r="5"/></svg>');
    const pngBytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);

    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes('shared.svg')) return new Response(svgBytes, { status: 200 });
      if (url.includes('second.png')) return new Response(pngBytes, { status: 200 });
      return new Response(null, { status: 403 });
    });
    vi.stubGlobal('fetch', fetchMock);

    try {
      const bundleV1: OfflineBundle = {
        version: 2,
        book: { slug: 'math-1', title: 'ریاضی ۱', updated_on: '2026-11-20T00:00:00Z' },
        labels: [{ name: 'مثال', style: 'formal', numbered: true, icon: 'bookmark' }],
        macros: { '\\R': '\\mathbb{R}' },
        media: [
          { ref: 'media:content/math-1/ch1/shared.svg', id: 'shared', url: 'https://cdn.example/shared.svg?exp=1&sig=ok', mime: 'image/svg+xml' },
          { ref: 'media:content/math-1/ch1/second.png', id: 'second', url: 'https://cdn.example/second.png?exp=1&sig=ok', mime: 'image/png' },
        ],
        sections: [
          {
            id: 10,
            kind: 'chapter',
            title: 'حد و پیوستگی',
            summary: '',
            full: 'مقدمه فصل:\n![نمودار](media:content/math-1/ch1/shared.svg)',
            chapter_number: 1,
            chapter_title: 'حد و پیوستگی',
            numbering: { chapter: 1, start: {}, refs: { ex1: { text: 'مثال ۱-۱', node: 11 } } },
            previous_id: null,
            next_id: 11,
            intro: { number: 1, sections: [{ id: 11, title: 'مفهوم حد', locked: false, state: 'empty' }], questions: 0, flashcards: 0, continue_id: 11, started: false },
          },
          {
            id: 11,
            kind: 'section',
            title: 'مفهوم حد',
            summary: 'خلاصه ![تکرار](media:content/math-1/ch1/shared.svg)',
            full: 'متن ![دوم](media:content/math-1/ch1/second.png) و [[#ex1]]',
            chapter_number: 1,
            chapter_title: 'حد و پیوستگی',
            numbering: { chapter: 1, start: {}, refs: { ex1: { text: 'مثال ۱-۱', node: 11 } } },
            previous_id: 10,
            next_id: null,
          },
        ],
        downloaded_at: '2026-11-20T10:00:00Z',
        valid_until: future,
      };

      const saved = await saveOfflineBook(bundleV1);
      expect(fetchMock).toHaveBeenCalledTimes(2);
      expect(saved.mediaFiles?.length).toBe(2);

      // Simulate expired URLs & airplane mode (fetch throws).
      fetchMock.mockRejectedValue(new Error('Network request failed'));
      const introSec = await offlineSection(10);
      expect(introSec?.kind).toBe('chapter');
      expect(introSec?.full).toContain('data:image/svg+xml;base64,');
      expect(introSec?.macros?.['\\R']).toBe('\\mathbb{R}');
      expect(introSec?.labels?.[0]?.name).toBe('مثال');
      expect(introSec?.numbering?.refs?.ex1?.text).toBe('مثال ۱-۱');

      const sec11 = await offlineSection(11);
      expect(sec11?.summary).toContain('data:image/svg+xml;base64,');
      expect(sec11?.full).toContain('data:image/png;base64,');

      // Re-download fails on 403 media -> previous v1 bundle + its media files remain intact!
      fetchMock.mockResolvedValueOnce(new Response(null, { status: 403 }));
      const bundleV2Fail: OfflineBundle = {
        ...bundleV1,
        media: [{ ref: 'media:content/math-1/ch1/shared.svg', id: 'shared', url: 'https://cdn.example/expired.svg', mime: 'image/svg+xml' }],
        sections: [{ ...bundleV1.sections[0], title: 'نسخه خراب' }],
        downloaded_at: '2026-11-24T10:00:00Z',
      };
      await expect(saveOfflineBook(bundleV2Fail)).rejects.toThrow();
      expect((await offlineSection(10))?.title).toBe('حد و پیوستگی');
      expect((await offlineSection(10))?.full).toContain('data:image/svg+xml;base64,');
      expect(Array.from(files.keys()).filter((k) => k.endsWith('.media')).length).toBe(2);

      // Successful re-download removes old media files and keeps only the new ones.
      fetchMock.mockResolvedValueOnce(new Response(svgBytes, { status: 200 }));
      const bundleV2Ok: OfflineBundle = {
        ...bundleV1,
        media: [{ ref: 'media:content/math-1/ch1/shared.svg', id: 'shared', url: 'https://cdn.example/shared.svg?exp=2&sig=ok', mime: 'image/svg+xml' }],
        sections: [{ ...bundleV1.sections[0], title: 'حد و پیوستگی (جدید)' }],
        downloaded_at: '2026-11-24T12:00:00Z',
      };
      const updated = await saveOfflineBook(bundleV2Ok);
      expect(updated.mediaFiles?.length).toBe(1);
      expect(Array.from(files.keys()).filter((k) => k.endsWith('.media')).length).toBe(1);
      expect((await offlineSection(10))?.title).toBe('حد و پیوستگی (جدید)');

      await removeOfflineBook('math-1');
      expect(Array.from(files.keys()).filter((k) => k.endsWith('.media')).length).toBe(0);
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('waits for all parallel image workers to settle/abort on failure and leaves zero orphan .media files', async () => {
    const future = new Date(Date.now() + 10 * 86400 * 1000).toISOString();
    const pngBytes = new Uint8Array([0x89, 0x50, 0x4e, 0x47]);

    let releaseSecondFetch!: () => void;
    const secondFetchGate = new Promise<void>((resolve) => {
      releaseSecondFetch = resolve;
    });
    let secondStarted!: () => void;
    const secondStartedPromise = new Promise<void>((resolve) => {
      secondStarted = resolve;
    });

    const fetchMock = vi.fn(async (url: string) => {
      if (url.includes('img-2.png')) {
        secondStarted();
        // Keep img-2 slightly slower so img-1 fails while img-2 is finishing its fetch/write.
        await secondFetchGate;
        return new Response(pngBytes, { status: 200 });
      }
      await secondStartedPromise;
      // Fail img-1 right as img-2 finishes its response so img-2 tests the settle+cleanup race.
      releaseSecondFetch();
      return new Response(null, { status: 500 });
    });
    vi.stubGlobal('fetch', fetchMock);

    try {
      const bundle: OfflineBundle = {
        ...sampleBundle('math-1', '2026-11-24T10:00:00Z', future),
        media: [
          { ref: 'media:content/math-1/ch1/img-1.png', id: 'img-1', url: 'https://cdn.example/img-1.png', mime: 'image/png' },
          { ref: 'media:content/math-1/ch1/img-2.png', id: 'img-2', url: 'https://cdn.example/img-2.png', mime: 'image/png' },
        ],
      };

      await expect(saveOfflineBook(bundle)).rejects.toThrow();
      // Give any stray microtask a tick to prove no background worker writes an orphan file after rejection.
      await new Promise((r) => setTimeout(r, 15));
      expect(Array.from(files.keys())).toEqual([]);
      expect(storage.get('limo.offlineIndex')).toBeUndefined();
    } finally {
      vi.unstubAllGlobals();
    }
  });

  it('retries failed .media deletions on next wipe and cleans up expired books + their .media files', async () => {
    const future = new Date(Date.now() + 10 * 86400 * 1000).toISOString();
    const svgBytes = new TextEncoder().encode('<svg/>');
    const fetchMock = vi.fn(async () => new Response(svgBytes, { status: 200 }));
    vi.stubGlobal('fetch', fetchMock);

    try {
      const bundle1: OfflineBundle = {
        ...sampleBundle('book-1', '2026-11-20T10:00:00Z', future),
        media: [
          { ref: 'media:content/book-1/ch1/a.svg', id: 'a', url: 'https://cdn.example/a.svg', mime: 'image/svg+xml' },
          { ref: 'media:content/book-1/ch1/b.svg', id: 'b', url: 'https://cdn.example/b.svg', mime: 'image/svg+xml' },
        ],
      };
      const saved1 = await saveOfflineBook(bundle1);
      const firstMediaName = saved1.mediaFiles![0];

      // Fail deleting the first .media file during wipe -> next reconcile must finish deleting BOTH .media and .bin + clear index.
      failNextDeleteUri = `offline/${firstMediaName}`;
      const revocations = [{ slug: 'book-1', revoked_at: '2026-11-24T11:00:00Z' }];
      await reconcileOfflineRevocations(revocations);
      expect(files.has(`offline/${firstMediaName}`)).toBe(true);

      await reconcileOfflineRevocations(revocations);
      expect(JSON.parse(storage.get('limo.offlineIndex') ?? '[]')).toEqual([]);
      expect(Array.from(files.keys())).toEqual([]);

      // Expired book scenario: save with future date, then advance time past validUntil, and fail deleting its .media once.
      const expBundle: OfflineBundle = {
        ...sampleBundle('book-exp', '2026-11-20T10:00:00Z', future),
        media: [{ ref: 'media:content/book-exp/ch1/c.svg', id: 'c', url: 'https://cdn.example/c.svg', mime: 'image/svg+xml' }],
      };
      const savedExp = await saveOfflineBook(expBundle);
      const expMedia = savedExp.mediaFiles![0];

      vi.useFakeTimers();
      vi.setSystemTime(new Date(Date.now() + 20 * 86400 * 1000));
      failNextDeleteUri = `offline/${expMedia}`;
      await reconcileOfflineRevocations([]);
      // Index has pruned expired book; pending media remains until retry.
      expect(JSON.parse(storage.get('limo.offlineIndex') ?? '[]')).toEqual([]);
      expect(files.has('offline/book-exp.bin')).toBe(false);
      expect(files.has(`offline/${expMedia}`)).toBe(true);

      // Next cleanup drains pending media file too -> disk is completely clean.
      await reconcileOfflineRevocations([]);
      expect(Array.from(files.keys())).toEqual([]);
    } finally {
      vi.useRealTimers();
      vi.unstubAllGlobals();
    }
  });
});
