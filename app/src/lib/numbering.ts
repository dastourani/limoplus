/**
 * Numbered boxes («مثال ۳-۵») and links to them («[[#sin-hamarz]]»), see backend apps/catalog/numbering.py.
 * The server sends, with each section, where its count starts (the boxes of earlier sections in the chapter) and the
 * book's names; renderMarkdown numbers the boxes as it draws them, so a moved box renumbers the rest.
 */
export type RefTarget = { text: string; node: number | string };
export type Numbering = { chapter?: number | null; start?: Record<string, number>; refs?: Record<string, RefTarget> };

let current: Numbering = {};

export function setNumbering(n: Numbering | null | undefined) {
  current = n ?? {};
}

export function numbering(): Numbering {
  return current;
}

const FA = '۰۱۲۳۴۵۶۷۸۹';
export const faDigits = (n: number | string) => String(n).replace(/\d/g, (d) => FA[Number(d)]);
