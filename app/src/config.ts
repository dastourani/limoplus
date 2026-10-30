import { storage } from './lib/storage';

/**
 * Server address. The default comes from app/.env (EXPO_PUBLIC_API_URL) — never written in code.
 * Test builds can override it from the settings screen (e.g. the laptop's IP on the same Wi-Fi).
 */
const defaultApiUrl = (process.env.EXPO_PUBLIC_API_URL ?? '').replace(/\/+$/, '');

let override: string | null | undefined;

export async function getApiUrl(): Promise<string> {
  if (override === undefined) override = await storage.getServerUrl();
  const url = override || defaultApiUrl;
  if (!url) throw new Error('No server address. Set EXPO_PUBLIC_API_URL in app/.env or in the app settings.');
  return url;
}

export async function setApiUrlOverride(url: string | null) {
  override = url ? url.trim().replace(/\/+$/, '') : null;
  await storage.setServerUrl(override);
}

export function getDefaultApiUrl() {
  return defaultApiUrl;
}
