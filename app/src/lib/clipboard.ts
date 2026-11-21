import * as Clipboard from 'expo-clipboard';

/** Put text on the clipboard once it arrives (from the server, with its fingerprint). Rejects with the text's error. */
export async function copyLater(text: Promise<string>): Promise<void> {
  await Clipboard.setStringAsync(await text);
}
