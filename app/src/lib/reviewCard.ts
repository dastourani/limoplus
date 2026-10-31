/**
 * The review card: a section's summary written in labelled parts (see backend apps/catalog/summary.py).
 *   در یک نگاه: …        مهم: - … [[phrase in the notes]]        واژه: - فارسی | English | معنی
 *   قاعده: - …            حفظی: - …                               تله: - …
 * Without labels the summary is plain Markdown, as before.
 */
export type PartKey = 'glance' | 'important' | 'terms' | 'rules' | 'memorize' | 'traps';
export type Term = { fa: string; en: string; meaning: string };

const NAMES: Record<string, PartKey> = {
  'در یک نگاه': 'glance',
  'مهم': 'important',
  'مهم‌ترین‌ها': 'important',
  'واژه': 'terms',
  'واژه‌ها': 'terms',
  'واژه‌نامه': 'terms',
  'قاعده': 'rules',
  'قاعده و فرمول': 'rules',
  'حفظی': 'memorize',
  'تله': 'traps',
  'تله‌ها': 'traps',
};
const LABEL = new RegExp(
  `^\\s*(${Object.keys(NAMES)
    .sort((a, b) => b.length - a.length)
    .join('|')})\\s*:\\s*(.*)$`,
);

export function parseParts(text: string): Partial<Record<PartKey, string[]>> | null {
  const parts: Partial<Record<PartKey, string[]>> = {};
  let current: PartKey | null = null;
  let found = false;
  for (const raw of (text ?? '').split('\n')) {
    const m = raw.match(LABEL);
    if (m) {
      current = NAMES[m[1]];
      found = true;
      parts[current] = parts[current] ?? [];
      if (m[2].trim()) parts[current]!.push(m[2].trim());
      continue;
    }
    if (!current) continue;
    const line = raw.trim();
    if (!line) continue;
    const list = parts[current]!;
    if (/^[-*]\s+/.test(line)) list.push(line.replace(/^[-*]\s+/, ''));
    else if (list.length) list[list.length - 1] += ' ' + line;
    else list.push(line);
  }
  return found ? parts : null;
}

export function parseTerms(text: string): Term[] {
  return (parseParts(text)?.terms ?? [])
    .map((item) => item.split('|').map((c) => c.trim()))
    .filter((c) => c[0])
    .map((c) => ({ fa: c[0], en: c[1] ?? '', meaning: c[2] ?? '' }));
}

/** «متن [[عبارت]]» → shown text and the phrase to find in the notes (or the first bold words). */
export function jumpTarget(item: string): { text: string; phrase: string } {
  const m = item.match(/\[\[([^\]]+)\]\]/);
  const text = item.replace(/\s*\[\[[^\]]+\]\]\s*/g, ' ').trim();
  if (m) return { text, phrase: m[1].trim() };
  const bold = text.match(/\*\*([^*]+)\*\*/);
  return { text, phrase: bold ? bold[1].trim() : '' };
}
