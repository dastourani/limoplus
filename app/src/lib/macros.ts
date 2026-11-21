/**
 * «دستورهای فرمول» (the panel's FormulaCommand list): short commands such as «\R» → «\mathbb{R}», used by KaTeX in every
 * formula. Kept apart from storage so the panel's preview bundle can use it too (lib/macrosStore.ts keeps it on the phone).
 */
let current: Record<string, string> = {};
let onChange: ((list: Record<string, string>) => void) | null = null;

export function setMacros(list: Record<string, string> | null | undefined) {
  if (!list) return;
  const changed = JSON.stringify(list) !== JSON.stringify(current);
  current = list;
  if (changed) onChange?.(list);
}

export function macros(): Record<string, string> {
  return current;
}

export function onMacrosChange(fn: (list: Record<string, string>) => void) {
  onChange = fn;
}
