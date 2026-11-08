import { StyleSheet, Text, View } from 'react-native';

import { hasFormula, quoteMarkdown, quoteText } from '../lib/noteQuote';
import { colors, rtl } from '../theme';
import { MarkdownView } from './MarkdownView';

/**
 * The highlighted words above a note (the coloured strip). Formulas are drawn as in the book, a fraction as a
 * fraction, an integral as an integral; plain words stay plain text (lighter, and the same as before).
 * maxHeight: in lists, a long quote is cut (the note opens in full).
 */
export function QuoteView({ quote, color, maxHeight }: { quote: string; color?: string; maxHeight?: number }) {
  const bg = { backgroundColor: color ?? '#FFE98A' };
  if (!hasFormula(quote)) return <Text style={[styles.text, rtl, bg]}>{quoteText(quote)}</Text>;
  return (
    // Taps go through to the note row around it (a WebView would keep them on the phone).
    <View pointerEvents="none" style={[styles.box, bg, maxHeight ? { maxHeight, overflow: 'hidden' } : null]}>
      <MarkdownView markdown={quoteMarkdown(quote)} compact fontSize={15} />
    </View>
  );
}

const styles = StyleSheet.create({
  text: { fontSize: 15, lineHeight: 28, color: colors.ink, borderRadius: 8, padding: 8 },
  box: { borderRadius: 8, paddingHorizontal: 8, paddingVertical: 6 },
});
