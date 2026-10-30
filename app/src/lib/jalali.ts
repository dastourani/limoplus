import { toPersianDigits } from '../theme';

const MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'];
const WEEKDAYS = ['یکشنبه', 'دوشنبه', 'سه‌شنبه', 'چهارشنبه', 'پنجشنبه', 'جمعه', 'شنبه'];

/** Gregorian → Jalali (Persian calendar). Standard arithmetic algorithm; no Intl calendar support needed. */
export function toJalali(gy: number, gm: number, gd: number): [number, number, number] {
  const gdm = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
  const gy2 = gm > 2 ? gy + 1 : gy;
  let days =
    355666 + 365 * gy + Math.floor((gy2 + 3) / 4) - Math.floor((gy2 + 99) / 100) + Math.floor((gy2 + 399) / 400) + gd + gdm[gm - 1];
  let jy = -1595 + 33 * Math.floor(days / 12053);
  days %= 12053;
  jy += 4 * Math.floor(days / 1461);
  days %= 1461;
  if (days > 365) {
    jy += Math.floor((days - 1) / 365);
    days = (days - 1) % 365;
  }
  const jm = days < 186 ? 1 + Math.floor(days / 31) : 7 + Math.floor((days - 186) / 30);
  const jd = 1 + (days < 186 ? days % 31 : (days - 186) % 30);
  return [jy, jm, jd];
}

function parse(value: string | Date): Date {
  return value instanceof Date ? value : new Date(value);
}

/** «۸ آبان ۱۴۰۵» */
export function jalaliDate(value: string | Date): string {
  const d = parse(value);
  if (isNaN(d.getTime())) return '';
  const [y, m, day] = toJalali(d.getFullYear(), d.getMonth() + 1, d.getDate());
  return `${toPersianDigits(day)} ${MONTHS[m - 1]} ${toPersianDigits(y)}`;
}

/** «۸ آبان ۱۴۰۵، ۱۴:۰۵» */
export function jalaliDateTime(value: string | Date): string {
  const d = parse(value);
  if (isNaN(d.getTime())) return '';
  const time = `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`;
  return `${jalaliDate(d)}، ${toPersianDigits(time)}`;
}

/** Short weekday initial for charts, e.g. «ش». */
export function weekdayShort(value: string | Date): string {
  return WEEKDAYS[parse(value).getDay()].slice(0, 1);
}

/** «امروز»، «دیروز»، «۳ روز پیش» or a date. */
export function relativeDay(value: string | Date): string {
  const d = parse(value);
  const startOf = (x: Date) => new Date(x.getFullYear(), x.getMonth(), x.getDate()).getTime();
  const diff = Math.round((startOf(new Date()) - startOf(d)) / 86400000);
  if (diff === 0) return 'امروز';
  if (diff === 1) return 'دیروز';
  if (diff > 1 && diff < 7) return `${toPersianDigits(diff)} روز پیش`;
  return jalaliDate(d);
}
