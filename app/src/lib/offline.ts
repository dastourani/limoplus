/**
 * Encrypted offline books (phone app only).
 *
 * A book's readable sections are downloaded once and stored encrypted with AES-256-GCM. The key is random per
 * install and lives in the Android keystore-backed secure store, so copying the files off the phone is useless.
 * Downloads expire (the server sets valid_until, 30 days) and are wiped on sign-out.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';
import { gcm } from '@noble/ciphers/aes';
import { getRandomBytes } from 'expo-crypto';
import * as Device from 'expo-device';
import { Directory, File, Paths } from 'expo-file-system';

import { ApiError } from '../api/client';
import type { OfflineBundle, OfflineRevocation } from '../api/endpoints';
import { secure } from './secure';
import { utf8Decode, utf8Encode } from './utf8';

const KEY_NAME = 'limo.offlineKey';
const INDEX_KEY = 'limo.offlineIndex';

export type OfflineBook = { slug: string; title: string; sectionIds: number[]; downloadedAt: string; validUntil: string };
export type OfflineSection = OfflineBundle['sections'][number] & { bookSlug: string; bookTitle: string };

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

function fileFor(slug: string) {
  return new File(dir(), `${slug.replace(/[^\w-]/g, '_')}.bin`);
}

function tempFileFor(slug: string) {
  return new File(dir(), `${slug.replace(/[^\w-]/g, '_')}.bin.tmp`);
}

function backupFileFor(slug: string) {
  return new File(dir(), `${slug.replace(/[^\w-]/g, '_')}.bin.bak`);
}

function toHex(bytes: Uint8Array) {
  return Array.from(bytes, (b) => b.toString(16).padStart(2, '0')).join('');
}

function fromHex(hex: string) {
  return new Uint8Array(hex.match(/../g)!.map((h) => parseInt(h, 16)));
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

async function readIndex(): Promise<OfflineBook[]> {
  const raw = await AsyncStorage.getItem(INDEX_KEY);
  const all = raw ? (JSON.parse(raw) as OfflineBook[]) : [];
  return all.filter((b) => new Date(b.validUntil).getTime() > Date.now());
}

export async function offlineBooks(): Promise<OfflineBook[]> {
  try {
    const valid = await readIndex();
    return valid.filter((b) => fileFor(b.slug).exists);
  } catch {
    return [];
  }
}

async function saveIndex(books: OfflineBook[]) {
  await AsyncStorage.setItem(INDEX_KEY, JSON.stringify(books));
}

export async function saveOfflineBook(bundle: OfflineBundle): Promise<OfflineBook> {
  if (await Device.isRootedExperimentalAsync().catch(() => false)) {
    throw new ApiError(403, 'rooted', 'دانلود آفلاین روی دستگاه‌های روت‌شده برای حفاظت از محتوا غیرفعال است.');
  }
  const slug = bundle.book.slug;
  return withSlugLock(slug, async () => {
    const epoch = clearEpoch;
    const k = (await key(true))!;
    const nonce = getRandomBytes(12);
    const sealed = gcm(k, nonce).encrypt(utf8Encode(JSON.stringify(bundle)));
    const out = new Uint8Array(nonce.length + sealed.length);
    out.set(nonce);
    out.set(sealed, nonce.length);
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
    };
    try {
      await withIndexLock(async () => {
        if (epoch !== clearEpoch) {
          throw new ApiError(401, 'signed_out', 'نشست کاربر بسته شده است.');
        }
        const existing = await readIndex();
        const books = existing.filter((b) => b.slug !== entry.slug);
        await saveIndex([...books, entry]);
      });
    } catch (e) {
      const written = fileFor(slug);
      if (written.exists) written.delete();
      const bak = backupFileFor(slug);
      if (bak.exists) {
        await bak.move(fileFor(slug), { overwrite: true }).catch(() => undefined);
      }
      throw e;
    }
    const bak = backupFileFor(slug);
    if (bak.exists) {
      try {
        bak.delete();
      } catch {
        // backup cleanup is best-effort after durable index commit
      }
    }
    return entry;
  });
}

async function readBundle(slug: string): Promise<OfflineBundle | null> {
  if (await Device.isRootedExperimentalAsync().catch(() => false)) return null;
  const k = await key(false);
  const f = fileFor(slug);
  if (!k || !f.exists) return null;
  try {
    const data = await f.bytes();
    const plain = gcm(k, data.slice(0, 12)).decrypt(data.slice(12));
    return JSON.parse(utf8Decode(plain)) as OfflineBundle;
  } catch {
    return null;
  }
}

/** A section from an offline book, if downloaded and not expired. */
export async function offlineSection(id: number): Promise<OfflineSection | null> {
  const book = (await offlineBooks()).find((b) => b.sectionIds.includes(id));
  if (!book) return null;
  const bundle = await readBundle(book.slug);
  const section = bundle?.sections.find((s) => s.id === id);
  return section ? { ...section, bookSlug: book.slug, bookTitle: book.title } : null;
}

export async function removeOfflineBook(slug: string) {
  return withSlugLock(slug, () =>
    withIndexLock(async () => {
      const existing = await readIndex();
      await saveIndex(existing.filter((b) => b.slug !== slug));
      try {
        const f = fileFor(slug);
        if (f.exists) f.delete();
        const bak = backupFileFor(slug);
        if (bak.exists) bak.delete();
      } catch (e) {
        await saveIndex(existing).catch(() => undefined);
        throw e;
      }
    }),
  );
}

/** Remove downloaded offline books that an admin explicitly wiped on revocation. */
export async function reconcileOfflineRevocations(revocations?: OfflineRevocation[]) {
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
      await secure.set(KEY_NAME, null);
    }),
  );
}
