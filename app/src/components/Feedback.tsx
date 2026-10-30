/**
 * App-wide confirmations and short messages, drawn in the app's own style (right to left, Vazirmatn) instead of the
 * system dialogs. `const { confirm, toast } = useFeedback();`
 *   await confirm({ title, message, confirmLabel, destructive })  → true/false
 *   toast('ذخیره شد') or toast('یادداشت حذف شد', { label: 'برگرداندن', onPress: undo })
 */
import { createContext, useCallback, useContext, useRef, useState, type ReactNode } from 'react';
import { Modal, Pressable, StyleSheet, View } from 'react-native';
import { useSafeAreaInsets } from 'react-native-safe-area-context';

import { colors, radius, rtl } from '../theme';
import { Icon, type IconName } from './Icon';
import { Text } from './Text';
import { Button } from './ui';

type ConfirmOptions = { title: string; message?: string; confirmLabel?: string; cancelLabel?: string; destructive?: boolean; icon?: IconName };
type ToastAction = { label: string; onPress: () => void };
type Feedback = { confirm: (o: ConfirmOptions) => Promise<boolean>; toast: (text: string, action?: ToastAction) => void };

const FeedbackContext = createContext<Feedback>({ confirm: async () => false, toast: () => undefined });

export function useFeedback() {
  return useContext(FeedbackContext);
}

export function FeedbackProvider({ children }: { children: ReactNode }) {
  const insets = useSafeAreaInsets();
  const [dialog, setDialog] = useState<(ConfirmOptions & { resolve: (v: boolean) => void }) | null>(null);
  const [message, setMessage] = useState<{ text: string; action?: ToastAction } | null>(null);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const confirm = useCallback((o: ConfirmOptions) => new Promise<boolean>((resolve) => setDialog({ ...o, resolve })), []);
  const toast = useCallback((text: string, action?: ToastAction) => {
    if (timer.current) clearTimeout(timer.current);
    setMessage({ text, action });
    timer.current = setTimeout(() => setMessage(null), action ? 5000 : 2800);
  }, []);

  const close = (value: boolean) => {
    dialog?.resolve(value);
    setDialog(null);
  };

  return (
    <FeedbackContext.Provider value={{ confirm, toast }}>
      {children}
      <Modal visible={!!dialog} transparent animationType="fade" onRequestClose={() => close(false)}>
        <View style={styles.backdrop}>
          <Pressable style={StyleSheet.absoluteFill} onPress={() => close(false)} accessibilityLabel="انصراف" />
          <View style={styles.dialog}>
            {dialog?.icon && (
              <View style={[styles.dialogIcon, dialog.destructive && { backgroundColor: colors.redSoft }]}>
                <Icon name={dialog.icon} size={26} color={dialog.destructive ? colors.redDark : colors.ink} />
              </View>
            )}
            <Text style={[styles.title, rtl]}>{dialog?.title}</Text>
            {!!dialog?.message && <Text style={[styles.message, rtl]}>{dialog.message}</Text>}
            <View style={styles.actions}>
              <Button
                label={dialog?.confirmLabel ?? 'بله'}
                variant={dialog?.destructive ? 'danger' : 'primary'}
                onPress={() => close(true)}
                style={{ flex: 1 }}
              />
              <Button label={dialog?.cancelLabel ?? 'انصراف'} variant="outline" onPress={() => close(false)} style={{ flex: 1 }} />
            </View>
          </View>
        </View>
      </Modal>
      {message && (
        <View style={[styles.toast, { bottom: Math.max(insets.bottom, 12) + 76 }]} pointerEvents="box-none">
          <View style={styles.toastBox}>
            <Text style={[styles.toastText, rtl]}>{message.text}</Text>
            {message.action && (
              <Pressable
                onPress={() => {
                  message.action!.onPress();
                  setMessage(null);
                }}
                hitSlop={10}
              >
                <Text style={styles.toastAction}>{message.action.label}</Text>
              </Pressable>
            )}
          </View>
        </View>
      )}
    </FeedbackContext.Provider>
  );
}

const styles = StyleSheet.create({
  backdrop: { flex: 1, backgroundColor: '#17201A88', alignItems: 'center', justifyContent: 'center', padding: 24 },
  dialog: { width: '100%', maxWidth: 420, backgroundColor: colors.surface, borderRadius: radius.lg, padding: 22, gap: 10 },
  dialogIcon: { width: 52, height: 52, borderRadius: 16, backgroundColor: colors.lemon, alignItems: 'center', justifyContent: 'center', alignSelf: 'flex-end' },
  title: { fontSize: 18, fontWeight: '800', color: colors.ink },
  message: { fontSize: 15, color: colors.muted, lineHeight: 26 },
  actions: { flexDirection: 'row-reverse', gap: 10, marginTop: 8 },
  toast: { position: 'absolute', zIndex: 1000, elevation: 10, left: 16, right: 16, alignItems: 'center' },
  toastBox: { flexDirection: 'row-reverse', alignItems: 'center', gap: 16, backgroundColor: colors.ink, borderRadius: 16, paddingHorizontal: 16, paddingVertical: 12, maxWidth: 480 },
  toastText: { color: colors.ground, fontSize: 14, flexShrink: 1 },
  toastAction: { color: colors.lemon, fontWeight: '700', fontSize: 14 },
});
