import * as Device from 'expo-device';
import { Platform } from 'react-native';

import { storage } from './lib/storage';

/** Build number of this app (set by the APK build from its run number; 0 in development and on the web). */
export const APP_BUILD = Number(process.env.EXPO_PUBLIC_APP_BUILD ?? 0) || 0;
/** Only the Android app names its build to the server; the web version is always the latest. */
export const APP_PLATFORM = Platform.OS === 'android' && APP_BUILD > 0 ? 'android' : null;
/** The phone's processor types, best first (e.g. «arm64-v8a,armeabi-v7a»): the server gives updates as the APK that fits. */
export const APP_ABIS = APP_PLATFORM ? (Device.supportedCpuArchitectures ?? []).join(',') : '';

/**
 * Server address. The default comes from app/.env (EXPO_PUBLIC_API_URL) — never written in code.
 * Test builds can override it from the settings screen (e.g. the laptop's IP on the same Wi-Fi).
 */
const defaultApiUrl = (
  process.env.EXPO_PUBLIC_API_URL ||
  // The web version built for the laptop server is served by that same server: no address needed, it asks its own.
  (Platform.OS === 'web' && typeof window !== 'undefined' ? window.location.origin : '')
).replace(/\/+$/, '');

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
