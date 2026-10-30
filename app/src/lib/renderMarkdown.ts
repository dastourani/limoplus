/**
 * Lesson Markdown → HTML, shared by the native (WebView) and web renderers.
 *
 * - Formulas: $…$ inline and $$…$$ display, rendered by KaTeX as MathML (no fonts or CSS files needed),
 *   always isolated left-to-right inside the right-to-left text.
 * - Boxes: :::نکته / :::تله / :::هشدار / :::مثال blocks.
 * - Raw HTML in the source is escaped (html: false).
 */
import katex from 'katex';
import MarkdownIt from 'markdown-it';

const md = new MarkdownIt({ html: false, linkify: false, typographer: false });

const BOX_LABEL: Record<string, string> = { نکته: 'نکته', تله: 'تله‌ی تستی', هشدار: 'هشدار', مثال: 'مثال' };

function renderMath(tex: string, display: boolean): string {
  const html = katex.renderToString(tex, { output: 'mathml', displayMode: display, throwOnError: false, strict: 'ignore' });
  return display ? `<div class="math-block" dir="ltr">${html}</div>` : `<span class="math" dir="ltr">${html}</span>`;
}

function renderPlain(source: string): string {
  const formulas: string[] = [];
  const keep = (html: string) => `@@MATH${formulas.push(html) - 1}@@`;
  let text = source.replace(/\$\$([\s\S]+?)\$\$/g, (_, tex: string) => `\n\n${keep(renderMath(tex.trim(), true))}\n\n`);
  text = text.replace(/(^|[^\\])\$([^$\n]+?)\$/g, (_, before: string, tex: string) => before + keep(renderMath(tex.trim(), false)));
  let html = md.render(text);
  html = html.replace(/<p>\s*(@@MATH\d+@@)\s*<\/p>/g, '$1');
  html = html.replace(/@@MATH(\d+)@@/g, (_, i: string) => formulas[Number(i)]);
  html = html.replace(/<table>/g, '<div class="table-wrap"><table>').replace(/<\/table>/g, '</table></div>');
  return html;
}

export function renderMarkdown(source: string): string {
  const lines = (source ?? '').replace(/\r\n?/g, '\n').split('\n');
  const parts: string[] = [];
  let buffer: string[] = [];
  const flush = () => {
    if (buffer.length) parts.push(renderPlain(buffer.join('\n')));
    buffer = [];
  };
  for (let i = 0; i < lines.length; i++) {
    const open = lines[i].match(/^:::\s*(\S+)\s*$/);
    if (open && BOX_LABEL[open[1]]) {
      const end = lines.findIndex((line, j) => j > i && line.trim() === ':::');
      if (end > i) {
        flush();
        const kind = open[1];
        parts.push(
          `<div class="box box-${['نکته', 'تله', 'هشدار', 'مثال'].indexOf(kind)}"><div class="box-title">${BOX_LABEL[kind]}</div>${renderPlain(
            lines.slice(i + 1, end).join('\n'),
          )}</div>`,
        );
        i = end;
        continue;
      }
    }
    buffer.push(lines[i]);
  }
  flush();
  return parts.join('\n');
}

export const CONTENT_CSS = `
:root { color-scheme: light; }
* { box-sizing: border-box; }
body { margin: 0; background: transparent; color: #17201A; }
.lesson { color: #17201A; }
.lesson { direction: rtl; text-align: right; font-family: Vazirmatn, "Segoe UI", Tahoma, system-ui, sans-serif;
  font-size: var(--fs, 17px); line-height: var(--lh, 2); padding: 4px 20px 32px; overflow-wrap: anywhere; }
.lesson.compact { padding: 0; font-size: 16px; line-height: 1.9; }
.lesson p { margin: 0 0 14px; }
.lesson h1, .lesson h2, .lesson h3 { line-height: 1.5; margin: 22px 0 10px; }
.lesson strong { background: #FFF1B8; border-radius: 4px; padding: 0 3px; }
.lesson ul, .lesson ol { padding-right: 22px; padding-left: 0; margin: 0 0 14px; }
.lesson img { display: block; max-width: 100%; height: auto; margin: 12px auto; border-radius: 12px; background: #fff; }
.math { direction: ltr; unicode-bidi: isolate; display: inline-block; }
.math-block { direction: ltr; unicode-bidi: isolate; overflow-x: auto; overflow-y: hidden; text-align: center;
  margin: 14px 0; padding: 10px 6px; background: #fff; border: 1px solid #E3E8DE; border-radius: 16px; font-size: 1.15em; }
math { font-family: "STIX Two Math", "Cambria Math", "Latin Modern Math", serif; }
.table-wrap { overflow-x: auto; margin: 0 0 16px; border: 1px solid #E3E8DE; border-radius: 14px; background: #fff; }
.table-wrap table { border-collapse: collapse; min-width: 100%; font-size: 0.92em; }
.table-wrap th, .table-wrap td { padding: 10px 12px; border-bottom: 1px solid #E3E8DE; text-align: right; white-space: nowrap; }
.table-wrap th { background: #F6F7F2; color: #56655B; font-weight: 700; }
.table-wrap tr:last-child td { border-bottom: 0; }
.box { border-radius: 16px; padding: 12px 14px 2px; margin: 0 0 16px; }
.box-title { font-weight: 800; margin-bottom: 4px; }
.box-0 { background: #E3F3E9; } .box-0 .box-title { color: #1F5E3A; }
.box-1, .box-2 { background: #FFF6D6; } .box-1 .box-title, .box-2 .box-title { color: #7A4F00; }
.box-3 { background: #EEF0FC; } .box-3 .box-title { color: #3B44B8; }
mark.hl { color: inherit; border-radius: 3px; padding: 0 1px; }
mark.hl-yellow { background: #FFE98A; } mark.hl-green { background: #BFE8CF; } mark.hl-blue { background: #C9DBFF; } mark.hl-pink { background: #FFD0DF; }
.lesson.no-select { -webkit-user-select: none; user-select: none; }
/* Sepia reading */
.lesson.sepia { color: #4A3B2A; }
.lesson.sepia strong { background: #F3DE9E; }
.lesson.sepia .math-block, .lesson.sepia .table-wrap, .lesson.sepia img { background: #FBF5E6; border-color: #E6D8B8; }
.lesson.sepia .table-wrap th { background: #F1E6CC; color: #6B5840; }
.lesson.sepia .table-wrap th, .lesson.sepia .table-wrap td { border-color: #E6D8B8; }
/* Night reading */
.lesson.dark { color: #E4E9E2; }
.lesson.dark strong { background: #4A3F12; }
.lesson.dark .math-block, .lesson.dark .table-wrap, .lesson.dark img { background: #1E2621; border-color: #33403A; }
.lesson.dark .table-wrap th { background: #26302A; color: #B9C4BC; }
.lesson.dark .table-wrap th, .lesson.dark .table-wrap td { border-color: #33403A; }
.lesson.dark .box-0 { background: #1D3326; } .lesson.dark .box-0 .box-title { color: #9BE3B4; }
.lesson.dark .box-1, .lesson.dark .box-2 { background: #3A3216; } .lesson.dark .box-1 .box-title, .lesson.dark .box-2 .box-title { color: #F5D96B; }
.lesson.dark .box-3 { background: #23264A; } .lesson.dark .box-3 .box-title { color: #AEB4F5; }
.lesson.dark mark.hl { color: #17201A; }
`;

/** Longest text a learner may copy at once; longer copies are blocked (the book is protected). */
export const MAX_COPY_CHARS = 200;

/**
 * Reader behaviour that runs inside the lesson page (native WebView and web DOM alike), as a function body with
 * parameters (root, post): highlights, selection reporting and the copy limit. Kept as a string because release builds
 * cannot stringify functions.
 */
export const READER_SCRIPT = `
var MAX_COPY = ${MAX_COPY_CHARS};
function textNodes() {
  var out = [], walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT, null);
  var n; while ((n = walker.nextNode())) { if (n.parentNode && n.parentNode.closest && n.parentNode.closest('math')) continue; out.push(n); }
  return out;
}
function clearMarks() {
  var marks = root.querySelectorAll('mark.hl');
  for (var i = 0; i < marks.length; i++) { var m = marks[i]; var p = m.parentNode; while (m.firstChild) p.insertBefore(m.firstChild, m); p.removeChild(m); p.normalize(); }
}
function norm(s) { return s.replace(/\s+/g, ' '); }
function mark(quote, color, id) {
  var q = norm(quote).trim(); if (!q) return false;
  var nodes = textNodes(), full = '', starts = [];
  for (var i = 0; i < nodes.length; i++) { starts.push(full.length); full += norm(nodes[i].nodeValue); }
  var at = full.indexOf(q); if (at < 0) return false;
  var end = at + q.length;
  for (var j = nodes.length - 1; j >= 0; j--) {
    var s = starts[j], len = norm(nodes[j].nodeValue).length, e = s + len;
    if (e <= at || s >= end || len === 0) continue;
    var node = nodes[j], from = Math.max(0, at - s), to = Math.min(len, end - s);
    if (norm(node.nodeValue) !== node.nodeValue) { from = 0; to = node.nodeValue.length; }
    var after = node.splitText(to); var middle = node.splitText(from);
    var m = document.createElement('mark'); m.className = 'hl hl-' + color; m.setAttribute('data-note', id);
    middle.parentNode.insertBefore(m, middle); m.appendChild(middle); void after;
  }
  return true;
}
root.__setHighlights = function (list) {
  clearMarks();
  var missing = [];
  for (var i = 0; i < list.length; i++) { if (list[i].quote && !mark(list[i].quote, list[i].color, list[i].id)) missing.push(list[i].id); }
  post({ type: 'highlights', missing: missing });
};
root.addEventListener('click', function (e) {
  var m = e.target && e.target.closest ? e.target.closest('mark.hl') : null;
  if (m) post({ type: 'note', id: Number(m.getAttribute('data-note')) });
});
var selTimer = null;
document.addEventListener('selectionchange', function () {
  clearTimeout(selTimer);
  selTimer = setTimeout(function () {
    var sel = window.getSelection(); var text = sel ? sel.toString() : '';
    if (sel && sel.rangeCount && !root.contains(sel.getRangeAt(0).commonAncestorContainer)) text = '';
    post({ type: 'selection', text: text.slice(0, 2000) });
  }, 250);
});
root.addEventListener('copy', function (e) {
  var text = (window.getSelection() || '').toString();
  if (text.length > MAX_COPY) { e.preventDefault(); post({ type: 'copy_blocked' }); }
});
root.addEventListener('contextmenu', function (e) { if (e.target && e.target.tagName === 'IMG') e.preventDefault(); });
`;
