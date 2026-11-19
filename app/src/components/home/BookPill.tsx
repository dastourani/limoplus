/**
 * One button-shaped label under every book on the shelves, the same size and shape for all; only its colour and icon
 * say what it is. Only «خبرم کن» is a real button.
 */
import { Pressable, StyleSheet, View } from 'react-native';

import type { BookListItem } from '../../api/endpoints';
import { colors, toPersianDigits } from '../../theme';
import { currentPrice, percentLabel } from '../../lib/pricing';
import { Icon, type IconName } from '../Icon';
import { Text } from '../Text';

/** «۲۴۹ هزار تومان» rather than «۲۴۹٬۰۰۰ تومان»: short enough for one line under a cover. */
export function shortToman(price: number): string {
  if (price >= 1000 && price % 1000 === 0) return `${toPersianDigits((price / 1000).toLocaleString('en-US').replace(/,/g, '٬'))} هزار تومان`;
  return `${toPersianDigits(price.toLocaleString('en-US').replace(/,/g, '٬'))} تومان`;
}

type Look = { icon: IconName; text: string; bg: string; fg: string; border: string; discountPercent?: number };

/** Option «ب»: the old wide button for every state; free and owned green, the price soft lemon, «خبرم کن» white,
 * «خبرت می‌کنیم» lemon with a ringing bell. */
export function bookPillLook(book: BookListItem, notify: { on: boolean; canCancel: boolean }): Look {
  const price = currentPrice(book);
  const green = { bg: colors.greenSoft, fg: colors.greenDark, border: '#BFE2CC' };
  if (book.is_coming_soon)
    return notify.on
      ? { icon: 'bell-ring', text: 'خبرت می‌کنیم', bg: colors.lemonSoft, fg: colors.ink, border: colors.lemon }
      : { icon: 'bell', text: 'خبرم کن', bg: colors.surface, fg: colors.ink, border: colors.line };
  if (book.progress != null && book.progress > 0 && (book.owned || book.all_free || !price.price))
    return { icon: 'book-open', text: `${toPersianDigits(Math.round(book.progress * 100))}٪ خوانده‌شده`, ...green };
  if (book.owned) return { icon: 'circle-check', text: 'مال توست', ...green };
  if (book.all_free || !price.price) return { icon: 'gift', text: 'رایگان', ...green };
  return {
    icon: 'tag',
    text: shortToman(price.price),
    discountPercent: price.discount?.percent,
    bg: price.discount ? colors.redSoft : '#FDF4D3',
    fg: price.discount ? colors.redDark : '#7A5B00',
    border: price.discount ? '#EBC0BE' : '#F1DE94',
  };
}

export function BookPill({ book, notify, onNotify }: { book: BookListItem; notify: { on: boolean; canCancel: boolean }; onNotify: () => void }) {
  const look = bookPillLook(book, notify);
  const body = (
    <>
      <Icon name={look.icon} size={15} color={look.fg} />
      <View style={styles.labelLine}>
        <Text style={[styles.text, { color: look.fg }]} numberOfLines={1}>{look.text}</Text>
        {look.discountPercent != null && <Text style={styles.percent}>{percentLabel(look.discountPercent)}٪</Text>}
      </View>
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
  labelLine: { flex: 1, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 5, minWidth: 0 },
  text: { flexShrink: 1, fontSize: 12, fontWeight: '700' },
  percent: { overflow: 'hidden', borderRadius: 6, paddingHorizontal: 4, paddingVertical: 1, backgroundColor: colors.redDark, color: '#FFFFFF', fontSize: 10, fontWeight: '900' },
});
