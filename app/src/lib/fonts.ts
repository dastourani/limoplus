import { Vazirmatn_400Regular } from '@expo-google-fonts/vazirmatn/400Regular';
import { Vazirmatn_700Bold } from '@expo-google-fonts/vazirmatn/700Bold';
import { Vazirmatn_800ExtraBold } from '@expo-google-fonts/vazirmatn/800ExtraBold';
import { Vazirmatn_900Black } from '@expo-google-fonts/vazirmatn/900Black';

/**
 * Vazirmatn (SIL Open Font License, free for commercial use).
 * On Android the files are also embedded at build time by the expo-font plugin (see app.json), so the family
 * names below equal the file names, and lesson WebViews load them from file:///android_asset/fonts/.
 */
export const FONT_FILES = {
  Vazirmatn_400Regular,
  Vazirmatn_700Bold,
  Vazirmatn_800ExtraBold,
  Vazirmatn_900Black,
};

/** Family for a fontWeight. Custom fonts on Android ignore fontWeight, so each weight is its own family. */
export function fontFamilyFor(weight: string | number | undefined): string {
  const w = Number(weight === 'bold' ? 700 : weight === 'normal' || weight == null ? 400 : weight);
  if (w >= 900) return 'Vazirmatn_900Black';
  if (w >= 800) return 'Vazirmatn_800ExtraBold';
  if (w >= 600) return 'Vazirmatn_700Bold';
  return 'Vazirmatn_400Regular';
}

/** @font-face rules for lesson HTML; `url` maps a family name to where the file can be loaded. */
export function fontFaceCss(url: (family: 'Vazirmatn_400Regular' | 'Vazirmatn_700Bold') => string): string {
  return (
    `@font-face{font-family:Vazirmatn;font-weight:400;font-display:swap;src:url("${url('Vazirmatn_400Regular')}") format("truetype")}` +
    `@font-face{font-family:Vazirmatn;font-weight:700 900;font-display:swap;src:url("${url('Vazirmatn_700Bold')}") format("truetype")}`
  );
}
