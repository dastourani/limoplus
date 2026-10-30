import AsyncStorage from '@react-native-async-storage/async-storage';

const KEYS = {
  serverUrl: 'limo.serverUrl',
  major: 'limo.major',
  lastSection: 'limo.lastSection',
  reader: 'limo.reader',
} as const;

export type ReaderPrefs = { fontSize: number; dark: boolean };

export type LastSection = { id: number; title: string; bookTitle: string; bookSlug: string };

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
  getServerUrl: () => getJson<string>(KEYS.serverUrl),
  setServerUrl: (url: string | null) => setJson(KEYS.serverUrl, url),
  getMajor: () => getJson<{ slug: string; name: string; color: string }>(KEYS.major),
  setMajor: (major: { slug: string; name: string; color: string } | null) => setJson(KEYS.major, major),
  getLastSection: () => getJson<LastSection>(KEYS.lastSection),
  setLastSection: (value: LastSection) => setJson(KEYS.lastSection, value),
  getReader: () => getJson<ReaderPrefs>(KEYS.reader),
  setReader: (value: ReaderPrefs) => setJson(KEYS.reader, value),
};
