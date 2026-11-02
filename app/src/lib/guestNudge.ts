import { router } from 'expo-router';
import { useCallback } from 'react';

import { useFeedback } from '../components/Feedback';
import { useAuth } from './auth';

let shown = false;

/** A guest who finished a section's notes or its tests is told, once per run of the app, that nothing of it is kept
 * without an account, with a button to sign in. */
export function useGuestNudge() {
  const { user } = useAuth();
  const { toast } = useFeedback();
  return useCallback(() => {
    if (user || shown) return;
    shown = true;
    toast('وارد شو تا خوانده‌ها و تست‌هایت ذخیره شود', { label: 'ورود', onPress: () => router.push('/login') });
  }, [user, toast]);
}
