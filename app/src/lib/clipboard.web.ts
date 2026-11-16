/**
 * Put text on the clipboard once it arrives (from the server, with its fingerprint). Rejects with the text's error.
 * Browsers only let a page write to the clipboard during the user's own action, so this must be called right inside the
 * copy event or click: a ClipboardItem that waits for the text keeps that permission while the server answers.
 */
export function copyLater(text: Promise<string>): Promise<void> {
  const clip = typeof navigator !== 'undefined' ? navigator.clipboard : undefined;
  if (!clip) return text.then(() => Promise.reject(new Error('no clipboard')));
  if (typeof ClipboardItem !== 'undefined' && clip.write) {
    try {
      const item = new ClipboardItem({ 'text/plain': text.then((t) => new Blob([t], { type: 'text/plain' })) });
      return clip.write([item]).catch(() => text.then((t) => clip.writeText(t)));
    } catch {
      // An older browser: plain text below.
    }
  }
  return text.then((t) => clip.writeText(t));
}
