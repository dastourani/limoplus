import AsyncStorage from '@react-native-async-storage/async-storage';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useRef, useState } from 'react';
import { Animated, Easing, Pressable, StyleSheet, View } from 'react-native';

import { endpoints } from '../../api/endpoints';
import { Text } from '../../components/Text';
import { Button, Empty, ErrorState, Header, Loading, Screen } from '../../components/ui';
import { useApi } from '../../lib/useApi';
import { useAuth } from '../../lib/auth';
import { sendOrQueue } from '../../lib/network';
import { colors, radius, rtl, toPersianDigits } from '../../theme';

type Term = { fa: string; en: string; meaning: string; section_id: number; section_title: string };
/** Per book: the words the learner said they know («بلدم»): on this device, and on the account when signed in. */
const KNOWN_KEY = (slug: string) => `limo.words.${slug}`;
const ROUND = 20;

/**
 * «مرور واژه‌ها»: the book's glossary as cards, for learners who ask for it (from the glossary page). The word on the
 * front (Persian, or English when turned around), its other name and meaning on the back. Words not yet known come
 * first; «بلدم» moves a word to the end of later rounds, «دوباره» brings it back in this round.
 */
export default function Words() {
  const { slug, chapter } = useLocalSearchParams<{ slug: string; chapter?: string }>();
  const { data, error, loading, retry } = useApi(() => endpoints.glossary(String(slug), chapter), [slug, chapter]);
  const { user } = useAuth();
  const [known, setKnown] = useState<Set<string> | null>(null);
  const [english, setEnglish] = useState(false);
  const [queue, setQueue] = useState<Term[] | null>(null);
  const [pos, setPos] = useState(0);
  const [open, setOpen] = useState(false);
  const [again, setAgain] = useState(0);
  const flip = useRef(new Animated.Value(0)).current;

  useEffect(() => {
    let alive = true;
    (async () => {
      let local: string[] = [];
      try {
        const v = await AsyncStorage.getItem(KNOWN_KEY(String(slug)));
        local = v ? JSON.parse(v) : [];
      } catch {
        // a convenience only
      }
      let all = new Set(local);
      if (user) {
        try {
          const server = (await endpoints.knownWords(String(slug))).known;
          // Words known only on this phone (from before signing in, or offline) go up once.
          const missing = local.filter((w) => !server.includes(w));
          all = new Set([...server, ...missing]);
          if (missing.length) endpoints.markWords(String(slug), missing, true).catch(() => undefined);
        } catch {
          // offline: this phone's list
        }
      }
      if (alive) setKnown(all);
    })();
    return () => {
      alive = false;
    };
  }, [slug, user]);

  // A round: the words not yet known, shuffled, then (if there is room) known ones for a refresher.
  const start = () => {
    if (!data || !known) return;
    const shuffle = <T,>(a: T[]) => a.map((x) => [Math.random(), x] as const).sort((p, q) => p[0] - q[0]).map(([, x]) => x);
    const fresh = shuffle(data.terms.filter((t) => !known.has(t.fa)));
    const old = shuffle(data.terms.filter((t) => known.has(t.fa)));
    setQueue([...fresh, ...old].slice(0, ROUND));
    setPos(0);
    setAgain(0);
    setOpen(false);
    flip.setValue(0);
  };
  useEffect(() => {
    if (data && known && !queue) start();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [data, known]);

  const knownCount = useMemo(() => (data && known ? data.terms.filter((t) => known.has(t.fa)).length : 0), [data, known]);

  const save = (next: Set<string>, term: string, ok: boolean) => {
    setKnown(next);
    AsyncStorage.setItem(KNOWN_KEY(String(slug)), JSON.stringify([...next])).catch(() => undefined);
    if (user) sendOrQueue(`books/${encodeURIComponent(String(slug))}/words/me/`, { term, known: ok });
  };
  const turn = () => {
    setOpen(true);
    Animated.timing(flip, { toValue: 1, duration: 260, easing: Easing.out(Easing.cubic), useNativeDriver: true }).start();
  };
  const answer = (ok: boolean) => {
    if (!queue || !known) return;
    const term = queue[pos];
    const next = new Set(known);
    if (ok) next.add(term.fa);
    else {
      next.delete(term.fa);
      setAgain((n) => n + 1);
      // Back three words later in this round.
      setQueue((q) => {
        const copy = [...q!];
        copy.splice(Math.min(copy.length, pos + 4), 0, term);
        return copy;
      });
    }
    save(next, term.fa, ok);
    flip.setValue(0);
    setOpen(false);
    setPos((p) => p + 1);
  };

  const title = 'مرور واژه‌ها';
  if (loading && !data) return <Screen><Header title={title} /><Loading /></Screen>;
  if (error || !data) return <Screen><Header title={title} /><ErrorState message={error?.message ?? ''} onRetry={retry} /></Screen>;
  if (!data.terms.length)
    return (
      <Screen>
        <Header title={title} subtitle={data.book} />
        <Empty icon="languages" title="هنوز واژه‌ای نیست" text="واژه‌های تخصصی از کارت مرور بخش‌ها اینجا جمع می‌شوند." />
      </Screen>
    );
  if (!queue) return <Screen><Header title={title} /><Loading /></Screen>;

  const term = queue[pos];
  const front = term && (english && term.en ? term.en : term.fa);
  const other = term && (english && term.en ? term.fa : term.en);
  const scale = flip.interpolate({ inputRange: [0, 0.5, 1], outputRange: [1, 0.96, 1] });

  return (
    <Screen>
      <Header title={title} subtitle={data.chapter ? `${data.chapter}، ${data.book}` : data.book} />
      <View style={styles.top}>
        <Text style={[styles.count, rtl]}>
          {toPersianDigits(knownCount)} از {toPersianDigits(data.terms.length)} واژه را بلدی
        </Text>
        <Pressable onPress={() => setEnglish((v) => !v)} style={styles.pill} accessibilityRole="button" accessibilityState={{ selected: english }}>
          <Text style={styles.pillText}>{english ? 'از انگلیسی' : 'از فارسی'}</Text>
        </Pressable>
      </View>
      {term ? (
        <View style={styles.body}>
          <Text style={styles.step}>
            {toPersianDigits(pos + 1)} / {toPersianDigits(queue.length)}
          </Text>
          <Pressable onPress={open ? undefined : turn} accessibilityRole="button" accessibilityLabel={open ? undefined : 'دیدن معنی'} style={{ alignSelf: 'stretch' }}>
            <Animated.View style={[styles.card, { transform: [{ scale }] }]}>
              <Text style={[styles.word, english && term.en ? styles.latin : null]}>{front}</Text>
              {open ? (
                <View style={styles.back}>
                  {!!other && <Text style={[styles.other, !english ? styles.latin : null]}>{other}</Text>}
                  {!!term.meaning && <Text style={[styles.meaning, rtl]}>{term.meaning}</Text>}
                  <Pressable onPress={() => router.push(`/section/${term.section_id}`)} accessibilityRole="link">
                    <Text style={styles.where}>در «{term.section_title}» ←</Text>
                  </Pressable>
                </View>
              ) : (
                <Text style={styles.hint}>بزن تا معنی را ببینی</Text>
              )}
            </Animated.View>
          </Pressable>
          {open ? (
            <View style={styles.buttons}>
              <Button label="دوباره" variant="outline" onPress={() => answer(false)} style={{ flex: 1 }} />
              <Button label="بلدم" onPress={() => answer(true)} style={{ flex: 1 }} />
            </View>
          ) : (
            <Button label="دیدن معنی" onPress={turn} style={{ alignSelf: 'stretch' }} />
          )}
        </View>
      ) : (
        <View style={styles.body}>
          <Text style={styles.doneTitle}>این دور تمام شد</Text>
          <Text style={[styles.doneText, rtl]}>
            {again ? `${toPersianDigits(again)} بار «دوباره» زدی؛ آن واژه‌ها دور بعد اول می‌آیند.` : 'همه را بلد بودی!'}
          </Text>
          <Button label="یک دور دیگر" onPress={start} style={{ alignSelf: 'stretch' }} />
          <Button label="بازگشت" variant="outline" onPress={() => router.back()} style={{ alignSelf: 'stretch' }} />
        </View>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  top: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', paddingHorizontal: 16, paddingBottom: 8 },
  count: { fontSize: 13, color: colors.muted },
  pill: { paddingHorizontal: 14, paddingVertical: 7, borderRadius: 999, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface },
  pillText: { fontSize: 13, fontWeight: '700', color: colors.ink },
  body: { flex: 1, padding: 16, gap: 14, alignItems: 'center', justifyContent: 'center', maxWidth: 560, width: '100%', alignSelf: 'center' },
  step: { fontSize: 13, color: colors.muted },
  card: { minHeight: 280, backgroundColor: colors.surface, borderRadius: radius.lg, borderWidth: 1, borderColor: colors.line, padding: 24, gap: 18, alignItems: 'center', justifyContent: 'center', shadowColor: '#17201A', shadowOpacity: 0.08, shadowRadius: 16, shadowOffset: { width: 0, height: 6 }, elevation: 3 },
  word: { fontSize: 28, fontWeight: '900', color: colors.ink, textAlign: 'center' },
  latin: { writingDirection: 'ltr', fontStyle: 'italic', color: '#3B44B8' },
  back: { alignItems: 'center', gap: 10 },
  other: { fontSize: 20, fontWeight: '700', color: colors.ink, textAlign: 'center' },
  meaning: { fontSize: 16, lineHeight: 26, color: colors.ink, textAlign: 'center' },
  where: { fontSize: 12, color: colors.green, fontWeight: '700' },
  hint: { fontSize: 13, color: colors.muted },
  buttons: { flexDirection: 'row-reverse', gap: 10, alignSelf: 'stretch' },
  doneTitle: { fontSize: 20, fontWeight: '900', color: colors.ink },
  doneText: { fontSize: 14, color: colors.muted, textAlign: 'center' },
});
