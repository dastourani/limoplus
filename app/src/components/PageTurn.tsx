/**
 * A page turning over by itself from its top-left corner (see Fold.tsx), while the new screen shows underneath.
 *   kind="cover": the book's dark cover with the lemon (entering a book)
 *   kind="paper": a page of the section just finished (going to the next section)
 * Drawn with transforms only (native driver), so it stays smooth on low-end phones. Tapping skips it.
 */
import { useEffect, useState, type ReactNode } from 'react';
import { AccessibilityInfo, Pressable, StyleSheet, View, useWindowDimensions } from 'react-native';

import { FoldLayer, corner, useFold } from './Fold';

import { colors, rtl } from '../theme';
import { LemonSlice } from './LemonSlice';
import { Text } from './Text';

function Face({ kind, title, w, h, face }: { kind: 'cover' | 'paper'; title?: string; w: number; h: number; face?: ReactNode }) {
  if (kind === 'cover' && face) {
    return <View style={[styles.cover, { width: w, height: h }]}>{face}</View>;
  }
  if (kind === 'cover') {
    return (
      <View style={[styles.cover, { width: w, height: h }]}>
        <LemonSlice size={Math.min(140, w * 0.38)} />
        {!!title && <Text style={styles.coverTitle}>{title}</Text>}
        <View style={styles.coverRule} />
        <Text style={styles.coverBrand}>لیموخوان</Text>
      </View>
    );
  }
  return (
    <View style={[styles.paper, { width: w, height: h }]}>
      {!!title && <Text style={[styles.paperTitle, rtl]}>{title}</Text>}
      {[92, 84, 96, 70, 88, 94, 66, 90, 80, 95, 72, 86].map((p, i) => (
        <View key={i} style={[styles.line, { width: `${p}%` }]} />
      ))}
    </View>
  );
}

export function PageTurn({
  kind,
  title,
  delay = 120,
  duration = 820,
  hold = false,
  face,
  onDone,
}: {
  kind: 'cover' | 'paper';
  title?: string;
  delay?: number;
  duration?: number;
  /** Show the page still (while the next screen loads). */
  hold?: boolean;
  /** What the turning page shows instead of the plain cover (e.g. the book's real cover). */
  face?: ReactNode;
  onDone?: () => void;
}) {
  const { width: W, height: H } = useWindowDimensions();
  const fold = useFold();
  const [done, setDone] = useState(false);
  fold.setSize(W, H);

  useEffect(() => {
    if (hold) return;
    let cancelled = false;
    const finish = () => {
      if (cancelled) return;
      setDone(true);
      onDone?.();
    };
    const timer = setTimeout(() => {
      AccessibilityInfo.isReduceMotionEnabled()
        .catch(() => false)
        .then((reduce) => {
          if (cancelled) return;
          if (reduce) finish();
          else fold.play(true, corner(true, H), duration).then(finish);
        });
    }, delay);
    return () => {
      cancelled = true;
      clearTimeout(timer);
      fold.stop();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [hold]);

  if (done) return null;

  return (
    <Pressable
      style={[StyleSheet.absoluteFill, { overflow: 'hidden' }]}
      onPress={() => {
        fold.stop();
        setDone(true);
        onDone?.();
      }}
      accessibilityLabel="رد کردن"
    >
      <FoldLayer fold={fold} W={W} H={H} back={kind === 'cover' ? '#22302A' : '#EEE6D2'} id="pt">
        <Face kind={kind} title={title} w={W} h={H} face={face} />
      </FoldLayer>
    </Pressable>
  );
}

const styles = StyleSheet.create({
  cover: { backgroundColor: colors.ink, alignItems: 'center', justifyContent: 'center', gap: 18, padding: 32 },
  coverTitle: { color: colors.lemon, fontSize: 22, fontWeight: '900', textAlign: 'center', lineHeight: 38 },
  coverRule: { width: 60, height: 4, borderRadius: 2, backgroundColor: '#3A4A40' },
  coverBrand: { color: '#8FA095', fontSize: 13 },
  paper: { backgroundColor: '#FFFDF6', paddingTop: 120, paddingHorizontal: 24, gap: 14 },
  paperTitle: { fontSize: 22, fontWeight: '800', color: colors.ink, marginBottom: 10 },
  line: { height: 8, borderRadius: 4, backgroundColor: '#E2E5DA', alignSelf: 'flex-end' },
});
