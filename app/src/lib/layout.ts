import { useWindowDimensions } from 'react-native';

/** At least this wide (a computer, a tablet on its side): a side menu instead of the bottom tabs, two columns on the
 * home page, and the chapter's sections beside the text while reading. */
export const WIDE = 1024;

export function useWide(): boolean {
  return useWindowDimensions().width >= WIDE;
}
