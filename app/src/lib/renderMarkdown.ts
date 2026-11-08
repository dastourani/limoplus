/**
 * Lesson Markdown → HTML, shared by the native (WebView) and web renderers.
 *
 * - Formulas: $…$ inline and $$…$$ display, rendered by KaTeX as MathML (no fonts or CSS files needed),
 *   always isolated left-to-right inside the right-to-left text.
 * - Boxes: «:::تعریف» … «:::» with any label of lib/labels.ts (the panel's «برچسب‌ها»).
 * - «[[phrase]]» (a jump link in the summary) shows as its plain words in the notes.
 * - Raw HTML in the source is escaped (html: false).
 */
import katex from 'katex';
import MarkdownIt from 'markdown-it';

import { findLabel } from './labels';
import { faDigits, numbering } from './numbering';
import { macros } from './macros';
import { fixMathVariants } from './mathvariant';
import { PLOT_CSS, renderPlot } from './plot';
import { DEFAULT_LABEL_ICON, labelIconSvg } from './labelIcons';
import { cells, jumpTarget, parseSummary } from './reviewCard';

const md = new MarkdownIt({ html: false, linkify: false, typographer: false });

function renderMath(tex: string, display: boolean, eq?: { id: string; label: string }): string {
  // A copy each time: KaTeX writes \gdef definitions into the object it is given.
  const html = fixMathVariants(
    katex.renderToString(tex, { output: 'mathml', displayMode: display, throwOnError: false, strict: 'ignore', macros: { ...macros() } }),
  );
  if (!display) return `<span class="math" dir="ltr">${html}</span>`;
  if (!eq) return `<div class="math-block" dir="ltr">${html}</div>`;
  // A named formula «$$…$$ {#name}»: its number on the left, «رابطه‌ی (۳-۲)» wherever [[#name]] points to it.
  return `<div class="math-block eq"${eq.id ? ` id="box-${esc(eq.id)}"` : ''} dir="ltr">${html}<span class="eq-n" aria-hidden="true">${eq.label}</span></div>`;
}

/** One formula alone (the panel's formula toolbox and the preview of the formula under the cursor). */
export function mathHtml(tex: string, display = false): string {
  return renderMath(tex, display);
}

/** Named display formulas are numbered over the chapter while a lesson is drawn (renderMarkdown sets this). */
let eqCount: { chapter?: number | null; n: number } | null = null;
function eqLabel(): string {
  if (!eqCount) return '';
  eqCount.n += 1;
  return `(${eqCount.chapter ? `${faDigits(eqCount.chapter)}-` : ''}${faDigits(eqCount.n)})`;
}

/** «==قرمز:متن==»: coloured words (red, blue, green). */
const COLORS: Record<string, string> = { قرمز: 'red', red: 'red', آبی: 'blue', blue: 'blue', سبز: 'green', green: 'green' };

function renderInline(source: string): string {
  const html = renderPlain(source).trim();
  return html.replace(/^<p>([\s\S]*)<\/p>$/, '$1');
}

function esc(s: string) {
  return s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
}

/** Escaped item text with a jump to the notes when it has «[[phrase]]» (or, for «مهم», its bold words). */
function itemHtml(item: string, alwaysJump: boolean): string {
  const { text, phrase } = jumpTarget(item);
  const linked = /\[\[(?!#)[^\]]+\]\]/.test(item) || (alwaysJump && phrase);
  if (!linked) return `<li>${renderInline(item)}</li>`;
  return `<li class="jl"><a class="jump" data-q="${esc(phrase)}">${renderInline(text)}<span class="go" aria-hidden="true">←</span></a></li>`;
}

/** A summary written in labelled parts becomes a review card; any other summary stays plain Markdown. */
export function renderSummary(source: string, opts: { hasCards?: boolean } = {}): string {
  const parsed = parseSummary(source);
  if (!parsed) return renderMarkdown(source);
  let html = '<div class="rc">';
  // Text written before the first label is part of the card too (shown as written, above the rest).
  if (parsed.lead) html += `<div class="rc-lead">${renderMarkdown(parsed.lead)}</div>`;
  if (parsed.glance) html += `<div class="rc-glance">${renderInline(jumpTarget(parsed.glance).text)}</div>`;
  for (const { label, items } of parsed.parts) {
    if (!items.length) continue;
    const role = label.role ? ` rc-${label.role}` : '';
    html += `<section class="rc-part rc-s-${label.style}${role}"><h4>${iconFor(label)}${esc(label.name)}</h4>`;
    if (label.role === 'terms') {
      for (const item of items) {
        const [fa, en = '', ...rest] = cells(item);
        const meaning = rest.join(' | ');
        html += `<div class="term"><div class="term-head"><b>${esc(fa)}</b>${en ? `<span class="en" dir="ltr">${esc(en)}</span>` : ''}</div>${meaning ? `<div class="mean">${renderInline(meaning)}</div>` : ''}</div>`;
      }
    } else if (label.style === 'table') {
      const cols = label.columns ?? [];
      html += '<div class="table-wrap"><table>';
      if (cols.length) html += `<thead><tr>${cols.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead>`;
      html += '<tbody>';
      for (const item of items) html += `<tr>${cells(item).map((c, i) => `<td${i ? '' : ' class="k"'}>${renderInline(c)}</td>`).join('')}</tr>`;
      html += '</tbody></table></div>';
    } else {
      html += '<ul>';
      for (const item of items) html += itemHtml(item, label.role === 'important');
      html += '</ul>';
    }
    if (label.role === 'memorize' && opts.hasCards) html += '<button class="rc-cards">مرور فلش‌کارت‌های این بخش</button>';
    html += '</section>';
  }
  return html + '</div>';
}

/** The label's icon before its title: its own (chosen in the panel), or the starting one for its name. */
function iconFor(label: { name: string; icon?: string }): string {
  return labelIconSvg(label.icon ?? DEFAULT_LABEL_ICON[label.name], 18);
}

/** A box's text; a «نمودار» box with «تابع:» lines is drawn as a plot (lib/plot.ts). */
function boxBody(name: string, body: string): string {
  if (name === 'نمودار') {
    const plot = renderPlot(body, renderInline);
    if (plot !== null) return plot;
  }
  if (name === 'پرسش و پاسخ') return qaBody(body);
  if (name === 'تمرین') return exerciseBody(body);
  return renderPlain(body);
}

/** Markdown with a bold key in front of its first paragraph: «پرسش: …». */
function keyed(key: string, text: string, cls: string): string {
  const html = renderPlain(text.trim() || ' ');
  const k = `<b class="qa-k">${esc(key)}:</b> `;
  return `<div class="${cls}">${html.startsWith('<p>') ? html.replace('<p>', `<p>${k}`) : k + html}</div>`;
}

const QA_KEY = /^\s*(پرسش|سؤال|سوال|پاسخ|جواب)\s*[:：]\s?(.*)$/;

/** «:::پرسش و پاسخ»: lines «پرسش: …» and «پاسخ: …» (several pairs if needed), always open. */
function qaBody(body: string): string {
  const parts: { key: string; lines: string[] }[] = [];
  for (const line of body.split('\n')) {
    const m = line.match(QA_KEY);
    if (m) parts.push({ key: m[1] === 'پاسخ' || m[1] === 'جواب' ? 'پاسخ' : 'پرسش', lines: [m[2]] });
    else if (parts.length) parts[parts.length - 1].lines.push(line);
    else parts.push({ key: '', lines: [line] });
  }
  return parts
    .map((p) => (p.key ? keyed(p.key, p.lines.join('\n'), p.key === 'پاسخ' ? 'qa-a' : 'qa-q') : renderPlain(p.lines.join('\n'))))
    .join('');
}

const SOLUTION = /^\s*(حل|پاسخ|جواب)\s*[:：]\s?(.*)$/;

/** «:::تمرین»: the question, then «حل:» (or «پاسخ:») and the solution, hidden until the box is tapped. */
function exerciseBody(body: string): string {
  const lines = body.split('\n');
  const at = lines.findIndex((l) => SOLUTION.test(l));
  if (at < 0) return renderPlain(body);
  const m = lines[at].match(SOLUTION)!;
  const solution = [m[2], ...lines.slice(at + 1)].join('\n');
  return (
    renderPlain(lines.slice(0, at).join('\n')) +
    `<details class="ex-sol"><summary>دیدن ${m[1] === 'حل' ? 'حل' : 'پاسخ'}</summary>${keyed(m[1] === 'حل' ? 'حل' : 'پاسخ', solution, 'ex-body')}</details>`
  );
}

function renderPlain(source: string): string {
  const formulas: string[] = [];
  const keep = (html: string) => `@@MATH${formulas.push(html) - 1}@@`;
  // «[[#name]]»: a link to a numbered box («مثال ۳-۵»), anywhere in the book; «[[phrase]]» shows as its words.
  const refs = numbering().refs ?? {};
  let text = source
    // In test explanations the server has already filled in the place: «[[#name|مثال ۳-۵|12]]».
    .replace(/\[\[#([^\]\s|]+)(?:\|([^|\]]+)\|([^\]|]+))?\]\]/g, (_, name: string, text?: string, node?: string) => {
      const r = text && node ? { text, node } : refs[name];
      return keep(
        r
          ? `<a class="ref" data-ref="${esc(name)}" data-node="${esc(String(r.node))}">${esc(r.text)}</a>`
          : `<span class="ref missing" title="کادری با این نام پیدا نشد">#${esc(name)}</span>`,
      );
    })
    .replace(/\[\[([^\]\n]+)\]\]/g, '$1')
    .replace(/\$\$([\s\S]+?)\$\$[ \t]*(?:\{#([^}\s]+)\})?/g, (_, tex: string, name?: string) => {
      const label = name ? eqLabel() : '';
      return `\n\n${keep(renderMath(tex.trim(), true, name ? { id: name, label } : undefined))}\n\n`;
    });
  text = text.replace(/(^|[^\\])\$([^$\n]+?)\$/g, (_, before: string, tex: string) => before + keep(renderMath(tex.trim(), false)));
  // «==قرمز:متن==» → marks the markdown leaves alone, made into coloured spans after.
  text = text.replace(/==(قرمز|آبی|سبز|red|blue|green):([^\n]+?)==/g, (_, c: string, inner: string) => `@@C${COLORS[c]}@@${inner}@@CE@@`);
  let html = md.render(text);
  html = html.replace(/@@C(red|blue|green)@@/g, '<span class="tc tc-$1">').replace(/@@CE@@/g, '</span>');
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
  // Numbered labels («مثال ۳-۵») go on from the earlier sections of the chapter.
  const { chapter, start, titles } = numbering();
  const counts: Record<string, number> = { ...(start ?? {}) };
  let boxIndex = 0;
  const outer = eqCount;
  eqCount = { chapter, n: start?.['رابطه'] ?? 0 };
  for (let i = 0; i < lines.length; i++) {
    const open = lines[i].match(/^:::\s*(\S.*?)\s*(?:\{#([^}\s]+)\})?\s*$/);
    const label = open ? findLabel(open[1]) : undefined;
    if (label) {
      const end = lines.findIndex((line, j) => j > i && line.trim() === ':::');
      if (end > i) {
        flush();
        let title = esc(label.name);
        const given = titles?.[boxIndex++];
        if (given) title = esc(given);
        else if (label.numbered) {
          counts[label.name] = (counts[label.name] ?? 0) + 1;
          title += ' ' + (chapter ? `${faDigits(chapter)}-${faDigits(counts[label.name])}` : faDigits(counts[label.name]));
        }
        const id = open![2] ? ` id="box-${esc(open![2])}"` : '';
        parts.push(
          `<div class="box box-${label.style}${label.name === 'نمودار' ? ' box-plot' : ''}"${id}><div class="box-title">${iconFor(label)}<span>${title}</span></div>${boxBody(label.name, lines.slice(i + 1, end).join('\n'))}</div>`,
        );
        i = end;
        continue;
      }
    }
    buffer.push(lines[i]);
  }
  flush();
  eqCount = outer;
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
/* Paragraphs aligned on both sides like a printed book (last line to the right); lists and short texts stay ragged.
   «ragged»: the learner chose right-aligned text. */
.lesson:not(.compact):not(.ragged) p { text-align: justify; text-align-last: start; text-justify: inter-word; }
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
.box-title { font-weight: 800; margin-bottom: 4px; display: flex; align-items: center; gap: 6px; }
.lb-icon { flex: none; }
.rc-part h4 { display: flex; align-items: center; gap: 6px; }
/* The four looks of a label (lib/labels.ts): formal, note, warn, table. */
.box-note { background: #E3F3E9; } .box-note .box-title { color: #1F5E3A; }
.box-warn { background: #FFF6D6; } .box-warn .box-title { color: #7A4F00; }
.box-formal { background: #EEF0FC; } .box-formal .box-title { color: #3B44B8; }
.box-table { background: #F6F7F2; border: 1px solid #E3E8DE; } .box-table .box-title { color: #56655B; }
/* «مثال ۳-۵»: a link to a numbered box; the box lights up when reached. */
a.ref { color: #3B44B8; font-weight: 700; text-decoration: none; border-bottom: 1px dashed currentColor; cursor: pointer; white-space: nowrap; }
.ref.missing { color: #9E2F2A; font-family: system-ui, sans-serif; font-size: .85em; }
.box.reached { box-shadow: 0 0 0 3px #FFD43B; transition: box-shadow 1.4s; } .box.reached.fade { box-shadow: 0 0 0 0 rgba(255,212,59,0); }
.lesson.dark a.ref { color: #AEB4F5; }
mark.hl { color: inherit; border-radius: 3px; padding: 0 1px; }
mark.hl-yellow { background: #FFE98A; } mark.hl-green { background: #BFE8CF; } mark.hl-blue { background: #C9DBFF; } mark.hl-pink { background: #FFD0DF; }
.hl-tip { position: fixed; z-index: 50; max-width: 320px; padding: 8px 12px; border-radius: 12px; background: #17201A; color: #F3F1E7;
  font: 14px/1.9 Vazirmatn, Tahoma, sans-serif; direction: rtl; text-align: right; white-space: pre-wrap; pointer-events: none; box-shadow: 0 6px 18px rgba(0,0,0,.18); }
.hl-tip.dark { background: #F3F1E7; color: #17201A; }
mark.hl[data-body] { box-shadow: inset 0 -2px 0 rgba(23,32,26,.35); }
.box-pen { margin-inline-start: auto; width: 30px; height: 30px; border: 0; border-radius: 8px; background: transparent; color: inherit;
  opacity: .55; cursor: pointer; display: inline-flex; align-items: center; justify-content: center; padding: 0; -webkit-user-select: none; user-select: none; }
.box-pen:hover, .box-pen:active { opacity: 1; background: rgba(0,0,0,.06); }
.box-pen svg { width: 17px; height: 17px; }
.math-picked { background: rgba(245,197,24,.28); box-shadow: 0 0 0 2px #F5C518; border-radius: 4px; }
@media (hover: hover) { .lesson:not(.compact) .math, .lesson:not(.compact) .math-block { cursor: pointer; } }
.math-block.hlb { cursor: pointer; } .math-block.hlb-yellow { background: #FFE98A; } .math-block.hlb-green { background: #BFE8CF; }
.math-block.hlb-blue { background: #C9DBFF; } .math-block.hlb-pink { background: #FFD0DF; }
.lesson.dark .math-block.hlb, .lesson.sepia .math-block.hlb { color: #17201A; }
.lesson.dark .math-block.hlb-yellow, .lesson.sepia .math-block.hlb-yellow { background: #FFE98A; } .lesson.dark .math-block.hlb-green, .lesson.sepia .math-block.hlb-green { background: #BFE8CF; }
.lesson.dark .math-block.hlb-blue, .lesson.sepia .math-block.hlb-blue { background: #C9DBFF; } .lesson.dark .math-block.hlb-pink, .lesson.sepia .math-block.hlb-pink { background: #FFD0DF; }
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
.lesson.dark .box-note { background: #1D3326; } .lesson.dark .box-note .box-title { color: #9BE3B4; }
.lesson.dark .box-warn { background: #3A3216; } .lesson.dark .box-warn .box-title { color: #F5D96B; }
.lesson.dark .box-formal { background: #23264A; } .lesson.dark .box-formal .box-title { color: #AEB4F5; }
.lesson.dark .box-table { background: #1E2621; border-color: #33403A; } .lesson.dark .box-table .box-title { color: #B9C4BC; }
.lesson.dark mark.hl { color: #17201A; }
.rc { display: grid; gap: 14px; }
.rc-lead { margin-bottom: 4px; }
.rc-glance { font-size: 1.08em; font-weight: 700; background: #FFF6CF; border-radius: 16px; padding: 12px 14px; }
.rc-part { background: #fff; border: 1px solid #E3E8DE; border-radius: 16px; padding: 10px 14px 12px; }
.rc-part h4 { margin: 0 0 6px; font-size: .82em; letter-spacing: .02em; color: #56655B; }
.rc-part ul { margin: 0; padding: 0 18px 0 0; }
.rc-part li { margin: 4px 0; }
.rc-part li.jl { list-style: none; margin-right: -18px; }
.rc-part a.jump { display: flex; align-items: center; gap: 8px; color: inherit; text-decoration: none; padding: 7px 10px; border-radius: 12px; background: #F6F7F2; cursor: pointer; }
.rc-part a.jump .go { margin-right: auto; color: #B9A23A; font-weight: 800; }
.rc-s-formal { border-color: #D5D9F5; background: #F8F9FF; } .rc-s-formal h4 { color: #3B44B8; }
.rc-s-note h4 { color: #1F5E3A; }
.rc-s-warn { border-color: #F2C7C4; background: #FFF8F7; } .rc-s-warn h4 { color: #9E2F2A; }
.rc-memorize h4 { color: #6B5200; }
.rc-part .table-wrap { margin: 0; } .rc-part td.k { font-weight: 700; }
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
.lesson.dark .rc-part a.jump { background: #26302A; } .lesson.dark .rc-s-warn { background: #2E1F1E; border-color: #5A3330; }
.lesson.dark .rc-s-formal { background: #20233A; border-color: #363B66; } .lesson.dark .rc-s-formal h4 { color: #AEB4F5; } .lesson.dark .rc-s-note h4 { color: #9BE3B4; }
.lesson.dark .term .en { color: #AEB4F5; } .lesson.dark mark.flash { color: #17201A; }
.lesson.sepia .rc-part { background: #FBF5E6; border-color: #E6D8B8; } .lesson.sepia .rc-part a.jump { background: #F1E6CC; }
.ci-head { display: flex; align-items: center; gap: 14px; margin: 6px 0 18px; padding: 18px; border-radius: 22px; background: #1B2620; color: #fff; }
.ci-text { flex: 1; min-width: 0; } .ci-lemon { flex: none; }
.ci-label { color: #F5C518; font-weight: 900; font-size: 13px; line-height: 1.6; }
.ci-title { font-size: 23px; font-weight: 900; line-height: 1.5; }
.ci-sizes { font-size: 12px; color: #C9D3CC; margin-top: 2px; line-height: 1.6; }
.ci-list { margin: 22px 0 0; }
.ci-h { font-weight: 900; font-size: 16px; margin-bottom: 4px; }
.ci-row { display: flex; align-items: center; gap: 10px; padding: 12px 14px; margin-top: 8px; border-radius: 14px; background: #fff; border: 1px solid #E3E8DE;
  color: inherit; text-decoration: none; cursor: pointer; font-size: 15px; line-height: 1.7; text-align: right; }
.ci-row.ci-on { border-color: #F5C518; background: #FFFBEA; }
.ci-st { flex: none; width: 20px; height: 20px; border-radius: 50%; border: 1.5px solid #D5DBCF; display: inline-flex; align-items: center; justify-content: center; font-size: 12px; font-weight: 900; }
.ci-st.ci-read { border-color: #F5C518; background: #FFF6CF; } .ci-st.ci-done { border-color: #2F7D4F; background: #2F7D4F; color: #fff; }
.ci-st.ci-lock { border: 0; font-size: 13px; }
.ci-n { flex: none; color: #56655B; font-weight: 700; } .ci-t { flex: 1; min-width: 0; } .ci-go { flex: none; color: #B9A23A; font-weight: 800; }
.ci-continue { margin-top: 16px; }
.ci-badge { flex: none; font-size: 11px; font-weight: 800; padding: 2px 8px; border-radius: 999px; background: #E8E4FA; color: #4A3A9E; }
.lesson.dark .ci-row { background: #1E2621; border-color: #33403A; } .lesson.dark .ci-row.ci-on { background: #2A2614; border-color: #8C7414; }
.lesson.dark .ci-n { color: #9AA79F; } .lesson.dark .ci-st { border-color: #3A463E; }
.lesson.sepia .ci-row { background: #FBF5E6; border-color: #E6D8B8; }
.box-plot { padding: 10px 8px 8px; }
/* Coloured words («==قرمز:…==») */
.tc-red { color: #C2413B; } .tc-blue { color: #2F5BC8; } .tc-green { color: #23784A; }
.lesson.dark .tc-red { color: #FF8A80; } .lesson.dark .tc-blue { color: #8FB0FF; } .lesson.dark .tc-green { color: #7FD9A2; }
.lesson.sepia .tc-red { color: #A8322C; } .lesson.sepia .tc-blue { color: #2A4FA8; } .lesson.sepia .tc-green { color: #1F6A40; }
/* «پرسش و پاسخ» and «تمرین» */
.qa-k { font-weight: 900; }
.qa-a { border-top: 1px dashed rgba(59,68,184,.3); margin-top: 6px; padding-top: 8px; }
details.ex-sol { margin: 4px 0 12px; }
details.ex-sol > summary { list-style: none; cursor: pointer; text-align: center; font-weight: 800; padding: 9px 12px; border-radius: 12px;
  border: 1.5px dashed rgba(31,94,58,.45); color: #1F5E3A; -webkit-user-select: none; user-select: none; }
details.ex-sol > summary::-webkit-details-marker { display: none; }
details.ex-sol[open] > summary { display: none; }
.ex-body { background: rgba(255,255,255,.75); border-radius: 12px; padding: 10px 12px 2px; }
.lesson.dark details.ex-sol > summary { color: #9BE3B4; border-color: rgba(155,227,180,.4); } .lesson.dark .ex-body { background: rgba(0,0,0,.2); }
/* Numbered formulas: «(۳-۲)» on the left. */
.math-block.eq { position: relative; padding-left: 52px; padding-right: 52px; }
.eq-n { position: absolute; left: 12px; top: 50%; transform: translateY(-50%); font-family: Vazirmatn, Tahoma, sans-serif; font-size: 15px; color: #56655B; }
.lesson.dark .eq-n { color: #9AA79F; }
.math-block.reached { box-shadow: 0 0 0 3px #FFD43B; transition: box-shadow 1.4s; } .math-block.reached.fade { box-shadow: 0 0 0 0 rgba(255,212,59,0); } .box-plot .box-title { padding: 0 6px; }
${PLOT_CSS}`;

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
  var blocks = root.querySelectorAll('.math-block[data-note]');
  for (var b = 0; b < blocks.length; b++) { blocks[b].removeAttribute('data-note'); blocks[b].removeAttribute('data-body'); blocks[b].className = 'math-block'; }
}
function norm(s) { return s.replace(/\\s+/g, ' '); }
// The page as one line of text in which each formula is written as its LaTeX ($…$), whitespace collapsed, a space
// between blocks. A highlight's quote is a piece of this line, so a selection that runs through formulas is found again.
var BLOCKS = /^(P|LI|DIV|H1|H2|H3|H4|TD|TH|TR|UL|OL|TABLE|BLOCKQUOTE)$/;
function isMathBox(el) { return el.classList && (el.classList.contains('math') || el.classList.contains('math-block')); }
function layout() {
  var units = [], full = '', space = true;
  function sep() { if (!space) { full += ' '; space = true; } }
  (function walk(n) {
    for (var c = n.firstChild; c; c = c.nextSibling) {
      if (c.nodeType === 3) {
        var raw = c.nodeValue, map = new Array(raw.length + 1);
        for (var k = 0; k < raw.length; k++) {
          map[k] = full.length;
          if (/\\s/.test(raw.charAt(k))) { if (!space) { full += ' '; space = true; } } else { full += raw.charAt(k); space = false; }
        }
        map[raw.length] = full.length;
        units.push({ node: c, map: map });
      } else if (c.nodeType === 1) {
        if (isMathBox(c)) {
          var a = c.querySelector('annotation'), tex = a ? a.textContent.trim() : '';
          var block = c.classList.contains('math-block');
          if (block) sep();
          var start = full.length; full += '$' + tex + '$'; space = false;
          units.push({ node: c, math: true, block: block, start: start, end: full.length });
          if (block) sep();
        } else if (c.tagName !== 'MATH' && c.tagName !== 'SCRIPT' && c.tagName !== 'STYLE') {
          var isBlock = BLOCKS.test(c.tagName);
          if (isBlock) sep();
          walk(c);
          if (isBlock) sep();
        }
      }
    }
  })(root);
  return { units: units, full: full };
}
function unitStart(u) { return u.math ? u.start : u.map[0]; }
function unitEnd(u) { return u.math ? u.end : u.map[u.map.length - 1]; }
// Where a selection boundary falls in the line of text.
function placeOf(L, container, offset, isEnd) {
  var el = container.nodeType === 1 ? container : container.parentNode;
  var box = el && el.closest ? el.closest('.math, .math-block') : null;
  for (var i = 0; i < L.units.length; i++) {
    var u = L.units[i];
    if (box && u.node === box) return isEnd ? u.end : u.start;
    if (!box && u.node === container) return u.map[Math.min(offset, u.map.length - 1)];
  }
  if (box) return isEnd ? L.full.length : 0;
  // An element and a child index: the first piece of text at or after that point.
  var at = container.childNodes[offset];
  for (var j = 0; j < L.units.length; j++) {
    var n = L.units[j].node;
    if (at ? n === at || at.contains(n) || (at.compareDocumentPosition(n) & 4) : (container.compareDocumentPosition(n) & 4) && !container.contains(n))
      return unitStart(L.units[j]);
  }
  return L.full.length;
}
function selectedQuote() {
  var sel = window.getSelection ? window.getSelection() : null;
  if (!sel || !sel.rangeCount || sel.isCollapsed) return '';
  var r = sel.getRangeAt(0);
  if (!root.isConnected || !root.contains(r.commonAncestorContainer)) return '';
  var L = layout();
  var s = placeOf(L, r.startContainer, r.startOffset, false), e = placeOf(L, r.endContainer, r.endOffset, true);
  return e > s ? L.full.slice(s, e).trim() : '';
}
function mark(quote, color, id, body) {
  var q = norm(quote).trim(); if (!q) return false;
  var L = layout();
  var at = L.full.indexOf(q); if (at < 0) return false;
  var end = at + q.length;
  for (var j = L.units.length - 1; j >= 0; j--) {
    var u = L.units[j];
    if (unitEnd(u) <= at || unitStart(u) >= end) continue;
    if (u.math) {
      if (u.block) { u.node.className = 'math-block hlb hlb-' + color; u.node.setAttribute('data-note', id); if (body) u.node.setAttribute('data-body', body); continue; }
      var mm = document.createElement('mark'); mm.className = 'hl hl-' + color; mm.setAttribute('data-note', id); if (body) mm.setAttribute('data-body', body);
      u.node.parentNode.insertBefore(mm, u.node); mm.appendChild(u.node);
      continue;
    }
    var len = u.map.length - 1, from = -1, to = len;
    for (var k = 0; k < len; k++) { if (from < 0 && u.map[k] >= at) from = k; if (u.map[k] >= end) { to = k; break; } }
    if (from < 0 || from >= to || !/\\S/.test(u.node.nodeValue.slice(from, to))) continue;
    var node = u.node, after = node.splitText(to), middle = node.splitText(from); void after;
    var m = document.createElement('mark'); m.className = 'hl hl-' + color; m.setAttribute('data-note', id); if (body) m.setAttribute('data-body', body);
    middle.parentNode.insertBefore(m, middle); m.appendChild(middle);
  }
  return true;
}
root.__setHighlights = function (list) {
  clearMarks();
  var missing = [];
  for (var i = 0; i < list.length; i++) { if (list[i].quote && !mark(list[i].quote, list[i].color, list[i].id, list[i].body || '')) missing.push(list[i].id); }
  post({ type: 'highlights', missing: missing });
};
root.addEventListener('click', function (e) {
  var t = e.target && e.target.closest ? e.target : null;
  if (!t) return;
  var j = t.closest('a.jump'); if (j) { e.preventDefault(); post({ type: 'jump', q: j.getAttribute('data-q') || '' }); return; }
  var r = t.closest('a.ref'); if (r) {
    e.preventDefault();
    var name = r.getAttribute('data-ref');
    if (!root.__box(name)) post({ type: 'ref', name: name, node: r.getAttribute('data-node') });
    return;
  }
  if (t.closest('.rc-cards')) { post({ type: 'cards' }); return; }
  if (t.closest('.next-card')) { post({ type: 'next' }); return; }
  var op = t.closest('[data-open]'); if (op) { post({ type: 'open', id: Number(op.getAttribute('data-open')) }); return; }
  var go = t.closest('[data-go]'); if (go) { post({ type: 'go', to: go.getAttribute('data-go') }); return; }
  var g = t.closest('.gl'); if (g) { post({ type: 'term', fa: g.getAttribute('data-t') }); return; }
  var m = t.closest('mark.hl, .math-block[data-note]');
  if (m) post({ type: 'note', id: Number(m.getAttribute('data-note')) });
});
// With a mouse: resting on a highlight that has a note shows the note above it.
(function () {
  if (root.__tipBound || !(window.matchMedia && window.matchMedia('(hover: hover)').matches)) return;
  root.__tipBound = true;
  var tip = null;
  function hide() { if (tip) { tip.remove(); tip = null; } }
  root.addEventListener('mouseover', function (e) {
    var m = e.target && e.target.closest ? e.target.closest('[data-body]') : null;
    if (!m) { hide(); return; }
    if (tip && tip.__for === m) return;
    hide();
    tip = document.createElement('div'); tip.className = 'hl-tip' + (root.classList.contains('dark') ? ' dark' : ''); tip.__for = m;
    tip.textContent = m.getAttribute('data-body');
    document.body.appendChild(tip);
    var r = m.getClientRects()[0] || m.getBoundingClientRect(), h = tip.offsetHeight, w = tip.offsetWidth;
    var top = r.top - h - 8; if (top < 8) top = r.bottom + 8;
    var left = Math.min(Math.max(8, r.left + r.width / 2 - w / 2), window.innerWidth - w - 8);
    tip.style.top = top + 'px'; tip.style.left = left + 'px';
  });
  root.addEventListener('mouseleave', hide);
  window.addEventListener('scroll', hide, true);
})();
// Show where an important point is in the notes: find it, scroll to it, light it up for a moment.
// A numbered box on this page («[[#name]]»): scroll to it and light it up. False when it is in another section.
root.__box = function (name) {
  var box = document.getElementById('box-' + name);
  if (!box) return false;
  box.scrollIntoView({ block: 'center', behavior: 'smooth' });
  box.classList.remove('fade'); box.classList.add('reached');
  setTimeout(function () { box.classList.add('fade'); }, 1800);
  setTimeout(function () { box.classList.remove('reached', 'fade'); }, 3400);
  return true;
};
root.__flash = function (q) {
  if (q && q.charAt(0) === '#') { if (!root.__box(q.slice(1))) post({ type: 'flash_missing' }); return; }
  var old = root.querySelectorAll('mark.flash');
  for (var i = 0; i < old.length; i++) { var o = old[i], p = o.parentNode; while (o.firstChild) p.insertBefore(o.firstChild, o); p.removeChild(o); p.normalize(); }
  q = norm(q || '').trim(); if (!q) return;
  var nodes = textNodes(), hit = null;
  for (var k = 0; k < nodes.length && !hit; k++) {
    var v = nodes[k].nodeValue.replace(/\\s/g, ' '), at = v.indexOf(q);
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
// The selection, told to the app as a quote (formulas as LaTeX). Some Android WebViews never fire «selectionchange»,
// so the selection is also checked after a touch ends and twice a second while the page is open.
var selTimer = null, lastSent = null;
root.__lastQuote = ''; root.__lastQuoteAt = 0;
function reportSelection() {
  if (!root.isConnected) return;
  var q = selectedQuote().slice(0, 2000);
  if (q) { root.__lastQuote = q; root.__lastQuoteAt = Date.now(); }
  if (q === lastSent) return;
  lastSent = q;
  post({ type: 'selection', text: q });
}
function soon() { clearTimeout(selTimer); selTimer = setTimeout(function () { snapToFormulas(); reportSelection(); }, 250); }
document.addEventListener('selectionchange', soon);
document.addEventListener('touchend', soon);
document.addEventListener('mouseup', soon);
var selPoll = setInterval(function () { if (!root.isConnected) { clearInterval(selPoll); return; } reportSelection(); }, 500);
// The phone's own selection menu («هایلایت», «یادداشت»): that menu closes the selection, so the last quote is used.
root.__menu = function (action, fallback) {
  var q = selectedQuote() || (Date.now() - root.__lastQuoteAt < 4000 ? root.__lastQuote : '') || norm(fallback || '').trim();
  post({ type: 'menu', action: action, text: q.slice(0, 2000) });
};
root.addEventListener('copy', function (e) {
  var text = (window.getSelection() || '').toString();
  if (text.length > MAX_COPY) { e.preventDefault(); post({ type: 'copy_blocked' }); }
});
root.addEventListener('contextmenu', function (e) { if (e.target && e.target.tagName === 'IMG') e.preventDefault(); });
// A formula is one piece: a long press on it (a click with a mouse) selects all of it, however long, so «هایلایت» and
// «یادداشت» take the whole formula without dragging across it. A long press usually starts the phone's own word
// selection; it fires «contextmenu» first, and stopping that leaves the formula's selection in place.
function pickFormula(box) {
  if (!box || !window.getSelection) return false;
  var sel = window.getSelection(), r = document.createRange();
  r.selectNodeContents(box);
  sel.removeAllRanges(); sel.addRange(r);
  var old = root.querySelector('.math-picked'); if (old) old.classList.remove('math-picked');
  box.classList.add('math-picked');
  reportSelection();
  return true;
}
function formulaAt(t) {
  var box = t && t.closest ? t.closest('.math, .math-block') : null;
  // A formula already highlighted opens its note instead (the click handler above).
  if (!box || box.closest('mark.hl') || box.hasAttribute('data-note')) return null;
  return box;
}
root.addEventListener('contextmenu', function (e) { var box = formulaAt(e.target); if (box) { e.preventDefault(); pickFormula(box); } });
if (window.matchMedia && window.matchMedia('(hover: hover)').matches) root.addEventListener('click', function (e) {
  var box = formulaAt(e.target), sel = window.getSelection ? window.getSelection() : null;
  // Not when the mouse just dragged a selection that ends here.
  if (box && (!sel || sel.isCollapsed || box.contains(sel.anchorNode))) pickFormula(box);
});
document.addEventListener('selectionchange', function () {
  var p = root.querySelector('.math-picked');
  if (p && !(window.getSelection() && !window.getSelection().isCollapsed && p.contains(window.getSelection().anchorNode))) p.classList.remove('math-picked');
});
// A selection that starts or ends partway into a formula takes the whole formula (on screen too, not only in the quote).
// Only once the selection has stood still for a moment, so dragging a handle across formulas is not disturbed.
function snapToFormulas() {
  var sel = window.getSelection ? window.getSelection() : null;
  if (!sel || !sel.rangeCount || sel.isCollapsed) return;
  var r = sel.getRangeAt(0);
  if (!root.contains(r.commonAncestorContainer)) return;
  function boxOf(n) { var el = n.nodeType === 1 ? n : n.parentNode; return el && el.closest ? el.closest('.math, .math-block') : null; }
  var a = boxOf(r.startContainer), b = boxOf(r.endContainer);
  if (!a && !b) return;
  var whole = function (box, n, off, end) { return n === box && off === (end ? box.childNodes.length : 0); };
  if ((!a || whole(a, r.startContainer, r.startOffset, false)) && (!b || whole(b, r.endContainer, r.endOffset, true))) return;
  var nr = r.cloneRange();
  if (a) nr.setStart(a, 0);
  if (b) nr.setEnd(b, b.childNodes.length);
  sel.removeAllRanges(); sel.addRange(nr);
}
// «یادداشت روی کل کادر»: a small pen in each box's title (proof, example, theorem…) selects everything in the box under
// its title and opens the note, so a note can belong to a whole box without selecting it by hand. The pen has no text,
// so it never becomes part of a quote.
var PEN = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z"/></svg>';
(function () {
  if (root.classList.contains('compact')) return;
  var titles = root.querySelectorAll('.box:not(.box-plot) > .box-title');
  for (var i = 0; i < titles.length; i++) {
    if (titles[i].querySelector('.box-pen')) continue;
    var b = document.createElement('button');
    b.type = 'button'; b.className = 'box-pen'; b.title = 'یادداشت روی کل کادر'; b.setAttribute('aria-label', 'یادداشت روی کل کادر');
    b.innerHTML = PEN;
    titles[i].appendChild(b);
  }
})();
function boxQuote(box) {
  var title = box.querySelector(':scope > .box-title');
  var r = document.createRange();
  if (title) r.setStartAfter(title); else r.setStart(box, 0);
  r.setEnd(box, box.childNodes.length);
  var sel = window.getSelection();
  sel.removeAllRanges(); sel.addRange(r);
  var q = selectedQuote();
  sel.removeAllRanges();
  return q;
}
root.addEventListener('click', function (e) {
  var pen = e.target && e.target.closest ? e.target.closest('.box-pen') : null;
  if (!pen) return;
  e.preventDefault(); e.stopPropagation();
  var q = boxQuote(pen.closest('.box'));
  if (q) post({ type: 'menu', action: 'note', text: q.slice(0, 2000) });
}, true);
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
/** A chapter's introduction page: its number, its sections with the learner's state, and where to go on. */
export type ChapterIntro = {
  number: number | null;
  sections: { id: number; title: string; locked: boolean; state: 'done' | 'read' | 'empty'; badge?: 'new' | 'updated' | null }[];
  questions: number;
  flashcards: number;
  continue_id: number | null;
  started: boolean;
};
export type PageEnd = {
  nextTitle?: string | null;
  status?: SectionStatus | null;
  chapterEnd?: ChapterEnd | null;
  /** On a chapter's introduction: the chapter (drawn above the text, sections and «ادامه» below). */
  intro?: ChapterIntro | null;
  introTitle?: string;
};

const escHtml = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
const fa = (n: number) => String(n).replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[Number(d)]);

/** The end of a section: what is left here (each part opens directly), then the next section, or the chapter's end. */
export function pageEndHtml(end?: PageEnd): string {
  if (!end) return '';
  if (end.intro) return introEndHtml(end.intro);
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

/** A small lemon, one wedge per section (the same drawing as LemonProgress). */
function lemonSvg(states: ('done' | 'read' | 'empty')[], size: number): string {
  const fill = { done: '#FFC414', read: '#FFDB5C', empty: '#ECE3C2' };
  const pt = (r: number, deg: number) => {
    const a = ((deg - 90) * Math.PI) / 180;
    return `${(r * Math.cos(a)).toFixed(2)} ${(r * Math.sin(a)).toFixed(2)}`;
  };
  const list = states.length > 1 ? states : Array.from({ length: 8 }, () => states[0] ?? 'empty');
  const n = list.length;
  const stroke = n > 16 ? 3.5 : n > 8 ? 4.5 : 6;
  const wedges = list
    .map((st, i) => {
      const a0 = (i * 360) / n, a1 = ((i + 1) * 360) / n;
      return `<path d="M0 0 L${pt(76, a0)} A76 76 0 ${a1 - a0 > 180 ? 1 : 0} 1 ${pt(76, a1)}Z" fill="${fill[st]}" stroke="#fff" stroke-width="${stroke}" stroke-linejoin="round"/>`;
    })
    .join('');
  return `<svg class="ci-lemon" width="${size}" height="${size}" viewBox="-100 -100 200 200" aria-hidden="true"><circle r="98" fill="#F5C518"/><circle r="98" fill="none" stroke="#E0AE0B" stroke-width="3"/><circle r="87" fill="#fff"/>${wedges}<circle r="9" fill="#fff"/></svg>`;
}

/** Above a chapter's introduction: the dark card with its number, title, sizes and lemon. */
export function pageStartHtml(end?: PageEnd): string {
  const c = end?.intro;
  if (!c) return '';
  const sizes = [
    c.sections.length ? `${fa(c.sections.length)} بخش` : '',
    c.questions ? `${fa(c.questions)} تست` : '',
    c.flashcards ? `${fa(c.flashcards)} فلش‌کارت` : '',
  ].filter(Boolean).join('، ');
  const label = c.number ? `مقدمه‌ی فصل ${fa(c.number)}` : 'مقدمه‌ی فصل';
  return `<div class="ci-head"><div class="ci-text"><div class="ci-label">${label}</div><div class="ci-title">${escHtml(end?.introTitle ?? '')}</div>${sizes ? `<div class="ci-sizes">${sizes}</div>` : ''}</div>${c.sections.length ? lemonSvg(c.sections.map((x) => x.state), 64) : ''}</div>`;
}

/** Below a chapter's introduction: its sections (tap to open) and «ادامه». */
function introEndHtml(c: ChapterIntro): string {
  if (!c.sections.length) return '';
  const rows = c.sections
    .map((x, i) => {
      const mark = x.locked
        ? '<span class="ci-st ci-lock">🔒</span>'
        : x.state === 'done'
          ? '<span class="ci-st ci-done">✓</span>'
          : `<span class="ci-st${x.state === 'read' ? ' ci-read' : ''}"></span>`;
      const badge = x.badge === 'updated' ? '<span class="ci-badge">به‌روز شده</span>' : '';
      return `<a class="ci-row${x.id === c.continue_id && c.started ? ' ci-on' : ''}" data-open="${x.id}" role="button">${mark}<span class="ci-n">${fa(i + 1)}.</span><span class="ci-t">${escHtml(x.title)}</span>${badge}<span class="ci-go">←</span></a>`;
    })
    .join('');
  const at = c.sections.findIndex((x) => x.id === c.continue_id);
  const go = c.continue_id
    ? `<a class="ch-btn ch-main ci-continue" data-open="${c.continue_id}" role="button">${c.started && at >= 0 ? `ادامه از بخش ${fa(at + 1)}` : 'شروع فصل'} ←</a>`
    : '';
  return `<div class="ci-list"><div class="ci-h">بخش‌های این فصل</div>${rows}</div>${go}`;
}
