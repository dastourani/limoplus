/**
 * Encrypted offline books (phone app only).
 *
 * A book's readable chapters/sections and their unique images are downloaded once and stored encrypted with
 * AES-256-GCM. The key is random per install and lives in the Android keystore-backed secure store, so copying the
 * files off the phone is useless. Images are saved per-asset and decrypted on demand only for the open section as
 * `data:` URIs (without enabling broad `file://` access in the WebView). Downloads expire (30 days) and are wiped
 * on sign-out or admin revocation.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { gcm } from '@noble/ciphers/aes';
import { getRandomBytes } from 'expo-crypto';
import * as Device from 'expo-device';
import { Directory, File, Paths } from 'expo-file-system';

import { ApiError } from '../api/client';
import type { BookDetail, ChapterSummary, NodeSummary, OfflineBundle, OfflineRevocation } from '../api/endpoints';
import type { Label } from './labels';
import type { Numbering } from './numbering';
import { bytesToBase64, utf8Decode, utf8Encode } from './utf8';
import { secure } from './secure';

const KEY_NAME = 'limo.offlineKey';
const INDEX_KEY = 'limo.offlineIndex';
const PENDING_CLEANUP_KEY = 'limo.offlinePendingCleanup';
const MEDIA_CONCURRENCY = 4;
const MEDIA_REF_RE = /!\[([^\]]*)\]\((media:content\/[^)\s]+)\)/g;

export type OfflineBook = {
  slug: string;
  title: string;
  sectionIds: number[];
  downloadedAt: string;
  validUntil: string;
  bookUpdatedOn?: string | null;
  mediaFiles?: string[];
};

export type OfflineSection = OfflineBundle['sections'][number] & {
  bookSlug: string;
  bookTitle: string;
  labels?: Label[];
  macros?: Record<string, string>;
};

type StoredMediaEntry = {
  file: string;
  mime: string;
};

type StoredBundle = OfflineBundle & {
  mediaManifest?: Record<string, StoredMediaEntry>;
};

export const offlineSupported = true;

let keyChain: Promise<unknown> = Promise.resolve();
let indexChain: Promise<unknown> = Promise.resolve();
const slugChains = new Map<string, Promise<unknown>>();
let clearEpoch = 0;

function serialize<T>(tail: Promise<unknown>, fn: () => Promise<T>): { tail: Promise<unknown>; result: Promise<T> } {
  const result = tail.then(fn, fn);
  return {
    tail: result.then(
      () => undefined,
      () => undefined,
    ),
    result,
  };
}

function withKeyLock<T>(fn: () => Promise<T>): Promise<T> {
  const next = serialize(keyChain, fn);
  keyChain = next.tail;
  return next.result;
}

function withIndexLock<T>(fn: () => Promise<T>): Promise<T> {
  const next = serialize(indexChain, fn);
  indexChain = next.tail;
  return next.result;
}

function withSlugLock<T>(slug: string, fn: () => Promise<T>): Promise<T> {
  const cur = slugChains.get(slug) ?? Promise.resolve();
  const next = serialize(cur, fn);
  const wrapped = next.tail.then(() => {
    if (slugChains.get(slug) === wrapped) slugChains.delete(slug);
  });
  slugChains.set(slug, wrapped);
  return next.result;
}

function dir() {
  return new Directory(Paths.document, 'offline');
}

function safeSlug(slug: string) {
  return slug.replace(/[^\w-]/g, '_');
}

function fileFor(slug: string) {
  return new File(dir(), `${safeSlug(slug)}.bin`);
}

function tempFileFor(slug: string) {
  return new File(dir(), `${safeSlug(slug)}.bin.tmp`);
}

function backupFileFor(slug: string) {
  return new File(dir(), `${safeSlug(slug)}.bin.bak`);
}

function mediaFileByName(fileName: string) {
  return new File(dir(), fileName);
}

function mediaFileName(slug: string, versionTag: string, assetId: string) {
  return `${safeSlug(slug)}__${versionTag}__${assetId.replace(/[^\w-]/g, '_')}.media`;
}

function toHex(bytes: Uint8Array) {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

function fromHex(hex: string) {
  return new Uint8Array(hex.match(/../g)!.map((h) => parseInt(h, 16)));
}

function sealBytes(k: Uint8Array, plain: Uint8Array): Uint8Array {
  const nonce = getRandomBytes(12);
  const sealed = gcm(k, nonce).encrypt(plain);
  const out = new Uint8Array(nonce.length + sealed.length);
  out.set(nonce);
  out.set(sealed, nonce.length);
  return out;
}

function unsealBytes(k: Uint8Array, data: Uint8Array): Uint8Array {
  return gcm(k, data.slice(0, 12)).decrypt(data.slice(12));
}

async function key(create: boolean): Promise<Uint8Array | null> {
  return withKeyLock(async () => {
    const stored = await secure.get(KEY_NAME);
    if (stored) return fromHex(stored);
    if (!create) return null;
    const fresh = getRandomBytes(32);
    await secure.set(KEY_NAME, toHex(fresh));
    return fresh;
  });
}

async function readIndexRaw(): Promise<OfflineBook[]> {
  const raw = await AsyncStorage.getItem(INDEX_KEY);
  return raw ? (JSON.parse(raw) as OfflineBook[]) : [];
}

async function readIndex(): Promise<OfflineBook[]> {
  const all = await readIndexRaw();
  return all.filter((b) => new Date(b.validUntil).getTime() > Date.now());
}

export async function offlineBooks(): Promise<OfflineBook[]> {
  try {
    return await withIndexLock(async () => {
      await drainPendingCleanupLocked();
      await pruneExpiredOfflineBooksLocked();
      const valid = await readIndex();
      return valid.filter((b) => fileFor(b.slug).exists);
    });
  } catch {
    return [];
  }
}

async function saveIndex(books: OfflineBook[]) {
  await AsyncStorage.setItem(INDEX_KEY, JSON.stringify(books));
}

async function readPendingCleanup(): Promise<string[]> {
  try {
    const raw = await AsyncStorage.getItem(PENDING_CLEANUP_KEY);
    const parsed = raw ? JSON.parse(raw) : [];
    return Array.isArray(parsed) ? parsed.filter((x): x is string => typeof x === 'string' && !!x) : [];
  } catch {
    return [];
  }
}

async function writePendingCleanup(names: string[]) {
  const unique = Array.from(new Set(names));
  if (!unique.length) await AsyncStorage.removeItem(PENDING_CLEANUP_KEY).catch(() => undefined);
  else await AsyncStorage.setItem(PENDING_CLEANUP_KEY, JSON.stringify(unique)).catch(() => undefined);
}

async function enqueuePendingCleanup(names: string[]) {
  if (!names.length) return;
  const existing = await readPendingCleanup();
  await writePendingCleanup([...existing, ...names]);
}

function deleteMediaFiles(fileNames?: string[]): { failed: string[]; error: unknown | null } {
  const failed: string[] = [];
  let firstError: unknown | null = null;
  if (!fileNames?.length) return { failed, error: null };
  for (const name of fileNames) {
    try {
      const mf = mediaFileByName(name);
      if (mf.exists) mf.delete();
    } catch (e) {
      failed.push(name);
      if (firstError === null) firstError = e;
    }
  }
  return { failed, error: firstError };
}

async function drainPendingCleanupLocked() {
  const pending = await readPendingCleanup();
  if (!pending.length) return;
  const res = deleteMediaFiles(pending);
  await writePendingCleanup(res.failed);
}

async function pruneExpiredOfflineBooksLocked() {
  const all = await readIndexRaw();
  const now = Date.now();
  const expired = all.filter((b) => new Date(b.validUntil).getTime() <= now);
  if (!expired.length) return;

  const active = all.filter((b) => new Date(b.validUntil).getTime() > now);
  await saveIndex(active);

  const failedFiles: string[] = [];
  for (const book of expired) {
    const mediaRes = deleteMediaFiles(book.mediaFiles);
    if (mediaRes.failed.length) failedFiles.push(...mediaRes.failed);
    for (const f of [fileFor(book.slug), backupFileFor(book.slug)]) {
      try {
        if (f.exists) f.delete();
      } catch {
        failedFiles.push(f.name);
      }
    }
  }
  if (failedFiles.length) await enqueuePendingCleanup(failedFiles);
}

async function downloadMediaAssets(
  slug: string,
  versionTag: string,
  k: Uint8Array,
  items: NonNullable<OfflineBundle['media']>,
): Promise<{ manifest: Record<string, StoredMediaEntry>; files: string[] }> {
  const manifest: Record<string, StoredMediaEntry> = {};
  const writtenFiles: string[] = [];
  if (!items.length) return { manifest, files: writtenFiles };

  const d = dir();
  if (!d.exists) d.create({ intermediates: true });

  // Deduplicate by ref while keeping order.
  const unique: typeof items = [];
  const seenRefs = new Set<string>();
  for (const item of items) {
    if (!item.ref || !item.url || seenRefs.has(item.ref)) continue;
    seenRefs.add(item.ref);
    unique.push(item);
  }

  const controller = new AbortController();
  let failedError: unknown = null;
  let cursor = 0;

  const worker = async () => {
    while (true) {
      if (controller.signal.aborted) return;
      const idx = cursor++;
      if (idx >= unique.length) return;
      const item = unique[idx];
      let fileName: string | null = null;
      try {
        const res = await fetch(item.url, { signal: controller.signal });
        if (!res.ok) {
          throw new ApiError(res.status, 'media_download_failed', 'دانلود یکی از تصاویر کتاب ممکن نشد.');
        }
        const bytes = new Uint8Array(await res.arrayBuffer());
        if (controller.signal.aborted) return;
        fileName = mediaFileName(slug, versionTag, item.id || String(idx));
        const f = mediaFileByName(fileName);
        f.create({ intermediates: true, overwrite: true });
        await f.write(sealBytes(k, bytes));
        writtenFiles.push(fileName);
        manifest[item.ref] = { file: fileName, mime: item.mime || 'application/octet-stream' };
      } catch (e) {
        if (fileName && mediaFileByName(fileName).exists && !writtenFiles.includes(fileName)) {
          writtenFiles.push(fileName);
        }
        if (failedError === null) failedError = e;
        controller.abort();
        return;
      }
    }
  };

  const workers = Array.from({ length: Math.min(MEDIA_CONCURRENCY, unique.length) }, () => worker());
  await Promise.allSettled(workers);
  if (failedError !== null || controller.signal.aborted) {
    const res = deleteMediaFiles(writtenFiles);
    if (res.failed.length) {
      await withIndexLock(() => enqueuePendingCleanup(res.failed)).catch(() => undefined);
    }
    throw failedError ?? new ApiError(0, 'media_download_failed', 'دانلود یکی از تصاویر کتاب ممکن نشد.');
  }
  return { manifest, files: writtenFiles };
}

export async function saveOfflineBook(bundle: OfflineBundle): Promise<OfflineBook> {
  if (await Device.isRootedExperimentalAsync().catch(() => false)) {
    throw new ApiError(403, 'rooted', 'دانلود آفلاین روی دستگاه‌های روت‌شده برای حفاظت از محتوا غیرفعال است.');
  }
  const slug = bundle.book.slug;
  return withSlugLock(slug, async () => {
    const epoch = clearEpoch;
    const k = (await key(true))!;
    const versionTag = `${Date.now().toString(36)}_${toHex(getRandomBytes(4))}`;

    // Download & encrypt all referenced images BEFORE touching the existing book bundle or index.
    const { manifest: mediaManifest, files: newMediaFiles } = await downloadMediaAssets(
      slug,
      versionTag,
      k,
      bundle.media ?? [],
    );

    const payload: StoredBundle = {
      ...bundle,
      mediaManifest,
    };
    const out = sealBytes(k, utf8Encode(JSON.stringify(payload)));
    const d = dir();
    if (!d.exists) d.create({ intermediates: true });
    const tmp = tempFileFor(slug);
    const hadExisting = fileFor(slug).exists;
    try {
      tmp.create({ intermediates: true, overwrite: true });
      await tmp.write(out);
      if (hadExisting) {
        await fileFor(slug).move(backupFileFor(slug), { overwrite: true });
      }
      await tempFileFor(slug).move(fileFor(slug), { overwrite: true });
    } catch (e) {
      const rollbackMedia = deleteMediaFiles(newMediaFiles);
      if (rollbackMedia.failed.length) {
        await withIndexLock(() => enqueuePendingCleanup(rollbackMedia.failed)).catch(() => undefined);
      }
      const leftoverTmp = tempFileFor(slug);
      if (leftoverTmp.exists) leftoverTmp.delete();
      const bak = backupFileFor(slug);
      if (bak.exists && !fileFor(slug).exists) {
        await bak.move(fileFor(slug), { overwrite: true }).catch(() => undefined);
      }
      throw e;
    }

    const entry: OfflineBook = {
      slug,
      title: bundle.book.title,
      sectionIds: bundle.sections.map((s) => s.id),
      downloadedAt: bundle.downloaded_at,
      validUntil: bundle.valid_until,
      bookUpdatedOn: bundle.book.updated_on ?? null,
      mediaFiles: newMediaFiles.length ? newMediaFiles : undefined,
    };
    let oldMediaFiles: string[] | undefined;
    try {
      await withIndexLock(async () => {
        if (epoch !== clearEpoch) {
          throw new ApiError(401, 'signed_out', 'نشست کاربر بسته شده است.');
        }
        const existing = await readIndex();
        oldMediaFiles = existing.find((b) => b.slug === entry.slug)?.mediaFiles;
        const books = existing.filter((b) => b.slug !== entry.slug);
        await saveIndex([...books, entry]);
      });
    } catch (e) {
      const rollbackMedia = deleteMediaFiles(newMediaFiles);
      if (rollbackMedia.failed.length) {
        await withIndexLock(() => enqueuePendingCleanup(rollbackMedia.failed)).catch(() => undefined);
      }
      const written = fileFor(slug);
      if (written.exists) written.delete();
      const bak = backupFileFor(slug);
      if (bak.exists) {
        await bak.move(fileFor(slug), { overwrite: true }).catch(() => undefined);
      }
      throw e;
    }

    // Commit succeeded: remove superseded backup and old version's media files.
    const bak = backupFileFor(slug);
    if (bak.exists) {
      try {
        bak.delete();
      } catch {
        // backup cleanup is best-effort after durable index commit
      }
    }
    const oldMediaRes = deleteMediaFiles(oldMediaFiles);
    if (oldMediaRes.failed.length) {
      await withIndexLock(() => enqueuePendingCleanup(oldMediaRes.failed)).catch(() => undefined);
    }
    return entry;
  });
}

async function readBundle(slug: string): Promise<{ bundle: StoredBundle; key: Uint8Array } | null> {
  if (await Device.isRootedExperimentalAsync().catch(() => false)) return null;
  const k = await key(false);
  const f = fileFor(slug);
  if (!k || !f.exists) return null;
  try {
    const data = await f.bytes();
    const plain = unsealBytes(k, data);
    return { bundle: JSON.parse(utf8Decode(plain)) as StoredBundle, key: k };
  } catch {
    return null;
  }
}

async function injectOfflineMedia(text: string, bundle: StoredBundle, k: Uint8Array): Promise<string> {
  if (!text || !text.includes('media:content/') || !bundle.mediaManifest) return text;

  const refs = new Set<string>();
  for (const m of text.matchAll(MEDIA_REF_RE)) {
    if (bundle.mediaManifest[m[2]]) refs.add(m[2]);
  }
  if (!refs.size) return text;

  const dataUrls = new Map<string, string>();
  await Promise.all(
    Array.from(refs).map(async (ref) => {
      const meta = bundle.mediaManifest![ref];
      if (!meta) return;
      try {
        const mf = mediaFileByName(meta.file);
        if (!mf.exists) return;
        const encrypted = await mf.bytes();
        const plain = unsealBytes(k, encrypted);
        dataUrls.set(ref, `data:${meta.mime};base64,${bytesToBase64(plain)}`);
      } catch {
        // missing or corrupted media asset falls back without crashing section open
      }
    }),
  );

  return text.replace(MEDIA_REF_RE, (full, alt: string, ref: string) => {
    const dataUri = dataUrls.get(ref);
    return dataUri ? `![${alt}](${dataUri})` : full;
  });
}

/** A section (or chapter intro) from an offline book, if downloaded and not expired, with its images hydrated as data: URIs. */
export async function offlineSection(id: number): Promise<OfflineSection | null> {
  const book = (await offlineBooks()).find((b) => b.sectionIds.includes(id));
  if (!book) return null;
  const loaded = await readBundle(book.slug);
  if (!loaded) return null;
  const { bundle, key: k } = loaded;
  const section = bundle.sections.find((s) => s.id === id);
  if (!section) return null;

  const [summary, full] = await Promise.all([
    injectOfflineMedia(section.summary, bundle, k),
    injectOfflineMedia(section.full, bundle, k),
  ]);

  return {
    ...section,
    summary,
    full,
    bookSlug: book.slug,
    bookTitle: book.title,
    labels: bundle.labels,
    macros: bundle.macros,
  };
}

/** Reconstructs a `BookDetail`-compatible view from the encrypted offline bundle for Airplane Mode browsing. */
export async function offlineBookDetail(slug: string): Promise<BookDetail | null> {
  const entry = (await offlineBooks()).find((b) => b.slug === slug);
  if (!entry) return null;
  const loaded = await readBundle(slug);
  if (!loaded) return null;
  const { bundle } = loaded;

  const chapters: ChapterSummary[] = [];
  const byChapterKey = new Map<string, ChapterSummary>();
  for (const item of bundle.sections) {
    if (item.kind === 'chapter') {
      const ch: ChapterSummary = {
        id: item.id,
        slug: `ch-${item.id}`,
        kind: 'chapter',
        title: item.title,
        is_locked: false,
        has_overview: true,
        sections: [],
        question_count: 0,
        flashcard_count: 0,
      };
      chapters.push(ch);
      byChapterKey.set(`${item.chapter_number ?? ''}:${item.chapter_title ?? item.title}`, ch);
      continue;
    }
    const keyName = `${item.chapter_number ?? ''}:${item.chapter_title ?? ''}`;
    let ch = byChapterKey.get(keyName);
    if (!ch) {
      ch = {
        id: -item.id,
        slug: `ch-${item.id}`,
        kind: 'chapter',
        title: item.chapter_title || bundle.book.title,
        is_locked: false,
        has_overview: false,
        sections: [],
        question_count: 0,
        flashcard_count: 0,
      };
      chapters.push(ch);
      byChapterKey.set(keyName, ch);
    }
    const sec: NodeSummary = {
      id: item.id,
      slug: `sec-${item.id}`,
      kind: 'section',
      title: item.title,
      is_locked: false,
      has_summary: Boolean(item.summary),
    };
    ch.sections.push(sec);
  }

  return {
    id: 0,
    slug: bundle.book.slug,
    title: bundle.book.title,
    title_en: '',
    author: '',
    edition: '',
    motif: '',
    drawing: null,
    cover: null,
    is_coming_soon: false,
    product_status: { state: 'free', preview: 'none', promotion: 'none' },
    price: null,
    regular_price: null,
    discount: null,
    chapter_count: chapters.length,
    section_count: bundle.sections.filter((s) => s.kind !== 'chapter').length,
    free_chapter: null,
    owned: true,
    progress: null,
    notify: false,
    about: 'نسخه‌ی آفلاین ذخیره‌شده روی این دستگاه.',
    majors: [],
    chapters,
    done_ids: [],
    read_ids: [],
    done_card_count: 0,
    updated_on: bundle.book.updated_on ?? null,
  };
}

export async function removeOfflineBook(slug: string) {
  return withSlugLock(slug, () =>
    withIndexLock(async () => {
      const existing = await readIndexRaw();
      const target = existing.find((b) => b.slug === slug);
      await saveIndex(existing.filter((b) => b.slug !== slug));

      const mediaRes = deleteMediaFiles(target?.mediaFiles);
      if (mediaRes.failed.length) {
        await saveIndex(
          existing.map((b) => (b.slug === slug ? { ...b, mediaFiles: mediaRes.failed } : b)),
        ).catch(() => undefined);
        await enqueuePendingCleanup(mediaRes.failed);
        throw mediaRes.error ?? new Error('Failed to delete offline media files');
      }

      try {
        const f = fileFor(slug);
        if (f.exists) f.delete();
        const bak = backupFileFor(slug);
        if (bak.exists) bak.delete();
      } catch (e) {
        await saveIndex(
          existing.map((b) => (b.slug === slug ? { ...b, mediaFiles: undefined } : b)),
        ).catch(() => undefined);
        throw e;
      }
    }),
  );
}

/** Remove downloaded offline books that an admin explicitly wiped on revocation, plus expired books and pending deletes. */
export async function reconcileOfflineRevocations(revocations?: OfflineRevocation[]) {
  await withIndexLock(async () => {
    await drainPendingCleanupLocked();
    await pruneExpiredOfflineBooksLocked();
  }).catch(() => undefined);

  if (!revocations?.length) return;
  const bySlug = new Map(revocations.map((r) => [r.slug, Date.parse(r.revoked_at)]));
  const books = await offlineBooks();
  for (const book of books) {
    const revokedAt = bySlug.get(book.slug);
    if (revokedAt === undefined || Number.isNaN(revokedAt)) continue;
    const downloadedAt = Date.parse(book.downloadedAt);
    if (Number.isNaN(downloadedAt) || revokedAt >= downloadedAt) {
      try {
        await removeOfflineBook(book.slug);
      } catch {
        // continue reconciling remaining books if one removal fails
      }
    }
  }
}

export async function clearOffline() {
  clearEpoch += 1;
  await withIndexLock(() =>
    withKeyLock(async () => {
      try {
        const d = dir();
        if (d.exists) d.delete();
      } catch {
        // nothing stored
      }
      await AsyncStorage.removeItem(INDEX_KEY).catch(() => undefined);
      await AsyncStorage.removeItem(PENDING_CLEANUP_KEY).catch(() => undefined);
      await secure.set(KEY_NAME, null);
    }),
  );
}
