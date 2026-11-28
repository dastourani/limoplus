/** «قوانین به‌روز شد»: a site page whose last important change came after the learner last opened it. The first time
 * the app sees the list it remembers that moment, so a new learner (who accepted the current text at login) is not told. */
import AsyncStorage from '@react-native-async-storage/async-storage';

import type { SitePageItem } from '../api/endpoints';

const KEY = 'limo.pagesSeen';
type Seen = { since: string; pages: Record<string, string> };

async function read(): Promise<Seen | null> {
  try {
    const raw = await AsyncStorage.getItem(KEY);
    return raw ? (JSON.parse(raw) as Seen) : null;
  } catch {
    return null;
  }
}

async function write(s: Seen) {
  try {
    await AsyncStorage.setItem(KEY, JSON.stringify(s));
  } catch {
    // A convenience only.
  }
}

/** The pages with an important change not yet opened. */
export async function changedPages(pages: SitePageItem[]): Promise<SitePageItem[]> {
  let s = await read();
  if (!s) {
    s = { since: new Date().toISOString(), pages: {} };
    await write(s);
    return [];
  }
  const seen = s;
  return pages.filter((p) => {
    if (!p.important_at) return false;
    const last = seen.pages[p.slug] ?? seen.since;
    return Date.parse(p.important_at) > Date.parse(last);
  });
}

export async function markPageSeen(slug: string) {
  const s = (await read()) ?? { since: new Date().toISOString(), pages: {} };
  s.pages[slug] = new Date().toISOString();
  await write(s);
}
