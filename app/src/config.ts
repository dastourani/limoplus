import * as Device from 'expo-device';
import { Platform } from 'react-native';

import { storage } from './lib/storage';

export type AppChannel = 'official' | 'test';

/** Release channel baked into this binary at build time (`official` vs `test`). */
export const APP_CHANNEL: AppChannel = process.env.EXPO_PUBLIC_APP_CHANNEL === 'official' ? 'official' : 'test';
export const APP_SCHEME = APP_CHANNEL === 'official' ? 'limookhan' : 'limookhan-test';

/** Build number of this app (set by the APK build from its run number; 0 in development and on the web). */
export const APP_BUILD = Number(process.env.EXPO_PUBLIC_APP_BUILD ?? 0) || 0;
/** Only the Android app names its build to the server; the web version is always the latest. */
export const APP_PLATFORM = Platform.OS === 'android' && APP_BUILD > 0 ? 'android' : null;
/** The phone's processor types, best first (e.g. «arm64-v8a,armeabi-v7a»): the server gives updates as the APK that fits. */
export const APP_ABIS = APP_PLATFORM ? (Device.supportedCpuArchitectures ?? []).join(',') : '';

/**
 * Server address. The default comes from app/.env (EXPO_PUBLIC_API_URL) — never written in code.
 * Test builds (and staff emergency access) can override it from the hidden settings screen.
 * Official builds strictly require https:// both when saving and when reading any legacy stored override.
 */
const defaultApiUrl = (
  process.env.EXPO_PUBLIC_API_URL ||
  // The web version built for the laptop server is served by that same server: no address needed, it asks its own.
  (Platform.OS === 'web' && typeof window !== 'undefined' ? window.location.origin : '')
).replace(/\/+$/, '');

let override: string | null | undefined;

export function isHttpsUrl(url: string): boolean {
  return /^https:\/\/[^\s/$.?#].[^\s]*$/i.test(url.trim());
}

export function normalizeServerUrl(raw: string, channel: AppChannel = APP_CHANNEL): string {
  const trimmed = raw.trim().replace(/\/+$/, '');
  if (!trimmed) throw new Error('آدرس سرور را وارد کنید.');
  const withScheme = /^https?:\/\//i.test(trimmed)
    ? trimmed
    : `${channel === 'official' ? 'https' : 'http'}://${trimmed}`;
  if (channel === 'official' && !isHttpsUrl(withScheme)) {
    throw new Error('در نسخه‌ی رسمی فقط نشانی‌های امن https:// مجاز است.');
  }
  return withScheme;
}

export async function getApiUrl(): Promise<string> {
  if (override === undefined) override = await storage.getServerUrl();
  if (override && APP_CHANNEL === 'official' && !isHttpsUrl(override)) {
    // Discard legacy cleartext http:// overrides in official builds rather than connecting insecurely.
    override = null;
    await storage.setServerUrl(null).catch(() => undefined);
  }
  const url = override || defaultApiUrl;
  if (!url) throw new Error('No server address. Set EXPO_PUBLIC_API_URL in app/.env or in the app settings.');
  if (APP_CHANNEL === 'official' && Platform.OS !== 'web' && !isHttpsUrl(url)) {
    throw new Error('در نسخه‌ی رسمی آدرس سرور باید با https:// شروع شود.');
  }
  return url;
}

export async function setApiUrlOverride(url: string | null) {
  override = url ? normalizeServerUrl(url) : null;
  await storage.setServerUrl(override);
}

export function getDefaultApiUrl() {
  return defaultApiUrl;
}
