import { flushOutbox, setOutboxOwner, setReconnectHandler } from './network';
import * as Device from 'expo-device';
import { router } from 'expo-router';
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { Platform } from 'react-native';

import { setAuthToken, setUnauthorizedHandler } from '../api/client';
import { endpoints, type User } from '../api/endpoints';
import AsyncStorage from '@react-native-async-storage/async-storage';

import { clearOffline, reconcileOfflineRevocations } from './offline';
import { secure } from './secure';
import { flushStudyTime, forgetStudyTime, setStudyOwner } from './studyTime';

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
  const signedInRef = useRef(false);

  const remember = useCallback((u: User) => {
    signedInRef.current = true;
    setOutboxOwner(u.id);
    setStudyOwner(u.id);
    setUser(u);
    AsyncStorage.setItem(USER_KEY, JSON.stringify(u)).catch(() => undefined);
    void reconcileOfflineRevocations(u.offline_revocations);
  }, []);

  const forget = useCallback(async () => {
    signedInRef.current = false;
    setOutboxOwner(null);
    setStudyOwner(null);
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
    setReconnectHandler(() => {
      if (signedInRef.current) endpoints.me().then(remember).catch(() => undefined);
    });
    (async () => {
      // Never wait for the server here: the app opens at once with what the phone knows, then refreshes in the
      // background. (Waiting made the app sit on a blank screen while an unreachable server timed out.)
      const token = await secure.get(TOKEN_KEY);
      if (token) {
        signedInRef.current = true;
        setAuthToken(token);
        const cached = await AsyncStorage.getItem(USER_KEY).catch(() => null);
        if (cached) {
          const u = JSON.parse(cached) as User;
          setOutboxOwner(u.id);
          setStudyOwner(u.id);
          setUser(u);
        }
      }
      setReady(true);
      if (token) {
        // A 401 is handled by the unauthorized handler (signs out); any other error keeps the cached profile.
        endpoints.me().then(remember).catch(() => undefined);
      }
    })();
    return () => {
      setUnauthorizedHandler(null);
      setReconnectHandler(null);
    };
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
        // Send what is still waiting from this account while it is still signed in.
        if (remote) {
          await flushStudyTime();
          await flushOutbox().catch(() => undefined);
        }
        forgetStudyTime();
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
