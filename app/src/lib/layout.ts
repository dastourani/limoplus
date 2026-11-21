import { useWindowDimensions } from 'react-native';

/** At least this wide (a computer, a tablet on its side): a side menu instead of the bottom tabs, two columns on the
 * home page, and the chapter's sections beside the text while reading. */
export const WIDE = 1024;

export function useWide(): boolean {
  return useWindowDimensions().width >= WIDE;
}

/** A large screen (about Full HD and up): the side menu opens out (icon and name side by side) instead of the narrow rail. */
export const ROOMY = 1800;
/** A very large screen (2K and up): the home page may grow to HOME_MAX_HUGE. */
export const HUGE = 2400;
export const HOME_MAX = 1600;
export const HOME_MAX_HUGE = 1900;

export function useRoomy(): boolean {
  return useWindowDimensions().width >= ROOMY;
}

/** How wide the home page may be; it stays next to the menu, so any room left over is on the far (left) side. */
export function useHomeMax(): number {
  return useWindowDimensions().width >= HUGE ? HOME_MAX_HUGE : HOME_MAX;
}
