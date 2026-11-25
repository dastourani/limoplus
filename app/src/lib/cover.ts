/**
 * Book covers: one fixed template for every book, with a line-drawn motif per subject in the middle.
 * The motifs are plain SVG text so the app (react-native-svg's SvgXml) and the panel's live preview
 * (admin-preview bundle) draw exactly the same picture. All motifs share one style: a 200×140 box,
 * a main line (lemon on dark, ink on light) and a softer second line.
 */

export type CoverTheme = 'dark' | 'light';
import { EXTRA_MOTIFS, extraMotif } from './coverExtra';

/** Every motif key; 'custom' draws the book's own uploaded line drawing. */
export const MOTIFS: string[] = ['ct', 'brain', 'ap', 'neuron', 'pixels', 'system', 'fourier', 'words', ...EXTRA_MOTIFS, 'custom'];

export type CoverPalette = {
  bg: string;
  line: string;
  soft: string;
  title: string;
  muted: string;
  rule: string;
  brand: string;
  ratingBg: string;
  ratingBorder: string;
  ratingStar: string;
  ratingText: string;
  /** Hounsfield bar, air → bone. */
  scale: [string, string, string, string, string];
  pixel: (alpha: number) => string;
};

export function coverPalette(theme: CoverTheme): CoverPalette {
  return theme === 'dark'
    ? {
        bg: '#17201A',
        line: '#F5C518',
        soft: 'rgba(255,255,255,0.5)',
        title: '#FFFFFF',
        muted: '#A9B6AD',
        rule: '#F5C518',
        brand: '#C9D2C9',
        ratingBg: 'rgba(255, 255, 255, 0.11)',
        ratingBorder: 'rgba(255, 255, 255, 0.18)',
        ratingStar: '#F5C518',
        ratingText: '#FFFFFF',
        scale: ['rgba(255,255,255,0.04)', 'rgba(255,255,255,0.2)', 'rgba(255,255,255,0.4)', 'rgba(255,255,255,0.65)', 'rgba(255,255,255,0.92)'],
        pixel: (a) => `rgba(255,255,255,${a})`,
      }
    : {
        bg: '#F4F0E3',
        line: '#17201A',
        soft: 'rgba(23,32,26,0.45)',
        title: '#17201A',
        muted: '#56655B',
        rule: '#D9A900',
        brand: '#56655B',
        ratingBg: 'rgba(23, 32, 26, 0.08)',
        ratingBorder: 'rgba(23, 32, 26, 0.16)',
        ratingStar: '#C59000',
        ratingText: '#17201A',
        scale: ['rgba(23,32,26,0.9)', 'rgba(23,32,26,0.62)', 'rgba(23,32,26,0.38)', 'rgba(23,32,26,0.16)', 'rgba(23,32,26,0.03)'],
        pixel: (a) => `rgba(23,32,26,${(a * 0.8).toFixed(3)})`,
      };
}

const SHADES = [0.15, 0.3, 0.55, 0.8, 0.6, 0.35, 0.2, 0.1, 0.25, 0.5, 0.85, 0.95, 0.7, 0.4, 0.2, 0.12, 0.35, 0.7, 0.95, 0.9, 0.65, 0.3, 0.15, 0.1, 0.3, 0.6, 0.85, 0.75, 0.45, 0.25, 0.12, 0.08, 0.2, 0.4, 0.6, 0.5];

const FOURIER_1 =
  '10,70 13,59.9 16,50.3 19,41.6 22,34 25,28.1 28,24 31,21.9 34,21.9 37,24 40,28.1 43,34 46,41.6 49,50.3 52,59.9 55,70 58,80.1 61,89.7 64,98.4 67,106 70,111.9 73,116 76,118.1 79,118.1 82,116 85,111.9 88,106 91,98.4 94,89.7 97,80.1 100,70 103,59.9 106,50.3 109,41.6 112,34 115,28.1 118,24 121,21.9 124,21.9 127,24 130,28.1 133,34 136,41.6 139,50.3 142,59.9 145,70 148,80.1 151,89.7 154,98.4 157,106 160,111.9 163,116 166,118.1 169,118.1 172,116 175,111.9 178,106 181,98.4 184,89.7 187,80.1 190,70';
const FOURIER_3 =
  '10,70 13,60.5 16,54.7 19,54.7 22,60.5 25,70 28,79.5 31,85.3 34,85.3 37,79.5 40,70 43,60.5 46,54.7 49,54.7 52,60.5 55,70 58,79.5 61,85.3 64,85.3 67,79.5 70,70 73,60.5 76,54.7 79,54.7 82,60.5 85,70 88,79.5 91,85.3 94,85.3 97,79.5 100,70 103,60.5 106,54.7 109,54.7 112,60.5 115,70 118,79.5 121,85.3 124,85.3 127,79.5 130,70 133,60.5 136,54.7 139,54.7 142,60.5 145,70 148,79.5 151,85.3 154,85.3 157,79.5 160,70 163,60.5 166,54.7 169,54.7 172,60.5 175,70 178,79.5 181,85.3 184,85.3 187,79.5 190,70';
const FOURIER_SUM =
  '10,70 12,44.8 14,28.7 16,25.2 18,29.8 20,35 22,35.8 24,32.4 26,29.2 28,29.4 30,32.5 32,34.9 34,34 36,30.8 38,28.8 40,30.5 42,34.4 44,36.1 46,32.8 48,26.9 50,25.5 52,35.2 54,56.7 56,83.3 58,104.8 60,114.5 62,113.1 64,107.2 66,103.9 68,105.6 70,109.5 72,111.2 74,109.2 76,106 78,105.1 80,107.5 82,110.6 84,110.8 86,107.6 88,104.2 90,105 92,110.2 94,114.8 96,111.3 98,95.2 100,70 102,44.8 104,28.7 106,25.2 108,29.8 110,35 112,35.8 114,32.4 116,29.2 118,29.4 120,32.5 122,34.9 124,34 126,30.8 128,28.8 130,30.5 132,34.4 134,36.1 136,32.8 138,26.9 140,25.5 142,35.2 144,56.7 146,83.3 148,104.8 150,114.5 152,113.1 154,107.2 156,103.9 158,105.6 160,109.5 162,111.2 164,109.2 166,106 168,105.1 170,107.5 172,110.6 174,110.8 176,107.6 178,104.2 180,105 182,110.2 184,114.8 186,111.3 188,95.2 190,70';
const DAMPED =
  '128,70 130,55.8 132,47.3 134,46.2 136,51.6 138,61.1 140,71.7 142,80.3 144,84.9 146,84.9 148,80.9 150,74.5 152,67.9 154,62.7 156,60.3 158,60.8 160,63.7 162,67.8 164,72 166,75 168,76.3 170,75.7 172,73.6 174,70.9 176,68.3 178,66.6 180,66 182,66.5 184,68 186,69.7 188,71.3 190,72.3 192,72.6 194,72.1 196,71.1 198,70';

function body(motif: string, p: CoverPalette): string {
  const extra = extraMotif(motif, p);
  if (extra) return extra;
  const L = (d: string, w = 2.6) => `<path d="${d}" stroke="${p.line}" stroke-width="${w}"/>`;
  const S = (d: string, w = 1.6, extra = '') => `<path d="${d}" stroke="${p.soft}" stroke-width="${w}"${extra}/>`;
  const dot = (x: number, y: number, r = 3) => `<circle cx="${x}" cy="${y}" r="${r}" fill="${p.line}" stroke="none"/>`;
  const label = (x: number, y: number, text: string, color: string, size = 9, extra = '') =>
    `<text x="${x}" y="${y}" fill="${color}" stroke="none" font-size="${size}" text-anchor="middle" font-family="Georgia, serif"${extra}>${text}</text>`;
  switch (motif) {
    case 'brain':
      return (
        L('M30,80 C24,50 50,25 85,22 C110,12 145,20 160,40 C178,50 182,75 170,92 C160,106 140,108 128,104 C120,112 100,114 88,108 C70,112 45,105 30,80 Z') +
        L('M128,104 C134,120 160,120 168,100') +
        S('M134,108 C142,112 154,112 162,104', 1.4) +
        L('M118,108 L116,132 M128,106 L127,132') +
        S('M58,40 C70,55 64,70 80,80 M95,28 C101,45 92,60 105,72 M132,30 C126,50 141,62 136,80 M52,86 C78,74 104,82 126,72 M150,52 C158,62 156,72 162,80 M70,96 C80,90 92,96 100,92')
      );
    case 'ap':
      return (
        S('M14,128 L14,14 M14,128 L190,128', 1.4) +
        S('M14,86 L190,86', 1.4, ' stroke-dasharray="4 5"') +
        L('M14,104 L62,104 C72,104 74,98 78,92 L88,22 C91,10 95,10 98,26 L108,116 C111,124 118,122 128,112 L190,104', 2.8) +
        dot(93, 14)
      );
    case 'neuron':
      return (
        S('M44,70 L20,48 M28,56 L14,58 M44,70 L18,90 M26,82 L22,100 M50,58 L46,26 M48,40 L34,30 M50,84 L52,118 M51,100 L38,112') +
        `<circle cx="52" cy="70" r="15" stroke="${p.line}" stroke-width="2.6"/>` +
        dot(52, 70, 5) +
        L('M67,70 L78,70') +
        [78, 106, 134].map((x) => `<rect x="${x}" y="64" width="22" height="12" rx="6" stroke="${p.line}" stroke-width="2.4"/>`).join('') +
        L('M100,70 L106,70 M128,70 L134,70 M156,70 L166,70 L180,56 M166,70 L184,72 M166,70 L178,88', 2.2) +
        dot(181, 54) +
        dot(187, 72) +
        dot(180, 91)
      );
    case 'pixels':
      return (
        SHADES.map((a, i) => `<rect x="${12 + (i % 6) * 16}" y="${26 + Math.floor(i / 6) * 16}" width="13" height="13" rx="2" fill="${p.pixel(a)}" stroke="none"/>`).join('') +
        `<rect x="27" y="40" width="47" height="47" rx="4" stroke="${p.line}" stroke-width="2.6"/>` +
        L('M118,64 L146,64 M138,57 L146,64 L138,71', 2.4) +
        `<rect x="158" y="55" width="18" height="18" rx="3" fill="${p.line}" stroke="none"/>`
      );
    case 'system':
      return (
        S('M14,90 L56,90 M28,90 L28,40 M24,48 L28,40 L32,48', 1.8) +
        L('M56,70 L74,70 M68,64 L74,70 L68,76', 2.4) +
        `<rect x="76" y="48" width="44" height="44" rx="8" stroke="${p.line}" stroke-width="2.8"/>` +
        label(98, 75, 'h(t)', p.line, 15, ' font-style="italic"') +
        L('M120,70 L128,70', 2.4) +
        `<polyline points="${DAMPED}" stroke="${p.line}" stroke-width="2.4"/>` +
        label(28, 112, 'x(t)', p.soft, 11, ' font-style="italic"') +
        label(164, 112, 'y(t)', p.soft, 11, ' font-style="italic"')
      );
    case 'fourier':
      return (
        `<polyline points="${FOURIER_1}" stroke="${p.soft}" stroke-width="1.3"/>` +
        `<polyline points="${FOURIER_3}" stroke="${p.soft}" stroke-width="1.3"/>` +
        `<polyline points="${FOURIER_SUM}" stroke="${p.line}" stroke-width="2.6"/>` +
        `<text x="190" y="136" fill="${p.soft}" stroke="none" font-size="10" font-style="italic" text-anchor="end" font-family="Georgia, serif">Σ sin(nωt)/n</text>`
      );
    case 'words':
      return (
        `<rect x="16" y="22" width="76" height="30" rx="8" stroke="${p.line}" stroke-width="2.4"/>` +
        label(54, 42, 'neuro', p.line, 15) +
        S('M100,37 L112,37 M106,31 L106,43', 1.8) +
        `<rect x="120" y="22" width="66" height="30" rx="8" stroke="${p.soft}" stroke-width="1.6"/>` +
        label(153, 42, '-logy', p.soft, 15) +
        `<rect x="16" y="66" width="76" height="30" rx="8" stroke="${p.soft}" stroke-width="1.6"/>` +
        label(54, 86, 'cardio', p.soft, 15) +
        S('M100,81 L112,81 M106,75 L106,87', 1.8) +
        `<rect x="120" y="66" width="66" height="30" rx="8" stroke="${p.line}" stroke-width="2.4"/>` +
        label(153, 86, '-gram', p.line, 15) +
        S('M16,118 L186,118', 1.2) +
        `<text x="16" y="113" fill="${p.line}" stroke="none" font-size="13" font-style="italic" font-family="Georgia, serif">Aa</text>`
      );
    case 'ct':
    default:
      return (
        `<circle cx="100" cy="50" r="40" stroke="${p.line}" stroke-width="2.8"/>` +
        `<circle cx="100" cy="50" r="31" stroke="${p.soft}" stroke-width="1.4"/>` +
        `<ellipse cx="100" cy="54" rx="20" ry="14" stroke="${p.soft}" stroke-width="1.6"/>` +
        S('M100,10 L84,88 M100,10 L116,88', 1, ' stroke-dasharray="2 4"') +
        `<rect x="22" y="104" width="156" height="12" rx="3" stroke="${p.line}" stroke-width="2"/>` +
        [24, 54, 85, 116, 147].map((x, i) => `<rect x="${x}" y="106" width="${i === 4 ? 29 : i === 0 ? 30 : 31}" height="8" fill="${p.scale[i]}" stroke="none"/>`).join('') +
        L('M24,118 L24,123 M100,118 L100,123 M176,118 L176,123', 2) +
        label(24, 135, '-1000', p.soft) +
        label(100, 135, '0', p.soft) +
        label(176, 135, '+1000', p.soft)
      );
  }
}

/**
 * The motif as a standalone SVG document (viewBox 200×140). For 'custom', `custom` is the book's own drawing as the
 * server cleaned it ({viewBox, body} with only shapes); its lines take the cover's colours.
 */
export function coverMotifSvg(motif: string, theme: CoverTheme, custom?: { viewBox: string; body: string } | null): string {
  const p = coverPalette(theme);
  if (motif === 'custom' && custom?.body) {
    const inner = custom.body.split('@L@').join(p.line).split('@S@').join(p.soft).split('@B@').join(p.bg);
    return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="${custom.viewBox}" fill="none" stroke-linecap="round" stroke-linejoin="round">${inner}</svg>`;
  }
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 200 140" fill="none" stroke-linecap="round" stroke-linejoin="round">${body(motif === 'custom' ? 'book' : motif, p)}</svg>`;
}

/** A book's line under its title: «بوشبرگ، ویرایش چهارم». */
export function coverByline(author?: string, edition?: string): string {
  return [author, edition].filter((x) => x && x.trim()).join('، ');
}

/** Compact cover rating text (e.g. «۴٫۸» or «۵»); returns null when a book has no approved ratings yet. */
export function coverRatingLabel(rating?: number | null, ratingCount?: number | null): string | null {
  if (rating == null || !Number.isFinite(rating) || rating <= 0) return null;
  if (ratingCount != null && ratingCount <= 0) return null;
  const rounded = Math.round(rating * 10) / 10;
  const text = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1).replace('.', '٫');
  return text.replace(/\d/g, (d) => '۰۱۲۳۴۵۶۷۸۹'[Number(d)]);
}
