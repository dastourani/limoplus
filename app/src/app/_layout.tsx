import { useFonts } from 'expo-font';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { I18nManager, View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { FeedbackProvider } from '../components/Feedback';
import { AuthProvider, useAuth } from '../lib/auth';
import { FONT_FILES } from '../lib/fonts';
import { NetworkProvider } from '../lib/network';
import { useScreenProtection } from '../lib/protect';
import { colors } from '../theme';

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
  if (!ready) return <View style={{ flex: 1, backgroundColor: colors.ground }} />;
  return <Stack screenOptions={{ headerShown: false, contentStyle: { backgroundColor: colors.ground }, animation: 'slide_from_left' }} />;
}

export default function RootLayout() {
  const [fontsLoaded, fontError] = useFonts(FONT_FILES);
  // Wait for the font so text doesn't jump; on error continue with the system font.
  if (!fontsLoaded && !fontError) return <View style={{ flex: 1, backgroundColor: colors.ground }} />;
  return (
    <SafeAreaProvider>
      <StatusBar style="dark" />
      <AuthProvider>
        <NetworkProvider>
          <FeedbackProvider>
            <Root />
          </FeedbackProvider>
        </NetworkProvider>
      </AuthProvider>
    </SafeAreaProvider>
  );
}
