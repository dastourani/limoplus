import { toPersianDigits } from '../theme';

/** The line above «سؤال ۱ از ۴» and «کارت ۱ از ۱۰»: «فصل ۱، نام بخش». The chapter comes first, so it stays in view
 * when a long section name is cut with «…». */
export function placeLabel(title?: string | null, chapter?: number | null): string | undefined {
  if (!title) return undefined;
  return chapter ? `فصل ${toPersianDigits(chapter)}، ${title}` : title;
}
