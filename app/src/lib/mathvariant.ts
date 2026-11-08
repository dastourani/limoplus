/**
 * KaTeX writes \mathbb{R}, \mathbf{v}, \mathcal{L}… as MathML «mathvariant», which Chrome and Android's WebView do not
 * draw (they show a plain R). The letters are rewritten as their own Unicode characters (ℝ, 𝐯, ℒ), which every
 * browser shows; text that has no such character (Persian in \textbf) keeps the look with a style.
 */
type Range = [upper: number, lower: number, digits?: number];
const RANGES: Record<string, Range> = {
  bold: [0x1d400, 0x1d41a, 0x1d7ce],
  italic: [0x1d434, 0x1d44e],
  'bold-italic': [0x1d468, 0x1d482],
  script: [0x1d49c, 0x1d4b6],
  'bold-script': [0x1d4d0, 0x1d4ea],
  fraktur: [0x1d504, 0x1d51e],
  'double-struck': [0x1d538, 0x1d552, 0x1d7d8],
  'bold-fraktur': [0x1d56c, 0x1d586],
  'sans-serif': [0x1d5a0, 0x1d5ba, 0x1d7e2],
  'bold-sans-serif': [0x1d5d4, 0x1d5ee, 0x1d7ec],
  'sans-serif-italic': [0x1d608, 0x1d622],
  'sans-serif-bold-italic': [0x1d63c, 0x1d656],
  monospace: [0x1d670, 0x1d68a, 0x1d7f6],
};
// Letters that live elsewhere in Unicode (the gaps in the ranges above).
const HOLES: Record<string, Record<string, string>> = {
  italic: { h: 'ℎ' },
  script: { B: 'ℬ', E: 'ℰ', F: 'ℱ', H: 'ℋ', I: 'ℐ', L: 'ℒ', M: 'ℳ', R: 'ℛ', e: 'ℯ', g: 'ℊ', o: 'ℴ' },
  fraktur: { C: 'ℭ', H: 'ℌ', I: 'ℑ', R: 'ℜ', Z: 'ℨ' },
  'double-struck': { C: 'ℂ', H: 'ℍ', N: 'ℕ', P: 'ℙ', Q: 'ℚ', R: 'ℝ', Z: 'ℤ' },
};
const STYLE: Record<string, string> = { bold: 'font-weight:bold', 'bold-italic': 'font-weight:bold;font-style:italic', italic: 'font-style:italic' };

function convert(text: string, variant: string): string | null {
  const range = RANGES[variant];
  if (!range) return null;
  let out = '';
  for (const ch of text) {
    const hole = HOLES[variant]?.[ch];
    const c = ch.charCodeAt(0);
    if (hole) out += hole;
    else if (c >= 65 && c <= 90) out += String.fromCodePoint(range[0] + c - 65);
    else if (c >= 97 && c <= 122) out += String.fromCodePoint(range[1] + c - 97);
    else if (c >= 48 && c <= 57 && range[2]) out += String.fromCodePoint(range[2] + c - 48);
    else if (/\s/.test(ch) || /[\p{P}\p{S}]/u.test(ch)) out += ch;
    else return null; // a letter with no such character (Persian): keep it and use a style instead
  }
  return out;
}

export function fixMathVariants(mathml: string): string {
  return mathml.replace(
    /<(mi|mn|mtext|mo)([^>]*?)\smathvariant="([a-z-]+)"([^>]*)>([^<]*)<\/\1>/g,
    (all, tag: string, before: string, variant: string, after: string, text: string) => {
      if (variant === 'normal') return all;
      const done = convert(text, variant);
      if (done !== null) return `<${tag}${before}${tag === 'mi' ? ' mathvariant="normal"' : ''}${after}>${done}</${tag}>`;
      const style = STYLE[variant];
      return style ? `<${tag}${before} style="${style}"${after}>${text}</${tag}>` : all;
    },
  );
}
