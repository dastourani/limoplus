import { useFonts } from 'expo-font';
import { Stack } from 'expo-router';
import * as SplashScreen from 'expo-splash-screen';
import { StatusBar } from 'expo-status-bar';
import { useEffect } from 'react';
import { I18nManager, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { CelebrationProvider } from '../components/Celebrate';
import { FeedbackProvider } from '../components/Feedback';
import { Intro } from '../components/Intro';
import { AuthProvider, useAuth } from '../lib/auth';
import { FONT_FILES } from '../lib/fonts';
import { NetworkProvider } from '../lib/network';
import { useScreenProtection } from '../lib/protect';
import { colors } from '../theme';

// Keep the lemon splash until fonts and the saved account are loaded, then the Intro animation takes over.
SplashScreen.preventAutoHideAsync().catch(() => undefined);

// The app lays itself out right to left on its own. Android must not mirror it again when the phone's language is
// Persian (the expo-localization plugin in app.json turns that off before React starts; this is a fallback).
if (I18nManager.isRTL) {
  I18nManager.allowRTL(false);
  I18nManager.forceRTL(false);
}

function Root() {
  const { ready } = useAuth();
  // Paid content is protected: no screenshots or screen recording in the app (Android FLAG_SECURE).
  useScreenProtection();
  useEffect(() => {
    if (ready) SplashScreen.hideAsync().catch(() => undefined);
  }, [ready]);
  if (!ready) return <View style={{ flex: 1, backgroundColor: colors.ink }} />;
  return (
    <>
      <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.ground }, animation: 'slide_from_left' }} />
      <Intro />
    </>
  );
}

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts(FONT_FILES);
  // Wait for the font so text doesn't jump; on error continue with the system font.
  if (!fontsLoaded && !fontError) return <View style={{ flex: 1, backgroundColor: colors.ink }} />;
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <AuthProvider>
        <NetworkProvider>
          <FeedbackProvider>
            <CelebrationProvider>
              <Root />
            </CelebrationProvider>
          </FeedbackProvider>
        </NetworkProvider>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
