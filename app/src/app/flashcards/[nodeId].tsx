import { useLocalSearchParams } from 'expo-router';
import { useEffect, useState } from 'react';

import { endpoints, type Flashcard, type FlashcardState } from '../../api/endpoints';
import { FlashcardDeck } from '../../components/FlashcardDeck';
import { ErrorState, Header, Loading, Screen } from '../../components/ui';
import { useAuth } from '../../lib/auth';
import { useApi } from '../../lib/useApi';

/** Flashcards of a section or chapter. Due and new cards first, then the weakest boxes. */
export default function Flashcards() {
  // ?done=1: a whole book, but only the cards of sections the learner has finished (green tick).
  const { nodeId, done } = useLocalSearchParams<{ nodeId: string; done?: string }>();
  const doneOnly = done === '1';
  const title = doneOnly ? 'فلش‌کارت‌های کتاب' : 'فلش‌کارت';
  const { user } = useAuth();
  const { data, error, loading, retry } = useApi(() => endpoints.flashcards(Number(nodeId), doneOnly), [nodeId, doneOnly]);
  const [state, setState] = useState<FlashcardState | null>(null);
  const [order, setOrder] = useState<Flashcard[] | null>(null);

  useEffect(() => {
    if (!data) return;
    if (!user) {
      setOrder(data.flashcards);
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
        setOrder([...data.flashcards].sort((a, b) => rank(a) - rank(b)));
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
      cards={order!}
      state={Object.fromEntries(Object.entries(state?.cards ?? {}).map(([id, c]) => [id, { box: c.box, hints: c.hints }]))}
      newHints={state?.new_hints}
      masteredBox={state?.mastered_box}
      reported={state?.reported}
    />
  );
}
