import { toPersianDigits } from '../theme';

/** «۳ روز و ۴ ساعت مانده» while more than a day is left; a live «۰۴:۱۲:۳۰» in the last 24 hours; null when over. */
export function countdownText(msLeft: number): string | null {
  if (msLeft <= 0) return null;
  const s = Math.floor(msLeft / 1000);
  const days = Math.floor(s / 86400);
  const hours = Math.floor((s % 86400) / 3600);
  if (days >= 3) return `${toPersianDigits(days)} روز مانده`;
  if (days >= 1) return hours ? `${toPersianDigits(days)} روز و ${toPersianDigits(hours)} ساعت مانده` : `${toPersianDigits(days)} روز مانده`;
  const pad = (n: number) => toPersianDigits(String(n).padStart(2, '0'));
  return `${pad(hours)}:${pad(Math.floor((s % 3600) / 60))}:${pad(s % 60)}`;
}
