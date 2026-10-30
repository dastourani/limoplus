import * as Device from 'expo-device';
import { router } from 'expo-router';
import { createContext, useCallback, useContext, useEffect, useMemo, useState, type ReactNode } from 'react';
import { Platform } from 'react-native';

import { setAuthToken, setUnauthorizedHandler } from '../api/client';
import { endpoints, type User } from '../api/endpoints';
import AsyncStorage from '@react-native-async-storage/async-storage';

import { clearOffline } from './offline';
import { secure } from './secure';

const TOKEN_KEY = 'limo.token';
const USER_KEY = 'limo.user'; // last known profile, so the app works signed-in while offline

type AuthState = {
  user: User | null;
  ready: boolean;
  signIn: (token: string, user: User) => Promise<void>;
  signOut: (options?: { remote?: boolean }) => Promise<void>;
  setUser: (user: User) => void;
};

const AuthContext = createContext<AuthState>({
  user: null,
  ready: false,
  signIn: async () => undefined,
  signOut: async () => undefined,
  setUser: () => undefined,
});

export function deviceName(): string {
  if (Platform.OS === 'web') return 'مرورگر وب';
  return [Device.manufacturer, Device.modelName].filter(Boolean).join(' ') || 'گوشی';
}

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(false);

  const remember = useCallback((u: User) => {
    setUser(u);
    AsyncStorage.setItem(USER_KEY, JSON.stringify(u)).catch(() => undefined);
  }, []);

  const forget = useCallback(async () => {
    setAuthToken(null);
    setUser(null);
    await secure.set(TOKEN_KEY, null);
    await AsyncStorage.removeItem(USER_KEY).catch(() => undefined);
    await clearOffline(); // offline books belong to the signed-in account
  }, []);

  useEffect(() => {
    // The server ended this session (signed out from another device, expired): forget it locally.
    setUnauthorizedHandler(() => {
      forget();
    });
    (async () => {
      const token = await secure.get(TOKEN_KEY);
      if (token) {
        setAuthToken(token);
        try {
          remember(await endpoints.me());
        } catch (e) {
          // Only a 401 means the session is gone (the unauthorized handler already forgot it). Network or server
          // errors (e.g. a restart) keep the token and the last known profile.
          const cached = await AsyncStorage.getItem(USER_KEY).catch(() => null);
          if ((e as { status?: number }).status !== 401 && cached) setUser(JSON.parse(cached) as User);
        }
      }
      setReady(true);
    })();
    return () => setUnauthorizedHandler(null);
  }, [forget, remember]);

  const value = useMemo<AuthState>(
    () => ({
      user,
      ready,
      setUser: remember,
      signIn: async (token, signedIn) => {
        setAuthToken(token);
        await secure.set(TOKEN_KEY, token);
        remember(signedIn);
      },
      signOut: async ({ remote = true } = {}) => {
        if (remote) await endpoints.logout().catch(() => undefined);
        await forget();
      },
    }),
    [user, ready, forget, remember],
  );
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  return useContext(AuthContext);
}

/** Sends a guest to sign in, explaining why. Returns true if the user is already signed in. */
export function requireLogin(user: User | null, reason: string): boolean {
  if (user) return true;
  router.push({ pathname: '/login', params: { reason } });
  return false;
}
