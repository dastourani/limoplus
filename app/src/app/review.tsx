import { useLocalSearchParams } from 'expo-router';
import { endpoints } from '../api/endpoints';
import { FlashcardDeck } from '../components/FlashcardDeck';
import { Empty, ErrorState, Header, Loading, Screen } from '../components/ui';
import { useApi } from '../lib/useApi';

/** «مرور امروز»: every card due for review today, from all books, in one session. */
export default function Review() {
  // After a few days away the home card asks for only the most important ones (lowest boxes first).
  const { limit } = useLocalSearchParams<{ limit?: string }>();
  const { data: all, error, loading, retry } = useApi(() => endpoints.dueFlashcards());
  const data = all && limit ? { ...all, flashcards: all.flashcards.slice(0, Number(limit)) } : all;
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
