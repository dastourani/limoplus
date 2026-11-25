/** Opening a chapter or book review from «مطالعه‌ی امروز» or the book page, and its one-line label. */
import { router } from 'expo-router';

import { endpoints, type ReviewItem, type ReviewSessionData } from '../api/endpoints';
import { toPersianDigits } from '../theme';

/** «مرور فصل ۲ «حد و پیوستگی» از ریاضی عمومی ۱: ۵ تست، حدود ۷ دقیقه» */
export function reviewLabel(r: ReviewItem): string {
  const size = `${toPersianDigits(r.questions)} تست، حدود ${toPersianDigits(r.minutes)} دقیقه`;
  if (r.kind === 'book') return `مرور ترکیبی «${r.book_title}»: ${size}`;
  const n = r.chapter_number ? `${toPersianDigits(r.chapter_number)} ` : '';
  return `${r.is_exam ? 'آزمون یادآوری' : 'مرور'} فصل ${n}«${r.chapter_title}» از ${r.book_title}: ${size}`;
}

export function reviewReasonLine(r: Pick<ReviewItem, 'reason' | 'small_chapter' | 'flashcard_count'>): string {
  return [
    r.reason,
    r.small_chapter
      ? r.flashcard_count
        ? `فصل کم‌تست؛ مرور ${toPersianDigits(r.flashcard_count)} فلش‌کارت هم پیشنهاد می‌شود`
        : 'فصل کم‌تست (یادآوری سریع)'
      : '',
  ]
    .filter(Boolean)
    .join(' · ');
}

export function reviewResumeState(session: Pick<ReviewSessionData, 'questions' | 'answers'>): {
  firstUnansweredIndex: number;
  answeredCount: number;
  allAnswered: boolean;
  resumeNote: string | null;
} {
  const sessionAnswers = session.answers ?? {};
  const answeredCount = Object.keys(sessionAnswers).length;
  const firstUnansweredIndex = session.questions.findIndex((x) => !(String(x.id) in sessionAnswers));
  const allAnswered = firstUnansweredIndex === -1 && session.questions.length > 0;
  const resumeNote =
    !allAnswered && firstUnansweredIndex >= 0 && answeredCount > 0
      ? `${toPersianDigits(answeredCount)} از ${toPersianDigits(session.questions.length)} پاسخ داده‌ای؛ ادامه از سؤال ${toPersianDigits(firstUnansweredIndex + 1)}`
      : null;
  return { firstUnansweredIndex, answeredCount, allAnswered, resumeNote };
}

/** Starts (or continues) the review: practice in fives, or for the one-month step an exam without negative marking. */
export async function openReview(r: ReviewItem): Promise<void> {
  const s = await endpoints.startReview(r.kind, r.id);
  if (s.exam_id && r.chapter_id) router.push({ pathname: '/exam/[nodeId]', params: { nodeId: String(r.chapter_id), attempt: String(s.exam_id) } });
  else router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: 'review', session: String(s.id) } });
}
