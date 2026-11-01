/**
 * A banner drawn from a template, like the book covers: «تخفیف» (with a countdown), «کتاب تازه» (with the book's own
 * cover), «یادآوری» (with a subject motif) and the plain lemon card. An uploaded image replaces the template.
 * The panel's preview draws the same layouts (admin-preview `bannerHtml`).
 */
import { useMemo } from 'react';
import { Image, StyleSheet, View } from 'react-native';
import { SvgXml } from 'react-native-svg';

import type { Banner } from '../api/endpoints';
import { coverMotifSvg } from '../lib/cover';
import { colors, rtl } from '../theme';
import { BookCover } from './BookCover';
import { Icon } from './Icon';
import { LemonSlice } from './LemonSlice';
import { Text } from './Text';

export function BannerFace({ banner: b, w, h, left }: { banner: Banner; w: number; h: number; left: string | null }) {
  const k = h / 180;
  const motif = useMemo(() => (b.template === 'exam' ? coverMotifSvg(b.motif || 'book', 'dark') : ''), [b.template, b.motif]);
  if (b.image) return <Image source={{ uri: b.image }} style={[styles.image, { width: w, height: h }]} resizeMode="cover" />;

  const text = (dark: boolean) => (
    <View style={{ gap: 6 * k, maxWidth: w * 0.62 }}>
      {!!b.subtitle && <Text style={[styles.small, rtl, { fontSize: 12 * k, color: dark ? colors.lemon : colors.greenDark }]}>{b.subtitle}</Text>}
      <Text style={[styles.title, rtl, { fontSize: 21 * k, lineHeight: 31 * k, color: dark ? '#FFFFFF' : colors.ink }]} numberOfLines={3}>
        {b.title}
      </Text>
      <View style={styles.row}>
        {!!b.button && (
          <View style={[styles.button, { paddingHorizontal: 14 * k, paddingVertical: 6 * k, backgroundColor: dark ? colors.lemon : colors.ink }]}>
            <Text style={{ fontSize: 13 * k, fontWeight: '800', color: dark ? colors.ink : colors.lemon }}>{b.button}</Text>
          </View>
        )}
        {!!left && (
          <View style={[styles.clock, { paddingHorizontal: 10 * k, paddingVertical: 5 * k, backgroundColor: dark ? 'rgba(255,255,255,0.12)' : '#FFFFFF' }]}>
            <Icon name="timer" size={14 * k} color={dark ? colors.lemon : colors.ink} />
            <Text style={{ fontSize: 13 * k, fontWeight: '800', color: dark ? '#FFFFFF' : colors.ink, fontVariant: ['tabular-nums'] }}>{left}</Text>
          </View>
        )}
      </View>
    </View>
  );

  if (b.template === 'book' && b.book) {
    return (
      <View style={[styles.card, { height: h, backgroundColor: '#F4F0E3', padding: 16 * k }]}>
        <View style={[styles.bookAt, { left: 18 * k, top: h * 0.1, transform: [{ rotate: '-5deg' }] }]}>
          <BookCover book={b.book} major={b.book.major} width={h * 0.54} theme="dark" />
        </View>
        {text(false)}
      </View>
    );
  }
  if (b.template === 'exam') {
    return (
      <View style={[styles.card, { height: h, backgroundColor: '#123B35', padding: 16 * k }]}>
        <View style={[styles.motif, { left: -h * 0.05, width: h * 1.15, height: h * 0.8 }]}>
          <SvgXml xml={motif} width="100%" height="100%" />
        </View>
        {text(true)}
      </View>
    );
  }
  // «تخفیف» and the plain lemon card
  return (
    <View style={[styles.card, { height: h, padding: 16 * k }]}>
      <View style={[styles.lemon, { width: h * 1.1, height: h * 1.1, left: -h * 0.3, bottom: -h * 0.35 }]}>
        <LemonSlice size={h * 1.1} />
      </View>
      {b.template === 'sale' ? (
        text(true)
      ) : (
        <View style={{ paddingLeft: h * 0.7, gap: 4 }}>
          <Text style={[styles.small, rtl, { color: '#B9C4BC' }]}>{b.subtitle || 'ویژه'}</Text>
          <Text style={[styles.title, rtl, { color: colors.lemon, fontSize: 20, lineHeight: 30 }]} numberOfLines={3}>
            {b.title}
          </Text>
          {!!left && <Text style={[styles.small, rtl, { color: '#FFFFFF' }]}>{left}</Text>}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  image: { borderRadius: 22, backgroundColor: colors.line },
  card: { flex: 1, borderRadius: 22, backgroundColor: colors.ink, justifyContent: 'center', alignItems: 'flex-end', overflow: 'hidden' },
  lemon: { position: 'absolute', opacity: 0.95 },
  motif: { position: 'absolute', top: '10%', opacity: 0.9 },
  bookAt: { position: 'absolute' },
  small: { fontWeight: '700' },
  title: { fontWeight: '900' },
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, flexWrap: 'wrap' },
  button: { borderRadius: 999 },
  clock: { flexDirection: 'row-reverse', alignItems: 'center', gap: 5, borderRadius: 999 },
});
