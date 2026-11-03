import { toPersianDigits } from '../theme';

/** Study time as the learner sees it: «۲۰ دقیقه», «۲ ساعت و ۱۵ دقیقه», from 10 hours on only hours («۱۲ ساعت»,
 * «۱۲۵ ساعت»; never days, which would read as calendar days). Only this text is rounded (down); the server keeps and
 * adds up the exact seconds. Under a minute: «کمتر از یک دقیقه». */
export function studyDuration(seconds: number): string {
  const minutes = Math.floor(Math.max(0, seconds) / 60);
  if (minutes < 1) return 'کمتر از یک دقیقه';
  const h = Math.floor(minutes / 60);
  const m = minutes % 60;
  if (!h) return `${toPersianDigits(m)} دقیقه`;
  return m && h < 10 ? `${toPersianDigits(h)} ساعت و ${toPersianDigits(m)} دقیقه` : `${toPersianDigits(h)} ساعت`;
}
