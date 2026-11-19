/** Design A ("lemon"): colours and spacing used across the app. */
export const colors = {
  ground: '#F6F7F2',
  paper: '#FBFBF7',
  surface: '#FFFFFF',
  ink: '#17201A',
  muted: '#56655B',
  line: '#E3E8DE',
  lemon: '#F5C518',
  lemonSoft: '#FFF6CF',
  green: '#2F7D4F',
  greenDark: '#1F5E3A',
  greenSoft: '#E3F3E9',
  red: '#C2413B',
  redDark: '#9E2F2A',
  redSoft: '#FBE7E6',
  disabled: '#E6EAE1',
  /** Unsure or late, not wrong: «شک‌دار», a review that is overdue. */
  amber: '#E8892B',
  amberSoft: '#FDEBD7',
  amberDark: '#8A4A0B',
} as const;

export const radius = { sm: 12, md: 18, lg: 24 } as const;

/** Spacing on a 4-point grid; `page` is the side margin of every list page (the reader has its own). */
export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24, xxl: 32, page: 16 } as const;

/** Text sizes: one scale (about ×1.2 a step), so the same role has the same size on every page. */
export const type = { tiny: 11, caption: 12, small: 13, body: 15, title: 18, heading: 22, display: 28 } as const;

/** A frame inside a frame looks right when its corner is the outer corner less the gap between them. */
export function innerRadius(outer: number, gap: number) {
  return Math.max(4, outer - gap);
}

/** Persian-first text: right aligned, right-to-left. */
export const rtl = { textAlign: 'right', writingDirection: 'rtl' } as const;

export const DIFFICULTY_LABEL: Record<string, string> = { easy: 'آسان', medium: 'متوسط', hard: 'سخت' };

export function toPersianDigits(value: string | number): string {
  return String(value).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[Number(d)]);
}

const ORDINAL_WORDS = [
  '', 'اول', 'دوم', 'سوم', 'چهارم', 'پنجم', 'ششم', 'هفتم', 'هشتم', 'نهم', 'دهم',
  'یازدهم', 'دوازدهم', 'سیزدهم', 'چهاردهم', 'پانزدهم', 'شانزدهم', 'هفدهم', 'هجدهم', 'نوزدهم', 'بیستم',
];

/** The chapter's number as a word: «فصل اول رایگان», not «فصل ۱ رایگان». */
export function toPersianOrdinal(value: number): string {
  return ORDINAL_WORDS[value] ?? toPersianDigits(value);
}

export function formatToman(value: number): string {
  return `${toPersianDigits(value.toLocaleString('en-US').replace(/,/g, '٬'))} تومان`;
}
