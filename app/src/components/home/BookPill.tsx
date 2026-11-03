/**
 * One pill under every book on the shelves, the same size and shape for all; only its colour and icon say what it is:
 * the price (lemon), how much is read or «مال توست» (green), free (green, a gift), «خبرم کن» (white with a border: the
 * only pill that is a button) and, once asked, «خبرت می‌کنیم» (grey with a tick).
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

type Look = { icon: IconName; text: string; bg: string; fg: string; border?: string };

export function bookPillLook(book: BookListItem, notify: { on: boolean; canCancel: boolean }): Look {
  const green = { bg: '#E7F3EC', fg: colors.green };
  if (book.is_coming_soon)
    return notify.on
      ? { icon: 'check', text: 'خبرت می‌کنیم', bg: '#EEF1EA', fg: colors.muted }
      : { icon: 'bell', text: 'خبرم کن', bg: colors.surface, fg: colors.ink, border: colors.ink };
  if (book.progress != null && book.progress > 0 && (book.owned || book.all_free || !book.price))
    return { icon: 'circle-check', text: `${toPersianDigits(Math.round(book.progress * 100))}٪ خوانده‌شده`, ...green };
  if (book.owned) return { icon: 'circle-check', text: 'مال توست', ...green };
  if (book.all_free || !book.price) return { icon: 'gift', text: 'رایگان', ...green };
  return { icon: 'tag', text: shortToman(book.price), bg: '#FDF4D3', fg: '#7A5B00' };
}

export function BookPill({ book, notify, onNotify }: { book: BookListItem; notify: { on: boolean; canCancel: boolean }; onNotify: () => void }) {
  const look = bookPillLook(book, notify);
  const body = (
    <>
      <Icon name={look.icon} size={14} color={look.fg} />
      <Text style={[styles.text, { color: look.fg }]} numberOfLines={1}>{look.text}</Text>
    </>
  );
  const style = [styles.pill, { backgroundColor: look.bg }, look.border ? { borderColor: look.border, borderWidth: 1.5 } : null];
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
  pill: { alignSelf: 'center', height: 32, borderRadius: 999, paddingHorizontal: 12, flexDirection: 'row-reverse', alignItems: 'center', gap: 5, maxWidth: '100%' },
  text: { fontSize: 12, fontWeight: '800' },
});
