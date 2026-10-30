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
.lesson { direction: rtl; text-align: right; font-family: Vazirmatn, "Segoe UI", Tahoma, system-ui, sans-serif;
  font-size: var(--fs, 17px); line-height: 2; padding: 4px 20px 32px; overflow-wrap: anywhere; }
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
`;
