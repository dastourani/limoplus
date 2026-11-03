/**
 * The summary («چکیده») written in labelled parts (see lib/labels.ts and backend apps/catalog/summary.py):
 *   در یک نگاه: …
 *   تعریف:
 *   - … [[phrase in the notes]]
 *   واژه:
 *   - فارسی | English | معنی
 * Parts appear in the order they are first written; the same label twice is one part. Without labels the summary
 * is plain Markdown, as before.
 */
import { labelLine, type Label } from './labels';

export type Term = { fa: string; en: string; meaning: string };
export type SummaryPart = { label: Label; items: string[] };
/** lead: lines written before the first label; kept and shown at the top as they are (never dropped). */
export type ParsedSummary = { lead: string; glance: string; parts: SummaryPart[] };

export function parseSummary(text: string): ParsedSummary | null {
  const parts: SummaryPart[] = [];
  const byName = new Map<string, SummaryPart>();
  const glance: string[] = [];
  const lead: string[] = [];
  let current: SummaryPart | 'glance' | null = null;
  for (const raw of (text ?? '').replace(/\r\n?/g, '\n').split('\n')) {
    const m = labelLine(raw);
    if (m) {
      if (m.label.role === 'glance') {
        current = 'glance';
        if (m.rest.trim()) glance.push(m.rest.trim());
        continue;
      }
      let part = byName.get(m.label.name);
      if (!part) {
        part = { label: m.label, items: [] };
        byName.set(m.label.name, part);
        parts.push(part);
      }
      current = part;
      if (m.rest.trim()) part.items.push(m.rest.trim());
      continue;
    }
    if (!current) {
      lead.push(raw);
      continue;
    }
    const line = raw.trim();
    if (!line) continue;
    if (current === 'glance') {
      glance.push(line.replace(/^[-*]\s+/, ''));
      continue;
    }
    const list = current.items;
    if (/^[-*]\s+/.test(line)) list.push(line.replace(/^[-*]\s+/, ''));
    else if (list.length) list[list.length - 1] += ' ' + line;
    else list.push(line);
  }
  if (!parts.length && !glance.length) return null;
  return { lead: lead.join('\n').trim(), glance: glance.join(' '), parts };
}

/** Cells of a table item: «a | b | c». */
export function cells(item: string): string[] {
  return item.split('|').map((c) => c.trim());
}

export function parseTerms(text: string): Term[] {
  return (parseSummary(text)?.parts ?? [])
    .filter((p) => p.label.role === 'terms')
    .flatMap((p) => p.items)
    .map(cells)
    .filter((c) => c[0])
    .map((c) => ({ fa: c[0], en: c[1] ?? '', meaning: c[2] ?? '' }));
}

/** «متن [[عبارت]]» → shown text and the phrase to find in the notes (or the first bold words). */
export function jumpTarget(item: string): { text: string; phrase: string } {
  // «[[#name]]» is a link to a numbered box (kept in the text), not a phrase of the notes.
  const m = item.match(/\[\[(?!#)([^\]]+)\]\]/);
  const text = item.replace(/\s*\[\[(?!#)[^\]]+\]\]\s*/g, ' ').trim();
  if (m) return { text, phrase: m[1].trim() };
  const bold = text.match(/\*\*([^*]+)\*\*/);
  return { text, phrase: bold ? bold[1].trim() : '' };
}
