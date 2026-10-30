import { router, useLocalSearchParams } from 'expo-router';
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Pressable, StyleSheet, View } from 'react-native';

import { ApiError } from '../../api/client';
import { endpoints, type NodeDetail, type Note } from '../../api/endpoints';
import { MarkdownView, type MarkdownViewHandle, type ReaderEvent } from '../../components/MarkdownView';
import { ReportSheet } from '../../components/ReportSheet';
import { Text, TextInput } from '../../components/Text';
import { Icon, IconBadge } from '../../components/Icon';
import { Button, ErrorState, Header, Loading, Screen, Sheet } from '../../components/ui';
import { Watermark } from '../../components/Watermark';
import { useFeedback } from '../../components/Feedback';
import { requireLogin, useAuth } from '../../lib/auth';
import { sendOrQueue } from '../../lib/network';
import { offlineBooks, offlineSection } from '../../lib/offline';
import { storage } from '../../lib/storage';
import { colors, formatToman, radius, rtl } from '../../theme';

const NOTE_COLORS: [string, string][] = [
  ['yellow', '#FFE98A'],
  ['green', '#BFE8CF'],
  ['blue', '#C9DBFF'],
  ['pink', '#FFD0DF'],
];

type Locked = { title?: string; price?: number | null; slug?: string };

export default function Section() {
  const { id } = useLocalSearchParams<{ id: string }>();
  const nodeId = Number(id);
  const { user } = useAuth();
  const reader = useRef<MarkdownViewHandle>(null);

  const [node, setNode] = useState<NodeDetail | null>(null);
  const [offline, setOffline] = useState(false);
  const [locked, setLocked] = useState<Locked | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(true);

  const [mode, setMode] = useState<'full' | 'summary'>('full');
  const [fontSize, setFontSize] = useState(17);
  const [dark, setDark] = useState(false);
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
        setDark(p.dark);
      }
    });
  }, [load]);

  useEffect(() => {
    if (!node) return;
    const book = node.breadcrumb[0];
    storage.setLastSection({ id: node.id, title: node.title, bookTitle: book?.title ?? '', bookSlug: book?.slug ?? '' });
    setMode('full');
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

  const savePrefs = (next: { fontSize?: number; dark?: boolean }) => {
    const prefs = { fontSize: next.fontSize ?? fontSize, dark: next.dark ?? dark };
    setFontSize(prefs.fontSize);
    setDark(prefs.dark);
    storage.setReader(prefs);
  };

  const onEvent = (e: ReaderEvent) => {
    if (e.type === 'selection') setSelection(e.text.trim());
    else if (e.type === 'copy_blocked') flash('کپی متن طولانی مجاز نیست.');
    else if (e.type === 'highlights') setMissing(e.missing);
    else if (e.type === 'note') {
      const n = notes.find((x) => x.id === e.id);
      if (n) {
        setNoteText(n.body);
        setNoteSheet({ note: n });
      }
    } else if (e.type === 'scroll' && user && node && !offline && mode === 'full') {
      const p = progress.current;
      if (e.percent >= p.sent + 10 || (e.percent >= 90 && !p.done)) {
        p.sent = Math.max(p.sent, e.percent);
        p.done = p.done || e.percent >= 90;
        sendOrQueue(`nodes/${node.id}/progress/`, { percent: e.percent, done: false });
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

  const saveNote = async () => {
    if (!node || !noteSheet) return;
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

  const toggleBookmark = async () => {
    if (!node || !requireLogin(user, 'برای نشان کردن بخش‌ها وارد شوید.')) return;
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
    }
  };

  if (loading) return <Screen><Header /><Loading /></Screen>;

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
  const body = mode === 'summary' && node.summary ? node.summary : node.full;
  const paper = dark ? '#121614' : colors.paper;
  const ink = dark ? '#E4E9E2' : colors.ink;
  const missingNotes = notes.filter((n) => missing.includes(n.id) && n.mode === mode);

  return (
    <Screen background={paper}>
      <View style={styles.header}>
        <Pressable onPress={() => (router.canGoBack() ? router.back() : router.replace('/home'))} style={styles.icon} accessibilityLabel="بازگشت">
          <Icon name="arrow-right" size={24} color={ink} />
        </Pressable>
        <View style={{ flex: 1 }}>
          <Text style={[styles.sub, rtl]} numberOfLines={1}>{offline ? `آفلاین · ${chapter?.title ?? ''}` : chapter?.title}</Text>
          <Text style={[styles.title, rtl, { color: ink }]} numberOfLines={1}>{node.title}</Text>
        </View>
        <Pressable onPress={toggleBookmark} style={styles.icon} accessibilityLabel="نشان کردن">
          <Icon name={bookmarked ? 'bookmark-check' : 'bookmark'} size={22} color={bookmarked ? colors.lemon : ink} />
        </Pressable>
        <Pressable onPress={() => setNotesOpen(true)} style={styles.icon} accessibilityLabel="یادداشت‌ها">
          <Icon name="notebook-pen" size={22} color={ink} />
          {notes.length > 0 && <Text style={styles.count}>{notes.length}</Text>}
        </Pressable>
        <Pressable onPress={() => savePrefs({ fontSize: fontSize >= 23 ? 15 : fontSize + 2 })} style={styles.icon} accessibilityLabel="اندازه‌ی متن">
          <Icon name="a-large-small" size={24} color={ink} />
        </Pressable>
        <Pressable onPress={() => savePrefs({ dark: !dark })} style={styles.icon} accessibilityLabel="حالت شب">
          <Icon name={dark ? 'sun' : 'moon'} size={22} color={ink} />
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

      <View style={{ flex: 1 }}>
        <MarkdownView ref={reader} markdown={body} fontSize={fontSize} dark={dark} highlights={highlights} onEvent={onEvent} />
        <Watermark text={user?.phone || 'لیمو پلاس'} dark={dark} />
        {!!selection && (
          <View style={styles.selBar}>
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
        <Button label="تست‌ها" variant={dark ? 'primary' : 'outline'} onPress={() => router.push(`/quiz/${node.id}`)} style={{ flex: 1 }} />
        <Button label="فلش‌کارت" variant={dark ? 'primary' : 'outline'} onPress={() => router.push(`/flashcards/${node.id}`)} style={{ flex: 1 }} />
        {node.next_id ? (
          <Button
            label="بخش بعد"
            variant="dark"
            onPress={() => {
              if (user && !offline && !progress.current.done) sendOrQueue(`nodes/${node.id}/progress/`, { percent: 100, done: true });
              router.replace(`/section/${node.next_id}`);
            }}
            style={{ flex: 1.2 }}
          />
        ) : null}
      </View>

      <Sheet visible={!!noteSheet} onClose={closeNoteSheet} title={noteSheet?.note ? 'یادداشت' : 'یادداشت تازه'}>
        {!!(noteSheet?.note?.quote || noteSheet?.quote) && <Text style={[styles.quote, rtl]}>{noteSheet?.note?.quote || noteSheet?.quote}</Text>}
        <TextInput value={noteText} onChangeText={setNoteText} multiline placeholder="یادداشت شما…" style={styles.noteInput} maxLength={5000} />
        <Button label="ذخیره" onPress={saveNote} />
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
        <Pressable onPress={() => (setNotesOpen(false), requireLogin(user, 'برای گزارش اشکال وارد شوید.') && setReportOpen(true))}>
          <Text style={[styles.link, rtl]}>{reported ? 'اشکال این بخش گزارش داده شد' : 'گزارش اشکال در متن این بخش'}</Text>
        </Pressable>
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
  header: { flexDirection: 'row-reverse', alignItems: 'center', paddingHorizontal: 6, paddingVertical: 4 },
  icon: { width: 40, height: 44, alignItems: 'center', justifyContent: 'center' },
  count: { position: 'absolute', top: 4, left: 2, minWidth: 18, height: 18, borderRadius: 8, backgroundColor: colors.lemon, color: colors.ink, fontSize: 12, textAlign: 'center', overflow: 'hidden' },
  iconText: { fontSize: 22, fontWeight: '800' },
  sub: { fontSize: 12, color: colors.muted },
  title: { fontSize: 16, fontWeight: '800' },
  toggle: { flexDirection: 'row-reverse', alignSelf: 'center', backgroundColor: colors.disabled, borderRadius: 999, padding: 3, marginBottom: 6 },
  toggleItem: { paddingHorizontal: 22, paddingVertical: 7, borderRadius: 999 },
  toggleOn: { backgroundColor: colors.ink },
  toggleText: { fontWeight: '700', color: colors.muted },
  toggleTextOn: { color: colors.lemon },
  bar: { flexDirection: 'row-reverse', gap: 8, padding: 12, borderTopWidth: 1 },
  locked: { flex: 1, alignItems: 'center', justifyContent: 'center', padding: 28, gap: 12 },
  lockIcon: { fontSize: 44 },
  lockTitle: { fontSize: 18, fontWeight: '800', color: colors.ink, textAlign: 'center', writingDirection: 'rtl' },
  lockPrice: { fontSize: 16, color: colors.muted, marginBottom: 8 },
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
