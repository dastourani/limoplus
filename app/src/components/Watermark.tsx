import { StyleSheet, View } from 'react-native';

import { toPersianDigits } from '../theme';
import { Text } from './Text';

/** Faint repeated mark (the reader's phone number) over paid content, so leaked photos are traceable. */
export function Watermark({ text, dark }: { text: string; dark?: boolean }) {
  const label = toPersianDigits(text);
  return (
    <View pointerEvents="none" style={styles.layer} accessibilityElementsHidden importantForAccessibility="no-hide-descendants">
      {Array.from({ length: 8 }, (_, row) => (
        <View key={row} style={[styles.row, { marginRight: row % 2 ? 60 : 0 }]}>
          {Array.from({ length: 3 }, (_, i) => (
            <Text key={i} style={[styles.text, { color: dark ? '#FFFFFF' : '#17201A' }]}>
              {label}
            </Text>
          ))}
        </View>
      ))}
    </View>
  );
}

const styles = StyleSheet.create({
  layer: { position: 'absolute', top: 0, right: 0, bottom: 0, left: 0, overflow: 'hidden', justifyContent: 'space-around', paddingVertical: 20 },
  row: { flexDirection: 'row', justifyContent: 'space-around', transform: [{ rotate: '-24deg' }] },
  text: { fontSize: 13, opacity: 0.06, fontWeight: '700' },
});
