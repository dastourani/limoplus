/**
 * Banners in one frame: swipe between them (first banner on the right, as in a Persian page), dots below, and
 * the next one comes by itself every few seconds unless the learner is touching the frame.
 * A banner with an image shows the image (2:1); without one, a text card with the lemon.
 */
import { useEffect, useRef, useState } from 'react';
import { Image, Pressable, ScrollView, StyleSheet, View, useWindowDimensions, type ScrollViewInstance } from 'react-native';

import type { Banner } from '../api/endpoints';
import { colors, rtl } from '../theme';
import { LemonSlice } from './LemonSlice';
import { Text } from './Text';

const AUTO_MS = 5000;

export function BannerCarousel({ banners, onOpen, gutter = 20 }: { banners: Banner[]; onOpen: (b: Banner) => void; gutter?: number }) {
  const { width } = useWindowDimensions();
  const w = Math.min(width, 760) - gutter * 2;
  const h = Math.round(w / 2);
  const ordered = [...banners].reverse(); // first banner sits at the right end
  const scroll = useRef<ScrollViewInstance>(null);
  const [page, setPage] = useState(0); // 0 = first banner
  const touching = useRef(false);
  const n = banners.length;
  const toX = (p: number) => (n - 1 - p) * w;

  useEffect(() => {
    // start on the first banner (right end)
    const t = setTimeout(() => scroll.current?.scrollTo({ x: toX(0), animated: false }), 0);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [n, w]);

  useEffect(() => {
    if (n < 2) return;
    const t = setInterval(() => {
      if (touching.current) return;
      setPage((p) => {
        const next = (p + 1) % n;
        scroll.current?.scrollTo({ x: toX(next), animated: true });
        return next;
      });
    }, AUTO_MS);
    return () => clearInterval(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [n, w]);

  return (
    <View style={{ gap: 8 }}>
      <ScrollView
        ref={scroll}
        horizontal
        pagingEnabled
        showsHorizontalScrollIndicator={false}
        style={{ width: w, alignSelf: 'center', borderRadius: 22 }}
        onTouchStart={() => (touching.current = true)}
        onTouchEnd={() => setTimeout(() => (touching.current = false), 2500)}
        onMomentumScrollEnd={(e) => setPage(n - 1 - Math.round(e.nativeEvent.contentOffset.x / w))}
        onScroll={(e) => {
          const p = n - 1 - Math.round(e.nativeEvent.contentOffset.x / w);
          if (p !== page && p >= 0 && p < n) setPage(p);
        }}
        scrollEventThrottle={64}
      >
        {ordered.map((b) => (
          <Pressable key={b.id} onPress={() => onOpen(b)} style={{ width: w, height: h }} accessibilityRole="button" accessibilityLabel={b.title}>
            {b.image ? (
              <Image source={{ uri: b.image }} style={[styles.image, { width: w, height: h }]} resizeMode="cover" />
            ) : (
              <View style={[styles.card, { height: h }]}>
                <View style={[styles.lemon, { width: h * 1.1, height: h * 1.1, left: -h * 0.3, bottom: -h * 0.35 }]}>
                  <LemonSlice size={h * 1.1} />
                </View>
                <View style={{ paddingLeft: h * 0.7, gap: 4 }}>
                  <Text style={[styles.small, rtl]}>{b.subtitle || 'ویژه'}</Text>
                  <Text style={[styles.title, rtl]} numberOfLines={3}>
                    {b.title}
                  </Text>
                </View>
              </View>
            )}
          </Pressable>
        ))}
      </ScrollView>
      {n > 1 && (
        <View style={styles.dots}>
          {banners.map((b, i) => (
            <View key={b.id} style={[styles.dot, i === page && styles.dotOn]} />
          ))}
        </View>
      )}
    </View>
  );
}

const styles = StyleSheet.create({
  image: { borderRadius: 22, backgroundColor: colors.line },
  card: { flex: 1, borderRadius: 22, backgroundColor: colors.ink, padding: 18, justifyContent: 'center', overflow: 'hidden' },
  lemon: { position: 'absolute', opacity: 0.95 },
  small: { color: '#B9C4BC', fontSize: 12 },
  title: { color: colors.lemon, fontSize: 20, fontWeight: '800', lineHeight: 30 },
  dots: { flexDirection: 'row-reverse', justifyContent: 'center', gap: 6 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.line },
  dotOn: { width: 18, backgroundColor: colors.ink },
});
