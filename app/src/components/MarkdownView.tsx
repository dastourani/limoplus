import { useMemo, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { WebView } from 'react-native-webview';

import { fontFaceCss } from '../lib/fonts';
import { CONTENT_CSS, renderMarkdown } from '../lib/renderMarkdown';

// Font files embedded in the APK by the expo-font plugin (app.json); Android WebViews can always read android_asset.
const FONT_CSS = fontFaceCss((family) => `file:///android_asset/fonts/${family}.ttf`);

type Props = {
  markdown: string;
  /** Short texts (questions, explanations): sized to their content inside a parent ScrollView. */
  compact?: boolean;
  fontSize?: number;
};

const HEIGHT_SCRIPT = `
  (function () {
    function send() { window.ReactNativeWebView.postMessage(String(document.documentElement.scrollHeight)); }
    new ResizeObserver(send).observe(document.body);
    send();
  })();
  true;
`;

/** Lesson text with formulas, tables and boxes. Native version: rendered in a WebView. */
export function MarkdownView({ markdown, compact = false, fontSize = 17 }: Props) {
  const [height, setHeight] = useState(compact ? 40 : 0);
  const html = useMemo(
    () => `<!doctype html><html dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<style>${FONT_CSS}${CONTENT_CSS} body{--fs:${fontSize}px}</style></head>
<body><div class="lesson${compact ? ' compact' : ''}">${renderMarkdown(markdown)}</div></body></html>`,
    [markdown, compact, fontSize],
  );

  return (
    <View style={compact ? { height } : styles.fill}>
      <WebView
        originWhitelist={['*']}
        source={{ html, baseUrl: 'file:///android_asset/' }}
        style={styles.web}
        scrollEnabled={!compact}
        injectedJavaScript={compact ? HEIGHT_SCRIPT : undefined}
        onMessage={(event) => {
          const value = Number(event.nativeEvent.data);
          if (compact && value > 0) setHeight(value);
        }}
        setSupportMultipleWindows={false}
        javaScriptEnabled={compact}
        showsVerticalScrollIndicator={!compact}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  web: { backgroundColor: 'transparent' },
});
