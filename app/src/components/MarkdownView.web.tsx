import { Asset } from 'expo-asset';
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import { ScrollView, StyleSheet, View } from 'react-native';

import { FONT_FILES, fontFaceCss } from '../lib/fonts';
import { CONTENT_CSS, READER_SCRIPT, renderMarkdown } from '../lib/renderMarkdown';
import type { Highlight, MarkdownViewHandle, ReaderEvent } from './MarkdownView';

export type { Highlight, MarkdownViewHandle, ReaderEvent } from './MarkdownView';

type Props = { markdown: string; compact?: boolean; fontSize?: number; dark?: boolean; highlights?: Highlight[]; onEvent?: (e: ReaderEvent) => void };

let cssInjected = false;
function injectCss() {
  if (cssInjected || typeof document === 'undefined') return;
  const style = document.createElement('style');
  style.textContent = fontFaceCss((family) => Asset.fromModule(FONT_FILES[family]).uri) + CONTENT_CSS;
  document.head.appendChild(style);
  cssInjected = true;
}

/** Lesson text with formulas, tables and boxes. Web version: rendered straight into the page. */
export const MarkdownView = forwardRef<MarkdownViewHandle, Props>(function MarkdownView(
  { markdown, compact = false, fontSize = 17, dark = false, highlights, onEvent },
  ref,
) {
  injectCss();
  const html = useMemo(() => renderMarkdown(markdown), [markdown]);
  const root = useRef<HTMLDivElement | null>(null);
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    if (compact || !root.current) return;
    // Same reader behaviour as the phone app (highlights, selection, copy limit).
    new Function('root', 'post', READER_SCRIPT)(root.current, (m: ReaderEvent) => handler.current?.(m));
  }, [compact, html]);

  useEffect(() => {
    const el = root.current as (HTMLDivElement & { __setHighlights?: (h: Highlight[]) => void }) | null;
    if (!compact && highlights && el?.__setHighlights) el.__setHighlights(highlights);
  }, [highlights, html, compact]);

  useImperativeHandle(ref, () => ({ clearSelection: () => window.getSelection()?.removeAllRanges() }));

  const content = (
    <div
      ref={root}
      className={`lesson${compact ? ' compact' : ''}${dark ? ' dark' : ''}`}
      style={{ ['--fs' as string]: `${fontSize}px` }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
  if (compact) return <View>{content}</View>;
  return (
    <ScrollView
      style={styles.fill}
      contentContainerStyle={styles.page}
      scrollEventThrottle={300}
      onScroll={(e) => {
        const { contentOffset, contentSize, layoutMeasurement } = e.nativeEvent;
        const h = contentSize.height - layoutMeasurement.height;
        onEvent?.({ type: 'scroll', percent: h <= 0 ? 100 : Math.round((contentOffset.y / h) * 100) });
      }}
      onContentSizeChange={(_, h) => {
        if (typeof window !== 'undefined' && h <= window.innerHeight) onEvent?.({ type: 'scroll', percent: 100 });
      }}
    >
      {content}
    </ScrollView>
  );
});

const styles = StyleSheet.create({
  fill: { flex: 1 },
  page: { maxWidth: 760, width: '100%', alignSelf: 'center' },
});
