import { Asset } from 'expo-asset';
import { useEffect, useMemo, useRef } from 'react';
import { ScrollView, StyleSheet } from 'react-native';

import { FONT_FILES, fontFaceCss } from '../lib/fonts';
import { QUIZ_CSS, QUIZ_SCRIPT, questionHtml, type QuizQuestion, type QuizViewState } from '../lib/quizHtml';
import { CONTENT_CSS } from '../lib/renderMarkdown';
import type { QuizEvent } from './QuizView';

export type { QuizEvent } from './QuizView';

let injected = false;
function injectCss() {
  if (injected || typeof document === 'undefined') return;
  const style = document.createElement('style');
  style.textContent = fontFaceCss((f) => Asset.fromModule(FONT_FILES[f]).uri) + CONTENT_CSS + QUIZ_CSS;
  document.head.appendChild(style);
  injected = true;
}

/** One practice question drawn straight into the page (web). */
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
  injectCss();
  const html = useMemo(() => questionHtml(question, mode), [question, mode]);
  const root = useRef<(HTMLDivElement & { __setState?: (s: QuizViewState) => void }) | null>(null);
  const handler = useRef(onEvent);
  handler.current = onEvent;
  useEffect(() => {
    if (root.current) new Function('root', 'post', QUIZ_SCRIPT)(root.current, (m: QuizEvent) => handler.current(m));
  }, [html]);
  useEffect(() => {
    root.current?.__setState?.(state);
  }, [state, html]);
  return (
    <ScrollView style={styles.fill} contentContainerStyle={styles.page}>
      <div ref={root} className="quiz lesson" dangerouslySetInnerHTML={{ __html: html }} />
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  fill: { flex: 1 },
  page: { maxWidth: 760, width: '100%', alignSelf: 'center' },
});
