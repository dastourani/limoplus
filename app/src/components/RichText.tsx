import { View } from 'react-native';

import { colors, rtl } from '../theme';
import { MarkdownView } from './MarkdownView';
import { Text } from './Text';

/** Short text: drawn natively when plain (fast); with formulas or markup it goes through the lesson renderer. */
export function RichText({ text, size = 16 }: { text: string; size?: number }) {
  if (/[$*`|!\[]/.test(text)) {
    return (
      <View pointerEvents="none">
        <MarkdownView markdown={text} compact fontSize={size} />
      </View>
    );
  }
  return <Text style={[{ fontSize: size, lineHeight: size * 1.8, color: colors.ink }, rtl]}>{text}</Text>;
}
