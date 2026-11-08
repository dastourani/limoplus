/**
 * The panel's text editor (backend/apps/catalog/static/catalog/limo-editor.js): CodeMirror in place of a <textarea>,
 * so Persian lines read right to left while formulas, Latin words and numbers inside them stay in the order they
 * were typed (each is isolated left to right), and $…$ formulas and «:::» box lines are tinted.
 *
 * `LimoCM.upgrade(textarea)` keeps the textarea in the page (hidden) and makes it speak for the editor: value,
 * selectionStart/End, setSelectionRange, setRangeText, focus, select, and 'input' / 'keydown' events, so the panel's
 * code works unchanged. `LimoCM.insert(textarea, text)` replaces the selection as one undo step.
 * Rebuild: cd app && npm run build:admin-editor
 */
import { EditorSelection, EditorState, RangeSetBuilder, Transaction } from '@codemirror/state';
import { Decoration, type DecorationSet, Direction, EditorView, keymap, ViewPlugin, type ViewUpdate } from '@codemirror/view';
import { defaultKeymap, history, historyKeymap, indentWithTab, redo as cmRedo, undo as cmUndo } from '@codemirror/commands';

type Upgraded = HTMLTextAreaElement & { __cm?: EditorView };

const PERSIAN = /[؀-ۿﭐ-﷿ﹰ-﻿]/;
// The browser draws an isolate only from the element's own dir and unicode-bidi; CodeMirror needs bidiIsolate too
// (for the cursor's movement through the line).
const ltr = Decoration.mark({ class: 'cm-ltr', attributes: { dir: 'ltr' }, bidiIsolate: Direction.LTR });
const math = Decoration.mark({ class: 'cm-math', attributes: { dir: 'ltr' }, bidiIsolate: Direction.LTR });
const boxLine = Decoration.line({ class: 'cm-box-line' });
const keyMark = Decoration.mark({ class: 'cm-key' });

/** The parts of a line to keep left to right: $…$ / $$…$$ formulas, and runs of Latin, digits and symbols. */
export function ltrRuns(line: string): { from: number; to: number; math: boolean }[] {
  const out: { from: number; to: number; math: boolean }[] = [];
  let i = 0;
  while (i < line.length) {
    if (line[i] === '$') {
      const dbl = line[i + 1] === '$';
      const close = line.indexOf(dbl ? '$$' : '$', i + (dbl ? 2 : 1));
      if (close > i) {
        const end = close + (dbl ? 2 : 1);
        out.push({ from: i, to: end, math: true });
        i = end;
        continue;
      }
    }
    // A Latin run starts at a Latin letter, digit, backslash or bracket and goes on until a Persian letter.
    if (/[A-Za-z0-9\\([{|^_]/.test(line[i]) || (line[i] === '-' && /[A-Za-z0-9(]/.test(line[i + 1] ?? ''))) {
      let j = i;
      while (j < line.length && !PERSIAN.test(line[j]) && line[j] !== '$') j++;
      // Trailing spaces and punctuation belong to the Persian text around it.
      let end = j;
      while (end > i && /[\s،؛:.]/.test(line[end - 1])) end--;
      if (end > i) out.push({ from: i, to: end, math: false });
      i = Math.max(j, i + 1);
      continue;
    }
    i++;
  }
  return out;
}

function build(view: EditorView): DecorationSet {
  const b = new RangeSetBuilder<Decoration>();
  for (const { from, to } of view.visibleRanges) {
    let pos = from;
    while (pos <= to) {
      const line = view.state.doc.lineAt(pos);
      const text = line.text;
      if (/^:::/.test(text)) b.add(line.from, line.from, boxLine);
      // «تابع: …» and other «key:» lines of plots and tests: the key in its own colour.
      const key = /^([^\s:$][^:$]{0,24}):/.exec(text);
      const runs = ltrRuns(text);
      let keyDone = !key || runs.some((r) => r.from < key[1].length);
      for (const r of runs) {
        if (!keyDone && r.from >= key![1].length) {
          b.add(line.from, line.from + key![1].length, keyMark);
          keyDone = true;
        }
        b.add(line.from + r.from, line.from + r.to, r.math ? math : ltr);
      }
      if (!keyDone) b.add(line.from, line.from + key![1].length, keyMark);
      if (line.to >= to) break;
      pos = line.to + 1;
    }
  }
  return b.finish();
}

const isolates = ViewPlugin.fromClass(
  class {
    decorations: DecorationSet;
    constructor(view: EditorView) {
      this.decorations = build(view);
    }
    update(u: ViewUpdate) {
      if (u.docChanged || u.viewportChanged) this.decorations = build(u.view);
    }
  },
  {
    decorations: (v) => v.decorations,
    provide: (plugin) => EditorView.bidiIsolatedRanges.of((view) => view.plugin(plugin)?.decorations ?? Decoration.none),
  },
);

const theme = EditorView.theme({
  '&': { fontSize: '15px', backgroundColor: 'var(--card, #fff)', border: '1px solid var(--line, #dde2d8)', borderRadius: '8px' },
  '&.cm-focused': { outline: '2px solid rgba(232,185,35,.45)' },
  '.cm-content': { fontFamily: 'inherit', lineHeight: '1.9', padding: '8px 4px', caretColor: 'currentColor' },
  '.cm-scroller': { fontFamily: 'inherit' },
  '.cm-line': { padding: '0 8px' },
  '.cm-math, .cm-ltr': { unicodeBidi: 'isolate' },
  // Colours are CSS variables (panel.css), so the admin's dark theme can give lighter ones.
  '.cm-math': { color: 'var(--cm-math, #3B44B8)', backgroundColor: 'var(--cm-math-bg, rgba(59,68,184,.06))', borderRadius: '3px' },
  '.cm-ltr': { color: 'var(--cm-ltr, #1f5e3a)' },
  '.cm-key': { color: 'var(--cm-key, #7A4F00)', fontWeight: '700' },
  '.cm-box-line': { backgroundColor: 'rgba(232,185,35,.12)' },
});

/** Replace the editor's selection (or a range) as one undo step, like typing it. */
function replace(view: EditorView, text: string, from?: number, to?: number) {
  const sel = view.state.selection.main;
  const a = from ?? sel.from, b = to ?? sel.to;
  view.dispatch({ changes: { from: a, to: b, insert: text }, selection: EditorSelection.cursor(a + text.length), userEvent: 'input' });
}

export function upgrade(ta: Upgraded, opts: { minLines?: number } = {}): EditorView | null {
  if (ta.__cm) return ta.__cm;
  if (!ta.parentNode) {
    // Not in the page yet: try again once it is.
    let tries = 0;
    const wait = () => (ta.parentNode ? upgrade(ta, opts) : tries++ < 50 && setTimeout(wait, 20));
    setTimeout(wait, 0);
    return null;
  }
  const minLines = opts.minLines ?? Number(ta.getAttribute('rows') || 3);
  const view = new EditorView({
    state: EditorState.create({
      doc: ta.value,
      extensions: [
        history(),
        keymap.of([...defaultKeymap, ...historyKeymap, indentWithTab]),
        EditorView.lineWrapping,
        EditorView.perLineTextDirection.of(true),
        EditorView.contentAttributes.of({ dir: 'auto', spellcheck: 'false' }),
        // CodeMirror owns the editor element's class attribute: a class added by hand is wiped on the next update.
        EditorView.editorAttributes.of({ class: 'limo-cm' }),
        isolates,
        theme,
        EditorView.theme({ '.cm-content': { minHeight: `${Math.max(1, minLines) * 1.9 + 1}em` } }),
        EditorView.updateListener.of((u) => {
          if (u.docChanged) ta.dispatchEvent(new Event('input', { bubbles: true }));
          // The cursor moved: the panel shows the formula under it.
          if (u.selectionSet || u.docChanged) ta.dispatchEvent(new Event('limo-cursor'));
        }),
        EditorView.domEventHandlers({
          keydown(e) {
            // The panel's own shortcuts (Ctrl+B) listen on the textarea.
            const copy = new KeyboardEvent('keydown', e);
            ta.dispatchEvent(copy);
            if (copy.defaultPrevented) {
              e.preventDefault();
              return true;
            }
            return false;
          },
        }),
      ],
    }),
  });
  ta.style.display = 'none';
  ta.parentNode.insertBefore(view.dom, ta.nextSibling);
  const doc = () => view.state.doc.toString();
  Object.defineProperties(ta, {
    value: {
      get: doc,
      // Setting the value from code starts over, like a textarea (not an undo step).
      set: (v: string) => view.dispatch({ changes: { from: 0, to: view.state.doc.length, insert: String(v ?? '') }, annotations: Transaction.addToHistory.of(false) }),
      configurable: true,
    },
    selectionStart: { get: () => view.state.selection.main.from, configurable: true },
    selectionEnd: { get: () => view.state.selection.main.to, configurable: true },
  });
  ta.setSelectionRange = (a: number | null, b: number | null) => {
    const len = view.state.doc.length;
    const from = Math.max(0, Math.min(len, a ?? 0)), to = Math.max(0, Math.min(len, b ?? from));
    view.dispatch({ selection: EditorSelection.range(from, to), scrollIntoView: true });
  };
  ta.setRangeText = ((text: string, a?: number, b?: number) => replace(view, text, a, b)) as HTMLTextAreaElement['setRangeText'];
  ta.focus = () => view.focus();
  ta.select = () => view.dispatch({ selection: EditorSelection.range(0, view.state.doc.length) });
  ta.__cm = view;
  return view;
}

/** ↶ and ↷ of the panel's toolbar; false for a plain textarea (the caller uses execCommand). */
export function undo(ta: Upgraded): boolean {
  if (!ta.__cm) return false;
  cmUndo(ta.__cm);
  ta.__cm.focus();
  return true;
}
export function redo(ta: Upgraded): boolean {
  if (!ta.__cm) return false;
  cmRedo(ta.__cm);
  ta.__cm.focus();
  return true;
}

/** Insert text at the selection of an upgraded textarea; false for a plain one (the caller uses execCommand). */
export function insert(ta: Upgraded, text: string): boolean {
  if (!ta.__cm) return false;
  replace(ta.__cm, text);
  return true;
}

(globalThis as unknown as { LimoCM: unknown }).LimoCM = { upgrade, insert, ltrRuns, undo, redo };
