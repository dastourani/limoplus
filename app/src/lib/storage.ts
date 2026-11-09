import AsyncStorage from '@react-native-async-storage/async-storage';

const KEYS = {
  serverUrl: 'limo.serverUrl',
  major: 'limo.major',
  lastSection: 'limo.lastSection',
  reader: 'limo.reader',
  reading: 'limo.reading',
} as const;

export type ReaderTheme = 'white' | 'paper' | 'sepia' | 'dark';
/** justify: lesson paragraphs aligned on both sides (the default); false keeps them right-aligned. */
export type ReaderPrefs = { fontSize: number; dark?: boolean; theme?: ReaderTheme; lineHeight?: number; justify?: boolean };

export type LastSection = { id: number; title: string; bookTitle: string; bookSlug: string };
/** Where the reader is in one book: the section, notes or summary, and how far down (0–100). */
export type ReadingSpot = LastSection & { mode: 'full' | 'summary'; percent: number; at: number };

async function getJson<T>(key: string): Promise<T | null> {
  try {
    const raw = await AsyncStorage.getItem(key);
    return raw ? (JSON.parse(raw) as T) : null;
  } catch {
    return null;
  }
}

async function setJson(key: string, value: unknown) {
  try {
    if (value === null) await AsyncStorage.removeItem(key);
    else await AsyncStorage.setItem(key, JSON.stringify(value));
  } catch {
    // Storage is a convenience; the app works without it.
  }
}

export const storage = {
  /** «درباره‌ی کتاب»: 'seen' once shown in full (folded from then on), 'open' when the learner opened it (stays open). */
  getAbout: async (slug: string) => (await getJson<Record<string, 'seen' | 'open'>>('limo.about'))?.[slug] ?? null,
  setAbout: async (slug: string, value: 'seen' | 'open') => {
    const all = (await getJson<Record<string, 'seen' | 'open'>>('limo.about')) ?? {};
    all[slug] = value;
    await setJson('limo.about', all);
  },
  getServerUrl: () => getJson<string>(KEYS.serverUrl),
  setServerUrl: (url: string | null) => setJson(KEYS.serverUrl, url),
  getMajor: () => getJson<{ slug: string; name: string; color: string }>(KEYS.major),
  setMajor: (major: { slug: string; name: string; color: string } | null) => setJson(KEYS.major, major),
  getLastSection: () => getJson<LastSection>(KEYS.lastSection),
  setLastSection: (value: LastSection) => setJson(KEYS.lastSection, value),
  getReading: async () => (await getJson<Record<string, ReadingSpot>>(KEYS.reading)) ?? {},
  /** Remembers the spot in this book (one per book, the 20 most recent books). */
  setReading: async (spot: ReadingSpot) => {
    const all = (await getJson<Record<string, ReadingSpot>>(KEYS.reading)) ?? {};
    all[spot.bookSlug] = spot;
    const keep = Object.values(all).sort((a, b) => b.at - a.at).slice(0, 20);
    await setJson(KEYS.reading, Object.fromEntries(keep.map((s) => [s.bookSlug, s])));
  },
  getReader: () => getJson<ReaderPrefs>(KEYS.reader),
  setReader: (value: ReaderPrefs) => setJson(KEYS.reader, value),
};
