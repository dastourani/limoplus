/**
 * Banners in one frame: swipe between them (first banner on the right, as in a Persian page), dots below, and
 * the next one comes by itself every few seconds unless the learner is touching the frame.
 * A banner with an image shows the image (2:1); without one, a text card with the lemon.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View, useWindowDimensions, type ScrollViewInstance } from 'react-native';

import type { Banner } from '../api/endpoints';
import { colors } from '../theme';
import { BannerFace } from './BannerFace';

const AUTO_MS = 5000;

export function BannerCarousel({ banners: all, onOpen, gutter = 20 }: { banners: Banner[]; onOpen: (b: Banner) => void; gutter?: number }) {
  const { width } = useWindowDimensions();
  // Countdowns run on the server's clock (the phone's may be wrong) and tick once a second.
  const offset = useMemo(() => {
    const now = all.find((b) => b.server_now)?.server_now;
    return now ? Date.parse(now) - Date.now() : 0;
  }, [all]);
  // Each banner's own countdown ticks inside it; here a check twice a minute takes out the banners whose time is up.
  const counting = all.some((b) => b.ends_at);
  const [tick, setTick] = useState(0);
  useEffect(() => {
    if (!counting) return;
    const t = setInterval(() => setTick((n) => n + 1), 30_000);
    return () => clearInterval(t);
  }, [counting]);
  const msLeft = (b: Banner) => (b.ends_at ? Date.parse(b.ends_at) - (Date.now() + offset) : Infinity);
  const banners = useMemo(() => all.filter((b) => msLeft(b) > 0), [all, tick]); // eslint-disable-line react-hooks/exhaustive-deps
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

  if (!n) return null;
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
            <BannerFace banner={b} w={w} h={h} offset={offset} />
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
  dots: { flexDirection: 'row-reverse', justifyContent: 'center', gap: 6 },
  dot: { width: 6, height: 6, borderRadius: 3, backgroundColor: colors.line },
  dotOn: { width: 18, backgroundColor: colors.ink },
});
