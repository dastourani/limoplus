import { useEffect, useMemo, useRef, useState } from 'react';
import { StyleSheet, View } from 'react-native';
import { WebView } from 'react-native-webview';

import { fontFaceCss } from '../lib/fonts';
import { QUIZ_CSS, QUIZ_SCRIPT, questionHtml, type QuizQuestion, type QuizViewState } from '../lib/quizHtml';
import { CONTENT_CSS } from '../lib/renderMarkdown';

const FONT_CSS = fontFaceCss((family) => `file:///android_asset/fonts/${family}.ttf`);

export type QuizEvent = { type: 'choose'; id: number } | { type: 'report' } | { type: 'swipe'; dir: 'next' | 'prev'; flung?: boolean };

const BOOT = `
  (function () {
    var root = document.querySelector('.quiz');
    function post(m) { window.ReactNativeWebView.postMessage(JSON.stringify(m)); }
    ${QUIZ_SCRIPT}
    post({ type: 'ready' });
  })();
  true;
`;

/** One practice question in a single web view (phone). */
export function QuizView({
  question,
  state,
  onEvent,
  mode = 'practice',
}: {
  question: QuizQuestion;
  state: QuizViewState;
  onEvent: (e: QuizEvent) => void;
  mode?: 'practice' | 'exam';
}) {
  const web = useRef<{ injectJavaScript: (s: string) => void } | null>(null);
  const [ready, setReady] = useState(false);
  const html = useMemo(
    () => `<!doctype html><html dir="rtl"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, maximum-scale=1">
<style>${FONT_CSS}${CONTENT_CSS}${QUIZ_CSS} html,body{margin:0;background:transparent;overflow-x:hidden} .quiz{min-height:100vh;box-sizing:border-box}</style></head>
<body><div class="quiz lesson">${questionHtml(question, mode)}</div></body></html>`,
    [question, mode],
  );
  useEffect(() => setReady(false), [html]);
  useEffect(() => {
    if (ready) web.current?.injectJavaScript(`document.querySelector('.quiz').__setState(${JSON.stringify(state)}); true;`);
  }, [state, ready]);

  return (
    <View style={styles.fill}>
      <WebView
        ref={(i: unknown) => {
          web.current = i as typeof web.current;
        }}
        originWhitelist={['*']}
        source={{ html, baseUrl: 'file:///android_asset/' }}
        style={styles.web}
        injectedJavaScript={BOOT}
        javaScriptEnabled
        setSupportMultipleWindows={false}
        onShouldStartLoadWithRequest={(req) => req.url.startsWith('about:') || req.url.startsWith('file:') || req.url.startsWith('data:')}
        onMessage={(e) => {
          try {
            const m = JSON.parse(e.nativeEvent.data);
            if (m.type === 'ready') setReady(true);
            else onEvent(m as QuizEvent);
          } catch {
            // ignore
          }
        }}
      />
    </View>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  web: { backgroundColor: 'transparent' },
});
