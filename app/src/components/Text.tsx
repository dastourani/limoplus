import type { ComponentProps } from 'react';
import { StyleSheet, Text as RNText, TextInput as RNTextInput } from 'react-native';

import { fontFamilyFor } from '../lib/fonts';

function withFont<S>(style: S) {
  const flat = StyleSheet.flatten(style as never) as { fontWeight?: string | number; fontFamily?: string } | undefined;
  if (flat?.fontFamily) return style;
  // fontWeight is dropped: with a custom family Android would otherwise fall back to synthetic bold.
  return [style, { fontFamily: fontFamilyFor(flat?.fontWeight), fontWeight: 'normal' as const }];
}

/** Text in the app font (Vazirmatn); fontWeight picks the matching weight file. Use instead of react-native's Text. */
// Follows the phone's text-size setting, up to 1.3× so layouts and buttons stay intact.
const MAX_SCALE = 1.3;

export function Text({ style, ...props }: ComponentProps<typeof RNText>) {
  return <RNText maxFontSizeMultiplier={MAX_SCALE} {...props} style={withFont(style)} />;
}

export function TextInput({ style, ...props }: ComponentProps<typeof RNTextInput>) {
  return <RNTextInput maxFontSizeMultiplier={MAX_SCALE} {...props} style={withFont(style)} />;
}
