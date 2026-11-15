import { usePreventScreenCapture } from 'expo-screen-capture';

/** Blocks screenshots and screen recording in the phone app (Android FLAG_SECURE). */
export const useScreenProtection = () => usePreventScreenCapture();
