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

import { jumpTarget, parseParts } from './reviewCard';

const md = new MarkdownIt({ html: false, linkify: false, typographer: false });

const BOX_LABEL: Record<string, string> = { نکته: 'نکته', تله: 'تله‌ی تستی', هشدار: 'هشدار', مثال: 'مثال' };

function renderMath(tex: string, display: boolean): string {
  const html = katex.renderToString(tex, { output: 'mathml', displayMode: display, throwOnError: false, strict: 'ignore' });
  return display ? `<div class="math-block" dir="ltr">${html}</div>` : `<span class="math" dir="ltr">${html}</span>`;
}

function renderInline(source: string): string {
  const html = renderPlain(source).trim();
  return html.replace(/^<p>([\s\S]*)<\/p>$/, '$1');
}

function esc(s: string) {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
}

const PART_TITLES: [string, string, string][] = [
  ['important', 'مهم‌ترین‌ها', 'rc-important'],
  ['rules', 'قاعده و فرمول', 'rc-rules'],
  ['memorize', 'حفظی', 'rc-memorize'],
  ['traps', 'تله‌ها', 'rc-traps'],
];

/** A summary written in labelled parts becomes a review card; any other summary stays plain Markdown. */
export function renderSummary(source: string, opts: { hasCards?: boolean } = {}): string {
  const parts = parseParts(source);
  if (!parts) return renderMarkdown(source);
  let html = '<div class="rc">';
  if (parts.glance?.length) html += `<div class="rc-glance">${renderInline(parts.glance.join(' '))}</div>`;
  for (const [key, title, cls] of PART_TITLES) {
    const items = parts[key as keyof typeof parts];
    if (!items?.length) continue;
    html += `<section class="rc-part ${cls}"><h4>${title}</h4><ul>`;
    for (const item of items) {
      if (key === 'important') {
        const { text, phrase } = jumpTarget(item);
        html += `<li><a class="jump" data-q="${esc(phrase)}">${renderInline(text)}<span class="go" aria-hidden="true">←</span></a></li>`;
      } else html += `<li>${renderInline(item)}</li>`;
    }
    html += '</ul>';
    if (key === 'memorize' && opts.hasCards) html += '<button class="rc-cards">مرور فلش‌کارت‌های این بخش</button>';
    html += '</section>';
  }
  if (parts.terms?.length) {
    html += '<section class="rc-part rc-terms"><h4>واژه‌نامه</h4>';
    for (const item of parts.terms) {
      const [fa, en = '', meaning = ''] = item.split('|').map((c) => c.trim());
      html += `<div class="term"><div class="term-head"><b>${esc(fa)}</b>${en ? `<span class="en" dir="ltr">${esc(en)}</span>` : ''}</div>${meaning ? `<div class="mean">${renderInline(meaning)}</div>` : ''}</div>`;
    }
    html += '</section>';
  }
  return html + '</div>';
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
.rc { display: grid; gap: 14px; }
.rc-glance { font-size: 1.08em; font-weight: 700; background: #FFF6CF; border-radius: 16px; padding: 12px 14px; }
.rc-part { background: #fff; border: 1px solid #E3E8DE; border-radius: 16px; padding: 10px 14px 12px; }
.rc-part h4 { margin: 0 0 6px; font-size: .82em; letter-spacing: .02em; color: #56655B; }
.rc-part ul { margin: 0; padding: 0 18px 0 0; }
.rc-part li { margin: 4px 0; }
.rc-important li { list-style: none; margin-right: -18px; }
.rc-important a.jump { display: flex; align-items: center; gap: 8px; color: inherit; text-decoration: none; padding: 7px 10px; border-radius: 12px; background: #F6F7F2; cursor: pointer; }
.rc-important a.jump .go { margin-right: auto; color: #B9A23A; font-weight: 800; }
.rc-traps { border-color: #F2C7C4; background: #FFF8F7; } .rc-traps h4 { color: #9E2F2A; }
.rc-memorize h4 { color: #6B5200; }
.next-card { display: block; margin: 28px 0 8px; padding: 14px 16px; border-radius: 18px; min-height: 48px; box-sizing: border-box; background: #17201A; color: #F3F1E7; text-decoration: none; cursor: pointer; }
.next-card small { display: block; color: #F5C518; font-weight: 800; font-size: .8em; }
.next-card b { display: block; font-size: 1em; margin-top: 2px; }
.next-card b::after { content: " ←"; color: #F5C518; } /* «←»; «‹» is mirrored in Persian text and points back */
.st-box { margin: 28px 0 0; padding: 10px 12px; border-radius: 18px; border: 1px solid #E3E8DE; background: #F6F7F2; }
.st-box small { display: block; color: #56655B; font-weight: 800; font-size: .75em; margin-bottom: 6px; }
.st-row { display: flex; flex-wrap: wrap; gap: 6px; }
.st-done, .st-go { display: inline-block; padding: 4px 10px; border-radius: 999px; font-size: .82em; font-weight: 700; line-height: 1.8; text-decoration: none; }
.st-done, .st-ok { background: #E3F3E9; color: #1F5E3A; }
.st-go { background: #fff; color: #17201A; border: 1px solid #E3E8DE; cursor: pointer; }
.st-go.st-ok { background: #E3F3E9; color: #1F5E3A; border-color: #BFE8CF; }
.st-box + .next-card, .st-box + .ch-end { margin-top: 10px; }
.ch-end { margin: 28px 0 8px; padding: 16px; border-radius: 18px; background: #17201A; color: #F3F1E7; }
.ch-title { color: #F5C518; font-weight: 900; font-size: 17px; line-height: 1.7; }
.ch-text { font-size: 14px; line-height: 1.8; color: #C9D2C6; margin: 4px 0 12px; }
/* Controls keep the app's size whatever the reading font: 48 high, 15px text, corners 12 inside the box's 18. */
.ch-btn { display: flex; align-items: center; justify-content: center; min-height: 48px; box-sizing: border-box; text-align: center;
  padding: 6px 12px; border-radius: 12px; margin-top: 8px; border: 1.5px solid #3A4A40; color: #F3F1E7; font-size: 15px; line-height: 1.6;
  font-weight: 800; text-decoration: none; cursor: pointer; }
.ch-main { background: #F5C518; border-color: #F5C518; color: #17201A; }
.lesson.dark .st-box { background: #1E2621; border-color: #33403A; } .lesson.dark .st-go { background: #26302A; color: #E4E9E2; border-color: #33403A; }
.rc-cards { margin-top: 8px; border: 0; border-radius: 12px; padding: 8px 12px; background: #17201A; color: #F5C518; font: inherit; font-size: .85em; font-weight: 800; cursor: pointer; }
.term { padding: 6px 0; border-bottom: 1px dashed #E3E8DE; } .term:last-child { border-bottom: 0; }
.term-head { display: flex; align-items: baseline; gap: 10px; flex-wrap: wrap; }
.term .en { font-family: system-ui, sans-serif; font-size: .88em; color: #3B44B8; }
.term .mean { font-size: .9em; color: #56655B; }
.gl { border-bottom: 1.5px dotted #B9A23A; cursor: help; }
mark.flash { background: #FFD43B; border-radius: 4px; box-shadow: 0 0 0 5px rgba(255,212,59,.45); transition: background 1.4s, box-shadow 1.4s; }
mark.flash.fade { background: transparent; box-shadow: 0 0 0 0 rgba(255,212,59,0); }
.lesson.dark .rc-glance { background: #3A3216; } .lesson.dark .rc-part { background: #1E2621; border-color: #33403A; }
.lesson.dark .rc-important a.jump { background: #26302A; } .lesson.dark .rc-traps { background: #2E1F1E; border-color: #5A3330; }
.lesson.dark .term .en { color: #AEB4F5; } .lesson.dark mark.flash { color: #17201A; }
.lesson.sepia .rc-part { background: #FBF5E6; border-color: #E6D8B8; } .lesson.sepia .rc-important a.jump { background: #F1E6CC; }
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
  var t = e.target && e.target.closest ? e.target : null;
  if (!t) return;
  var j = t.closest('a.jump'); if (j) { e.preventDefault(); post({ type: 'jump', q: j.getAttribute('data-q') || '' }); return; }
  if (t.closest('.rc-cards')) { post({ type: 'cards' }); return; }
  if (t.closest('.next-card')) { post({ type: 'next' }); return; }
  var go = t.closest('[data-go]'); if (go) { post({ type: 'go', to: go.getAttribute('data-go') }); return; }
  var g = t.closest('.gl'); if (g) { post({ type: 'term', fa: g.getAttribute('data-t') }); return; }
  var m = t.closest('mark.hl');
  if (m) post({ type: 'note', id: Number(m.getAttribute('data-note')) });
});
// Show where an important point is in the notes: find it, scroll to it, light it up for a moment.
root.__flash = function (q) {
  var old = root.querySelectorAll('mark.flash');
  for (var i = 0; i < old.length; i++) { var o = old[i], p = o.parentNode; while (o.firstChild) p.insertBefore(o.firstChild, o); p.removeChild(o); p.normalize(); }
  q = norm(q || '').trim(); if (!q) return;
  var nodes = textNodes(), hit = null;
  for (var k = 0; k < nodes.length && !hit; k++) {
    var v = nodes[k].nodeValue.replace(/\s/g, ' '), at = v.indexOf(q);
    if (at >= 0) { var after = nodes[k].splitText(at + q.length); var mid = nodes[k].splitText(at); void after; hit = mid; }
  }
  if (!hit) { post({ type: 'flash_missing' }); return; }
  var m = document.createElement('mark'); m.className = 'flash'; hit.parentNode.insertBefore(m, hit); m.appendChild(hit);
  var block = m.closest('li, p, .box, .table-wrap') || m;
  block.scrollIntoView({ block: 'center', behavior: 'smooth' });
  setTimeout(function () { m.classList.add('fade'); }, 1800);
};
// Glossary words in the notes: dotted underline, tap for the English word and meaning.
root.__setTerms = function (list) {
  if (!list || !list.length) return;
  var words = list.slice().sort(function (a, b) { return b.length - a.length; });
  var nodes = textNodes();
  for (var i = 0; i < nodes.length; i++) {
    var n = nodes[i]; if (!n.parentNode || (n.parentNode.closest && n.parentNode.closest('.gl, mark, .rc, h1, h2, h3, h4'))) continue;
    for (var w = 0; w < words.length; w++) {
      var at = n.nodeValue.indexOf(words[w]);
      if (at < 0) continue;
      var before = at > 0 ? n.nodeValue.charAt(at - 1) : ' ', after = n.nodeValue.charAt(at + words[w].length) || ' ';
      if (/[\u0600-\u06FFa-zA-Z]/.test(before)) continue;
      var rest = n.splitText(at); var tail = rest.splitText(words[w].length); void tail;
      var s = document.createElement('span'); s.className = 'gl'; s.setAttribute('data-t', words[w]);
      rest.parentNode.insertBefore(s, rest); s.appendChild(rest);
      break;
    }
  }
};
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
// Turning the page with a finger: a clear sideways drag (not a scroll, not a long press, not inside a wide table)
// moves the page with the finger, right here in the page (no round trip to the app, so it stays smooth on slow
// phones). Let go far enough, or flick, and the page slides out and the app opens the next or previous section.
// The app says which way there is a page to go to with root.__setTurn({ next: bool, prev: bool }).
(function () {
  if (root.__turnBound) return;
  root.__turnBound = true;
  var can = { next: false, prev: false };
  root.__setTurn = function (c) { can = c || can; };
  var target = window.ReactNativeWebView ? document : root;
  var t = null;
  function scrollsSideways(el) {
    for (; el && el !== document.body && el !== document.documentElement; el = el.parentElement) {
      if (el.scrollWidth > el.clientWidth + 2) { var o = getComputedStyle(el).overflowX; if (o === 'auto' || o === 'scroll') return true; }
    }
    return false;
  }
  function place(x, ms) {
    root.style.transition = ms ? 'transform ' + ms + 'ms cubic-bezier(.2,.7,.2,1), opacity ' + ms + 'ms' : 'none';
    root.style.transform = x ? 'translate3d(' + x + 'px,0,0)' : '';
    root.style.opacity = x ? String(Math.max(0.35, 1 - Math.abs(x) / (window.innerWidth * 1.4))) : '';
  }
  target.addEventListener('touchstart', function (e) {
    if (e.touches.length !== 1) { t = null; return; }
    var p = e.touches[0], sel = window.getSelection ? String(window.getSelection()) : '';
    t = { x0: p.clientX, y0: p.clientY, at: Date.now(), on: false, off: !!sel || scrollsSideways(e.target), px: p.clientX, pt: Date.now(), vx: 0, dx: 0 };
  }, { passive: true });
  target.addEventListener('touchmove', function (e) {
    if (!t || t.off) return;
    var p = e.touches[0], dx = p.clientX - t.x0, dy = p.clientY - t.y0;
    if (!t.on) {
      if (Date.now() - t.at > 450 || (Math.abs(dy) > 12 && Math.abs(dy) > Math.abs(dx))) { t.off = true; return; }
      if (Math.abs(dx) < 14 || Math.abs(dx) < 1.6 * Math.abs(dy)) return;
      t.on = true;
      if (window.getSelection) window.getSelection().removeAllRanges();
    }
    e.preventDefault();
    var now = Date.now();
    if (now > t.pt) { t.vx = (p.clientX - t.px) / (now - t.pt); t.px = p.clientX; t.pt = now; }
    // Right is the next section (a Persian book turns to the right), left the previous one.
    var open = dx > 0 ? can.next : can.prev;
    t.dx = open ? dx : dx * 0.22;
    place(t.dx, 0);
  }, { passive: false });
  function end() {
    if (!t || !t.on) { t = null; return; }
    var dx = t.dx, w = window.innerWidth, dir = dx > 0 ? 1 : -1;
    var open = dir > 0 ? can.next : can.prev;
    var flick = Math.abs(t.vx) > 0.3 && (t.vx > 0) === (dx > 0);
    t = null;
    if (open && (Math.abs(dx) > w * 0.28 || flick)) {
      place(dir * w, 180);
      setTimeout(function () { post({ type: 'turn', dir: dir }); }, 170);
    } else place(0, 220);
  }
  target.addEventListener('touchend', end);
  target.addEventListener('touchcancel', end);
  // Coming back to this page (the app keeps it): put it in place again.
  root.__resetTurn = function () { place(0, 0); };
})();
`;

/** What is left in this section for the learner (shown at the end of the page). */
export type SectionStatus = { read: boolean; questions: number; questions_left: number; cards: number; cards_due: number; cards_new: number };
/** The last section of a chapter: the chapter's summary exam and the next chapter, or the end of the book. */
export type ChapterEnd = {
  chapter_id: number;
  chapter_title: string;
  chapter_number?: number | null;
  /** The suggested summary exam: how many questions (0 = the chapter has none) and about how many minutes. */
  exam_questions?: number;
  exam_minutes?: number;
  book_slug: string;
  book_title: string;
  next_chapter: { id: number; chapter_title: string; title: string; locked: boolean } | null;
  /** The learner's chapter: complete (read and tested), or what is left. Null for a guest. */
  progress?: { state: 'complete' | 'tests' | 'notes'; tests_left: number; notes_left: number } | null;
};
export type PageEnd = { nextTitle?: string | null; status?: SectionStatus | null; chapterEnd?: ChapterEnd | null };

const escHtml = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
const fa = (n: number) => String(n).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[Number(d)]);

/** The end of a section: what is left here (each part opens directly), then the next section, or the chapter's end. */
export function pageEndHtml(end?: PageEnd): string {
  if (!end) return '';
  let html = '';
  const s = end.status;
  if (s && (s.questions || s.cards || s.read)) {
    const parts: string[] = [];
    if (s.read) parts.push('<span class="st-done">✓ جزوه خوانده شد</span>');
    if (s.questions)
      parts.push(
        s.questions_left
          ? `<a class="st-go" data-go="quiz" role="button">${fa(s.questions_left)} تست باقی است</a>`
          : `<a class="st-go st-ok" data-go="quiz" role="button">✓ همه‌ی ${fa(s.questions)} تست را زده‌ای</a>`,
      );
    if (s.cards_due) parts.push(`<a class="st-go" data-go="cards" role="button">${fa(s.cards_due)} کارت موعد مرور دارد</a>`);
    else if (s.cards_new) parts.push(`<a class="st-go" data-go="cards" role="button">${fa(s.cards_new)} فلش‌کارت تازه</a>`);
    html += `<div class="st-box"><small>این بخش</small><div class="st-row">${parts.join('')}</div></div>`;
  }
  if (end.nextTitle) {
    html += `<a class="next-card" role="button"><small>بخش بعد</small><b>${escHtml(end.nextTitle)}</b></a>`;
  } else if (end.chapterEnd) {
    const c = end.chapterEnd;
    const next = c.next_chapter;
    const name = `فصل ${c.chapter_number ? fa(c.chapter_number) + ' ' : ''}«${escHtml(c.chapter_title)}»`;
    const n = c.exam_questions ?? 0;
    const p = c.progress;
    // Three states, so reaching the last page is never mistaken for finishing the chapter.
    const title =
      p?.state === 'complete'
        ? `${name} را کامل کردی!${next ? '' : ` کتاب «${escHtml(c.book_title)}» هم به آخر رسید.`}`
        : `به پایان جزوه‌های ${name} رسیدی`;
    const text =
      p?.state === 'tests'
        ? `برای کامل شدن این فصل، ${fa(p.tests_left)} تست مانده.`
        : p?.state === 'notes'
          ? `${fa(p.notes_left)} بخش این فصل هنوز تا آخر خوانده نشده.`
          : n
            ? `با یک آزمون ${fa(n)} سؤالی از کل این فصل (حدود ${fa(c.exam_minutes || 1)} دقیقه) ببین چقدرش در ذهنت مانده.`
            : '';
    // One main action that fits the state; the next chapter (or the book) is the second.
    const main =
      p?.state === 'tests'
        ? `<a class="ch-btn ch-main" data-go="chapter-quiz" role="button">زدن ${fa(p.tests_left)} تست مانده</a>`
        : p?.state === 'notes'
          ? '<a class="ch-btn ch-main" data-go="book" role="button">دیدن بخش‌های مانده</a>'
          : n
            ? `<a class="ch-btn ch-main" data-go="exam" role="button">آزمون ${fa(n)} سؤالی این فصل</a>`
            : '';
    const second = next
      ? `<a class="ch-btn${main ? '' : ' ch-main'}" data-go="next-chapter" role="button">${next.locked ? '🔒 ' : ''}فصل بعد: ${escHtml(next.chapter_title)} ←</a>`
      : p?.state === 'notes'
        ? ''
        : '<a class="ch-btn" data-go="book" role="button">برگشت به صفحه‌ی کتاب</a>';
    html += `<div class="ch-end"><div class="ch-title">${title}</div>${text ? `<div class="ch-text">${text}</div>` : ''}${main}${second}</div>`;
  }
  return html;
}
