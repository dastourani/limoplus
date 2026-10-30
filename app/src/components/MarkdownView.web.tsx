import { useMemo } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { Asset } from 'expo-asset';

import { FONT_FILES, fontFaceCss } from '../lib/fonts';
import { CONTENT_CSS, renderMarkdown } from '../lib/renderMarkdown';

type Props = { markdown: string; compact?: boolean; fontSize?: number };

let cssInjected = false;
function injectCss() {
  if (cssInjected || typeof document === 'undefined') return;
  const style = document.createElement('style');
  style.textContent = fontFaceCss((family) => Asset.fromModule(FONT_FILES[family]).uri) + CONTENT_CSS;
  document.head.appendChild(style);
  cssInjected = true;
}

/** Lesson text with formulas, tables and boxes. Web version: rendered straight into the page. */
export function MarkdownView({ markdown, compact = false, fontSize = 17 }: Props) {
  injectCss();
  const html = useMemo(() => renderMarkdown(markdown), [markdown]);
  const content = (
    <div
      className={`lesson${compact ? ' compact' : ''}`}
      style={{ ['--fs' as string]: `${fontSize}px` }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
  if (compact) return <View>{content}</View>;
  return (
    <ScrollView style={styles.fill} contentContainerStyle={styles.page}>
      {content}
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  page: { maxWidth: 760, width: '100%', alignSelf: 'center' },
});
