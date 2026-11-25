import { describe, expect, it, vi } from 'vitest';

vi.mock('expo-router', () => ({
  router: { push: vi.fn() },
}));

vi.mock('../../api/endpoints', () => ({
  endpoints: { startReview: vi.fn() },
}));

import { reviewReasonLine, reviewResumeState } from '../reviews';

const mkQuestions = (ids: number[]) =>
  ids.map((id) => ({
    id,
    node_id: 1,
    node_title: 'بخش',
    chapter_number: 1,
    stem: 'سوال',
    choices: [],
  })) as never;

const dummyAnswer = {
  picked: 1,
  result: {
    is_correct: true,
    correct_choice_id: 1,
    explanation: '',
    flashcards: [],
  },
};

describe('reviewResumeState', () => {
  it('jumps to the first unanswered question when answers are non-sequential (1, 3, 5 -> question 2)', () => {
    const state = reviewResumeState({
      questions: mkQuestions([101, 102, 103, 104, 105]),
      answers: { '101': dummyAnswer, '103': dummyAnswer, '105': dummyAnswer },
    });
    expect(state).toEqual({
      firstUnansweredIndex: 1,
      answeredCount: 3,
      allAnswered: false,
      resumeNote: '۳ از ۵ پاسخ داده‌ای؛ ادامه از سؤال ۲',
    });
  });

  it('shows resume note even when question 1 is the first unanswered question (2, 3, 4 -> question 1)', () => {
    const state = reviewResumeState({
      questions: mkQuestions([101, 102, 103, 104, 105]),
      answers: { '102': dummyAnswer, '103': dummyAnswer, '104': dummyAnswer },
    });
    expect(state).toEqual({
      firstUnansweredIndex: 0,
      answeredCount: 3,
      allAnswered: false,
      resumeNote: '۳ از ۵ پاسخ داده‌ای؛ ادامه از سؤال ۱',
    });
  });

  it('marks allAnswered when every served question is answered', () => {
    const state = reviewResumeState({
      questions: mkQuestions([101, 102]),
      answers: { '101': dummyAnswer, '102': dummyAnswer },
    });
    expect(state).toEqual({
      firstUnansweredIndex: -1,
      answeredCount: 2,
      allAnswered: true,
      resumeNote: null,
    });
  });

  it('starts cleanly at index 0 with no resumeNote on a fresh sitting', () => {
    const state = reviewResumeState({
      questions: mkQuestions([101, 102, 103]),
      answers: {},
    });
    expect(state).toEqual({
      firstUnansweredIndex: 0,
      answeredCount: 0,
      allAnswered: false,
      resumeNote: null,
    });
  });
});

describe('reviewReasonLine', () => {
  it('combines suggestion reason and flashcard hint for small chapters', () => {
    expect(
      reviewReasonLine({
        reason: 'نوبت مرور یک‌روزه بعد از پایان فصل',
        small_chapter: true,
        flashcard_count: 3,
      }),
    ).toBe('نوبت مرور یک‌روزه بعد از پایان فصل · فصل کم‌تست؛ مرور ۳ فلش‌کارت هم پیشنهاد می‌شود');
  });

  it('shows quick recall hint when small chapter has no flashcards', () => {
    expect(
      reviewReasonLine({
        reason: 'نوبت مرور یک‌هفته‌ای فصل',
        small_chapter: true,
        flashcard_count: 0,
      }),
    ).toBe('نوبت مرور یک‌هفته‌ای فصل · فصل کم‌تست (یادآوری سریع)');
  });

  it('returns plain reason for normal chapters', () => {
    expect(
      reviewReasonLine({
        reason: 'مرور دوره‌ای برای تثبیت فصل',
        small_chapter: false,
        flashcard_count: 0,
      }),
    ).toBe('مرور دوره‌ای برای تثبیت فصل');
  });
});
