/** The web app reads online only; encrypted offline storage is a phone-app feature. */
import type { OfflineBundle } from '../api/endpoints';

export type OfflineBook = { slug: string; title: string; sectionIds: number[]; downloadedAt: string; validUntil: string };
export type OfflineSection = OfflineBundle['sections'][number] & { bookSlug: string; bookTitle: string };

export const offlineSupported = false;
export const offlineBooks = async (): Promise<OfflineBook[]> => [];
export const saveOfflineBook = async (_bundle: OfflineBundle): Promise<OfflineBook> => {
  throw new Error('offline not supported on web');
};
export const offlineSection = async (_id: number): Promise<OfflineSection | null> => null;
export const removeOfflineBook = async (_slug: string) => undefined;
export const clearOffline = async () => undefined;
