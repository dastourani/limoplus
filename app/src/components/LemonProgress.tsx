/**
 * Progress drawn as a cut lemon: one wedge per item (question, card, section). Wedges fill with juice as items are
 * done; in practice a wrong answer shows as a pink wedge. With many items, neighbouring items share a wedge.
 */
import { useEffect, useRef } from 'react';
import { Animated, Pressable, View } from 'react-native';
import Svg, { Circle, G, Path } from 'react-native-svg';

export type PartState = 'empty' | 'done' | 'soft' | 'wrong';

const MAX_WEDGES = 24;
const FILL: Record<PartState | 'partial', string> = {
  empty: '#ECE3C2',
  partial: '#FFE27A',
  soft: '#FFDB5C',
  done: '#FFC414',
  wrong: '#F28B82',
};

function point(r: number, deg: number) {
  const a = ((deg - 90) * Math.PI) / 180;
  return `${(r * Math.cos(a)).toFixed(2)} ${(r * Math.sin(a)).toFixed(2)}`;
}

function wedgePath(i: number, n: number) {
  const step = 360 / n;
  const gap = Math.min(4.5, step / 5);
  // Clockwise from the top; mirrored for right-to-left reading order (first item at the top, going right-to-left).
  const a0 = -(i + 1) * step + gap;
  const a1 = -i * step - gap;
  const inner = n > 16 ? 16 : 13;
  const outer = 74;
  const mid = (a0 + a1) / 2;
  return `M ${point(inner, mid)} L ${point(outer, a0)} A ${outer} ${outer} 0 0 1 ${point(outer, a1)} Z`;
}

/** Squeeze many items into at most MAX_WEDGES wedges. */
function group(parts: PartState[]): (PartState | 'partial')[] {
  if (parts.length <= MAX_WEDGES) return parts;
  const out: (PartState | 'partial')[] = [];
  for (let w = 0; w < MAX_WEDGES; w++) {
    const slice = parts.slice(Math.floor((w * parts.length) / MAX_WEDGES), Math.floor(((w + 1) * parts.length) / MAX_WEDGES));
    const filled = slice.filter((p) => p !== 'empty');
    if (filled.length === 0) out.push('empty');
    else if (filled.length < slice.length) out.push('partial');
    else out.push(filled.filter((p) => p === 'wrong').length * 2 > filled.length ? 'wrong' : 'done');
  }
  return out;
}

export function LemonProgress({
  parts,
  value,
  segments = 10,
  current,
  size = 56,
  onPress,
  accessibilityLabel,
}: {
  /** One state per item. */
  parts?: PartState[];
  /** Or a share between 0 and 1, drawn over `segments` wedges. */
  value?: number;
  segments?: number;
  /** Item being worked on now (outlined). */
  current?: number;
  size?: number;
  onPress?: () => void;
  accessibilityLabel?: string;
}) {
  const items: PartState[] =
    parts ?? Array.from({ length: segments }, (_, i) => ((value ?? 0) * segments >= i + 1 - 1e-6 ? 'done' : (value ?? 0) * segments > i ? 'soft' : 'empty'));
  const wedges = group(items);
  const n = Math.max(1, wedges.length);
  const currentWedge = current == null || current < 0 ? -1 : items.length > MAX_WEDGES ? Math.floor((current * MAX_WEDGES) / items.length) : current;
  const filledCount = items.filter((p) => p !== 'empty').length;

  // A little squeeze each time a wedge fills.
  const pop = useRef(new Animated.Value(1)).current;
  const last = useRef(filledCount);
  useEffect(() => {
    if (filledCount > last.current) {
      pop.setValue(1.14);
      Animated.spring(pop, { toValue: 1, friction: 4, tension: 160, useNativeDriver: true }).start();
    }
    last.current = filledCount;
  }, [filledCount, pop]);

  const label = accessibilityLabel ?? `${filledCount} از ${items.length}`;
  const art = (
    <Animated.View style={{ width: size, height: size, transform: [{ scale: pop }] }}>
      <Svg width={size} height={size} viewBox="-100 -100 200 200">
        <Circle r={98} fill="#F5C518" />
        <Circle r={98} fill="none" stroke="#E0AE0B" strokeWidth={3} />
        <Circle r={87} fill="#FFFFFF" />
        <G>
          {n === 1 ? (
            <Circle r={70} fill={FILL[wedges[0] ?? 'empty']} />
          ) : (
            wedges.map((w, i) => (
              <Path
                key={i}
                d={wedgePath(i, n)}
                fill={FILL[w]}
                stroke={i === currentWedge ? '#17201A' : FILL[w]}
                strokeWidth={i === currentWedge ? 5 : n > 16 ? 5 : 8}
                strokeLinejoin="round"
              />
            ))
          )}
        </G>
        <Circle r={9} fill="#FFFFFF" />
      </Svg>
    </Animated.View>
  );
  if (!onPress) {
    return (
      <View accessible accessibilityLabel={label}>
        {art}
      </View>
    );
  }
  return (
    <Pressable onPress={onPress} hitSlop={8} accessibilityRole="button" accessibilityLabel={label}>
      {art}
    </Pressable>
  );
}
