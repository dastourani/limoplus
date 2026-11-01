import { router, useLocalSearchParams } from 'expo-router';
import { useEffect, useRef, useState } from 'react';
import { Pressable, ScrollView, StyleSheet, View } from 'react-native';

import { endpoints, type SearchResult } from '../api/endpoints';
import { Icon, type IconName } from '../components/Icon';
import { Text, TextInput } from '../components/Text';
import { Header, Loading, Screen } from '../components/ui';
import { colors, rtl, toPersianDigits } from '../theme';

type Kind = SearchResult['kind'] | 'all';
const TABS: [Kind, string][] = [
  ['all', 'همه'],
  ['section', 'جزوه'],
  ['question', 'تست'],
  ['flashcard', 'فلش‌کارت'],
  ['note', 'یادداشت'],
];
const KIND: Record<SearchResult['kind'], { icon: IconName; label: string }> = {
  section: { icon: 'book-open', label: 'جزوه' },
  question: { icon: 'clipboard-list', label: 'تست' },
  flashcard: { icon: 'layers', label: 'فلش‌کارت' },
  note: { icon: 'notebook-pen', label: 'یادداشت من' },
};

/** Search in what the learner may read: notes and summaries, questions, flashcards and their own notes. */
export default function SearchScreen() {
  const { book, bookTitle } = useLocalSearchParams<{ book?: string; bookTitle?: string }>();
  const [q, setQ] = useState('');
  const [tab, setTab] = useState<Kind>('all');
  const [results, setResults] = useState<SearchResult[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [short, setShort] = useState(false);
  const seq = useRef(0);

  // Searches a moment after typing stops; an older answer arriving late is ignored.
  useEffect(() => {
    const text = q.trim();
    if (text.length < 2) {
      setResults(null);
      setShort(text.length > 0);
      return;
    }
    const n = ++seq.current;
    const t = setTimeout(() => {
      setBusy(true);
      endpoints
        .search(text, book ?? '')
        .then((r) => {
          if (n !== seq.current) return;
          setShort(!!r.too_short);
          setResults(r.results);
        })
        .catch(() => n === seq.current && setResults([]))
        .finally(() => n === seq.current && setBusy(false));
    }, 350);
    return () => clearTimeout(t);
  }, [q, book]);

  const open = (r: SearchResult) => {
    if (r.kind === 'section' || r.kind === 'note')
      router.push({ pathname: '/section/[id]', params: { id: String(r.node_id), find: r.match, mode: r.mode ?? 'full' } });
    else if (r.kind === 'question') router.push({ pathname: '/quiz/[nodeId]', params: { nodeId: String(r.node_id), q: String(r.id) } });
    else router.push(`/flashcards/${r.node_id}`);
  };

  const shown = (results ?? []).filter((r) => tab === 'all' || r.kind === tab);
  const count = (k: Kind) => (results ?? []).filter((r) => k === 'all' || r.kind === k).length;

  return (
    <Screen>
      <Header title={bookTitle ? `جست‌وجو در ${bookTitle}` : 'جست‌وجو'} />
      <View style={styles.box}>
        <Icon name="search" size={20} color={colors.muted} />
        <TextInput
          value={q}
          onChangeText={setQ}
          placeholder="یک کلمه یا عبارت؛ مثلاً «حد چپ»"
          autoFocus
          returnKeyType="search"
          style={styles.input}
          accessibilityLabel="جست‌وجو"
        />
        {!!q && (
          <Pressable onPress={() => setQ('')} hitSlop={8} accessibilityLabel="پاک کردن">
            <Icon name="x" size={18} color={colors.muted} />
          </Pressable>
        )}
      </View>
      {results && results.length > 0 && (
        <ScrollView horizontal showsHorizontalScrollIndicator={false} style={{ transform: [{ scaleX: -1 }], flexGrow: 0 }} contentContainerStyle={styles.tabs}>
          {TABS.filter(([k]) => k === 'all' || count(k) > 0).map(([k, label]) => (
            <Pressable key={k} onPress={() => setTab(k)} style={[styles.tab, tab === k && styles.tabOn, { transform: [{ scaleX: -1 }] }]} accessibilityRole="tab" accessibilityState={{ selected: tab === k }}>
              <Text style={[styles.tabText, tab === k && { color: colors.lemon }]}>
                {label} {toPersianDigits(count(k))}
              </Text>
            </Pressable>
          ))}
        </ScrollView>
      )}
      {busy && !results ? (
        <Loading />
      ) : (
        <ScrollView contentContainerStyle={styles.list} keyboardShouldPersistTaps="handled">
          {short && <Text style={[styles.hint, rtl]}>دست‌کم دو حرف بنویس.</Text>}
          {results && results.length === 0 && <Text style={[styles.hint, rtl]}>چیزی پیدا نشد. کلمه‌ی کوتاه‌تر یا هم‌معنی را امتحان کن.</Text>}
          {!results && !short && (
            <Text style={[styles.hint, rtl]}>«ي/ی»، «ك/ک»، نیم‌فاصله و فاصله مهم نیست؛ «میشود»، «می شود» و «می‌شود» یکی‌اند.</Text>
          )}
          {shown.map((r) => (
            <Pressable key={`${r.kind}-${r.id}`} onPress={() => open(r)} style={styles.row} accessibilityRole="button">
              <View style={styles.rowHead}>
                <Icon name={KIND[r.kind].icon} size={15} color={colors.greenDark} />
                <Text style={[styles.kind, rtl]} numberOfLines={1}>
                  {KIND[r.kind].label}
                  {r.kind === 'section' && r.mode === 'summary' ? '، خلاصه' : ''}، {r.title}
                  {r.book_title ? `، ${r.book_title}` : ''}
                </Text>
              </View>
              <Text style={[styles.snippet, rtl]} numberOfLines={3}>
                {highlight(r.snippet, r.match)}
              </Text>
            </Pressable>
          ))}
        </ScrollView>
      )}
    </Screen>
  );
}

/** The matched words in bold inside the snippet. */
function highlight(snippet: string, match: string) {
  const at = match ? snippet.indexOf(match) : -1;
  if (at < 0) return snippet;
  return (
    <>
      {snippet.slice(0, at)}
      <Text style={styles.mark}>{match}</Text>
      {snippet.slice(at + match.length)}
    </>
  );
}

const styles = StyleSheet.create({
  box: { flexDirection: 'row-reverse', alignItems: 'center', gap: 8, marginHorizontal: 16, marginBottom: 8, paddingHorizontal: 14, borderRadius: 16, borderWidth: 1.5, borderColor: colors.line, backgroundColor: colors.surface },
  input: { flex: 1, minHeight: 48, fontSize: 16, textAlign: 'right', writingDirection: 'rtl' },
  tabs: { gap: 8, paddingHorizontal: 16, paddingBottom: 8 },
  tab: { paddingHorizontal: 12, paddingVertical: 6, borderRadius: 999, borderWidth: 1.5, borderColor: colors.line, backgroundColor: colors.surface },
  tabOn: { backgroundColor: colors.ink, borderColor: colors.ink },
  tabText: { fontSize: 13, fontWeight: '700', color: colors.ink },
  list: { padding: 16, paddingTop: 4, gap: 10 },
  hint: { fontSize: 13, color: colors.muted, lineHeight: 22 },
  row: { backgroundColor: colors.surface, borderRadius: 16, borderWidth: 1, borderColor: colors.line, padding: 12, gap: 6 },
  rowHead: { flexDirection: 'row-reverse', alignItems: 'center', gap: 6 },
  kind: { flex: 1, fontSize: 12, fontWeight: '700', color: colors.greenDark },
  snippet: { fontSize: 14, color: colors.ink, lineHeight: 24 },
  mark: { backgroundColor: '#FFE98A', fontWeight: '800' },
});
