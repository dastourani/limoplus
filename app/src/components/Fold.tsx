/**
 * Turning a page from its corner, as in a Persian book: the spine is on the right, the reader takes the left corner
 * (top or bottom, wherever the finger is) and pulls it to the right; the page folds along a straight crease and its
 * paper back shows, until it has turned over the spine.
 *
 * Geometry: the corner C has been pulled to P. The crease is the perpendicular bisector of C–P. What stays flat is the
 * page on P's side of the crease; the folded part is the page on C's side, mirrored across the crease (so it also lies
 * on P's side). Both are drawn inside one big view rotated so that its top edge lies on the crease and clipping the
 * rest away (overflow hidden), with the page counter-rotated inside it so it stays put. In that rotated frame the
 * mirror is simply scaleY(-1). Only transforms change from frame to frame, so the real page (a web view) is never
 * re-rendered or re-mounted, and at rest everything is an identity transform.
 */
import { useMemo, useRef, type ReactNode } from 'react';
import { Animated, Easing, StyleSheet, View } from 'react-native';
import Svg, { Defs, LinearGradient, Path, Rect, Stop } from 'react-native-svg';

import { rtl } from '../theme';
import { Text } from './Text';

export type Pt = { x: number; y: number };

const sub = (a: Pt, b: Pt): Pt => ({ x: a.x - b.x, y: a.y - b.y });
const len = (a: Pt) => Math.hypot(a.x, a.y);

/** The page can't stretch: the pulled corner stays within reach of both ends of the spine. */
export function clampP(P: Pt, W: number, H: number, cy: number): Pt {
  const near = { x: W, y: cy };
  const far = { x: W, y: H - cy };
  const r = Math.hypot(W, H);
  for (let k = 0; k < 2; k++) {
    let d = sub(P, near);
    let l = len(d);
    if (l > W) P = { x: near.x + (d.x / l) * W, y: near.y + (d.y / l) * W };
    d = sub(P, far);
    l = len(d);
    if (l > r) P = { x: far.x + (d.x / l) * r, y: far.y + (d.y / l) * r };
  }
  return P;
}

/** Where the corner is at time t (0 flat, 1 turned over the spine) when the page turns by itself. */
export function foldPath(t: number, C: Pt, W: number, H: number): Pt {
  const lift = C.y > 0 ? -1 : 1;
  return { x: C.x + 2 * W * t, y: C.y + lift * H * 0.2 * Math.sin(Math.PI * t) };
}

export const corner = (top: boolean, H: number): Pt => ({ x: 0, y: top ? 0 : H });

type Values = Record<'a' | 'ox' | 'oy' | 'ac' | 'ocx' | 'ocy' | 'shade' | 'crease', Animated.Value>;

export type FoldCtl = {
  v: Values;
  size: { W: number; H: number };
  setSize: (W: number, H: number) => void;
  /** Flat: the whole page shows. */
  rest: () => void;
  /** Turned over: nothing of the page shows. */
  gone: (cy: number) => void;
  set: (P: Pt, C: Pt) => void;
  at: () => { P: Pt; C: Pt } | null;
  /** Move the corner in a straight line to `to`. */
  slide: (to: Pt, C: Pt, ms: number) => Promise<void>;
  /** Turn by itself along the natural arc: forward (flat → over) or back (over → flat). */
  play: (forward: boolean, C: Pt, ms: number) => Promise<void>;
  stop: () => void;
};

const side = (W: number, H: number) => 2 * Math.hypot(W, H) + 40;

export function useFold(): FoldCtl {
  const v = useRef<Values>({
    a: new Animated.Value(0),
    ox: new Animated.Value(0),
    oy: new Animated.Value(0),
    ac: new Animated.Value(Math.PI),
    ocx: new Animated.Value(0),
    ocy: new Animated.Value(0),
    shade: new Animated.Value(0),
    crease: new Animated.Value(0),
  }).current;
  const state = useRef<{ P: Pt; C: Pt } | null>(null);
  const frame = useRef<number | null>(null);
  const size = useRef({ W: 1, H: 1 }).current;

  return useMemo(() => {
    const line = (M: Pt, n: Pt, depth: number, creaseLen: number) => {
      const S = side(size.W, size.H);
      const a = Math.atan2(-n.x, n.y);
      const u = { x: n.y, y: -n.x };
      v.a.setValue(a);
      v.ox.setValue(M.x - (u.x * S) / 2);
      v.oy.setValue(M.y - (u.y * S) / 2);
      v.ac.setValue(a + Math.PI);
      v.ocx.setValue(M.x + (u.x * S) / 2);
      v.ocy.setValue(M.y + (u.y * S) / 2);
      v.shade.setValue(depth);
      v.crease.setValue(creaseLen);
    };
    const ctl: FoldCtl = {
      v,
      size,
      setSize(W, H) {
        size.W = Math.max(1, W);
        size.H = Math.max(1, H);
        const s = state.current;
        if (s) ctl.set(s.P, s.C);
        else ctl.rest();
      },
      rest() {
        state.current = null;
        line({ x: size.W / 2, y: -4 }, { x: 0, y: 1 }, 0, 0);
      },
      gone(cy) {
        ctl.set({ x: 2 * size.W, y: cy }, { x: 0, y: cy });
      },
      set(P, C) {
        P = clampP(P, size.W, size.H, C.y);
        state.current = { P, C };
        const d = sub(P, C);
        const l = len(d);
        if (l < 0.5) {
          line({ x: size.W / 2, y: -4 }, { x: 0, y: 1 }, 0, 0);
          return;
        }
        line({ x: (P.x + C.x) / 2, y: (P.y + C.y) / 2 }, { x: d.x / l, y: d.y / l }, Math.min(1, l / size.W), Math.min(1, l / 56));
      },
      at: () => state.current,
      stop() {
        if (frame.current != null) cancelAnimationFrame(frame.current);
        frame.current = null;
      },
      slide(to, C, ms) {
        const from = state.current?.P ?? C;
        return run(ms, (t) => {
          const e = 1 - Math.pow(1 - t, 3);
          ctl.set({ x: from.x + (to.x - from.x) * e, y: from.y + (to.y - from.y) * e }, C);
        });
      },
      play(forward, C, ms) {
        return run(ms, (t) => {
          const e = Easing.inOut(Easing.cubic)(t);
          ctl.set(foldPath(forward ? e : 1 - e, C, size.W, size.H), C);
        });
      },
    };
    function run(ms: number, step: (t: number) => void) {
      ctl.stop();
      return new Promise<void>((resolve) => {
        const t0 = Date.now();
        const tick = () => {
          const t = Math.min(1, (Date.now() - t0) / Math.max(1, ms));
          step(t);
          if (t < 1) frame.current = requestAnimationFrame(tick);
          else {
            frame.current = null;
            resolve();
          }
        };
        tick();
      });
    }
    ctl.rest();
    return ctl;
  }, [v, size]);
}

const rad = (x: Animated.Value | Animated.AnimatedMultiplication) =>
  (x as Animated.Value).interpolate({ inputRange: [-100, 100], outputRange: ['-100rad', '100rad'] });

function Gradient({ id, w, h, stops }: { id: string; w: number; h: number; stops: [number, string, number][] }) {
  return (
    <Svg width={w} height={h} preserveAspectRatio="none">
      <Defs>
        <LinearGradient id={id} x1="0" y1="0" x2="0" y2="1">
          {stops.map(([o, c, a]) => (
            <Stop key={o} offset={o} stopColor={c} stopOpacity={a} />
          ))}
        </LinearGradient>
      </Defs>
      <Rect width={w} height={h} fill={`url(#${id})`} />
    </Svg>
  );
}

/**
 * One turning page. `children` is the page itself (W×H); `back` the colour of its paper back. Put whatever lies
 * under the page before this layer.
 */
export function FoldLayer({
  fold,
  W,
  H,
  back,
  paper,
  children,
  id,
}: {
  fold: FoldCtl;
  W: number;
  H: number;
  back: string;
  /** The page's own colour, so nothing under it shows through a see-through page. */
  paper?: string;
  children: ReactNode;
  id: string;
}) {
  const { v } = fold;
  const S = side(W, H);
  const neg = useMemo(
    () => ({ a: rad(Animated.multiply(v.a, -1)), ox: Animated.multiply(v.ox, -1), oy: Animated.multiply(v.oy, -1) }),
    [v],
  );
  const pageTransform = [{ rotate: neg.a }, { translateX: neg.ox }, { translateY: neg.oy }];
  return (
    <View style={StyleSheet.absoluteFill} pointerEvents="box-none">
      {/* the shadow the lifted page casts on what lies under it, deepest at the crease */}
      <Animated.View
        pointerEvents="none"
        style={[styles.box, { width: S, height: S, transform: [{ translateX: v.ocx }, { translateY: v.ocy }, { rotate: rad(v.ac) }] }]}
      >
        <Animated.View style={{ width: S, height: 70, opacity: v.shade, transformOrigin: 'top', transform: [{ scaleY: Animated.add(0.35, Animated.multiply(v.shade, 0.65)) }] }}>
          <Gradient id={`${id}-s`} w={S} h={70} stops={[[0, '#17201A', 0.42], [0.35, '#17201A', 0.14], [1, '#17201A', 0]]} />
        </Animated.View>
      </Animated.View>
      {/* the flat part of the page and, over it, the folded part's back */}
      <Animated.View
        pointerEvents="box-none"
        style={[styles.box, styles.clip, { width: S, height: S, transform: [{ translateX: v.ox }, { translateY: v.oy }, { rotate: rad(v.a) }] }]}
      >
        <Animated.View style={[styles.page, { width: W, height: H, backgroundColor: paper, transform: pageTransform }]}>{children}</Animated.View>
        <Animated.View
          pointerEvents="none"
          style={[styles.page, { width: W, height: H, backgroundColor: back, transform: [{ scaleY: -1 }, ...pageTransform] }]}
        />
        {/* the crease: a little shade on the back, so the fold reads as paper */}
        <Animated.View pointerEvents="none" style={{ position: 'absolute', top: 0, left: 0, width: S, height: 26, opacity: v.crease }}>
          <Gradient id={`${id}-c`} w={S} h={26} stops={[[0, '#17201A', 0.2], [1, '#17201A', 0]]} />
        </Animated.View>
      </Animated.View>
    </View>
  );
}

/** A plain stand-in for a page that isn't loaded: its title and grey lines, in the reader's colours. */
export function PaperFace({ title, paper, ink, line }: { title?: string; paper: string; ink: string; line: string }) {
  return (
    <View style={[StyleSheet.absoluteFill, styles.paper, { backgroundColor: paper }]}>
      {!!title && <Text style={[styles.paperTitle, rtl, { color: ink }]} numberOfLines={2}>{title}</Text>}
      {[92, 84, 96, 70, 88, 94, 66, 90, 80, 95, 72, 86].map((p, i) => (
        <View key={i} style={[styles.line, { width: `${p}%`, backgroundColor: line }]} />
      ))}
    </View>
  );
}

/** A small turned-up corner at the bottom left: the page can be taken there and turned. */
export function CornerHint({ back, under }: { back: string; under: string }) {
  return (
    <View pointerEvents="none" style={styles.hint}>
      <Svg width={20} height={20} viewBox="0 0 20 20">
        {/* what the turned corner uncovers, then the corner itself lying over the page */}
        <Path d="M0 0 L0 20 L20 20 Z" fill={under} />
        <Path d="M0 0 L20 0 L20 20 Z" fill={back} />
        <Path d="M0 0 L20 20" stroke="#17201A" strokeOpacity={0.22} strokeWidth={1} />
      </Svg>
    </View>
  );
}

const styles = StyleSheet.create({
  box: { position: 'absolute', left: 0, top: 0, transformOrigin: 'top left' },
  clip: { overflow: 'hidden' },
  page: { position: 'absolute', left: 0, top: 0, transformOrigin: 'top left', overflow: 'hidden' },
  paper: { paddingTop: 28, paddingHorizontal: 24, gap: 14 },
  paperTitle: { fontSize: 22, fontWeight: '800', marginBottom: 10 },
  line: { height: 8, borderRadius: 4, alignSelf: 'flex-end' },
  hint: { position: 'absolute', left: 0, bottom: 0 },
});
