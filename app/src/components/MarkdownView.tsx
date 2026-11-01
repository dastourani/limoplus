import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { WebView } from 'react-native-webview';

import { fontFaceCss } from '../lib/fonts';
import { CONTENT_CSS, READER_SCRIPT, pageEndHtml, renderMarkdown, type PageEnd, renderSummary } from '../lib/renderMarkdown';

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
  | { type: 'flash_missing' }
  /** The page is drawn (time to take away a stand-in). */
  | { type: 'ready' }
  /** The finger turned the page: 1 to the next section, -1 to the previous one. */
  | { type: 'turn'; dir: 1 | -1 }
  /** The «بخش بعد» card at the end was tapped. */
  | { type: 'next' }
  /** A part of the page end was tapped: «N تست باقی است», a due card, the chapter exam, the next chapter, the book. */
  | { type: 'go'; to: 'quiz' | 'cards' | 'exam' | 'next-chapter' | 'book' };

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
  /** Sideways finger turning: which ways there is a section to go to. */
  turn?: { next: boolean; prev: boolean };
  /** The end of the page: what is left in the section, then the next section or the chapter's end. Keep it memoized. */
  end?: PageEnd;
  /** Open scrolled to this point (0–1), to continue where the reader left off. */
  startAt?: number;
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
    requestAnimationFrame(function () { post({ type: 'ready' }); });
  })();
  true;
`;

/** Lesson text with formulas, tables and boxes. Native version: rendered in a WebView. */
export const MarkdownView = forwardRef<MarkdownViewHandle, Props>(function MarkdownView(
  { markdown, compact = false, fontSize = 17, dark = false, sepia = false, lineHeight = 2, highlights, variant = 'notes', hasCards, flash, terms, onEvent, turn, end, startAt },
  ref,
) {
  const web = useRef<{ injectJavaScript: (script: string) => void } | null>(null);
  const [height, setHeight] = useState(compact ? 40 : 0);
  const [loaded, setLoaded] = useState(false);
  const html = useMemo(
    () => `<!doctype html><html dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<style>${FONT_CSS}${CONTENT_CSS} body{--fs:${fontSize}px;--lh:${lineHeight}}</style></head>
<body><div class="lesson${compact ? ' compact no-select' : ''}${dark ? ' dark' : ''}${sepia ? ' sepia' : ''}">${variant === 'summary' ? renderSummary(markdown, { hasCards }) : renderMarkdown(markdown)}${compact ? '' : pageEndHtml(end)}</div></body></html>`,
    [markdown, compact, fontSize, dark, sepia, lineHeight, variant, hasCards, end],
  );

  useEffect(() => setLoaded(false), [html]);
  useEffect(() => {
    if (!compact && loaded && highlights) web.current?.injectJavaScript(`document.querySelector('.lesson').__setHighlights(${JSON.stringify(highlights)}); true;`);
  }, [highlights, loaded, compact]);

  useEffect(() => {
    if (!compact && loaded && turn) web.current?.injectJavaScript(`document.querySelector('.lesson').__setTurn(${JSON.stringify(turn)}); true;`);
  }, [turn?.next, turn?.prev, loaded, compact]); // eslint-disable-line react-hooks/exhaustive-deps

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

  useEffect(() => {
    if (!compact && loaded && startAt && startAt > 0.02)
      web.current?.injectJavaScript(
        `setTimeout(function(){var h=document.documentElement.scrollHeight-window.innerHeight;if(h>0)window.scrollTo(0,h*${Math.min(1, startAt)});},120); true;`,
      );
  }, [loaded, compact, startAt]); // eslint-disable-line react-hooks/exhaustive-deps

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
