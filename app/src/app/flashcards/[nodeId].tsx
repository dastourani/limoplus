import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';

import { endpoints, type Flashcard, type FlashcardState } from '../../api/endpoints';
import { FlashcardDeck } from '../../components/FlashcardDeck';
import { ErrorState, Header, Loading, Screen } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { useApi } from '../../lib/useApi';

/** Flashcards of a section or chapter. Due and new cards first, then the weakest boxes. */
export default function Flashcards() {
  // ?done=1: a whole book, but only the cards of sections the learner has finished (green tick).
  // ?ids=…&keep=1: the cards linked to a test, in that order (the tapped one first).
  const { nodeId, done, ids, keep } = useLocalSearchParams<{ nodeId: string; done?: string; ids?: string; keep?: string }>();
  const doneOnly = done === '1';
  const title = ids ? 'فلش‌کارت مرتبط' : doneOnly ? 'فلش‌کارت‌های کتاب' : 'فلش‌کارت';
  const { user } = useAuth();
  const { data, error, loading, retry } = useApi(() => endpoints.flashcards(Number(nodeId), doneOnly, ids), [nodeId, doneOnly, ids]);
  const asked = (list: Flashcard[]) => {
    if (!ids || keep !== '1') return null;
    const want = ids.split(',').map(Number);
    return [...list].sort((a, b) => want.indexOf(a.id) - want.indexOf(b.id));
  };
  const [state, setState] = useState<FlashcardState | null>(null);
  const [order, setOrder] = useState<Flashcard[] | null>(null);

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
  if (order!.length === 0) {
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
  return (
    <FlashcardDeck
      title={title}
      onTests={(c) =>
        router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: String(data?.book_id ?? nodeId), ids: (c.question_ids ?? []).join(',') } })
      }
      cards={order!}
      state={Object.fromEntries(Object.entries(state?.cards ?? {}).map(([id, c]) => [id, { box: c.box, hints: c.hints }]))}
      newHints={state?.new_hints}
      masteredBox={state?.mastered_box}
      reported={state?.reported}
    />
  );
}
