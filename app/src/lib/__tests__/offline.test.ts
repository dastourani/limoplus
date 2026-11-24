import { beforeEach, describe, expect, it, vi } from 'vitest';

const storage = new Map<string, string>();
const files = new Map<string, Uint8Array>();
let failNextTempWrite = false;
let failNextIndexWrite = false;
let failNextIndexRead = false;
let failNextDeleteUri: string | null = null;

vi.mock('@react-native-async-storage/async-storage', () => ({
  default: {
    getItem: vi.fn(async (k: string) => {
      if (failNextIndexRead && k === 'limo.offlineIndex') {
        failNextIndexRead = false;
        throw new Error('storage read failed');
      }
      return storage.get(k) ?? null;
    }),
    setItem: vi.fn(async (k: string, v: string) => {
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
  getRandomBytes: (n: number) => new Uint8Array(n).fill(7),
}));

vi.mock('expo-device', () => ({
  isRootedExperimentalAsync: vi.fn(async () => false),
}));

vi.mock('../secure', () => {
  const sec = new Map<string, string>();
  return {
    secure: {
      get: vi.fn(async (k: string) => sec.get(k) ?? null),
      set: vi.fn(async (k: string, v: string | null) => {
        if (v === null) sec.delete(k);
        else sec.set(k, v);
      }),
    },
  };
});

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

const sampleBundle = (slug: string, downloadedAt: string, validUntil: string, sectionTitle = 'بخش اول'): OfflineBundle => ({
  book: { slug, title: `کتاب ${slug}` },
  sections: [{ id: 101, title: sectionTitle, summary: 'خلاصه', full: 'متن کامل' }],
  downloaded_at: downloadedAt,
  valid_until: validUntil,
});

describe('offline atomic writes & hybrid revocation sync', () => {
  beforeEach(() => {
    storage.clear();
    files.clear();
    failNextTempWrite = false;
    failNextIndexWrite = false;
    failNextIndexRead = false;
    failNextDeleteUri = null;
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
});
