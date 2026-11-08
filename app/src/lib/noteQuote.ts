/** A highlight's quote as plain text: formulas are kept as LaTeX ($…$); shown without the dollars, left to right. */
export function quoteText(quote: string): string {
  return quote.replace(/\$([^$]+)\$/g, '⁦$1⁩');
}
