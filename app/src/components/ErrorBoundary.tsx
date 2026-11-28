import React, { Component, type ErrorInfo, type ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { reportDiagnostic, sanitizeErrorName, sanitizeStack } from '../lib/diagnostics';
import { colors, rtl } from '../theme';
import { Text } from './Text';
import { Button } from './ui';

type Props = { children: ReactNode };
type State = { hasError: boolean; isChunkError: boolean };

const CHUNK_RELOAD_KEY = 'limo.chunkReloadAt';

function isAsyncChunkError(error: Error): boolean {
  return (
    error.name === 'AsyncRequireError' ||
    error.name === 'ChunkLoadError' ||
    /Loading (?:module|chunk) /i.test(error.message || '')
  );
}

function tryReloadOnceForChunkError(): boolean {
  try {
    const w = typeof window !== 'undefined' ? window : undefined;
    if (!w?.location?.reload || !w.sessionStorage) return false;
    const now = Date.now();
    const prev = Number(w.sessionStorage.getItem(CHUNK_RELOAD_KEY) || '0');
    if (prev && now - prev < 30_000) return false;
    w.sessionStorage.setItem(CHUNK_RELOAD_KEY, String(now));
    w.location.reload();
    return true;
  } catch {
    return false;
  }
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false, isChunkError: false };

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, isChunkError: isAsyncChunkError(error) };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    const chunkError = isAsyncChunkError(error);
    if (chunkError && tryReloadOnceForChunkError()) {
      return;
    }
    const safeName = sanitizeErrorName(error.name || 'Error');
    void reportDiagnostic({
      kind: 'client_error',
      severity: 'critical',
      code: 'react_render',
      title: `خطای نمایش صفحه: ${safeName}`,
      expected: 'صفحه بدون خطای رندر نمایش داده شود.',
      observed: `خطای رندر (${safeName}) در نمایش صفحه رخ داد.`,
      context: {
        error_name: safeName,
        stack: sanitizeStack(error.stack),
        component_stack: sanitizeStack(info.componentStack ?? ''),
      },
    });
  }

  private reset = () => {
    if (this.state.isChunkError) {
      try {
        if (typeof window !== 'undefined' && window.location?.reload) {
          window.location.reload();
          return;
        }
      } catch {
        // fallback to resetting state
      }
    }
    this.setState({ hasError: false, isChunkError: false });
  };

  render() {
    if (!this.state.hasError) return this.props.children;
    return (
      <View style={styles.wrap}>
        <Text style={[styles.title, rtl]}>مشکلی در نمایش این صفحه پیش آمد</Text>
        <Text style={[styles.desc, rtl]}>گزارش فنی برای بررسی ثبت شد. می‌توانید دوباره تلاش کنید.</Text>
        <Button label="تلاش دوباره" onPress={this.reset} />
      </View>
    );
  }
}

const styles = StyleSheet.create({
  wrap: {
    flex: 1,
    backgroundColor: colors.ground,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 24,
    gap: 12,
  },
  title: { fontSize: 18, fontWeight: '800', color: colors.ink, textAlign: 'center' },
  desc: { fontSize: 14, color: colors.muted, textAlign: 'center', lineHeight: 22 },
});
