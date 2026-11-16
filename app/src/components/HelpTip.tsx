/** A small «؟» that opens a sheet explaining a number or a word on the screen. */
import { useState } from 'react';
import { Pressable, StyleSheet } from 'react-native';

import { colors, rtl } from '../theme';
import { Text } from './Text';
import { Sheet } from './ui';

export function HelpTip({ title, text, size = 22 }: { title: string; text: string; size?: number }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <Pressable
        onPress={() => setOpen(true)}
        hitSlop={10}
        accessibilityRole="button"
        accessibilityLabel={`${title} یعنی چه؟`}
        style={[styles.q, { width: size, height: size, borderRadius: size / 2 }]}
      >
        <Text style={[styles.qText, { fontSize: Math.round(size * 0.55) }]}>؟</Text>
      </Pressable>
      <Sheet visible={open} onClose={() => setOpen(false)} title={title}>
        <Text style={[styles.help, rtl]}>{text}</Text>
      </Sheet>
    </>
  );
}

const styles = StyleSheet.create({
  q: { borderWidth: 1, borderColor: colors.line, alignItems: 'center', justifyContent: 'center', backgroundColor: colors.surface },
  qText: { fontWeight: '800', color: colors.muted },
  help: { fontSize: 15, lineHeight: 26, color: colors.ink },
});
