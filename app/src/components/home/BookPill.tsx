/**
 * One button-shaped label under every book on the shelves, the same size and shape for all; only its colour and icon
 * say what it is. Only «خبرم کن» is a real button.
 *
 * The pill holds the price and nothing else: the free-preview label («۲ فصل رایگان») rides on the cover as a ribbon
 * (see `shelfLabel`), so it is not repeated here.
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

type Look = {
  icon: IconName;
  text: string;
  bg: string;
  fg: string;
  border: string;
  discountPercent?: number;
};

/** Option «ب»: the old wide button for every state; free and owned green, the price soft lemon, «خبرم کن» white,
 * «خبرت می‌کنیم» lemon with a ringing bell. Product categories come only from the API's product_status. */
export function bookPillLook(book: BookListItem, notify: { on: boolean; canCancel: boolean }): Look {
  const price = currentPrice(book);
  const state = book.product_status.state;
  const discounted = book.product_status.promotion === 'discount' && price.discount !== null;
  const green = { bg: colors.greenSoft, fg: colors.greenDark, border: '#BFE2CC' };
  const neutral = { bg: colors.surface, fg: colors.muted, border: colors.line };
  if (state === 'coming_soon')
    return notify.on
      ? { icon: 'bell-ring', text: 'خبرت می‌کنیم', bg: colors.lemonSoft, fg: colors.ink, border: colors.lemon }
      : { icon: 'bell', text: 'خبرم کن', bg: colors.surface, fg: colors.ink, border: colors.line };
  if (book.progress != null && book.progress > 0 && (book.owned || state === 'free'))
    return { icon: 'book-open', text: `${toPersianDigits(Math.round(book.progress * 100))}٪ خوانده‌شده`, ...green };
  if (book.owned) return { icon: 'circle-check', text: 'مال توست', ...green };
  if (state === 'free') return { icon: 'gift', text: 'رایگان', ...green };
  if (state === 'paid') {
    return {
      icon: 'tag',
      text: price.price == null ? 'قیمت در دسترس نیست' : shortToman(price.price),
      discountPercent: discounted ? price.discount?.percent : undefined,
      bg: discounted ? colors.redSoft : '#FDF4D3',
      fg: discounted ? colors.redDark : '#7A5B00',
      border: discounted ? '#EBC0BE' : '#F1DE94',
    };
  }
  if (state === 'preparing') return { icon: 'book-open', text: 'در حال آماده‌سازی', ...neutral };
  if (state === 'unpriced') return { icon: 'tag', text: 'قیمت تعیین نشده', ...neutral };
  return { icon: 'lock', text: 'در دسترس نیست', ...neutral };
}

export function BookPill({ book, notify, onNotify, onPress }: { book: BookListItem; notify: { on: boolean; canCancel: boolean }; onNotify: () => void; onPress?: () => void }) {
  const look = bookPillLook(book, notify);
  const body = (
    <View style={styles.labelLine}>
      <Icon name={look.icon} size={15} color={look.fg} />
      <Text style={[styles.text, { color: look.fg }]} numberOfLines={1}>{look.text}</Text>
      {look.discountPercent != null && <Text style={styles.percent}>{percentLabel(look.discountPercent)}٪</Text>}
    </View>
  );
  const style = [styles.pill, { backgroundColor: look.bg, borderColor: look.border }];
  if (book.product_status.state === 'coming_soon')
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
  // The cover is the link to the book; the button under it opens the same book («خبرم کن» stays the only real button).
  if (onPress)
    return (
      <Pressable onPress={onPress} style={({ pressed }) => [...style, pressed && { opacity: 0.75 }]} accessibilityRole="link">
        {body}
      </Pressable>
    );
  return <View style={style}>{body}</View>;
}

const styles = StyleSheet.create({
  pill: { alignSelf: 'stretch', minHeight: 38, borderRadius: 12, borderWidth: 1, paddingHorizontal: 8, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 6 },
  labelLine: { flex: 1, flexDirection: 'row-reverse', alignItems: 'center', justifyContent: 'center', gap: 5, minWidth: 0 },
  text: { flexShrink: 1, fontSize: 12, fontWeight: '700' },
  percent: { flexShrink: 0, overflow: 'hidden', borderRadius: 6, paddingHorizontal: 4, paddingVertical: 1, backgroundColor: colors.redDark, color: '#FFFFFF', fontSize: 10, fontWeight: '900' },
});
