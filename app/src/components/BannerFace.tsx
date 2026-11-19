/**
 * A banner drawn from a template, like the book covers: «تخفیف» (with a countdown), «کتاب تازه» (with the book's own
 * cover), «یادآوری» (with a subject motif) and the plain lemon card. An uploaded image replaces the template.
 * The panel's preview draws the same layouts (admin-preview `bannerHtml`).
 */
import { memo, useMemo } from 'react';
import { Image } from 'expo-image';
import { StyleSheet, View } from 'react-native';
import { SvgXml } from 'react-native-svg';

import type { Banner } from '../api/endpoints';
import { coverMotifSvg } from '../lib/cover';
import { useCountdown } from '../lib/countdown';
import { colors, formatToman, rtl, toPersianDigits } from '../theme';
import { percentLabel } from '../lib/pricing';
import { BookCover } from './BookCover';
import { Icon } from './Icon';
import { LemonSlice } from './LemonSlice';
import { Text } from './Text';

/** Drawn once; only its countdown text ticks (see useCountdown). */
export const BannerFace = memo(function BannerFace({ banner: b, w, h, offset = 0 }: { banner: Banner; w: number; h: number; offset?: number }) {
  const left = useCountdown(b.ends_at, offset);
  const k = h / 180;
  const motif = useMemo(() => (b.template === 'exam' ? coverMotifSvg(b.motif || 'book', 'dark') : ''), [b.template, b.motif]);
  if (b.image) return (
    <View style={[styles.imageWrap, { width: w, height: h }]}>
      <Image source={{ uri: b.image }} style={[styles.image, { width: w, height: h }]} contentFit="cover" cachePolicy="memory-disk" transition={120} />
      {b.discount && (
        <View pointerEvents="none" style={styles.imageDeal}>
          <Text style={styles.imageProduct} numberOfLines={1}>
            {b.discount.product_title}{b.discount.kind === 'plan' ? ` · ${toPersianDigits(b.discount.months ?? 1)} ماه` : ''}
          </Text>
          <View style={styles.saleRow}>
            <Text style={styles.salePrice}>{formatToman(b.discount.price)}</Text>
            <Text style={styles.saleOld}>{formatToman(b.discount.regular_price)}</Text>
            <Text style={styles.saleBadge}>{percentLabel(b.discount.percent)}٪</Text>
          </View>
          {!!left && <Text style={styles.imageCountdown}>تا پایان {left}</Text>}
        </View>
      )}
    </View>
  );

  const text = (dark: boolean) => (
    <View style={{ gap: 6 * k, maxWidth: w * 0.62 }}>
      {!!b.subtitle && <Text style={[styles.small, rtl, { fontSize: 12 * k, color: dark ? colors.lemon : colors.greenDark }]}>{b.subtitle}</Text>}
      <Text style={[styles.title, rtl, { fontSize: 22 * k, lineHeight: 31 * k, color: dark ? '#FFFFFF' : colors.ink }]} numberOfLines={b.discount ? 2 : 3}>
        {b.title}
      </Text>
      {b.discount && (
        <View style={styles.saleSummary}>
          <Text style={[styles.saleProduct, rtl]} numberOfLines={1}>
            {b.discount.product_title}{b.discount.kind === 'plan' ? ` · ${toPersianDigits(b.discount.months ?? 1)} ماه` : ''}
          </Text>
          <View style={styles.saleRow}>
            <Text style={styles.salePrice}>{formatToman(b.discount.price)}</Text>
            <Text style={styles.saleOld}>{formatToman(b.discount.regular_price)}</Text>
            <Text style={styles.saleBadge}>{percentLabel(b.discount.percent)}٪</Text>
          </View>
        </View>
      )}
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
          <Text style={[styles.title, rtl, { color: colors.lemon, fontSize: 22, lineHeight: 30 }]} numberOfLines={3}>
            {b.title}
          </Text>
          {!!left && <Text style={[styles.small, rtl, { color: '#FFFFFF' }]}>{left}</Text>}
        </View>
      )}
    </View>
  );
});

const styles = StyleSheet.create({
  imageWrap: { position: 'relative', overflow: 'hidden', borderRadius: 22, backgroundColor: colors.line },
  image: { borderRadius: 22, backgroundColor: colors.line },
  imageDeal: { position: 'absolute', left: 0, right: 0, bottom: 0, paddingHorizontal: 12, paddingVertical: 8, backgroundColor: 'rgba(23,32,26,0.9)', gap: 2 },
  imageProduct: { color: '#FFFFFF', fontSize: 11, fontWeight: '800', textAlign: 'right', writingDirection: 'rtl' },
  imageCountdown: { color: '#FFFFFF', fontSize: 10, textAlign: 'right', writingDirection: 'rtl' },
  saleSummary: { gap: 2 },
  saleProduct: { color: '#E6ECE7', fontSize: 11, fontWeight: '700' },
  saleRow: { flexDirection: 'row-reverse', alignItems: 'center', gap: 7, flexWrap: 'wrap' },
  salePrice: { color: colors.lemon, fontSize: 14, fontWeight: '900' },
  saleOld: { color: '#C9D3CC', fontSize: 10, textDecorationLine: 'line-through' },
  saleBadge: { color: colors.ink, backgroundColor: colors.lemon, fontSize: 10, fontWeight: '900', borderRadius: 6, paddingHorizontal: 6, paddingVertical: 1, overflow: 'hidden' },
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
