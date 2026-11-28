/** One look for every section of the home page: the title on the right, a short note under it, and something small on
 * the left (a count, or the «۵ دقیقه» button). */
import type { ReactNode } from 'react';
import { StyleSheet, View } from 'react-native';

import { colors, rtl } from '../../theme';
import { IconBadge, type IconName } from '../Icon';
import { Text } from '../Text';

/** The same look as the stats page: an icon in a lemon circle beside the title (when given). */
export function SectionHeader({ title, sub, side, icon }: { title: string; sub?: string | null; side?: ReactNode; icon?: IconName }) {
  return (
    <View style={styles.row}>
      {!!icon && <IconBadge name={icon} size={30} />}
      <View style={{ flex: 1, gap: 1 }}>
        <Text style={[styles.title, rtl]} accessibilityRole="header">
          {title}
        </Text>
        {!!sub && <Text style={[styles.sub, rtl]}>{sub}</Text>}
      </View>
      {typeof side === 'string' ? <Text style={styles.side}>{side}</Text> : side}
    </View>
  );
}

const styles = StyleSheet.create({
  row: { flexDirection: 'row-reverse', alignItems: 'center', gap: 10 },
  title: { fontSize: 17, fontWeight: '900', color: colors.ink },
  sub: { fontSize: 12, color: colors.muted },
  side: { fontSize: 12, color: colors.muted },
});
