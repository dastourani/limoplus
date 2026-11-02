import { memo, useMemo } from 'react';
import { Image, StyleSheet, View } from 'react-native';
import { SvgXml } from 'react-native-svg';

import { coverByline, coverMotifSvg, coverPalette, type CoverTheme } from '../lib/cover';
import { useCoverTheme } from '../lib/coverTheme';
import { LemonSlice } from './LemonSlice';
import { Text } from './Text';

export type CoverBook = {
  title: string;
  title_en?: string;
  author?: string;
  edition?: string;
  motif?: string;
  /** The book's own line drawing (motif «custom»), as the server cleaned it. */
  drawing?: { viewBox: string; body: string } | null;
  /** An uploaded cover picture replaces the drawn cover. */
  cover?: string | null;
};

/**
 * A book's cover, drawn from one template: the major's colour strip, the subject's line motif, the title, the
 * English name, author and edition, and the LimoPlus mark. 2:3, any width; dark or light by the learner's choice.
 */
export const BookCover = memo(function BookCover({
  book,
  major,
  width = 240,
  theme: forced,
  edge = false,
}: {
  book: CoverBook;
  major?: { name: string; color: string } | null;
  width?: number;
  theme?: CoverTheme;
  /** A thin lemon frame, so a dark cover stands out on a dark screen. */
  edge?: boolean;
}) {
  const chosen = useCoverTheme();
  const theme = forced ?? chosen;
  const p = coverPalette(theme);
  const k = width / 240;
  const strip = major?.color || '#3FB8A9';
  const xml = useMemo(() => coverMotifSvg(book.motif || 'ct', theme, book.drawing), [book.motif, book.drawing, theme]);
  const byline = coverByline(book.author, book.edition);
  const frame = {
    width,
    height: width * 1.5,
    borderRadius: 10 * k,
    backgroundColor: p.bg,
    borderWidth: edge ? 1 : 0,
    borderColor: 'rgba(245,197,24,0.38)',
  };

  if (book.cover) {
    return (
      <View style={[styles.shadow, frame, { overflow: 'hidden' }]} accessibilityLabel={`جلد کتاب ${book.title}`}>
        <Image source={{ uri: book.cover }} style={StyleSheet.absoluteFill} resizeMode="cover" />
      </View>
    );
  }

  return (
    <View style={[styles.shadow, frame, { overflow: 'hidden' }]} accessibilityLabel={`جلد کتاب ${book.title}`}>
      <View style={{ height: 6 * k, backgroundColor: strip }} />
      {!!major?.name && (
        <Text allowFontScaling={false} style={[styles.major, { fontSize: 10 * k, color: strip, paddingHorizontal: 18 * k, paddingTop: 12 * k }]}>
          لیمو {major.name}
        </Text>
      )}
      <View style={[styles.motif, { paddingHorizontal: 14 * k, paddingTop: 6 * k }]}>
        <SvgXml xml={xml} width={208 * k} height={146 * k} />
      </View>
      <View style={{ paddingHorizontal: 18 * k, paddingBottom: 16 * k, gap: 3 * k }}>
        <Text allowFontScaling={false} numberOfLines={2} style={[styles.title, { fontSize: 21 * k, lineHeight: 30 * k, color: p.title }]}>
          {book.title}
        </Text>
        {!!book.title_en && (
          <Text allowFontScaling={false} numberOfLines={1} style={[styles.en, { fontSize: 11 * k, color: p.muted }]}>
            {book.title_en}
          </Text>
        )}
        {!!byline && (
          <Text allowFontScaling={false} numberOfLines={1} style={[styles.byline, { fontSize: 11 * k, color: p.muted }]}>
            {byline}
          </Text>
        )}
        <View style={{ height: 2 * k, width: 34 * k, borderRadius: 2, backgroundColor: p.rule, marginTop: 8 * k, marginBottom: 6 * k }} />
        <View style={styles.brand}>
          <LemonSlice size={16 * k} />
          <Text allowFontScaling={false} style={{ fontSize: 10 * k, fontWeight: '700', color: p.brand }}>
            لیمو پلاس
          </Text>
        </View>
      </View>
    </View>
  );
});

const styles = StyleSheet.create({
  // A light shadow: many covers with a heavy one made scrolling stutter on slower Android phones.
  shadow: { shadowColor: '#17201A', shadowOpacity: 0.18, shadowRadius: 8, shadowOffset: { width: 0, height: 4 }, elevation: 3 },
  major: { fontWeight: '700', textAlign: 'right', writingDirection: 'rtl' },
  motif: { flex: 1, alignItems: 'center', justifyContent: 'center' },
  title: { fontWeight: '900', textAlign: 'right', writingDirection: 'rtl' },
  en: { fontStyle: 'italic', textAlign: 'right', writingDirection: 'ltr' },
  byline: { textAlign: 'right', writingDirection: 'rtl' },
  brand: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
});
