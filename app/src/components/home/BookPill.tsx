/**
 * One button-shaped label under every book on the shelves, the same size and shape for all; only its colour and icon
 * say what it is. Only «خبرم کن» is a real button.
 */
import { Pressable, StyleSheet, View } from 'react-native';

import type { BookListItem } from '../../api/endpoints';
import { colors, toPersianDigits } from '../../theme';
import { Icon, type IconName } from '../Icon';
import { Text } from '../Text';

/** «۲۴۹ هزار تومان» rather than «۲۴۹٬۰۰۰ تومان»: short enough for one line under a cover. */
export function shortToman(price: number): string {
  if (price >= 1000 && price % 1000 === 0) return `${toPersianDigits((price / 1000).toLocaleString('en-US').replace(/,/g, '٬'))} هزار تومان`;
  return `${toPersianDigits(price.toLocaleString('en-US').replace(/,/g, '٬'))} تومان`;
}

type Look = { icon: IconName; text: string; bg: string; fg: string; border: string };

/** Option «ب»: the old wide button for every state; free and owned green, the price soft lemon, «خبرم کن» white,
 * «خبرت می‌کنیم» lemon with a ringing bell. */
export function bookPillLook(book: BookListItem, notify: { on: boolean; canCancel: boolean }): Look {
  const green = { bg: colors.greenSoft, fg: colors.greenDark, border: '#BFE2CC' };
  if (book.is_coming_soon)
    return notify.on
      ? { icon: 'bell-ring', text: 'خبرت می‌کنیم', bg: colors.lemonSoft, fg: colors.ink, border: colors.lemon }
      : { icon: 'bell', text: 'خبرم کن', bg: colors.surface, fg: colors.ink, border: colors.line };
  if (book.progress != null && book.progress > 0 && (book.owned || book.all_free || !book.price))
    return { icon: 'book-open', text: `${toPersianDigits(Math.round(book.progress * 100))}٪ خوانده‌شده`, ...green };
  if (book.owned) return { icon: 'circle-check', text: 'مال توست', ...green };
  if (book.all_free || !book.price) return { icon: 'gift', text: 'رایگان', ...green };
  return { icon: 'tag', text: shortToman(book.price), bg: '#FDF4D3', fg: '#7A5B00', border: '#F1DE94' };
}

export function BookPill({ book, notify, onNotify }: { book: BookListItem; notify: { on: boolean; canCancel: boolean }; onNotify: () => void }) {
  const look = bookPillLook(book, notify);
  const body = (
    <>
      <Icon name={look.icon} size={15} color={look.fg} />
      <Text style={[styles.text, { color: look.fg }]} numberOfLines={1}>{look.text}</Text>
    </>
  );
  const style = [styles.pill, { backgroundColor: look.bg, borderColor: look.border }];
  if (book.is_coming_soon)
    return (
      <Pressable
        onPress={onNotify}
        disabled={notify.on && !notify.canCancel}
        style={({ pressed }) => [...style, pressed && { opacity: 0.7 }]}
        accessibilityRole="button"
        accessibilityState={{ selected: notify.on }}
        accessibilityLabel={notify.on ? (notify.canCancel ? 'خبرت می‌کنیم؛ برای لغو بزنید' : 'خبرت می‌کنیم') : 'خبرم کن'}
      >
        {body}
      </Pressable>
    );
  return <View style={style}>{body}</View>;
}

const styles = StyleSheet.create({
  pill: { alignSelf: 'stretch', minHeight: 38, borderRadius: 12, borderWidth: 1, paddingHorizontal: 8, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6 },
  text: { fontSize: 12, fontWeight: '700' },
});
