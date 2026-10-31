import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { WebView } from 'react-native-webview';

import { fontFaceCss } from '../lib/fonts';
import { CONTENT_CSS, READER_SCRIPT, renderMarkdown, renderSummary } from '../lib/renderMarkdown';

// Font files embedded in the APK by the expo-font plugin (app.json); Android WebViews can always read android_asset.
const FONT_CSS = fontFaceCss((family) => `file:///android_asset/fonts/${family}.ttf`);

export type Highlight = { id: number; quote: string; color: string };
export type ReaderEvent =
  | { type: 'scroll'; percent: number }
  | { type: 'selection'; text: string }
  | { type: 'copy_blocked' }
  | { type: 'note'; id: number }
  | { type: 'highlights'; missing: number[] }
  | { type: 'jump'; q: string }
  | { type: 'cards' }
  | { type: 'term'; fa: string }
  | { type: 'flash_missing' };

type Props = {
  markdown: string;
  /** Short texts (questions, explanations): sized to their content inside a parent ScrollView. */
  compact?: boolean;
  fontSize?: number;
  dark?: boolean;
  sepia?: boolean;
  /** Line spacing multiplier for lessons (default 2). */
  lineHeight?: number;
  highlights?: Highlight[];
  /** Render a summary as a review card (labelled parts) when it has them. */
  variant?: 'notes' | 'summary';
  /** The review card's «حفظی» part offers the section's flashcards. */
  hasCards?: boolean;
  /** Scroll to and light up this phrase (n changes to repeat the same phrase). */
  flash?: { q: string; n: number } | null;
  /** Glossary words to underline in the notes. */
  terms?: string[];
  onEvent?: (event: ReaderEvent) => void;
};

export type MarkdownViewHandle = { clearSelection: () => void };

const HEIGHT_SCRIPT = `
  (function () {
    function send() { window.ReactNativeWebView.postMessage(JSON.stringify({ type: 'height', value: document.documentElement.scrollHeight })); }
    new ResizeObserver(send).observe(document.body);
    send();
  })();
  true;
`;

const READER_BOOT = `
  (function () {
    var root = document.querySelector('.lesson');
    function post(m) { window.ReactNativeWebView.postMessage(JSON.stringify(m)); }
    ${READER_SCRIPT}
    var last = -1;
    window.addEventListener('scroll', function () {
      var h = document.documentElement.scrollHeight - window.innerHeight;
      var p = h <= 0 ? 100 : Math.round(window.scrollY / h * 100);
      if (Math.abs(p - last) >= 5 || p >= 98) { last = p; post({ type: 'scroll', percent: p }); }
    }, { passive: true });
    setTimeout(function () {
      var h = document.documentElement.scrollHeight - window.innerHeight;
      if (h <= 0) post({ type: 'scroll', percent: 100 });
    }, 800);
  })();
  true;
`;

/** Lesson text with formulas, tables and boxes. Native version: rendered in a WebView. */
export const MarkdownView = forwardRef<MarkdownViewHandle, Props>(function MarkdownView(
  { markdown, compact = false, fontSize = 17, dark = false, sepia = false, lineHeight = 2, highlights, variant = 'notes', hasCards, flash, terms, onEvent },
  ref,
) {
  const web = useRef<{ injectJavaScript: (script: string) => void } | null>(null);
  const [height, setHeight] = useState(compact ? 40 : 0);
  const [loaded, setLoaded] = useState(false);
  const html = useMemo(
    () => `<!doctype html><html dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<style>${FONT_CSS}${CONTENT_CSS} body{--fs:${fontSize}px;--lh:${lineHeight}}</style></head>
<body><div class="lesson${compact ? ' compact no-select' : ''}${dark ? ' dark' : ''}${sepia ? ' sepia' : ''}">${variant === 'summary' ? renderSummary(markdown, { hasCards }) : renderMarkdown(markdown)}</div></body></html>`,
    [markdown, compact, fontSize, dark, sepia, lineHeight, variant, hasCards],
  );

  useEffect(() => setLoaded(false), [html]);
  useEffect(() => {
    if (!compact && loaded && highlights) web.current?.injectJavaScript(`document.querySelector('.lesson').__setHighlights(${JSON.stringify(highlights)}); true;`);
  }, [highlights, loaded, compact]);

  useEffect(() => {
    if (!compact && loaded && terms?.length) web.current?.injectJavaScript(`document.querySelector('.lesson').__setTerms(${JSON.stringify(terms)}); true;`);
  }, [terms, loaded, compact]);
  useEffect(() => {
    if (!compact && loaded && flash?.q) {
      const q = JSON.stringify(flash.q);
      // Give the page a moment to lay out before scrolling.
      setTimeout(() => web.current?.injectJavaScript(`document.querySelector('.lesson').__flash(${q}); true;`), 250);
    }
  }, [flash, loaded, compact]);

  useImperativeHandle(ref, () => ({
    clearSelection: () => web.current?.injectJavaScript('window.getSelection && window.getSelection().removeAllRanges(); true;'),
  }));

  return (
    <View style={compact ? { height } : styles.fill}>
      <WebView
        ref={(instance: unknown) => {
          web.current = instance as typeof web.current;
        }}
        originWhitelist={['*']}
        source={{ html, baseUrl: 'file:///android_asset/' }}
        style={styles.web}
        scrollEnabled={!compact}
        injectedJavaScript={compact ? HEIGHT_SCRIPT : READER_BOOT}
        onLoadEnd={() => setLoaded(true)}
        onMessage={(event) => {
          let message: { type: string; value?: number } & Record<string, unknown>;
          try {
            message = JSON.parse(event.nativeEvent.data);
          } catch {
            return;
          }
          if (message.type === 'height') {
            if (compact && (message.value ?? 0) > 0) setHeight(message.value!);
          } else onEvent?.(message as unknown as ReaderEvent);
        }}
        setSupportMultipleWindows={false}
        javaScriptEnabled
        showsVerticalScrollIndicator={!compact}
        // Links in lessons never navigate the reader away.
        onShouldStartLoadWithRequest={(req) => req.url.startsWith('about:') || req.url.startsWith('file:') || req.url.startsWith('data:')}
      />
    </View>
  );
});

const styles = StyleSheet.create({
  fill: { flex: 1 },
  web: { backgroundColor: 'transparent' },
});
