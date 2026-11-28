export type ErrorKindIcon = 'cloud-off' | 'lock' | 'search';

/**
 * Picks a user-facing title and icon matching the HTTP/transport failure kind,
 * so 403/404 responses never falsely claim «ارتباط برقرار نشد».
 */
export function errorPresentation(status?: number): { title: string; icon: ErrorKindIcon } {
  if (status === 403) return { title: 'دسترسی محدود', icon: 'lock' };
  if (status === 404) return { title: 'پیدا نشد', icon: 'search' };
  return { title: 'ارتباط برقرار نشد', icon: 'cloud-off' };
}
