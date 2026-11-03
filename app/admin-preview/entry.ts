/**
 * The app's own lesson renderer and book cover, bundled for the panel's live previews
 * (backend/apps/catalog/static/catalog/limo-preview.js), so the panel shows exactly what learners see.
 * Rebuild after changing renderMarkdown.ts, reviewCard.ts or cover.ts:
 *   npm run build:admin-preview
 */
import { coverByline, coverMotifSvg, coverPalette, MOTIFS, type CoverTheme } from '../src/lib/cover';
import { CONTENT_CSS, renderMarkdown, renderSummary } from '../src/lib/renderMarkdown';
import { allLabels, findLabel, normalizeName, setLabels } from '../src/lib/labels';
import { cells, jumpTarget, parseSummary } from '../src/lib/reviewCard';

function esc(s: string) {
  return (s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
}

const LEMON = (size: number) =>
  `<svg width="${size}" height="${size}" viewBox="0 0 20 20"><circle cx="10" cy="10" r="9" fill="#F5C518"/><circle cx="10" cy="10" r="6.5" fill="#FFE98A"/>` +
  `<path d="M10,3.5 L10,16.5 M3.5,10 L16.5,10 M5.4,5.4 L14.6,14.6 M14.6,5.4 L5.4,14.6" stroke="#F5C518" stroke-width="1.1"/></svg>`;

type CoverInput = {
  title: string;
  title_en?: string;
  author?: string;
  edition?: string;
  motif?: string;
  major?: string;
  strip?: string;
  drawing?: { viewBox: string; body: string } | null;
};

/** Break a title into lines of about `max` characters (SVG text does not wrap by itself). */
function lines(text: string, max: number): string[] {
  const out: string[] = [];
  let line = '';
  for (const word of (text || '').split(/\s+/).filter(Boolean)) {
    if (line && (line + ' ' + word).length > max) {
      out.push(line);
      line = word;
    } else line = line ? line + ' ' + word : word;
  }
  if (line) out.push(line);
  return out.slice(0, 3);
}

/**
 * The whole cover as one SVG (for «دریافت جلد»): the same template as coverHtml, drawn at 240×360 units.
 * `fontCss` is an @font-face rule with the font inlined, so the picture renders the same everywhere.
 */
function coverSvg(book: CoverInput, theme: CoverTheme, fontCss = ''): string {
  const p = coverPalette(theme);
  const strip = book.strip || '#3FB8A9';
  const byline = coverByline(book.author, book.edition);
  const title = lines(book.title || 'نام کتاب', 17);
  const motif = coverMotifSvg(book.motif || 'ct', theme, book.drawing).replace('<svg ', '<svg x="16" y="70" width="208" height="146" ');
  // Laid out from the bottom up, like the app's cover: brand, rule, byline, English title, title.
  const parts: string[] = [];
  let y = 312;
  if (byline) {
    parts.push(`<text x="222" y="${y}" direction="rtl" text-anchor="start" font-size="11" fill="${p.muted}">${esc(byline)}</text>`);
    y -= 17;
  }
  if (book.title_en) {
    parts.push(`<text x="222" y="${y}" font-size="11" fill="${p.muted}" font-style="italic" font-family="Georgia, serif" direction="ltr" text-anchor="end">${esc(book.title_en)}</text>`);
    y -= 17;
  }
  y -= 6;
  for (const t of title.slice(0, 2).reverse()) {
    parts.push(`<text x="222" y="${y}" direction="rtl" text-anchor="start" font-size="21" font-weight="900" fill="${p.title}">${esc(t)}</text>`);
    y -= 30;
  }
  return (
    `<svg xmlns="http://www.w3.org/2000/svg" width="240" height="360" viewBox="0 0 240 360" font-family="Vazirmatn, Tahoma, sans-serif">` +
    (fontCss ? `<style>${fontCss}</style>` : '') +
    `<defs><clipPath id="c"><rect width="240" height="360" rx="10"/></clipPath></defs><g clip-path="url(#c)">` +
    `<rect width="240" height="360" fill="${p.bg}"/><rect width="240" height="6" fill="${strip}"/>` +
    (book.major ? `<text x="222" y="30" direction="rtl" text-anchor="start" font-size="10" font-weight="700" fill="${strip}">لیمو ${esc(book.major)}</text>` : '') +
    motif +
    parts.join('') +
    `<rect x="188" y="324" width="34" height="2" rx="1" fill="${p.rule}"/>` +
    `<g transform="translate(206 328)">${LEMON(16).replace('<svg ', '<svg x="0" y="0" ')}</g>` +
    `<text x="200" y="340" direction="rtl" text-anchor="start" font-size="10" font-weight="700" fill="${p.brand}">لیموخوان</text>` +
    `</g></svg>`
  );
}

/** The cover as HTML (same template as the app's BookCover), `width` px wide, 2:3. */
function coverHtml(
  book: CoverInput,
  theme: CoverTheme,
  width = 240,
): string {
  const p = coverPalette(theme);
  const k = width / 240;
  const strip = book.strip || '#3FB8A9';
  const byline = coverByline(book.author, book.edition);
  return (
    `<div style="width:${width}px;height:${width * 1.5}px;box-sizing:border-box;position:relative;overflow:hidden;border-radius:${10 * k}px;background:${p.bg};` +
    `font-family:Vazirmatn,Tahoma,sans-serif;direction:rtl;display:flex;flex-direction:column;box-shadow:0 ${10 * k}px ${28 * k}px rgba(23,32,26,.25)">` +
    `<div style="height:${6 * k}px;background:${strip}"></div>` +
    `<div style="padding:${12 * k}px ${18 * k}px 0;font-size:${10 * k}px;font-weight:700;color:${strip}">لیمو ${esc(book.major || '')}</div>` +
    `<div style="flex:1;display:flex;align-items:center;justify-content:center;padding:${6 * k}px ${14 * k}px 0">` +
    `<div style="width:${208 * k}px;height:${146 * k}px">${coverMotifSvg(book.motif || 'ct', theme, book.drawing).replace('<svg ', '<svg width="100%" height="100%" ')}</div></div>` +
    `<div style="padding:0 ${18 * k}px ${16 * k}px;display:flex;flex-direction:column;gap:${4 * k}px">` +
    `<div style="font-size:${21 * k}px;font-weight:900;line-height:1.45;color:${p.title}">${esc(book.title || 'نام کتاب')}</div>` +
    (book.title_en ? `<div style="font-size:${11 * k}px;color:${p.muted};direction:ltr;text-align:right;font-family:Georgia,serif;font-style:italic">${esc(book.title_en)}</div>` : '') +
    (byline ? `<div style="font-size:${11 * k}px;color:${p.muted}">${esc(byline)}</div>` : '') +
    `<div style="height:${2 * k}px;width:${34 * k}px;background:${p.rule};border-radius:2px;margin:${8 * k}px 0 ${6 * k}px"></div>` +
    `<div style="display:flex;align-items:center;gap:${6 * k}px;font-size:${10 * k}px;font-weight:700;color:${p.brand}">${LEMON(16 * k)}لیموخوان</div></div></div>`
  );
}

type BannerInput = { template: string; title: string; subtitle?: string; button?: string; motif?: string; left?: string | null; book?: CoverInput | null };

/** A banner as HTML, `w` px wide (2:1), the same layouts as the app's BannerFace. */
function bannerHtml(b: BannerInput, w = 360): string {
  const h = w / 2;
  const k = h / 180;
  const dark = b.template !== 'book';
  const text =
    `<div style="position:relative;max-width:${w * 0.62}px;display:flex;flex-direction:column;gap:${6 * k}px;align-items:flex-start">` +
    (b.subtitle ? `<div style="font-size:${12 * k}px;font-weight:700;color:${dark ? '#F5C518' : '#2F7D4F'}">${esc(b.subtitle)}</div>` : '') +
    `<div style="font-size:${21 * k}px;line-height:1.45;font-weight:900;color:${dark ? '#FFFFFF' : '#17201A'}">${esc(b.title || 'عنوان بنر')}</div>` +
    `<div style="display:flex;gap:${8 * k}px;align-items:center;flex-wrap:wrap">` +
    (b.button ? `<span style="border-radius:999px;padding:${6 * k}px ${14 * k}px;font-size:${13 * k}px;font-weight:800;background:${dark ? '#F5C518' : '#17201A'};color:${dark ? '#17201A' : '#F5C518'}">${esc(b.button)}</span>` : '') +
    (b.left ? `<span style="border-radius:999px;padding:${5 * k}px ${10 * k}px;font-size:${13 * k}px;font-weight:800;background:${dark ? 'rgba(255,255,255,.12)' : '#fff'};color:${dark ? '#fff' : '#17201A'}">⏱ ${esc(b.left)}</span>` : '') +
    `</div></div>`;
  const frame = (bg: string, inner: string) =>
    `<div dir="rtl" style="position:relative;width:${w}px;height:${h}px;border-radius:22px;overflow:hidden;background:${bg};display:flex;align-items:center;padding:${16 * k}px;box-sizing:border-box;font-family:Vazirmatn,Tahoma,sans-serif">${inner}</div>`;
  if (b.template === 'book' && b.book) {
    return frame('#F4F0E3', `<div style="position:absolute;left:${18 * k}px;top:${h * 0.1}px;transform:rotate(-5deg)">${coverHtml(b.book, 'dark', h * 0.54)}</div>` + text);
  }
  if (b.template === 'exam') {
    const svg = coverMotifSvg(b.motif || 'book', 'dark').replace('<svg ', '<svg width="100%" height="100%" ');
    return frame('#123B35', `<div style="position:absolute;left:${-h * 0.05}px;top:10%;width:${h * 1.15}px;height:${h * 0.8}px;opacity:.9">${svg}</div>` + text);
  }
  const lemon = `<div style="position:absolute;left:${-h * 0.3}px;bottom:${-h * 0.35}px;opacity:.95">${LEMON(h * 1.1)}</div>`;
  if (b.template === 'sale') return frame('#17201A', lemon + text);
  return frame(
    '#17201A',
    lemon +
      `<div style="position:relative;padding-left:${h * 0.7}px"><div style="color:#B9C4BC;font-size:12px">${esc(b.subtitle || 'ویژه')}</div>` +
      `<div style="color:#F5C518;font-size:20px;font-weight:800;line-height:1.5">${esc(b.title || 'عنوان بنر')}</div></div>`,
  );
}

(globalThis as unknown as { LimoPreview: unknown }).LimoPreview = {
  bannerHtml,
  CONTENT_CSS,
  renderMarkdown,
  renderSummary,
  parseSummary,
  cells,
  jumpTarget,
  setLabels,
  allLabels,
  findLabel,
  normalizeName,
  coverHtml,
  coverSvg,
  MOTIFS,
};
