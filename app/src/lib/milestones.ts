/**
 * Finished sections, chapters and books, celebrated once each when the learner comes back to the book page (the hub
 * every path returns to: notes, tests, cards, exams). What was already finished before this app version is noted
 * quietly the first time a book is opened, so updating the app never sets off a wave of celebrations.
 */
import AsyncStorage from '@react-native-async-storage/async-storage';

import type { BookDetail } from '../api/endpoints';
import type { CelebrationKind, CelebrationOptions } from '../components/Celebrate';
import { toPersianDigits } from '../theme';

type Celebrate = (kind: CelebrationKind, o: CelebrationOptions) => void;

const keyOf = (user: number, book: string) => `limo.milestones.${user}.${book}`;

export async function celebrateProgress(user: number, book: BookDetail, celebrate: Celebrate) {
  const done = new Set(book.done_ids);
  const chapters = book.chapters.filter((c) => !c.is_locked && c.sections.length > 0);
  const completeChapters = chapters.filter((c) => c.sections.every((s) => done.has(s.id)));
  const bookComplete = chapters.length > 0 && completeChapters.length === book.chapters.length;
  const now = { sections: [...done], chapters: completeChapters.map((c) => c.id), book: bookComplete };

  let seen: { sections: number[]; chapters: number[]; book: boolean } | null = null;
  try {
    const raw = await AsyncStorage.getItem(keyOf(user, book.slug));
    seen = raw ? JSON.parse(raw) : null;
  } catch {
    return;
  }
  AsyncStorage.setItem(keyOf(user, book.slug), JSON.stringify(now)).catch(() => undefined);
  if (!seen) return; // first look at this book: what is finished already is not news

  const newSections = now.sections.filter((id) => !seen!.sections.includes(id));
  const newChapters = completeChapters.filter((c) => !seen!.chapters.includes(c.id));
  const number = (id: number) => book.chapters.findIndex((c) => c.id === id) + 1;

  // Biggest first: smaller news that comes while it is open joins it as a line.
  if (bookComplete && !seen.book) {
    celebrate('book', {
      title: `کتاب «${book.title}» تمام شد!`,
      text: 'همه‌ی فصل‌ها را خواندی و تمرین کردی. مرورها سر وقتشان می‌آیند تا یادت بماند.',
      parts: chapters.length,
      primary: 'ادامه',
    });
  } else {
    for (const c of newChapters) {
      celebrate('chapter', {
        title: `فصل ${toPersianDigits(number(c.id))} کامل شد!`,
        text: `«${c.title}» را خواندی و تست‌هایش را زدی. فردا اولین مرورش می‌آید.`,
        parts: c.sections.length,
        primary: 'ادامه',
      });
    }
  }
  const lone = newSections.filter((id) => !newChapters.some((c) => c.sections.some((s) => s.id === id)));
  if (lone.length === 1) {
    const s = book.chapters.flatMap((c) => c.sections).find((x) => x.id === lone[0]);
    if (s) celebrate('small', { title: `بخش «${s.title}» تمام شد`, text: 'جزوه و تست‌هایش، هر دو.' });
  } else if (lone.length > 1) {
    celebrate('small', { title: `${toPersianDigits(lone.length)} بخش تمام شد`, text: 'جزوه و تست‌هایشان، هر دو.' });
  }
}
