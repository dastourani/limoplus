import { Asset } from 'expo-asset';
import { forwardRef, useEffect, useImperativeHandle, useMemo, useRef } from 'react';
import { ScrollView, StyleSheet, View, type ScrollViewInstance } from 'react-native';

import { FONT_FILES, fontFaceCss } from '../lib/fonts';
import { CONTENT_CSS, READER_SCRIPT, pageEndHtml, pageStartHtml, renderMarkdown, type PageEnd, renderSummary } from '../lib/renderMarkdown';
import type { Highlight, MarkdownViewHandle, ReaderEvent } from './MarkdownView';

export type { Highlight, MarkdownViewHandle, ReaderEvent } from './MarkdownView';

type Props = {
  markdown: string;
  compact?: boolean;
  fontSize?: number;
  dark?: boolean;
  sepia?: boolean;
  lineHeight?: number;
  justify?: boolean;
  highlights?: Highlight[];
  variant?: 'notes' | 'summary';
  hasCards?: boolean;
  flash?: { q: string; n: number } | null;
  terms?: string[];
  onEvent?: (e: ReaderEvent) => void;
  turn?: { next: boolean; prev: boolean };
  end?: PageEnd;
  startAt?: number;
};

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
  { markdown, compact = false, fontSize = 17, dark = false, sepia = false, lineHeight = 2, justify = true, highlights, variant = 'notes', hasCards, flash, terms, onEvent, turn, end, startAt },
  ref,
) {
  injectCss();
  const html = useMemo(
    () => (compact ? '' : pageStartHtml(end)) + (variant === 'summary' ? renderSummary(markdown, { hasCards }) : renderMarkdown(markdown)) + (compact ? '' : pageEndHtml(end)),
    [markdown, variant, hasCards, compact, end],
  );
  const root = useRef<HTMLDivElement | null>(null);
  const handler = useRef(onEvent);
  const scroller = useRef<ScrollViewInstance>(null);
  // Placed once per text (the notes and the summary each get their own place). The place may arrive after the text
  // is drawn; 0 means the top (switching to a tab not read yet must not keep the other tab's scroll).
  const placed = useRef('');
  const textKey = `${variant}:${markdown.length}:${markdown.slice(0, 80)}`;
  useEffect(() => {
    if (compact || placed.current === textKey || startAt == null || typeof window === 'undefined') return;
    const t = setTimeout(() => {
      const el = (scroller.current as unknown as { getScrollableNode?: () => HTMLElement })?.getScrollableNode?.();
      if (!el) return;
      if (startAt <= 0.02) {
        el.scrollTop = 0;
        placed.current = textKey;
      } else if (el.scrollHeight > el.clientHeight) {
        placed.current = textKey;
        el.scrollTop = (el.scrollHeight - el.clientHeight) * Math.min(1, startAt);
      }
    }, 150);
    return () => clearTimeout(t);
  }, [startAt, compact, html, textKey]);
  handler.current = onEvent;

  useEffect(() => {
    if (compact || !root.current) return;
    // Same reader behaviour as the phone app (highlights, selection, copy limit).
    new Function('root', 'post', READER_SCRIPT)(root.current, (m: ReaderEvent) => handler.current?.(m));
    requestAnimationFrame(() => handler.current?.({ type: 'ready' }));
  }, [compact, html]);

  // In a browser the lesson cannot be copied at all (the phone app has no copy in its selection menu either): copy and
  // cut are refused, the browser's own menu and dragging text out are off, and printing shows a notice instead.
  useEffect(() => {
    const el = root.current;
    if (compact || !el) return;
    const refuse = (e: Event) => {
      e.preventDefault();
      e.stopPropagation();
      if (e.type === 'copy' || e.type === 'cut') handler.current?.({ type: 'copy_blocked' });
    };
    const events = ['copy', 'cut', 'contextmenu', 'dragstart'];
    events.forEach((n) => el.addEventListener(n, refuse, true));
    if (!document.getElementById('limo-no-print')) {
      const style = document.createElement('style');
      style.id = 'limo-no-print';
      style.textContent =
        "@media print { .lesson { display: none !important; } body::after { content: 'چاپ متن درس‌های لیموخوان ممکن نیست.'; display: block; padding: 40px; font: 20px Vazirmatn, Tahoma, sans-serif; text-align: center; direction: rtl; } }";
      document.head.appendChild(style);
    }
    return () => events.forEach((n) => el.removeEventListener(n, refuse, true));
  }, [compact, html]);

  useEffect(() => {
    const el = root.current as (HTMLDivElement & { __setHighlights?: (h: Highlight[]) => void }) | null;
    if (!compact && highlights && el?.__setHighlights) el.__setHighlights(highlights);
  }, [highlights, html, compact]);

  useEffect(() => {
    const el = root.current as (HTMLDivElement & { __setTurn?: (t: { next: boolean; prev: boolean }) => void }) | null;
    if (!compact && turn && el?.__setTurn) el.__setTurn(turn);
  }, [turn?.next, turn?.prev, html, compact]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    const el = root.current as (HTMLDivElement & { __setTerms?: (t: string[]) => void }) | null;
    if (!compact && terms?.length && el?.__setTerms) el.__setTerms(terms);
  }, [terms, html, compact]);
  useEffect(() => {
    const el = root.current as (HTMLDivElement & { __flash?: (q: string) => void }) | null;
    if (!compact && flash?.q && el?.__flash) setTimeout(() => el.__flash?.(flash.q), 200);
  }, [flash, html, compact]);

  useImperativeHandle(ref, () => ({ clearSelection: () => window.getSelection()?.removeAllRanges() }));

  const content = (
    <div
      ref={root}
      className={`lesson${compact ? ' compact' : ''}${dark ? ' dark' : ''}${sepia ? ' sepia' : ''}${justify ? '' : ' ragged'}`}
      style={{ ['--fs' as string]: `${fontSize}px`, ['--lh' as string]: String(lineHeight) }}
      dangerouslySetInnerHTML={{ __html: html }}
    />
  );
  if (compact) return <View>{content}</View>;
  return (
    <ScrollView
      ref={scroller}
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
