import AsyncStorage from '@react-native-async-storage/async-storage';
import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useMemo, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { endpoints, type Flashcard, type FlashcardState } from '../../api/endpoints';
import { FlashcardDeck } from '../../components/FlashcardDeck';
import { Text } from '../../components/Text';
import { ErrorState, Header, Loading, Screen } from '../../components/ui';
import { colors, toPersianDigits } from '../../theme';
import { useAuth } from '../../lib/auth';
import { useApi } from '../../lib/useApi';
import { setMacros } from '../../lib/macros';

type Mode = 'smart' | 'shuffle' | 'book';
const MODES: [Mode, string][] = [['smart', 'هوشمند'], ['shuffle', 'تصادفی'], ['book', 'ترتیب کتاب']];
const SHORT = 20;
const MODE_KEY = 'limo.cards.mode';
const SHORT_KEY = 'limo.cards.short';

function shuffled<T>(list: T[], seed: number): T[] {
  const out = [...list];
  let s = seed || 1;
  for (let i = out.length - 1; i > 0; i--) {
    s = (s * 1103515245 + 12345) % 2147483648;
    const j = s % (i + 1);
    [out[i], out[j]] = [out[j], out[i]];
  }
  return out;
}

/**
 * Flashcards of a section, chapter or book. Order: «هوشمند» (due and new cards first, then the weakest boxes),
 * «تصادفی» (new every time) or «ترتیب کتاب»; «فقط ۲۰ کارت» keeps a long deck short. Both choices are remembered.
 */
export default function Flashcards() {
  // ?done=1: a whole book, but only the cards of sections the learner has finished (green tick).
  // ?ids=…&keep=1: the cards linked to a test, in that order (the tapped one first).
  const { nodeId, done, ids, keep } = useLocalSearchParams<{ nodeId: string; done?: string; ids?: string; keep?: string }>();
  const doneOnly = done === '1';
  const title = ids ? 'فلش‌کارت مرتبط' : doneOnly ? 'فلش‌کارت‌های کتاب' : 'فلش‌کارت';
  const { user } = useAuth();
  const { data, error, loading, retry } = useApi(() => endpoints.flashcards(Number(nodeId), doneOnly, ids), [nodeId, doneOnly, ids]);
  setMacros(data?.macros);
  const asked = (list: Flashcard[]) => {
    if (!ids || keep !== '1') return null;
    const want = ids.split(',').map(Number);
    return [...list].sort((a, b) => want.indexOf(a.id) - want.indexOf(b.id));
  };
  const [state, setState] = useState<FlashcardState | null>(null);
  const [order, setOrder] = useState<Flashcard[] | null>(null);
  const [mode, setMode] = useState<Mode>('smart');
  const [short, setShort] = useState(false);
  const [seed, setSeed] = useState(() => Math.floor(Math.random() * 1e9));
  useEffect(() => {
    AsyncStorage.multiGet([MODE_KEY, SHORT_KEY])
      .then(([[, m], [, sh]]) => {
        if (m === 'smart' || m === 'shuffle' || m === 'book') setMode(m);
        setShort(sh === '1');
      })
      .catch(() => undefined);
  }, []);
  const pick = (m: Mode) => {
    setMode(m);
    if (m === 'shuffle') setSeed(Math.floor(Math.random() * 1e9));
    AsyncStorage.setItem(MODE_KEY, m).catch(() => undefined);
  };
  const toggleShort = () => {
    setShort((v) => {
      AsyncStorage.setItem(SHORT_KEY, v ? '0' : '1').catch(() => undefined);
      return !v;
    });
  };
  // The cards asked for by a test keep their own order; a deck follows the chosen order.
  const cards = useMemo(() => {
    if (!order || !data) return null;
    if (asked(data.flashcards)) return order;
    const base = mode === 'book' ? data.flashcards : mode === 'shuffle' ? shuffled(data.flashcards, seed) : order;
    return short && base.length > SHORT ? base.slice(0, SHORT) : base;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [order, data, mode, short, seed]);

  useEffect(() => {
    if (!data) return;
    if (!user) {
      setOrder(asked(data.flashcards) ?? data.flashcards);
      return;
    }
    endpoints
      .flashcardState(Number(nodeId))
      .then((s) => {
        setState(s);
        const rank = (f: Flashcard) => {
          const st = s.cards[f.id];
          return st ? (st.due ? 0 : 10) + st.box : 0;
        };
        setOrder(asked(data.flashcards) ?? [...data.flashcards].sort((a, b) => rank(a) - rank(b)));
      })
      .catch(() => setOrder(data.flashcards));
  }, [data, user, nodeId]);

  if (loading || (data && !order)) return <Screen><Header title={title} /><Loading /></Screen>;
  if (error) return <Screen><Header title={title} /><ErrorState message={error.message} onRetry={retry} /></Screen>;
  if (!cards || cards.length === 0) {
    return (
      <Screen>
        <Header title={title} />
        <ErrorState icon={data!.locked_count ? 'lock' : 'layers'} message={
            doneOnly
              ? 'هر بخشی را که تمام کنی (تیک سبز)، فلش‌کارت‌هایش اینجا می‌آید.'
              : data!.locked_count
                ? 'فلش‌کارت‌های این بخش در نسخه‌ی کامل کتاب است.'
                : 'برای این بخش هنوز فلش‌کارتی نیست.'
          } />
      </Screen>
    );
  }
  const many = !ids && (data?.flashcards.length ?? 0) > 1;
  const toolbar = many ? (
    <View style={styles.bar}>
      {MODES.map(([m, label]) => (
        <Pressable key={m} onPress={() => pick(m)} style={[styles.pill, mode === m && styles.pillOn]} accessibilityRole="button" accessibilityState={{ selected: mode === m }}>
          <Text style={[styles.pillText, mode === m && styles.pillTextOn]}>{label}</Text>
        </Pressable>
      ))}
      {(data?.flashcards.length ?? 0) > SHORT && (
        <Pressable onPress={toggleShort} style={[styles.pill, short && styles.pillOn]} accessibilityRole="switch" accessibilityState={{ checked: short }}>
          <Text style={[styles.pillText, short && styles.pillTextOn]}>فقط {toPersianDigits(SHORT)} کارت</Text>
        </Pressable>
      )}
    </View>
  ) : null;
  return (
    <FlashcardDeck
      key={`${mode}-${short}-${seed}`}
      toolbar={toolbar}
      title={title}
      onTests={(c) =>
        router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: String(data?.book_id ?? nodeId), ids: (c.question_ids ?? []).join(',') } })
      }
      cards={cards}
      state={Object.fromEntries(Object.entries(state?.cards ?? {}).map(([id, c]) => [id, { box: c.box, hints: c.hints }]))}
      newHints={state?.new_hints}
      masteredBox={state?.mastered_box}
      reported={state?.reported}
    />
  );
}

const styles = StyleSheet.create({
  bar: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 6, paddingHorizontal: 16, marginBottom: 4 },
  pill: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1, borderColor: colors.line, backgroundColor: colors.surface },
  pillOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  pillText: { fontSize: 12.5, fontWeight: '700', color: colors.ink },
  pillTextOn: { color: colors.lemon },
});
