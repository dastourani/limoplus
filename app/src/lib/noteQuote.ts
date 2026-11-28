/** A highlight's quote as plain text: formulas are kept as LaTeX ($…$); shown without the dollars, left to right. */
export function quoteText(quote: string): string {
  return quote.replace(/\$([^$]+)\$/g, '⁦$1⁩');
}

/** Does the quote hold a formula (then it is drawn, not shown as LaTeX)? */
export function hasFormula(quote: string): boolean {
  return /\$[^$]+\$/.test(quote);
}

/**
 * The quote as lesson Markdown, so its formulas are drawn as in the book. The words around them are the reader's own
 * selection, not Markdown: their punctuation is escaped so nothing turns into a list, a box or bold text.
 * A quote that is one formula alone is drawn full size (\displaystyle), without the card of a display formula.
 */
export function quoteMarkdown(quote: string): string {
  const q = quote.trim();
  const alone = /^\$([^$]+)\$$/.exec(q);
  if (alone) return `$\\displaystyle ${alone[1].trim()}$`;
  return q
    .split(/(\$[^$]+\$)/)
    .map((part, i) => (i % 2 ? part : part.replace(/([\\`*_{}[\]<>#|~=:!+.()-])/g, '\\$1')))
    .join('');
}
