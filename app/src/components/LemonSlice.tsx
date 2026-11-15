import { View } from 'react-native';
import Svg, { Circle, G, Path } from 'react-native-svg';

const SEGMENTS = 9;

/** Polar point helper: angle in degrees, 0 = up. */
function point(r: number, deg: number) {
  const a = ((deg - 90) * Math.PI) / 180;
  return `${(r * Math.cos(a)).toFixed(2)} ${(r * Math.sin(a)).toFixed(2)}`;
}

function segment(i: number) {
  const step = 360 / SEGMENTS;
  const a0 = i * step + 4.5;
  const a1 = (i + 1) * step - 4.5;
  const inner = 13;
  const outer = 72;
  const mid = (a0 + a1) / 2;
  return `M ${point(inner, mid)} L ${point(outer, a0)} A ${outer} ${outer} 0 0 1 ${point(outer, a1)} Z`;
}

/** A cut lemon seen from above: rind, pith and juicy segments. Drawn as vectors so it stays sharp at any size. */
export function LemonSlice({ size = 150 }: { size?: number }) {
  return (
    // Hidden from screen readers on a View: on the web an Svg would hand these props to the DOM as unknown attributes.
    <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={{ width: size, height: size }}>
    <Svg width={size} height={size} viewBox="-100 -100 200 200">
      <Circle r={98} fill="#F5C518" />
      <Circle r={98} fill="none" stroke="#E0AE0B" strokeWidth={3} />
      <Circle r={86} fill="#FFF7D6" />
      <G>
        {Array.from({ length: SEGMENTS }, (_, i) => (
          <Path key={i} d={segment(i)} fill="#FFD43B" stroke="#FFD43B" strokeWidth={9} strokeLinejoin="round" />
        ))}
        {Array.from({ length: SEGMENTS }, (_, i) => {
          const mid = (i + 0.5) * (360 / SEGMENTS);
          return <Path key={`j${i}`} d={`M ${point(34, mid - 6)} Q ${point(52, mid)} ${point(62, mid - 3)}`} stroke="#FFE98A" strokeWidth={4} strokeLinecap="round" fill="none" />;
        })}
      </G>
      <Circle r={9} fill="#FFF7D6" />
    </Svg>
    </View>
  );
}
