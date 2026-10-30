import { endpoints } from '../api/endpoints';
import { FlashcardDeck } from '../components/FlashcardDeck';
import { Empty, ErrorState, Header, Loading, Screen } from '../components/ui';
import { useApi } from '../lib/useApi';

/** «مرور امروز»: every card due for review today, from all books, in one session. */
export default function Review() {
  const { data, error, loading, retry } = useApi(() => endpoints.dueFlashcards());
  if (loading) return <Screen><Header title="مرور امروز" /><Loading /></Screen>;
  if (error) return <Screen><Header title="مرور امروز" /><ErrorState message={error.message} onRetry={retry} /></Screen>;
  if (!data!.flashcards.length) {
    return (
      <Screen>
        <Header title="مرور امروز" />
        <Empty icon="circle-check" title="برای امروز مروری نمانده" text="کارت‌هایی که امروز باید مرور شوند تمام شده‌اند. فردا سر بزن!" />
      </Screen>
    );
  }
  return (
    <FlashcardDeck
      title="مرور امروز"
      cards={data!.flashcards}
      state={Object.fromEntries(data!.flashcards.map((c) => [String(c.id), { box: c.box, hints: c.hints }]))}
      puzzle={false}
    />
  );
}
