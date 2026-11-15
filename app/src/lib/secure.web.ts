import AsyncStorage from '@react-native-async-storage/async-storage';

/** Web has no keystore; the browser's storage is used (the web app is for convenience, the phone app for security). */
export const secure = {
  get: (key: string) => AsyncStorage.getItem(key).catch(() => null),
  set: (key: string, value: string | null) =>
    (value === null ? AsyncStorage.removeItem(key) : AsyncStorage.setItem(key, value)).catch(() => undefined),
};
