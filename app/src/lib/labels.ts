/**
 * Labels («برچسب‌ها») of the lesson text, managed in the panel (backend apps/catalog Label).
 *
 * The same names work in both tabs:
 *   درسنامه (notes): a box   :::تعریف … :::
 *   چکیده (summary): a part  تعریف:  then «- » items
 *
 * Every label has one of four looks: formal (definitions, theorems), note (tips, reminders), warn (traps,
 * counter-examples), table (words with columns «فارسی | English | معنی»). A few names also do something:
 * «در یک نگاه» is the headline, «مهم» items always jump to the notes, «واژه» feeds the glossary, «حفظی» offers the
 * section's flashcards. The list below is the starting list; the server's list (sent with every section) replaces it.
 */
export type LabelStyle = 'formal' | 'note' | 'warn' | 'table';
export type LabelRole = '' | 'glance' | 'important' | 'terms' | 'memorize';
export type Label = {
  name: string;
  group?: string;
  style: LabelStyle;
  role?: LabelRole;
  /** Other spellings accepted in the text («تله‌ها» for «تله»). */
  aliases?: string[];
  /** Column titles of a table label, e.g. ['فارسی', 'English', 'معنی']. */
  columns?: string[];
  /** Hidden labels are not offered in the panel's buttons, but text already using them still shows as before. */
  hidden?: boolean;
};

export const DEFAULT_LABELS: Label[] = [
  { name: 'در یک نگاه', group: 'عمومی', style: 'note', role: 'glance' },
  { name: 'مهم', group: 'عمومی', style: 'note', role: 'important', aliases: ['مهم‌ترین‌ها'] },
  { name: 'تعریف', group: 'ریاضی و علوم', style: 'formal' },
  { name: 'قضیه', group: 'ریاضی و علوم', style: 'formal' },
  { name: 'نتیجه', group: 'ریاضی و علوم', style: 'formal' },
  { name: 'گزاره', group: 'ریاضی و علوم', style: 'formal' },
  { name: 'فرمول', group: 'ریاضی و علوم', style: 'formal' },
  { name: 'قاعده', group: 'ریاضی و علوم', style: 'formal', aliases: ['قاعده و فرمول'] },
  { name: 'شرط کاربرد', group: 'ریاضی و علوم', style: 'note' },
  { name: 'نمودار', group: 'ریاضی و علوم', style: 'formal' },
  { name: 'مثال', group: 'عمومی', style: 'formal' },
  { name: 'مثال نقض', group: 'ریاضی و علوم', style: 'warn' },
  { name: 'نکته', group: 'عمومی', style: 'note' },
  { name: 'یادآوری', group: 'عمومی', style: 'note' },
  { name: 'حفظی', group: 'عمومی', style: 'note', role: 'memorize' },
  { name: 'تله', group: 'عمومی', style: 'warn', aliases: ['تله‌ها', 'تله‌ی تستی'] },
  { name: 'هشدار', group: 'عمومی', style: 'warn', hidden: true },
  { name: 'واژه', group: 'زبان', style: 'table', role: 'terms', aliases: ['واژه‌ها', 'واژه‌نامه'], columns: ['فارسی', 'English', 'معنی'] },
  { name: 'مترادف', group: 'زبان', style: 'table', columns: ['واژه', 'مترادف'] },
  { name: 'متضاد', group: 'زبان', style: 'table', columns: ['واژه', 'متضاد'] },
];

/** «مثال‌نقض», «مثال  نقض» and «مثال نقض» are the same name; Arabic ي/ك too. */
export function normalizeName(name: string): string {
  return (name ?? '').replace(/ي/g, 'ی').replace(/ك/g, 'ک').replace(/[‌\s]+/g, ' ').trim();
}

let current: Label[] = DEFAULT_LABELS;
let index: Map<string, Label> | null = null;
let pattern: RegExp | null = null;

/** Use the server's list (it includes the starting list and anything added in the panel). */
export function setLabels(list: Label[] | null | undefined) {
  if (!list || !list.length) return;
  const next = list.map((l) => ({ ...l, role: l.role ?? '', aliases: l.aliases ?? [], columns: l.columns ?? [] }));
  if (JSON.stringify(next) === JSON.stringify(current)) return;
  current = next;
  index = null;
  pattern = null;
}

export function allLabels(): Label[] {
  return current;
}

export function findLabel(name: string): Label | undefined {
  if (!index) {
    index = new Map();
    for (const l of current) for (const n of [l.name, ...(l.aliases ?? [])]) index.set(normalizeName(n), l);
  }
  return index.get(normalizeName(name));
}

function escapeRe(s: string) {
  return s.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}

/** A summary line that starts a part: «تعریف: …» (the name, any spacing, a colon). */
export function labelLine(line: string): { label: Label; rest: string } | null {
  if (!pattern) {
    const names = current.flatMap((l) => [l.name, ...(l.aliases ?? [])]).map(normalizeName);
    const alts = [...new Set(names)]
      .sort((a, b) => b.length - a.length)
      .map((n) => n.split(' ').map(escapeRe).join('[\\u200c\\s]+'));
    pattern = new RegExp(`^\\s*(${alts.join('|')})\\s*[:：]\\s*(.*)$`);
  }
  const m = line.replace(/ي/g, 'ی').replace(/ك/g, 'ک').match(pattern);
  if (!m) return null;
  const label = findLabel(m[1]);
  return label ? { label, rest: m[2].replace(/^[-*]\s+/, '') } : null;
}
