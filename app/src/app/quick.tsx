import { router } from 'expo-router';
import { useEffect } from 'react';

import { endpoints } from '../api/endpoints';
import { FlashcardDeck } from '../components/FlashcardDeck';
import { Empty, ErrorState, Header, Loading, Screen } from '../components/ui';
import { useApi } from '../lib/useApi';
import { toPersianDigits } from '../theme';

/** «فقط ۵ دقیقه وقت دارم»: a few cards to review, then three questions (mistakes first). */
export default function Quick() {
  const { data, error, loading, retry } = useApi(() => endpoints.quick());
  const onlyQuestions = !!data && !data.cards.length && data.questions.length > 0;
  // No cards due: straight to the questions.
  useEffect(() => {
    if (onlyQuestions) router.replace('/quiz/quick');
  }, [onlyQuestions]);
  if (loading) return <Screen><Header title="فقط ۵ دقیقه" /><Loading /></Screen>;
  if (error) return <Screen><Header title="فقط ۵ دقیقه" /><ErrorState message={error.message} onRetry={retry} /></Screen>;
  const toQuestions = () => router.replace('/quiz/quick');
  if (!data!.cards.length) {
    if (onlyQuestions) return <Screen><Header title="فقط ۵ دقیقه" /><Loading /></Screen>;
    return (
      <Screen>
        <Header title="فقط ۵ دقیقه" />
        <Empty icon="circle-check" title="فعلاً چیزی برای این چند دقیقه نیست" text="یک بخش را بخوان یا چند تست بزن؛ از فردا این‌جا برایت کارت و تست کوتاه می‌چینیم." />
      </Screen>
    );
  }
  return (
    <FlashcardDeck
      title="فقط ۵ دقیقه"
      cards={data!.cards}
      state={Object.fromEntries(data!.cards.map((c) => [String(c.id), { box: c.box, hints: c.hints }]))}
      puzzle={false}
      next={data!.questions.length ? { label: `${toPersianDigits(data!.questions.length)} تست کوتاه`, onPress: toQuestions } : undefined}
    />
  );
}
