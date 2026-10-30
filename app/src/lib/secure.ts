import * as SecureStore from 'expo-secure-store';

/** Secrets (the session token, the offline key) live in the Android keystore-backed secure store. */
export const secure = {
  get: (key: string) => SecureStore.getItemAsync(key).catch(() => null),
  set: (key: string, value: string | null) =>
    (value === null ? SecureStore.deleteItemAsync(key) : SecureStore.setItemAsync(key, value)).catch(() => undefined),
};
