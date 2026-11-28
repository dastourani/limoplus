/** The phone keeps the last «دستورهای فرمول» for offline reading; at start the kept list comes first, then the server's. */
import AsyncStorage from '@react-native-async-storage/async-storage';

import { macros, onMacrosChange, setMacros } from './macros';

const KEY = 'limo.macros';

export async function loadMacros(fetchList: () => Promise<{ macros: Record<string, string> }>) {
  onMacrosChange((list) => AsyncStorage.setItem(KEY, JSON.stringify(list)).catch(() => undefined));
  try {
    const kept = await AsyncStorage.getItem(KEY);
    if (kept && !Object.keys(macros()).length) setMacros(JSON.parse(kept));
  } catch {
    // nothing kept
  }
  fetchList()
    .then((r) => setMacros(r.macros))
    .catch(() => undefined);
}
