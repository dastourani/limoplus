import { useFonts } from 'expo-font';
import { Stack } from 'expo-router';
import { StatusBar } from 'expo-status-bar';
import { View } from 'react-native';
import { SafeAreaProvider } from 'react-native-safe-area-context';

import { AuthProvider, useAuth } from '../lib/auth';
import { FONT_FILES } from '../lib/fonts';
import { useScreenProtection } from '../lib/protect';
import { colors } from '../theme';

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
        <Root />
      </AuthProvider>
    </SafeAreaProvider>
  );
}
