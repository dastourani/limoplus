import { StyleSheet, View } from 'react-native';

import { shelfLabel, type ShelfLabel } from '../lib/access';
import { colors } from '../theme';
import { Icon } from './Icon';
import { Text } from './Text';

const RIBBON: Record<
  ShelfLabel['kind'],
  { box: object; color: string; icon?: 'circle-check' | 'lock' | 'gift' | 'calendar' }
> = {
  soon: { box: { backgroundColor: '#8A938C' }, color: '#FFFFFF' },
  access: { box: { backgroundColor: '#3FB8A9' }, color: '#FFFFFF', icon: 'circle-check' },
  free: { box: { backgroundColor: colors.lemon }, color: colors.ink, icon: 'gift' },
  planning: { box: { backgroundColor: '#56655B' }, color: '#FFFFFF', icon: 'calendar' },
  locked: {
    box: { backgroundColor: colors.ink, borderWidth: 1, borderColor: 'rgba(245, 197, 24, 0.38)' },
    color: colors.ground,
    icon: 'lock',
  },
};

export type CoverRibbonBook = Parameters<typeof shelfLabel>[0];

/** Shared top-left cover label rendered identically on Home shelves and the Book detail hero. */
export function CoverRibbon({ book }: { book: CoverRibbonBook }) {
  const label = shelfLabel(book);
  const style = RIBBON[label.kind];
  return (
    <View style={[styles.ribbon, style.box]} pointerEvents="none">
      {style.icon && <Icon name={style.icon} size={12} color={style.color} />}
      <Text style={[styles.ribbonText, { color: style.color }]}>{label.text}</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  ribbon: {
    position: 'absolute',
    top: 12,
    left: -4,
    flexDirection: 'row-reverse',
    alignItems: 'center',
    gap: 4,
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderTopLeftRadius: 6,
    borderTopRightRadius: 6,
    borderBottomRightRadius: 6,
  },
  ribbonText: { fontSize: 11, fontWeight: '800' },
});
