import { View } from 'react-native';
import Svg, { Circle, G, Path } from 'react-native-svg';

const SEGMENTS = 8;

/** Polar point helper: angle in degrees, 0 = up. */
function point(r: number, deg: number) {
  const a = ((deg - 90) * Math.PI) / 180;
  return `${(r * Math.cos(a)).toFixed(2)} ${(r * Math.sin(a)).toFixed(2)}`;
}

function wedgePath(i: number) {
  const step = 360 / SEGMENTS;
  const a0 = i * step;
  const a1 = (i + 1) * step;
  const outer = 76;
  return `M 0 0 L ${point(outer, a0)} A ${outer} ${outer} 0 0 1 ${point(outer, a1)} Z`;
}

/** A cut lemon seen from above: rind, white pith and eight juicy wedges (matching LemonProgress everywhere). */
export function LemonSlice({ size = 150 }: { size?: number }) {
  return (
    // Hidden from screen readers on a View: on the web an Svg would hand these props to the DOM as unknown attributes.
    <View accessibilityElementsHidden importantForAccessibility="no-hide-descendants" style={{ width: size, height: size }}>
      <Svg width={size} height={size} viewBox="-100 -100 200 200">
        <Circle r={98} fill="#F5C518" />
        <Circle r={98} fill="none" stroke="#E0AE0B" strokeWidth={3} />
        <Circle r={87} fill="#FFFFFF" />
        <G>
          {Array.from({ length: SEGMENTS }, (_, i) => (
            <Path key={i} d={wedgePath(i)} fill={i % 2 === 0 ? '#FFC414' : '#FFD43B'} stroke="#FFFFFF" strokeWidth={6} strokeLinejoin="round" />
          ))}
          {Array.from({ length: SEGMENTS }, (_, i) => {
            const mid = (i + 0.5) * (360 / SEGMENTS);
            return <Path key={`j${i}`} d={`M ${point(34, mid - 5)} Q ${point(50, mid)} ${point(60, mid - 2)}`} stroke="#FFF4B8" strokeWidth={3.5} strokeLinecap="round" fill="none" />;
          })}
        </G>
        <Circle r={9} fill="#FFFFFF" />
      </Svg>
    </View>
  );
}
