import AsyncStorage from '@react-native-async-storage/async-storage';
import { useEffect, useState } from 'react';

import type { CoverTheme } from './cover';

/** The learner's choice of cover look (profile › «جلد کتاب‌ها»); dark by default. Shared by every screen. */
const KEY = 'limo.coverTheme';
let current: CoverTheme = 'dark';
let loaded = false;
const listeners = new Set<(t: CoverTheme) => void>();

async function load() {
  if (loaded) return current;
  try {
    const raw = await AsyncStorage.getItem(KEY);
    if (raw === 'light' || raw === 'dark') current = raw;
  } catch {
    // Storage is a convenience; dark covers it is.
  }
  loaded = true;
  return current;
}

export async function setCoverTheme(theme: CoverTheme) {
  current = theme;
  loaded = true;
  listeners.forEach((l) => l(theme));
  try {
    await AsyncStorage.setItem(KEY, theme);
  } catch {
    // ignore
  }
}

export function useCoverTheme(): CoverTheme {
  const [theme, setTheme] = useState<CoverTheme>(current);
  useEffect(() => {
    let alive = true;
    load().then((t) => alive && setTheme(t));
    listeners.add(setTheme);
    return () => {
      alive = false;
      listeners.delete(setTheme);
    };
  }, []);
  return theme;
}
