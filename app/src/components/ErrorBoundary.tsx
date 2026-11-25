import React, { Component, type ErrorInfo, type ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { reportDiagnostic } from '../lib/diagnostics';
import { colors, rtl } from '../theme';
import { Text } from './Text';
import { Button } from './ui';

type Props = { children: ReactNode };
type State = { hasError: boolean };

export class ErrorBoundary extends Component<Props, State> {
  state: State = { hasError: false };

  static getDerivedStateFromError(): State {
    return { hasError: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    void reportDiagnostic({
      kind: 'client_error',
      severity: 'critical',
      code: 'react_render',
      title: `خطای نمایش صفحه: ${error.name || 'Error'}`,
      expected: 'صفحه بدون خطای رندر نمایش داده شود.',
      observed: error.message || 'خطای پیش‌بینی‌نشده هنگام نمایش صفحه رخ داد.',
      context: {
        error_name: error.name || 'Error',
        error_message: error.message,
        stack: error.stack,
        component_stack: info.componentStack ?? undefined,
      },
    });
  }

  private reset = () => {
    this.setState({ hasError: false });
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
