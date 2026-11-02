import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AccessibilityInfo, Animated, Easing, Pressable, StyleSheet, View, useWindowDimensions } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints, type NodeDetail, type Note } from '../../api/endpoints';
import { MarkdownView, type MarkdownViewHandle, type ReaderEvent } from '../../components/MarkdownView';
import { ReportSheet } from '../../components/ReportSheet';
import { ReportButton } from '../../components/Tags';
import { Text, TextInput } from '../../components/Text';
import { Icon, IconBadge } from '../../components/Icon';
import { Button, ErrorState, Header, Loading, Screen, Sheet } from '../../components/ui';
import { Watermark } from '../../components/Watermark';
import { useFeedback } from '../../components/Feedback';
import { requireLogin, useAuth } from '../../lib/auth';
import { useGuestNudge } from '../../lib/guestNudge';
import { useStudyTimer } from '../../lib/studyTime';
import { sendOrQueue } from '../../lib/network';
import { parseTerms, type Term } from '../../lib/reviewCard';
import { offlineBooks, offlineSection } from '../../lib/offline';
import { storage, type ReaderTheme } from '../../lib/storage';
import { colors, formatToman, radius, rtl, toPersianDigits } from '../../theme';

/** Reading colours: each background comes with its own text colour. */
const THEMES: Record<ReaderTheme, { paper: string; ink: string; label: string }> = {
  white: { paper: '#FFFFFF', ink: '#17201A', label: 'سفید' },
  paper: { paper: colors.paper, ink: '#17201A', label: 'کاغذی' },
  sepia: { paper: '#F4ECD8', ink: '#4A3B2A', label: 'کاهی' },
  dark: { paper: '#121614', ink: '#E4E9E2', label: 'شب' },
};
const LINE_HEIGHTS: [number, string][] = [
  [1.7, 'فشرده'],
  [2, 'معمولی'],
  [2.4, 'باز'],
];

const NOTE_COLORS: [string, string][] = [
  ['yellow', '#FFE98A'],
  ['green', '#BFE8CF'],
  ['blue', '#C9DBFF'],
  ['pink', '#FFD0DF'],
];

type Locked = { title?: string; price?: number | null; slug?: string };

export default function Section() {
  const { id, from, title: titleParam, resume, find, mode: modeParam } = useLocalSearchParams<{
    id: string;
    from?: string;
    title?: string;
    resume?: string;
    /** From search: these words, lit up where they are, in this mode. */
    find?: string;
    mode?: string;
  }>();
  // «ادامه بده»: open in the same mode and at the same place as last time.
  const [startAt, setStartAt] = useState<number | undefined>(undefined);
  const spotPercent = useRef(0);
  const lastSpotSent = useRef<{ percent: number; mode: string }>({ percent: 0, mode: 'full' });
  // While the old place is being restored, the page's first scroll reports (0%) must not overwrite it.
  const restoring = useRef(resume === '1');
  // Arriving from the next or previous section: the page slides in from that side once it is drawn.
  const { width: screenW } = useWindowDimensions();
  const arriving = from === '1' || from === '-1' ? Number(from) : 0;
  const slide = useRef(new Animated.Value(arriving ? -arriving * screenW * 0.35 : 0)).current;
  const shown = useRef(new Animated.Value(arriving ? 0 : 1)).current;
  const arrived = useRef(!arriving);
  const leaving = useRef(false);
  const nodeId = Number(id);
  const { user } = useAuth();
  const reader = useRef<MarkdownViewHandle>(null);

  const [node, setNode] = useState<NodeDetail | null>(null);
  const [offline, setOffline] = useState(false);
  const [locked, setLocked] = useState<Locked | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const [mode, setMode] = useState<'full' | 'summary'>('full');
  const [flashTarget, setFlashTarget] = useState<{ q: string; n: number } | null>(null);
  const [term, setTerm] = useState<Term | null>(null);
  const [fontSize, setFontSize] = useState(17);
  const [theme, setTheme] = useState<ReaderTheme>('paper');
  const [lineHeight, setLineHeight] = useState(2);
  const [panelOpen, setPanelOpen] = useState(false);
  const [bookmarked, setBookmarked] = useState(false);
  const [notes, setNotes] = useState<Note[]>([]);
  const [missing, setMissing] = useState<number[]>([]);
  const [selection, setSelection] = useState('');
  const [noteSheet, setNoteSheet] = useState<{ note?: Note; quote?: string } | null>(null);
  const [noteText, setNoteText] = useState('');
  const [notesOpen, setNotesOpen] = useState(false);
  const [reportOpen, setReportOpen] = useState(false);
  const [reported, setReported] = useState(false);
  const progress = useRef({ sent: 0, done: false });

  const { toast: flash, confirm } = useFeedback();

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setLocked(null);
    setOffline(false);
    progress.current = { sent: 0, done: false };
    try {
      setNode(await endpoints.node(nodeId));
    } catch (e) {
      const err = e instanceof ApiError ? e : new ApiError(0, 'error', 'خطا');
      if (err.code === 'locked') setLocked((err.data.book as Locked) ?? {});
      else if (err.status === 0) {
        // No internet: read the encrypted offline copy if this book was downloaded.
        const copy = await offlineSection(nodeId);
        if (copy) {
          const book = (await offlineBooks()).find((b) => b.slug === copy.bookSlug);
          const ids = book?.sectionIds ?? [];
          const at = ids.indexOf(nodeId);
          setNode({
            id: copy.id,
            kind: 'section',
            title: copy.title,
            breadcrumb: [{ id: 0, kind: 'book', slug: copy.bookSlug, title: copy.bookTitle }],
            summary: copy.summary,
            full: copy.full,
            previous_id: at > 0 ? ids[at - 1] : null,
            next_id: at >= 0 && at + 1 < ids.length ? ids[at + 1] : null,
          });
          setOffline(true);
        } else setError(err);
      } else setError(err);
    } finally {
      setLoading(false);
    }
  }, [nodeId]);

  useEffect(() => {
    load();
    storage.getReader().then((p) => {
      if (p) {
        setFontSize(p.fontSize);
        setTheme(p.theme ?? (p.dark ? 'dark' : 'paper'));
        setLineHeight(p.lineHeight ?? 2);
      }
    });
  }, [load]);

  useEffect(() => {
    if (!node) return;
    const book = node.breadcrumb[0];
    storage.setLastSection({ id: node.id, title: node.title, bookTitle: book?.title ?? '', bookSlug: book?.slug ?? '' });
    setMode(find && modeParam === 'summary' && node.summary ? 'summary' : 'full');
    if (find) setFlashTarget({ q: find, n: 1 });
    spotPercent.current = 0;
    lastSpotSent.current = { percent: 0, mode: 'full' };
    if (restoring.current && book?.slug)
      (async () => {
        // This phone's own spot, or (signed in) the account's, whichever is newer: read on another device, go on here.
        const local = (await storage.getReading())[book.slug];
        let spot = local?.id === node.id ? { mode: local.mode, percent: local.percent, at: local.at } : null;
        if (user && !offline) {
          const s = await endpoints.nodeState(node.id).catch(() => null);
          const at = s?.at ? Date.parse(s.at) : 0;
          if (s && (s.position ?? 0) > 0 && (!spot || at > spot.at + 5000)) spot = { mode: s.mode ?? 'full', percent: s.position ?? 0, at };
        }
        if (spot) {
          if (spot.mode === 'summary' && node.summary) setMode('summary');
          spotPercent.current = spot.percent;
          setStartAt(spot.percent / 100);
        }
        setTimeout(() => (restoring.current = false), 1500);
      })();
    if (user && !offline) {
      endpoints
        .nodeState(node.id)
        .then((s) => {
          setBookmarked(s.bookmarked);
          setNotes(s.notes);
          progress.current = { sent: s.percent, done: s.is_done };
        })
        .catch(() => undefined);
    } else {
      setNotes([]);
      setBookmarked(false);
    }
  }, [node, user, offline]);

  const savePrefs = (next: { fontSize?: number; theme?: ReaderTheme; lineHeight?: number }) => {
    const prefs = { fontSize: next.fontSize ?? fontSize, theme: next.theme ?? theme, lineHeight: next.lineHeight ?? lineHeight };
    setFontSize(prefs.fontSize);
    setTheme(prefs.theme);
    setLineHeight(prefs.lineHeight);
    storage.setReader(prefs);
  };

  const showPage = useCallback(() => {
    if (arrived.current) return;
    arrived.current = true;
    Animated.parallel([
      Animated.timing(slide, { toValue: 0, duration: 240, easing: Easing.out(Easing.cubic), useNativeDriver: true }),
      Animated.timing(shown, { toValue: 1, duration: 200, useNativeDriver: true }),
    ]).start();
  }, [slide, shown]);
  useEffect(() => {
    if (!node || arrived.current) return;
    const t = setTimeout(showPage, 1500); // in case the page never says it is ready
    return () => clearTimeout(t);
  }, [node, showPage]);

  // ---- going to the next or previous section: a short slide, light enough for slow phones ----
  const goTo = (dir: 1 | -1) => {
    if (!node) return;
    const target = dir > 0 ? node.next_id : node.previous_id;
    if (!target) return;
    if (dir > 0 && user && !offline && !progress.current.done) sendOrQueue(`nodes/${node.id}/progress/`, { percent: 100, done: true });
    router.replace({ pathname: `/section/${target}`, params: { from: String(dir), title: (dir > 0 ? node.next_title : node.previous_title) ?? '' } });
  };
  const turnBy = async (dir: 1 | -1) => {
    if (!node || leaving.current || !(dir > 0 ? node.next_id : node.previous_id)) return;
    leaving.current = true;
    const reduce = await AccessibilityInfo.isReduceMotionEnabled().catch(() => false);
    if (!reduce)
      await new Promise<void>((done) =>
        Animated.parallel([
          // Right is the next section: a Persian book turns to the right.
          Animated.timing(slide, { toValue: dir * screenW, duration: 200, easing: Easing.in(Easing.cubic), useNativeDriver: true }),
          Animated.timing(shown, { toValue: 0.4, duration: 200, useNativeDriver: true }),
        ]).start(() => done()),
      );
    goTo(dir);
  };

  const rememberSpot = (percent: number) => {
    const book = node?.breadcrumb.find((b) => b.kind === 'book');
    if (!node || !book || restoring.current) return;
    spotPercent.current = percent;
    storage.setReading({ id: node.id, title: node.title, bookTitle: book.title, bookSlug: book.slug, mode, percent, at: Date.now() });
    // The account keeps the place too (every 10% or on a change of mode), for «ادامه بده» on another device.
    const last = lastSpotSent.current;
    if (user && !offline && (last.mode !== mode || Math.abs(last.percent - percent) >= 10)) {
      lastSpotSent.current = { percent, mode };
      sendOrQueue(`nodes/${node.id}/progress/`, { percent: mode === 'full' ? percent : 0, done: false, position: percent, mode });
    }
  };
  useEffect(() => {
    if (node) rememberSpot(mode === 'full' ? spotPercent.current : 0);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [node?.id, mode]);

  const terms = useMemo(() => parseTerms(node?.summary ?? ''), [node?.summary]);
  const pageEnd = useMemo(
    () => (node ? { nextTitle: node.next_title, status: node.status, chapterEnd: node.chapter_end } : undefined),
    [node],
  );
  const termWords = useMemo(() => terms.map((t) => t.fa), [terms]);

  const onEvent = (e: ReaderEvent) => {
    if (e.type === 'turn') {
      // The page already slid out under the finger.
      if (!leaving.current) {
        leaving.current = true;
        goTo(e.dir);
      }
    } else if (e.type === 'next') turnBy(1);
    else if (e.type === 'go' && node) {
      const end = node.chapter_end;
      const book = node.breadcrumb.find((b) => b.kind === 'book');
      if (e.to === 'quiz') router.push(`/quiz/${node.id}`);
      else if (e.to === 'cards') router.push(`/flashcards/${node.id}`);
      else if (e.to === 'exam' && end) router.push({ pathname: '/exam/[nodeId]', params: { nodeId: String(end.chapter_id), count: String(end.exam_questions ?? 10) } });
      else if (e.to === 'book' && (end?.book_slug || book)) router.push(`/book/${end?.book_slug ?? book!.slug}`);
      else if (e.to === 'next-chapter' && end?.next_chapter) {
        const next = end.next_chapter;
        if (user && !offline && !progress.current.done) sendOrQueue(`nodes/${node.id}/progress/`, { percent: 100, done: true });
        if (next.locked) router.push(`/book/${end.book_slug}`);
        else router.replace({ pathname: `/section/${next.id}`, params: { from: '1', title: next.title } });
      }
    }
    else if (e.type === 'ready') showPage();
    else if (e.type === 'jump') {
      // From an important point in the review card to the same place in the notes.
      setMode('full');
      if (e.q) setFlashTarget((f) => ({ q: e.q, n: (f?.n ?? 0) + 1 }));
    } else if (e.type === 'cards') {
      if (node) router.push(`/flashcards/${node.id}`);
    } else if (e.type === 'term') {
      setTerm(terms.find((t) => t.fa === e.fa) ?? null);
    } else if (e.type === 'selection') setSelection(e.text.trim());
    else if (e.type === 'copy_blocked') flash('کپی متن طولانی مجاز نیست.');
    else if (e.type === 'highlights') setMissing(e.missing);
    else if (e.type === 'note') {
      const n = notes.find((x) => x.id === e.id);
      if (n) {
        setNoteText(n.body);
        setNoteSheet({ note: n });
      }
    } else if (e.type === 'scroll' && node) {
      rememberSpot(e.percent);
      if (!user && e.percent >= 90) nudgeGuest();
      if (!(user && !offline && mode === 'full')) return;
      const p = progress.current;
      if (e.percent >= p.sent + 10 || (e.percent >= 90 && !p.done)) {
        p.sent = Math.max(p.sent, e.percent);
        p.done = p.done || e.percent >= 90;
        sendOrQueue(`nodes/${node.id}/progress/`, { percent: e.percent, done: false, position: e.percent, mode });
        lastSpotSent.current = { percent: e.percent, mode };
      }
    }
  };

  const highlights = useMemo(
    () => notes.filter((n) => n.quote && n.mode === mode).map((n) => ({ id: n.id, quote: n.quote, color: n.color })),
    [notes, mode],
  );

  const addHighlight = async (color: string, body = '') => {
    if (!node || !requireLogin(user, 'برای هایلایت و یادداشت وارد شوید؛ روی همه‌ی دستگاه‌هایتان می‌ماند.')) return;
    try {
      const note = await endpoints.addNote(node.id, { quote: selection, body, color, mode });
      setNotes((list) => [...list, note]);
      setSelection('');
      reader.current?.clearSelection();
    } catch (e) {
      flash(e instanceof ApiError ? e.message : 'ذخیره نشد.');
    }
  };

  const [noteBusy, setNoteBusy] = useState(false);
  const saveNote = async () => {
    if (!node || !noteSheet || noteBusy) return;
    setNoteBusy(true);
    try {
      if (noteSheet.note) {
        const updated = await endpoints.editNote(noteSheet.note.id, { body: noteText });
        setNotes((list) => list.map((n) => (n.id === updated.id ? updated : n)));
      } else if (requireLogin(user, 'برای یادداشت وارد شوید.')) {
        const note = await endpoints.addNote(node.id, { quote: noteSheet.quote ?? '', body: noteText, color: 'yellow', mode });
        setNotes((list) => [...list, note]);
        setSelection('');
        reader.current?.clearSelection();
      }
      setNoteSheet(null);
    } catch (e) {
      flash(e instanceof ApiError ? e.message : 'ذخیره نشد.');
    } finally {
      setNoteBusy(false);
    }
  };

  const deleteNote = async (note: Note) => {
    try {
      await endpoints.deleteNote(note.id);
    } catch (e) {
      flash(e instanceof ApiError ? e.message : 'حذف نشد.');
      return;
    }
    setNotes((list) => list.filter((n) => n.id !== note.id));
    setNoteSheet(null);
    flash(note.quote && !note.body ? 'هایلایت حذف شد.' : 'یادداشت حذف شد.', {
      label: 'برگرداندن',
      onPress: () => {
        if (!node) return;
        endpoints
          .addNote(node.id, { quote: note.quote, body: note.body, color: note.color, mode: note.mode })
          .then((restored) => setNotes((list) => [...list, restored]))
          .catch(() => flash('برگرداندن ممکن نشد.'));
      },
    });
  };

  // Closing the note editor with unsaved text asks first.
  const closeNoteSheet = async () => {
    const original = noteSheet?.note?.body ?? '';
    if (noteText.trim() && noteText !== original) {
      const discard = await confirm({ title: 'یادداشت ذخیره نشده است', message: 'بدون ذخیره بسته شود؟', confirmLabel: 'بستن بدون ذخیره', cancelLabel: 'ادامه‌ی نوشتن', destructive: true });
      if (!discard) return;
    }
    setNoteSheet(null);
  };

  const [bookmarkBusy, setBookmarkBusy] = useState(false);
  const toggleBookmark = async () => {
    if (bookmarkBusy || !node || !requireLogin(user, 'برای نشان کردن بخش‌ها وارد شوید.')) return;
    setBookmarkBusy(true);
    try {
      const r = await endpoints.toggleBookmark(node.id);
      setBookmarked(r.bookmarked);
      if (r.bookmarked) flash('به نشان‌شده‌ها اضافه شد.');
      else
        flash('از نشان‌شده‌ها برداشته شد.', {
          label: 'برگرداندن',
          onPress: () => endpoints.toggleBookmark(node.id).then((x) => setBookmarked(x.bookmarked)).catch(() => undefined),
        });
    } catch {
      flash('ذخیره نشد. اتصال اینترنت را بررسی کنید.');
    } finally {
      setBookmarkBusy(false);
    }
  };

  const { paper, ink } = THEMES[theme];
  const dark = theme === 'dark';

  const nudgeGuest = useGuestNudge();
  // «زمان مطالعه»: reading this section while the screen is open (two minutes without a touch stops it).
  useStudyTimer(node ? nodeId : null, 'read', !!user);

  if (loading)
    return arriving ? (
      <Screen background={paper}>
        <View style={styles.header}>
          <View style={styles.icon}>
            <Icon name="arrow-right" size={24} color={ink} />
          </View>
          <Text style={[styles.title, rtl, { color: ink, flex: 1 }]} numberOfLines={1}>{titleParam}</Text>
        </View>
      </Screen>
    ) : (
      <Screen>
        <Header />
        <Loading />
      </Screen>
    );

  if (locked) {
    return (
      <Screen>
        <Header title={locked.title} />
        <View style={styles.locked}>
          <IconBadge name="lock" size={72} />
          <Text style={styles.lockTitle}>این بخش در نسخه‌ی کامل کتاب است</Text>
          {locked.price ? <Text style={styles.lockPrice}>{formatToman(locked.price)}</Text> : null}
          {locked.slug && <Button label="خرید یا اشتراک" onPress={() => router.push(`/buy/${locked.slug}`)} style={{ alignSelf: 'stretch' }} />}
          <Button label="بازگشت" variant="outline" onPress={() => router.back()} style={{ alignSelf: 'stretch' }} />
        </View>
      </Screen>
    );
  }
  if (error || !node) return <Screen><Header /><ErrorState message={error?.message ?? 'پیدا نشد.'} onRetry={load} /></Screen>;

  const chapter = node.breadcrumb[node.breadcrumb.length - 1];
  // «فصل ۲: تابش و اتم»: the number comes from the chapter's place in the book.
  const chapterLabel = chapter ? (chapter.kind === 'chapter' && chapter.number ? `فصل ${toPersianDigits(chapter.number)}، ${chapter.title}` : chapter.title) : '';
  const body = mode === 'summary' && node.summary ? node.summary : node.full;
  const bookSlug = node.breadcrumb.find((b) => b.kind === 'book')?.slug;
  const missingNotes = notes.filter((n) => missing.includes(n.id) && n.mode === mode);

  return (
    <Screen background={paper}>
      <View style={styles.header}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/home'))} style={styles.icon} accessibilityLabel="بازگشت">
          <Icon name="arrow-right" size={24} color={ink} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={[styles.sub, rtl]} numberOfLines={1}>{offline ? `آفلاین، ${chapterLabel}` : chapterLabel}</Text>
          <Text style={[styles.title, rtl, { color: ink }]} numberOfLines={1}>{node.title}</Text>
        </View>
        <Pressable onPress={toggleBookmark} disabled={bookmarkBusy} style={[styles.icon, bookmarkBusy && { opacity: 0.35 }]} accessibilityLabel="نشان کردن">
          <Icon name={bookmarked ? 'bookmark-check' : 'bookmark'} size={22} color={bookmarked ? colors.lemon : ink} />
        </Pressable>
        <Pressable onPress={() => setNotesOpen(true)} style={styles.icon} accessibilityLabel="یادداشت‌ها">
          <Icon name="notebook-pen" size={22} color={ink} />
          {notes.length > 0 && <Text style={styles.count}>{notes.length}</Text>}
        </Pressable>
        <Pressable onPress={() => setPanelOpen(true)} style={styles.icon} accessibilityLabel="تنظیمات نمایش متن">
          <Icon name="a-large-small" size={24} color={ink} />
        </Pressable>
      </View>
      {!!node.summary && (
        <View style={[styles.toggle, dark && { backgroundColor: '#26302A' }]}>
          {(['full', 'summary'] as const).map((m) => (
            <Pressable key={m} onPress={() => setMode(m)} style={[styles.toggleItem, mode === m && styles.toggleOn]} accessibilityRole="tab" accessibilityState={{ selected: mode === m }}>
              <Text style={[styles.toggleText, mode === m && styles.toggleTextOn]}>{m === 'full' ? 'جزوه' : 'خلاصه'}</Text>
            </Pressable>
          ))}
        </View>
      )}

      <View style={{ flex: 1, overflow: 'hidden' }}>
        <Animated.View style={{ flex: 1, opacity: shown, transform: [{ translateX: slide }] }}>
        <MarkdownView
          ref={reader}
          markdown={body}
          variant={mode === 'summary' && node.summary ? 'summary' : 'notes'}
          hasCards
          flash={flashTarget}
          terms={mode === 'full' ? termWords : undefined}
          fontSize={fontSize}
          dark={dark}
          sepia={theme === 'sepia'}
          lineHeight={lineHeight}
          highlights={highlights}
          onEvent={onEvent}
          turn={{ next: !!node.next_id, prev: !!node.previous_id }}
          end={pageEnd}
          startAt={startAt}
        />
        <Watermark text={user?.phone || 'لیمو پلاس'} dark={dark} />
        </Animated.View>
        <Sheet visible={!!term} onClose={() => setTerm(null)} title={term?.fa ?? ''}>
          {!!term?.en && <Text style={styles.termEn}>{term.en}</Text>}
          {!!term?.meaning && <Text style={[styles.termMean, rtl]}>{term.meaning}</Text>}
          {!!bookSlug && (
            <Button
              label="واژه‌نامه‌ی کتاب"
              variant="outline"
              onPress={() => {
                setTerm(null);
                router.push(`/glossary/${bookSlug}`);
              }}
            />
          )}
        </Sheet>
        {!!selection && (
          <View style={[styles.selBar, { bottom: 12 }]}>
            {NOTE_COLORS.map(([name, hex]) => (
              <Pressable key={name} onPress={() => addHighlight(name)} style={[styles.swatch, { backgroundColor: hex }]} accessibilityLabel="هایلایت" />
            ))}
            <Pressable
              onPress={() => {
                setNoteText('');
                setNoteSheet({ quote: selection });
              }}
              style={styles.selNote}
            >
              <Text style={styles.selNoteText}>یادداشت</Text>
            </Pressable>
          </View>
        )}
      </View>

      <View style={[styles.bar, { backgroundColor: paper, borderTopColor: dark ? '#26302A' : '#ECEFE6' }]}>
        <Pressable
          onPress={() => turnBy(-1)}
          disabled={!node.previous_id}
          style={[styles.arrow, { borderColor: dark ? '#3A463E' : colors.line }, !node.previous_id && { opacity: 0.3 }]}
          accessibilityRole="button"
          accessibilityLabel="بخش قبل"
        >
          <Icon name="chevron-right" size={24} color={ink} />
        </Pressable>
        <Button label="تست‌ها" variant={dark ? 'primary' : 'outline'} onPress={() => router.push(`/quiz/${node.id}`)} style={styles.barButton} />
        <Button label="فلش‌کارت" variant={dark ? 'primary' : 'outline'} onPress={() => router.push(`/flashcards/${node.id}`)} style={styles.barButton} />
        <Pressable
          onPress={() => turnBy(1)}
          disabled={!node.next_id}
          style={[styles.arrow, { borderColor: dark ? '#3A463E' : colors.line }, !node.next_id && { opacity: 0.3 }]}
          accessibilityRole="button"
          accessibilityLabel="بخش بعد"
        >
          <Icon name="chevron-left" size={24} color={ink} />
        </Pressable>
      </View>

      <Sheet visible={panelOpen} onClose={() => setPanelOpen(false)} title="نمایش متن">
        <Text style={[styles.panelLabel, rtl]}>رنگ زمینه</Text>
        <View style={styles.themes}>
          {(Object.keys(THEMES) as ReaderTheme[]).map((key) => (
            <Pressable
              key={key}
              onPress={() => savePrefs({ theme: key })}
              style={[styles.theme, { backgroundColor: THEMES[key].paper }, theme === key && styles.themeOn]}
              accessibilityRole="radio"
              accessibilityState={{ checked: theme === key }}
            >
              <Text style={{ color: THEMES[key].ink, fontSize: 18, fontWeight: '700' }}>آ</Text>
              <Text style={{ color: THEMES[key].ink, fontSize: 12 }}>{THEMES[key].label}</Text>
            </Pressable>
          ))}
        </View>
        <Text style={[styles.panelLabel, rtl]}>اندازه‌ی متن</Text>
        <View style={styles.stepper}>
          <Pressable onPress={() => savePrefs({ fontSize: Math.min(25, fontSize + 1) })} style={styles.step} accessibilityLabel="بزرگ‌تر">
            <Text style={{ fontSize: 22, fontWeight: '700' }}>آ+</Text>
          </Pressable>
          <Text style={styles.stepValue}>{toPersianDigits(fontSize)}</Text>
          <Pressable onPress={() => savePrefs({ fontSize: Math.max(14, fontSize - 1) })} style={styles.step} accessibilityLabel="کوچک‌تر">
            <Text style={{ fontSize: 15, fontWeight: '700' }}>آ−</Text>
          </Pressable>
        </View>
        <Text style={[styles.panelLabel, rtl]}>فاصله‌ی خطوط</Text>
        <View style={styles.themes}>
          {LINE_HEIGHTS.map(([value, label]) => (
            <Pressable key={value} onPress={() => savePrefs({ lineHeight: value })} style={[styles.lh, lineHeight === value && styles.themeOn]}>
              <Text style={{ fontWeight: '700', color: colors.ink }}>{label}</Text>
            </Pressable>
          ))}
        </View>
      </Sheet>

      <Sheet visible={!!noteSheet} onClose={closeNoteSheet} title={noteSheet?.note ? 'یادداشت' : 'یادداشت تازه'}>
        {!!(noteSheet?.note?.quote || noteSheet?.quote) && <Text style={[styles.quote, rtl]}>{noteSheet?.note?.quote || noteSheet?.quote}</Text>}
        <TextInput value={noteText} onChangeText={setNoteText} multiline placeholder="یادداشت شما…" style={styles.noteInput} maxLength={5000} />
        <Button label="ذخیره" onPress={saveNote} loading={noteBusy} />
        {noteSheet?.note && <Button label="حذف" variant="outline" onPress={() => deleteNote(noteSheet.note!)} />}
      </Sheet>

      <Sheet visible={notesOpen} onClose={() => setNotesOpen(false)} title="یادداشت‌ها و هایلایت‌های این بخش">
        {notes.length === 0 && <Text style={[styles.help, rtl]}>متنی را انتخاب کنید تا هایلایت یا یادداشت بگذارید.</Text>}
        {notes.map((n) => (
          <Pressable
            key={n.id}
            onPress={() => {
              setNotesOpen(false);
              setNoteText(n.body);
              setNoteSheet({ note: n });
            }}
            style={styles.noteRow}
          >
            {!!n.quote && <Text style={[styles.quote, rtl, { backgroundColor: NOTE_COLORS.find(([c]) => c === n.color)?.[1] }]}>{n.quote}</Text>}
            {!!n.body && <Text style={[styles.help, rtl, { color: colors.ink }]}>{n.body}</Text>}
            {missingNotes.some((m) => m.id === n.id) && <Text style={[styles.help, rtl]}>متن این بخش ویرایش شده و جای این هایلایت پیدا نشد.</Text>}
          </Pressable>
        ))}
        <View style={{ paddingVertical: 8 }}>
          <ReportButton
            reported={reported}
            label="گزارش اشکال در متن این بخش"
            onPress={() => {
              setNotesOpen(false);
              if (requireLogin(user, 'برای گزارش اشکال وارد شوید.')) setReportOpen(true);
            }}
          />
        </View>
      </Sheet>

      <ReportSheet
        visible={reportOpen}
        onClose={() => setReportOpen(false)}
        onSend={(reason, text) => endpoints.reportNode(node.id, reason, text)}
        onDone={() => {
          setReported(true);
          flash('گزارش داده شد. ممنون!');
        }}
      />
    </Screen>
  );
}

const styles = StyleSheet.create({
  termEn: { fontSize: 18, fontWeight: '700', color: '#3B44B8', textAlign: 'left', writingDirection: 'ltr' },
  termMean: { fontSize: 15, color: colors.ink, lineHeight: 26 },
  header: { flexDirection: 'row-reverse', alignItems: 'center', paddingHorizontal: 6, paddingVertical: 4 },
  icon: { width: 40, height: 44, alignItems: 'center', justifyContent: 'center' },
  panelLabel: { fontSize: 15, fontWeight: '700', color: colors.muted },
  themes: { flexDirection: 'row-reverse', gap: 8 },
  theme: { flex: 1, alignItems: 'center', paddingVertical: 10, borderRadius: 14, borderWidth: 1.5, borderColor: colors.line, gap: 2 },
  themeOn: { borderColor: colors.ink, borderWidth: 2.5 },
  stepper: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', borderWidth: 1.5, borderColor: colors.line, borderRadius: 14 },
  step: { width: 72, height: 48, alignItems: 'center', justifyContent: 'center' },
  stepValue: { fontSize: 18, fontWeight: '800', color: colors.ink },
  lh: { flex: 1, alignItems: 'center', paddingVertical: 12, borderRadius: 14, borderWidth: 1.5, borderColor: colors.line },
  count: { position: 'absolute', top: 4, left: 2, minWidth: 18, height: 18, borderRadius: 8, backgroundColor: colors.lemon, color: colors.ink, fontSize: 12, textAlign: 'center', overflow: 'hidden' },
  iconText: { fontSize: 22, fontWeight: '800' },
  sub: { fontSize: 12, color: colors.muted },
  title: { fontSize: 15, fontWeight: '800' },
  toggle: { flexDirection: 'row-reverse', alignSelf: 'center', backgroundColor: colors.disabled, borderRadius: 999, padding: 3, marginBottom: 6 },
  toggleItem: { paddingHorizontal: 22, paddingVertical: 7, borderRadius: 999 },
  toggleOn: { backgroundColor: colors.ink },
  toggleText: { fontWeight: '700', color: colors.muted },
  toggleTextOn: { color: colors.lemon },
  bar: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1, alignItems: 'stretch' },
  barButton: { flex: 1, paddingHorizontal: 6 },
  arrow: { width: 48, minHeight: 48, alignItems: 'center', justifyContent: 'center', borderRadius: radius.sm, borderWidth: 1.5 },
  locked: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  lockIcon: { fontSize: 44 },
  lockTitle: { fontSize: 18, fontWeight: '800', color: colors.ink, textAlign: 'center', writingDirection: 'rtl' },
  lockPrice: { fontSize: 15, color: colors.muted, marginBottom: 8 },
  selBar: { position: 'absolute', bottom: 12, alignSelf: 'center', flexDirection: 'row-reverse', alignItems: 'center', gap: 10, backgroundColor: colors.ink, borderRadius: 999, paddingHorizontal: 14, paddingVertical: 10, elevation: 6, shadowColor: '#000', shadowOpacity: 0.2, shadowRadius: 10 },
  swatch: { width: 28, height: 28, borderRadius: 14, borderWidth: 2, borderColor: '#fff' },
  selNote: { paddingHorizontal: 10 },
  selNoteText: { color: colors.lemon, fontWeight: '800' },
  toast: { position: 'absolute', top: 10, alignSelf: 'center', backgroundColor: colors.ink, borderRadius: 999, paddingHorizontal: 16, paddingVertical: 8 },
  toastText: { color: colors.ground, fontSize: 13 },
  quote: { fontSize: 15, lineHeight: 28, color: colors.ink, backgroundColor: '#FFE98A', borderRadius: 8, padding: 8 },
  noteInput: { minHeight: 110, borderWidth: 1.5, borderColor: colors.line, borderRadius: radius.sm, padding: 12, textAlign: 'right', textAlignVertical: 'top', writingDirection: 'rtl', fontSize: 15 },
  help: { fontSize: 13, color: colors.muted, lineHeight: 22 },
  noteRow: { gap: 6, paddingVertical: 8, borderBottomWidth: 1, borderBottomColor: colors.line },
  link: { color: colors.greenDark, fontWeight: '800', paddingVertical: 8 },
});
