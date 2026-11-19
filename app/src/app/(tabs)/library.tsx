import { router, useFocusEffect } from 'expo-router';
import { useCallback, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { endpoints, type Library, type LibraryBook, type LibraryShelfStatus } from '../../api/endpoints';
import { Text } from '../../components/Text';
import { Icon } from '../../components/Icon';
import { BookCover } from '../../components/BookCover';
import { LemonProgress, type PartState } from '../../components/LemonProgress';
import { Button, Card, Empty, ErrorState, Loading, Screen, usePullRefresh } from '../../components/ui';
import { ListRow } from '../../components/ListRow';
import { Pill } from '../../components/Pill';
import { useAuth } from '../../lib/auth';
import { useFeedback } from '../../components/Feedback';
import { QuoteView } from '../../components/QuoteView';
import { relativeDay } from '../../lib/jalali';
import { colors, radius, rtl, toPersianDigits } from '../../theme';

const TABS = [
  ['reading', 'در حال مطالعه'],
  ['books', 'کتاب‌ها'],
  ['bookmarks', 'نشان‌شده‌ها'],
  ['notes', 'یادداشت‌ها'],
] as const;

const BOOK_SHELVES: { id: LibraryShelfStatus; label: string }[] = [
  { id: 'reading', label: 'در حال مطالعه' },
  { id: 'later', label: 'بعداً' },
  { id: 'finished', label: 'تمام‌شده' },
];

/** Always shown, even empty: where wrong and blank answers gather (harmonized with TodayTiles & ReadingCards). */
function NotebookCard({ counts }: { counts?: Library['mistakes'] }) {
  const n = counts?.count ?? 0;
  const settling = counts?.settling ?? 0;
  const due = counts?.due ?? 0;
  const parts: PartState[] =
    n === 0
      ? ['empty']
      : Array.from({ length: Math.min(24, n) }, (_, i) => (i < Math.round((settling / Math.max(1, n)) * Math.min(24, n)) ? 'soft' : 'wrong'));
  const sub =
    n === 0
      ? 'تست‌های غلط و بی‌پاسخت این‌جا جمع می‌شوند.'
      : [counts!.open ? `${toPersianDigits(counts!.open)} منتظر جبران` : '', counts!.settling ? `${toPersianDigits(counts!.settling)} در حال تثبیت` : '']
          .filter(Boolean)
          .join('، ');
  return (
    <Pressable
      onPress={() => router.push('/mistakes')}
      style={({ pressed }) => [styles.notebookRow, pressed && { opacity: 0.9 }]}
      accessibilityRole="button"
      accessibilityLabel="اشتباهات من"
    >
      <LemonProgress parts={parts} size={44} />
      <View style={{ flex: 1, minWidth: 0, gap: 2 }}>
        <Text style={[styles.itemTitle, rtl]} numberOfLines={1}>اشتباهات من</Text>
        <Text style={[styles.muted, rtl]} numberOfLines={1}>{sub}</Text>
      </View>
      {due > 0 ? (
        <View style={styles.go}>
          <Text style={styles.goText}>مرور {toPersianDigits(due)} تست</Text>
        </View>
      ) : n > 0 ? (
        <View style={[styles.go, { backgroundColor: colors.ground, borderWidth: 1, borderColor: colors.line }]}>
          <Text style={styles.goText}>{toPersianDigits(n)} تست</Text>
        </View>
      ) : (
        <Icon name="chevron-left" size={18} color={colors.muted} />
      )}
    </Pressable>
  );
}

const NOTE_COLORS: Record<string, string> = { yellow: '#FFE98A', green: '#BFE8CF', blue: '#C9DBFF', pink: '#FFD0DF' };

function PersonalBookCard({
  item,
  hiddenView,
  index,
  count,
  busy,
  onStatus,
  onVisibility,
  onMove,
}: {
  item: LibraryBook;
  hiddenView: boolean;
  index: number;
  count: number;
  busy: boolean;
  onStatus: (status: LibraryShelfStatus) => void;
  onVisibility: (hidden: boolean) => void;
  onMove: (delta: -1 | 1) => void;
}) {
  const details = [
    item.book.major?.name,
    item.book.progress !== null && item.book.progress !== undefined
      ? `${toPersianDigits(Math.round(item.book.progress * 100))}٪ پیشرفت`
      : '',
  ].filter(Boolean).join(' · ');
  return (
    <Card style={styles.bookCard}>
      <Pressable
        onPress={() => router.push(`/book/${item.book.slug}`)}
        style={({ pressed }) => [styles.bookMain, pressed && { opacity: 0.8 }]}
        accessibilityRole="button"
        accessibilityLabel={`باز کردن کتاب ${item.book.title}`}
      >
        <BookCover book={item.book} major={item.book.major} width={54} edge />
        <View style={styles.bookCopy}>
          <Text style={[styles.itemTitle, rtl]} numberOfLines={2}>{item.book.title}</Text>
          {!!details && <Text style={[styles.muted, rtl]} numberOfLines={1}>{details}</Text>}
        </View>
        <Icon name="chevron-left" size={20} color={colors.muted} />
      </Pressable>
      {hiddenView ? (
        <View style={styles.hiddenActions}>
          <Text style={[styles.muted, rtl, { flex: 1 }]}>
            فقط از قفسه پنهان است؛ خرید، پیشرفت و حق دسترسی‌ات محفوظ مانده.
          </Text>
          <Pressable
            onPress={() => onVisibility(false)}
            disabled={busy}
            style={({ pressed }) => [styles.restore, busy && styles.actionDisabled, pressed && !busy && { opacity: 0.75 }]}
            accessibilityRole="button"
            accessibilityLabel={`بازگرداندن ${item.book.title} به قفسه`}
          >
            <Icon name="rotate-ccw" size={16} color={colors.greenDark} />
            <Text style={styles.restoreText}>بازگردانی</Text>
          </Pressable>
        </View>
      ) : (
        <View style={styles.bookActions}>
          <View style={styles.statusPills}>
            {BOOK_SHELVES.map((shelf) => (
              <Pill
                key={shelf.id}
                label={shelf.label}
                selected={item.status === shelf.id}
                onPress={() => onStatus(shelf.id)}
                small
                role="radio"
              />
            ))}
          </View>
          <View style={styles.bookActionBottom}>
            <View style={styles.moveButtons}>
              <Pressable
                onPress={() => onMove(-1)}
                disabled={busy || index === 0}
                style={({ pressed }) => [styles.moveButton, (busy || index === 0) && styles.actionDisabled, pressed && !busy && index > 0 && { opacity: 0.7 }]}
                accessibilityRole="button"
                accessibilityLabel={`جابجایی ${item.book.title} به بالای فهرست`}
              >
                <Icon name="chevron-up" size={17} color={colors.muted} />
              </Pressable>
              <Pressable
                onPress={() => onMove(1)}
                disabled={busy || index === count - 1}
                style={({ pressed }) => [styles.moveButton, (busy || index === count - 1) && styles.actionDisabled, pressed && !busy && index < count - 1 && { opacity: 0.7 }]}
                accessibilityRole="button"
                accessibilityLabel={`جابجایی ${item.book.title} به پایین فهرست`}
              >
                <Icon name="chevron-down" size={17} color={colors.muted} />
              </Pressable>
            </View>
            <Pressable
              onPress={() => onVisibility(true)}
              disabled={busy}
              style={({ pressed }) => [styles.hideButton, busy && styles.actionDisabled, pressed && !busy && { opacity: 0.7 }]}
              accessibilityRole="button"
              accessibilityLabel={`پنهان کردن ${item.book.title} از قفسه`}
            >
              <Text style={styles.hideText}>پنهان‌کردن</Text>
            </Pressable>
          </View>
        </View>
      )}
    </Card>
  );
}

export default function LibraryTab() {
  const { user } = useAuth();
  const [tab, setTab] = useState<(typeof TABS)[number][0]>('reading');
  const [data, setData] = useState<Library | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [bookShelf, setBookShelf] = useState<LibraryShelfStatus | 'hidden'>('reading');
  const [busyBookId, setBusyBookId] = useState<number | null>(null);
  const [reordering, setReordering] = useState(false);

  const load = useCallback(() => {
    if (!user) return;
    setLoading(true);
    endpoints
      .library()
      .then((d) => {
        setData(d);
        setError(null);
      })
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  }, [user]);
  useFocusEffect(load);
  const { toast } = useFeedback();

  const updateLibraryBook = async (bookId: number, patch: { status?: LibraryShelfStatus; hidden?: boolean }, message: string) => {
    if (reordering || busyBookId !== null) return;
    setBusyBookId(bookId);
    try {
      const saved = await endpoints.updateLibraryBook(bookId, patch);
      setData((current) => current ? {
        ...current,
        books: (current.books ?? []).map((item) => item.book_id === bookId
          ? { ...item, status: saved.status, hidden: saved.hidden, position: saved.position }
          : item),
      } : current);
      toast(message);
    } catch {
      toast('تغییر ذخیره نشد؛ اتصال را بررسی کنید و دوباره تلاش کنید.');
      load();
    } finally {
      setBusyBookId(null);
    }
  };

  const moveLibraryBook = async (shelf: LibraryShelfStatus, books: LibraryBook[], index: number, delta: -1 | 1) => {
    if (reordering || busyBookId !== null) return;
    const target = index + delta;
    if (target < 0 || target >= books.length) return;
    const reordered = [...books];
    const [moved] = reordered.splice(index, 1);
    reordered.splice(target, 0, moved);
    const positions = new Map(reordered.map((item, position) => [item.book_id, position]));
    setData((current) => current ? {
      ...current,
      books: (current.books ?? []).map((item) => positions.has(item.book_id)
        ? { ...item, position: positions.get(item.book_id)! }
        : item),
    } : current);
    setReordering(true);
    try {
      await endpoints.reorderLibrary(shelf, reordered.map((item) => item.book_id));
    } catch {
      toast('ترتیب ذخیره نشد؛ فهرست تازه می‌شود.');
      load();
    } finally {
      setReordering(false);
    }
  };

  // × on a note: gone at once, with «برگرداندن» for a few seconds (the server only archives it).
  const removeNote = async (n: Library['notes'][number]) => {
    try {
      await endpoints.deleteNote(n.id);
    } catch {
      toast('حذف نشد. اتصال اینترنت را بررسی کنید.');
      return;
    }
    setData((d) => (d ? { ...d, notes: d.notes.filter((x) => x.id !== n.id) } : d));
    toast(n.quote && !n.body ? 'هایلایت حذف شد.' : 'یادداشت حذف شد.', {
      label: 'برگرداندن',
      onPress: () => {
        endpoints
          .addNote(n.node_id, { quote: n.quote, body: n.body, color: n.color, mode: n.mode })
          .then(() => load())
          .catch(() => toast('برگرداندن ممکن نشد.'));
      },
    });
  };
  const refresh = usePullRefresh(loading, load);
  const hiddenView = bookShelf === 'hidden';
  const shelfBooks = (data?.books ?? [])
    .filter((item) => hiddenView ? item.hidden : !item.hidden && item.status === bookShelf)
    .sort((a, b) => a.position - b.position);
  const hiddenBookCount = data?.books?.filter((item) => item.hidden).length ?? 0;
  const shelfCount = (shelf: LibraryShelfStatus) => data?.books?.filter((item) => !item.hidden && item.status === shelf).length ?? 0;

  if (!user) {
    return (
      <Screen tab desktopMax={1600}>
        <Text style={[styles.title, rtl]}>کتابخانه‌ی من</Text>
        <Empty
          icon="library-big"
          title="کتابخانه‌ات اینجاست"
          text="بعد از ورود، کتاب‌هایی که می‌خوانی، بخش‌های نشان‌شده و یادداشت‌هایت اینجا جمع می‌شوند و روی همه‌ی دستگاه‌هایت هست."
          action={<Button label="ورود یا ثبت‌نام" onPress={() => router.push('/login')} style={{ alignSelf: 'stretch' }} />}
        />
      </Screen>
    );
  }

  return (
    <Screen tab desktopMax={1600}>
      <Text style={[styles.title, rtl]}>کتابخانه‌ی من</Text>
      <View style={styles.tabs}>
        {TABS.map(([key, label]) => (
          <Pill key={key} label={label} selected={tab === key} onPress={() => setTab(key)} role="tab" />
        ))}
      </View>
      {!data ? (
        error ? <ErrorState message={error} onRetry={load} /> : <Loading />
      ) : (
        <ScrollView contentContainerStyle={styles.page} refreshControl={refresh}>
          <NotebookCard counts={data.mistakes} />
          {tab === 'reading' &&
            (data!.reading.length === 0 ? (
              <Empty title="هنوز کتابی را شروع نکرده‌ای" text="از صفحه‌ی خانه یک کتاب باز کن." />
            ) : (
              data!.reading.map((r) => (
                <ListRow
                  key={r.book_slug}
                  icon="book-open"
                  title={r.book_title}
                  subtitle={`آخرین بخش: ${r.last_section.title}، ${relativeDay(r.updated_at)}`}
                  onPress={() => router.push(`/book/${r.book_slug}`)}
                  value={
                    <Pressable onPress={() => router.push(`/section/${r.last_section.id}`)} style={styles.go} accessibilityRole="button" accessibilityLabel={`ادامه‌ی ${r.book_title}`}>
                      <Text style={styles.goText}>ادامه</Text>
                    </Pressable>
                  }
                />
              ))
            ))}
          {tab === 'books' && (
            <View style={styles.booksTab}>
              <View style={styles.shelfFilters}>
                {BOOK_SHELVES.map((shelf) => (
                  <Pill
                    key={shelf.id}
                    label={`${shelf.label} · ${toPersianDigits(shelfCount(shelf.id))}`}
                    selected={bookShelf === shelf.id}
                    onPress={() => setBookShelf(shelf.id)}
                    small
                    role="tab"
                  />
                ))}
                <Pill
                  label={`پنهان‌شده‌ها · ${toPersianDigits(hiddenBookCount)}`}
                  selected={hiddenView}
                  onPress={() => setBookShelf('hidden')}
                  small
                  role="tab"
                />
              </View>
              {shelfBooks.length === 0 ? (
                <Empty
                  icon="library-big"
                  title={hiddenView ? 'کتاب پنهان‌شده‌ای نداری' : 'این قفسه هنوز خالی است'}
                  text={hiddenView ? 'کتاب‌هایی که پنهان می‌کنی، بدون حذف خرید یا دسترسی، اینجا برای بازگرداندن می‌مانند.' : 'کتاب‌های رایگان، خریداری‌شده و دسترسی‌های فعال گروهی به‌طور خودکار اینجا می‌آیند.'}
                />
              ) : (
                shelfBooks.map((item, index) => (
                  <PersonalBookCard
                    key={item.book_id}
                    item={item}
                    hiddenView={hiddenView}
                    index={index}
                    count={shelfBooks.length}
                    busy={busyBookId !== null || reordering}
                    onStatus={(next) => { if (item.status !== next) void updateLibraryBook(item.book_id, { status: next }, `به قفسه‌ی «${BOOK_SHELVES.find((s) => s.id === next)?.label ?? ''}» منتقل شد.`); }}
                    onVisibility={(hidden) => void updateLibraryBook(item.book_id, { hidden }, hidden ? 'کتاب از قفسه پنهان شد؛ دسترسی‌ات محفوظ است.' : 'کتاب به قفسه‌ی قبلی برگشت.')}
                    onMove={(delta) => {
                      if (bookShelf !== 'hidden') void moveLibraryBook(bookShelf, shelfBooks, index, delta);
                    }}
                  />
                ))
              )}
            </View>
          )}
          {tab === 'bookmarks' &&
            (data!.bookmarks.length === 0 ? (
              <Empty icon="bookmark" title="بخشی نشان نکرده‌ای" text="در صفحه‌ی درس، دکمه‌ی نشان را بزن تا اینجا بیاید." />
            ) : (
              data!.bookmarks.map((b) => (
                <ListRow key={b.id} icon="bookmark" title={b.title} subtitle={relativeDay(b.created_at)} onPress={() => router.push(`/section/${b.id}`)} chevron />
              ))
            ))}
          {tab === 'notes' &&
            (data!.notes.length === 0 ? (
              <Empty icon="notebook-pen" title="یادداشتی نداری" text="در صفحه‌ی درس متنی را انتخاب کن تا هایلایت یا یادداشت بگذاری." />
            ) : (
              data!.notes.map((n) => (
                <Pressable key={n.id} onPress={() => router.push(`/section/${n.node_id}`)}>
                  <Card>
                    <View style={styles.noteHead}>
                      <Text style={[styles.muted, rtl, { flex: 1 }]}>{n.node_title}، {relativeDay(n.updated_at)}</Text>
                      <Pressable onPress={() => removeNote(n)} hitSlop={10} style={styles.noteX} accessibilityRole="button" accessibilityLabel="حذف">
                        <Icon name="x" size={18} color={colors.muted} />
                      </Pressable>
                    </View>
                    {!!n.quote && <QuoteView quote={n.quote} color={NOTE_COLORS[n.color] ?? NOTE_COLORS.yellow} maxHeight={160} />}
                    {!!n.body && <Text selectable style={[styles.body, rtl]}>{n.body}</Text>}
                  </Card>
                </Pressable>
              ))
            ))}
        </ScrollView>
      )}
    </Screen>
  );
}

const styles = StyleSheet.create({
  notebookRow: {
    flexDirection: 'row-reverse',
    alignItems: 'center',
    gap: 12,
    padding: 14,
    backgroundColor: colors.surface,
    borderRadius: radius.md,
    borderWidth: 1,
    borderColor: colors.line,
  },
  booksTab: { gap: 12 },
  shelfFilters: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 6 },
  bookCard: { gap: 10, padding: 12 },
  bookMain: { flexDirection: 'row-reverse', alignItems: 'center', gap: 12 },
  bookCopy: { flex: 1, minWidth: 0, gap: 4 },
  bookActions: { gap: 8 },
  statusPills: { flexDirection: 'row-reverse', flexWrap: 'wrap', gap: 6 },
  bookActionBottom: { flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'space-between', gap: 10 },
  moveButtons: { flexDirection: 'row-reverse', alignItems: 'center', gap: 4 },
  moveButton: { width: 34, height: 30, borderRadius: 8, borderWidth: 1, borderColor: colors.line, alignItems: 'center', justifyContent: 'center' },
  actionDisabled: { opacity: 0.4 },
  hideButton: { minHeight: 32, paddingHorizontal: 12, borderRadius: 9, backgroundColor: colors.ground, borderWidth: 1, borderColor: colors.line, alignItems: 'center', justifyContent: 'center' },
  hideText: { fontSize: 12, fontWeight: '700', color: colors.muted },
  hiddenActions: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10, borderTopWidth: 1, borderTopColor: colors.line, paddingTop: 9 },
  restore: { flexDirection: 'row-reverse', alignItems: 'center', gap: 5, minHeight: 34, paddingHorizontal: 10, borderRadius: 9, backgroundColor: colors.greenSoft },
  restoreText: { color: colors.greenDark, fontSize: 12, fontWeight: '800' },
  go: { backgroundColor: colors.lemon, borderRadius: 10, paddingHorizontal: 14, paddingVertical: 7 },
  goText: { fontSize: 12, fontWeight: '800', color: colors.ink },
  // The four tabs start alike: the page title 12 from the top, on the 16 margin.
  title: { fontSize: 22, fontWeight: '800', color: colors.ink, paddingHorizontal: 16, paddingTop: 12 },
  tabs: { flexDirection: 'row-reverse', gap: 8, paddingHorizontal: 16, paddingVertical: 12 },
  page: { padding: 16, paddingTop: 0, gap: 12 },
  itemTitle: { fontSize: 15, fontWeight: '800', color: colors.ink },
  muted: { fontSize: 12, color: colors.muted },
  quote: { fontSize: 15, lineHeight: 28, color: colors.ink, borderRadius: 8, padding: 8 },
  body: { fontSize: 15, lineHeight: 24, color: colors.ink },
  noteHead: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8 },
  noteX: { width: 32, height: 32, borderRadius: 16, alignItems: 'center', justifyContent: 'center', marginVertical: -6 },
});
