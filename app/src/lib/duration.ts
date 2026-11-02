import { toPersianDigits } from '../theme';

/** Study time as the learner sees it: «۲ ساعت و ۱۵ دقیقه», «۲۰ دقیقه». Only this text is rounded (down to the
 * minute); the server keeps and adds up the exact seconds. Under a minute: «کمتر از یک دقیقه». */
export function studyDuration(seconds: number): string {
  const minutes = Math.floor(Math.max(0, seconds) / 60);
  if (minutes < 1) return 'کمتر از یک دقیقه';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${toPersianDigits(m)} دقیقه`;
  return m ? `${toPersianDigits(h)} ساعت و ${toPersianDigits(m)} دقیقه` : `${toPersianDigits(h)} ساعت`;
}
