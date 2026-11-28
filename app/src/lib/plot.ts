/**
 * «:::نمودار» boxes drawn from a description, as SVG inside the lesson (same code in the app and the panel preview,
 * so what the author approves is what learners see). Colours come from CSS classes, so night mode works.
 *
 *   :::نمودار {#sin-zoj}
 *   تابع: sin(x)
 *   روی: 0 تا pi
 *   گسترش: زوج
 *   تناوب: 2pi
 *   فوریه: 1، 3، 10
 *   بازه: -3pi تا 3pi
 *   محور: pi
 *   :::
 *
 * Per curve (after its «تابع:»): روی، گسترش (ساده، زوج، فرد)، تناوب، فوریه، رنگ، خط (پیوسته، خط‌چین، نقطه‌چین)، نام،
 * معکوس (بله: the inverse, mirrored in y = x). For the whole plot: بازه، بازه‌ی y، محور (pi یا عدد)، متغیر (x یا t)،
 * برچسب x، برچسب y، پرش (شکسته یا عمودی)، شبکه، ارتفاع (کوتاه، معمولی، بلند)، نقطه، مجانب. Other lines are the caption.
 *
 * Signals and systems (the box may have no «تابع:» then):
 *   ضربه: 0، (2, -0.5)        impulses δ, weight 1 or (place, weight); «قطار ضربه: T» or «قطار ضربه: T، وزن» repeats one
 *   متغیر: n                   a discrete signal: every «تابع:» drawn as stems at whole n; «مقادیر: 1، 2، 3 از -1» a list
 *   صفر: -1، 0.5±0.5j          zeros and poles (j or i; «±» gives the pair; «0.9∠pi/4» polar) drawn ○ and × in the z
 *   قطب: 0.8، -0.5             plane (unit circle) or «صفحه: s»; «ناحیه: |z| > 0.8» or «-1 < Re(s) < 2» shades the ROC
 *   بود: بله                   Bode plot of H(s) = بهره × ∏(s − صفر) / ∏(s − قطب): exact and straight-line magnitude
 *                              (dB) over log ω, and phase («فاز: خیر» hides it, «مجانبی: خیر» the straight lines)
 * Formulas: lib/expr.ts. Checked by scripts/plot-check.ts.
 */
import { compile, ExprError, value, type Compiled } from './expr';
import { evalAt, factor, parseTransfer, TransferError, type Rational } from './transfer';

export type Extension = 'none' | 'simple' | 'even' | 'odd';
export type Curve = {
  source: string;
  f: Compiled;
  on?: [number, number];
  extension: Extension;
  period?: number;
  fourier: number[];
  color?: string;
  line: 'solid' | 'dash' | 'dot';
  name?: string;
  inverse: boolean;
};
export type Point = { x: number; y: number; open: boolean; label?: string };
export type Cx = { re: number; im: number };
/** Region of convergence: lo < |z| < hi, or lo < Re(s) < hi. */
export type Roc = { plane: 'z' | 's'; lo: number; hi: number };
export type PlotSpec = {
  curves: Curve[];
  x?: [number, number];
  y?: [number, number];
  piAxis: boolean;
  variable: 'x' | 't' | 'n';
  xLabel?: string;
  yLabel?: string;
  jumps: 'break' | 'vertical';
  grid: boolean;
  /** Numbers on the axes: none by default (a clean textbook look); «عدد: بله» both, «عدد: x» or «عدد: y» one. */
  numbers: { x: boolean; y: boolean };
  /** Only these values marked on the axes («علامت x: 1، pi»). */
  marks: { x: number[]; y: number[] };
  /** Removable gaps such as (x²−1)/(x−1) at 1 get an open circle by themselves («حفره: خیر» turns it off). */
  autoHoles: boolean;
  height: number;
  points: Point[];
  asymptotes: { axis: 'x' | 'y'; at: number }[];
  caption: string[];
  impulses: { x: number; w: number }[];
  trains: { T: number; w: number }[];
  seq?: { start: number; values: number[] };
  zeros: Cx[];
  poles: Cx[];
  plane?: 'z' | 's';
  roc?: Roc;
  bode: boolean;
  nyquist: boolean;
  /** H(s) as written («بود: 10/(s+10)»); its poles and zeros fill zeros, poles and gain. */
  tf?: Rational;
  gain: number;
  phase: boolean;
  straight: boolean;
};

export const COLORS: Record<string, string> = {
  آبی: 'blue', قرمز: 'red', سبز: 'green', نارنجی: 'orange', بنفش: 'purple', صورتی: 'pink', خاکستری: 'gray',
  زرد: 'yellow', مشکی: 'ink', سیاه: 'ink',
};
const PALETTE = ['blue', 'red', 'green', 'orange', 'purple', 'pink', 'yellow', 'gray'];

const W = 360;
const M = { l: 34, r: 14, t: 14, b: 24 };
const SAMPLES = 1400;

/** Numbers on plots are written in English digits, with a true minus sign. */
const fa = (s: string | number) => String(s).replace(/-/g, '−');
const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

export class PlotError extends Error {}

function key(raw: string): string {
  return raw.replace(/[‌\s\u064B-\u065Fـ]/g, '').replace(/ي/g, 'ی').replace(/ك/g, 'ک').toLowerCase();
}
const KEYS: Record<string, string> = {
  تابع: 'fn', روی: 'on', دامنه: 'on', گسترش: 'ext', تناوب: 'period', دوره: 'period', فوریه: 'fourier', سریفوریه: 'fourier',
  رنگ: 'color', خط: 'line', نام: 'name', معکوس: 'inverse', وارون: 'inverse',
  بازه: 'x', بازهx: 'x', بازهیx: 'x', بازهی: 'x', بازهy: 'y', بازهیy: 'y', محدودهy: 'y', محدودهیy: 'y',
  محور: 'axis', متغیر: 'var', برچسبx: 'xlabel', برچسبy: 'ylabel', پرش: 'jumps', شبکه: 'grid', ارتفاع: 'height',
  نقطه: 'point', مجانب: 'asym', عدد: 'numbers', اعداد: 'numbers', عددها: 'numbers', علامتx: 'markx', علامتy: 'marky',
  حفره: 'holes',
  ضربه: 'impulse', ضربهها: 'impulse', قطارضربه: 'train', مقادیر: 'seq', دنباله: 'seq',
  صفر: 'zero', صفرها: 'zero', قطب: 'pole', قطبها: 'pole', ناحیه: 'roc', ناحیهیهمگرایی: 'roc', roc: 'roc',
  صفحه: 'plane', بود: 'bode', بد: 'bode', bode: 'bode', نایکوئیست: 'nyquist', نایکویست: 'nyquist', nyquist: 'nyquist',
  تابعتبدیل: 'tf', بهره: 'gain', فاز: 'phase', مجانبی: 'straight',
};
const PLOT_KEYS = ['fn', 'impulse', 'train', 'seq', 'zero', 'pole', 'bode', 'nyquist', 'tf'];

/** Splits at commas outside brackets: «(1, 2)، sqrt(2)» → «(1, 2)», «sqrt(2)». */
function splitTop(v: string): string[] {
  const out: string[] = [];
  let depth = 0, cur = '';
  for (const ch of v) {
    if (ch === '(') depth++;
    if (ch === ')') depth--;
    if ((ch === ',' || ch === '،') && depth === 0) { out.push(cur); cur = ''; } else cur += ch;
  }
  out.push(cur);
  return out.map((x) => x.trim()).filter(Boolean);
}

/** «0.5+0.3j», «-2j», «j», «0.9∠pi/4»; «a±bj» is the pair a+bj and a−bj. */
export function parseComplex(src: string): Cx[] {
  const s = src.replace(/\s/g, '').replace(/[−–]/g, '-').replace(/\+-|-\+/g, '±');
  // «j0.3», «0.3j», «j», and the same with i (unless it is the end of «pi»). No look-behind: older engines lack it.
  const endsI = (t: string) => /i$/.test(t) && !/pi$/.test(t);
  const isImag = (t: string) => /^[ij]/.test(t) || /j$/.test(t) || endsI(t);
  const imag = (t: string) => {
    let body = t;
    if (/^[ij]/.test(body)) body = body.slice(1);
    else if (/j$/.test(body) || endsI(body)) body = body.slice(0, -1);
    body = body.replace(/^\*|\*$/g, '');
    return body === '' ? 1 : value(body);
  };
  if (s.includes('∠')) {
    const [r, th] = s.split('∠');
    const R = value(r), T = value(th);
    return [{ re: R * Math.cos(T), im: R * Math.sin(T) }];
  }
  const pm = s.indexOf('±');
  if (pm >= 0) {
    const re = pm ? value(s.slice(0, pm)) : 0;
    const im = imag(s.slice(pm + 1));
    return [{ re, im }, { re, im: -im }];
  }
  // The last + or − outside brackets that is not a sign of an exponent splits the real and imaginary parts.
  let depth = 0, at = -1;
  for (let i = 0; i < s.length; i++) {
    const ch = s[i];
    if (ch === '(') depth++;
    else if (ch === ')') depth--;
    else if ((ch === '+' || ch === '-') && depth === 0 && i > 0 && !/[eE(^*/]/.test(s[i - 1])) at = i;
  }
  if (at > 0 && isImag(s.slice(at + 1))) {
    const im = imag(s.slice(at + 1));
    return [{ re: value(s.slice(0, at)), im: s[at] === '-' ? -im : im }];
  }
  if (isImag(s)) {
    const neg = s.startsWith('-');
    const im = imag(s.replace(/^[+-]/, ''));
    return [{ re: 0, im: neg ? -im : im }];
  }
  return [{ re: value(s), im: 0 }];
}

function parseRoc(v: string): Roc {
  const t = v.replace(/\s/g, '').replace(/[≤]/g, '<').replace(/[≥]/g, '>').replace(/[−–]/g, '-').replace(/\{/g, '(').replace(/\}/g, ')').toLowerCase();
  if (/^(همه|کل|کلصفحه|همهجا|all)/.test(t)) return { plane: 'z', lo: 0, hi: Infinity };
  const zm = /\|z\|/.test(t), sm = /re\(s\)|σ/.test(t);
  if (!zm && !sm) throw new PlotError(`ناحیه را به شکل «|z| > 0.8» یا «Re(s) > -1» بنویسید: «${v}»`);
  const plane = zm ? 'z' : 's';
  const name = zm ? /\|z\|/ : /re\(s\)|σ/;
  const [left, right] = t.split(name);
  const roc: Roc = { plane, lo: plane === 'z' ? 0 : -Infinity, hi: Infinity };
  const num = (x: string) => value(x.replace(/=/g, ''));
  // «a < |z|», «a > |z|», «|z| > a», «|z| < a», and «a < |z| < b».
  if (left) {
    if (left.endsWith('<') || left.endsWith('<=')) roc.lo = num(left.replace(/<=?$/, ''));
    else if (left.endsWith('>') || left.endsWith('>=')) roc.hi = num(left.replace(/>=?$/, ''));
  }
  if (right) {
    if (right.startsWith('>')) roc.lo = num(right.replace(/^>=?/, ''));
    else if (right.startsWith('<')) roc.hi = num(right.replace(/^<=?/, ''));
  }
  if (!(roc.hi > roc.lo)) throw new PlotError(`ناحیه‌ی همگرایی خالی است: «${v}»`);
  return roc;
}
const CURVE_KEYS = new Set(['on', 'ext', 'period', 'fourier', 'color', 'line', 'name', 'inverse']);

/** A box's lines → a plot description, or null when the box has no «تابع:» line (an ordinary box, e.g. a picture). */
export function parsePlot(body: string): PlotSpec | null {
  const lines = (body ?? '').split('\n');
  const keyed = lines.map((l) => {
    const m = /^\s*([^:：]{1,20}?)\s*[:：]\s*(.*)$/.exec(l);
    const k = m ? KEYS[key(m[1])] : undefined;
    return k ? { k, v: m![2].trim() } : null;
  });
  if (!keyed.some((x) => x && PLOT_KEYS.includes(x.k))) return null;
  const spec: PlotSpec = {
    curves: [], piAxis: false, variable: 'x', jumps: 'break', grid: false, numbers: { x: false, y: false }, marks: { x: [], y: [] }, autoHoles: true, height: 225, points: [], asymptotes: [], caption: [],
    impulses: [], trains: [], zeros: [], poles: [], bode: false, nyquist: false, gain: 1, phase: true, straight: true,
  };
  const range = (v: string): [number, number] => {
    const parts = v.split(/\s+تا\s+|\s+to\s+|\.\.|…/);
    if (parts.length !== 2) throw new PlotError(`بازه را به شکل «-2pi تا 2pi» بنویسید: «${v}»`);
    const a = value(parts[0]), b = value(parts[1]);
    if (!(b > a)) throw new PlotError(`انتهای بازه باید بزرگ‌تر از ابتدایش باشد: «${v}»`);
    return [a, b];
  };
  const yes = (v: string) => /^(بله|آره|yes|true|1)$/i.test(v.trim());
  let current: Curve | null = null;
  lines.forEach((line, n) => {
    const item = keyed[n];
    if (!item) {
      if (line.trim()) spec.caption.push(line);
      return;
    }
    const { k, v } = item;
    const where = ` (خط ${fa(n + 1)} نمودار)`;
    try {
      if (CURVE_KEYS.has(k) && !current) throw new PlotError(`«${line.trim()}» باید بعد از یک «تابع:» بیاید`);
      const c = current!;
      switch (k) {
        case 'fn':
          current = { source: v, f: compile(v), extension: 'none', fourier: [], line: 'solid', inverse: false };
          spec.curves.push(current);
          break;
        case 'on': c.on = range(v); break;
        case 'ext': {
          const e = { ساده: 'simple', متناوب: 'simple', زوج: 'even', فرد: 'odd' }[v.replace(/\s/g, '')] as Extension | undefined;
          if (!e) throw new PlotError(`«گسترش» یکی از ساده، زوج یا فرد است: «${v}»`);
          c.extension = e;
          break;
        }
        case 'period': c.period = value(v); if (!(c.period > 0)) throw new PlotError('تناوب باید مثبت باشد'); break;
        case 'fourier':
          c.fourier = v.split(/[,،\s]+|\s*و\s*/).filter(Boolean).map((x) => Math.round(value(x))).filter((x) => x >= 0).slice(0, 6);
          break;
        case 'color': {
          const name = COLORS[v.trim()] ?? (PALETTE.includes(v.trim()) ? v.trim() : undefined);
          if (!name) throw new PlotError(`رنگ «${v}» شناخته نشد (${Object.keys(COLORS).join('، ')})`);
          c.color = name;
          break;
        }
        case 'line': c.line = /نقطه/.test(v) ? 'dot' : /چین|dash/.test(v) ? 'dash' : 'solid'; break;
        case 'name': c.name = v; break;
        case 'inverse': c.inverse = yes(v); break;
        case 'x': spec.x = range(v); break;
        case 'y': spec.y = range(v); break;
        // «محور: pi» asks for π labels, so the horizontal axis gets its numbers.
        case 'axis': spec.piAxis = /pi|π/i.test(v); if (spec.piAxis) spec.numbers.x = true; break;
        case 'numbers': {
          const t = v.trim().toLowerCase();
          spec.numbers = t === 'x' || t === 't' ? { x: true, y: false } : t === 'y' ? { x: false, y: true } : yes(v) ? { x: true, y: true } : { x: false, y: false };
          break;
        }
        case 'markx': case 'marky':
          spec.marks[k === 'markx' ? 'x' : 'y'] = v.split(/[,،]|\s+و\s+/).map((x) => x.trim()).filter(Boolean).map(value);
          break;
        case 'holes': spec.autoHoles = yes(v); break;
        case 'var': spec.variable = /^\s*n\s*$/i.test(v) || /گسسته/.test(v) ? 'n' : /t/i.test(v) ? 't' : 'x'; break;
        case 'impulse':
          for (const item of splitTop(v)) {
            const pair = /^\((.+)\)$/.exec(item);
            const parts = pair ? splitTop(pair[1]) : [item];
            if (parts.length > 2) throw new PlotError(`ضربه را به شکل «0» یا «(2, -0.5)» بنویسید: «${item}»`);
            spec.impulses.push({ x: value(parts[0]), w: parts[1] !== undefined ? value(parts[1]) : 1 });
          }
          break;
        case 'train': {
          const [T, w] = splitTop(v);
          const period = value(T ?? '');
          if (!(period > 0)) throw new PlotError('تناوب قطار ضربه باید مثبت باشد');
          spec.trains.push({ T: period, w: w !== undefined ? value(w) : 1 });
          break;
        }
        case 'seq': {
          const [vals, from] = v.split(/\s+از\s+|\s+from\s+/);
          spec.seq = { start: from ? Math.round(value(from)) : 0, values: splitTop(vals).map(value) };
          spec.variable = 'n';
          break;
        }
        case 'zero': case 'pole':
          for (const item of splitTop(v)) (k === 'zero' ? spec.zeros : spec.poles).push(...parseComplex(item));
          break;
        case 'roc': spec.roc = parseRoc(v); break;
        case 'tf': spec.tf = parseTransfer(v); break;
        case 'plane': spec.plane = /s/i.test(v) ? 's' : 'z'; break;
        case 'bode': case 'nyquist': {
          const off = /^(خیر|نه|no)$/i.test(v.trim());
          if (k === 'bode') spec.bode = !off; else spec.nyquist = !off;
          // «بود: 10/(s+10)»: the transfer function itself; «بود: بله» uses the zeros, poles and gain lines.
          if (!off && !yes(v)) spec.tf = parseTransfer(v);
          break;
        }
        case 'gain': spec.gain = value(v); break;
        case 'phase': spec.phase = yes(v); break;
        case 'straight': spec.straight = yes(v); break;
        case 'xlabel': spec.xLabel = v; break;
        case 'ylabel': spec.yLabel = v; break;
        case 'jumps': spec.jumps = /عمود/.test(v) ? 'vertical' : 'break'; break;
        case 'grid': spec.grid = yes(v); break;
        case 'height': spec.height = /کوتاه/.test(v) ? 180 : /بلند/.test(v) ? 300 : 225; break;
        case 'point': {
          const m = /\(\s*([^,،]+?)\s*[,،]\s*([^)]+?)\s*\)\s*(.*)$/.exec(v);
          if (!m) throw new PlotError(`نقطه را به شکل «(1, 2) توخالی» بنویسید: «${v}»`);
          const label = /[«"]([^»"]+)[»"]/.exec(m[3])?.[1];
          spec.points.push({ x: value(m[1]), y: value(m[2]), open: /توخالی|باز|open/.test(m[3]), label });
          break;
        }
        case 'asym': {
          const m = /^\s*([xyt])\s*=\s*(.+)$/i.exec(v);
          if (!m) throw new PlotError(`مجانب را به شکل «x = pi/2» یا «y = 1» بنویسید: «${v}»`);
          spec.asymptotes.push({ axis: m[1].toLowerCase() === 'y' ? 'y' : 'x', at: value(m[2]) });
          break;
        }
      }
    } catch (e) {
      if (e instanceof PlotError || e instanceof ExprError || e instanceof TransferError) throw new PlotError(e.message + where);
      throw e;
    }
  });
  if (spec.tf && !spec.zeros.length && !spec.poles.length) {
    const f = factor(spec.tf);
    spec.zeros = f.zeros;
    spec.poles = f.poles;
    spec.gain = f.gain;
  }
  for (const c of spec.curves) {
    if ((c.extension !== 'none' || c.period) && !c.on) {
      if (c.period && c.extension !== 'even' && c.extension !== 'odd') c.on = [0, c.period];
      else throw new PlotError(`برای «${c.source}» بازه‌ی تعریف لازم است، مثلاً «روی: 0 تا pi».`);
    }
  }
  return spec;
}

/** The curve as a function of x: its definition interval, extended and repeated as asked. */
export function curveFunction(c: Curve): { g: Compiled; period?: number; start?: number } {
  const f = c.f;
  if (!c.on) return { g: f };
  const [a, b] = c.on;
  const L = b - a;
  const inside = (x: number) => (x >= a - 1e-12 && x <= b + 1e-12 ? f(x) : NaN);
  if (c.extension === 'none' && !c.period) return { g: inside };
  if (c.extension === 'even' || c.extension === 'odd') {
    const h = (x: number) => {
      const d = x - a;
      if (Math.abs(d) > L + 1e-12) return NaN;
      const y = f(a + Math.abs(d));
      return c.extension === 'odd' && d < 0 ? -y : y;
    };
    const T = c.period ?? 2 * L;
    const start = a - L;
    return { g: (x) => h(start + (((x - start) % T) + T) % T), period: T, start };
  }
  const T = c.period ?? L;
  // One period starts at a; beyond the definition (T > L) there is nothing.
  return { g: (x) => inside(a + (((x - a) % T) + T) % T), period: T, start: a };
}

/** Partial sums of the Fourier series of a T-periodic g, computed numerically. */
export function fourierSums(g: Compiled, T: number, start: number, orders: number[]): Compiled[] {
  // Midpoint rule over one period (8192 steps): exact for the trigonometric terms we keep, and it never samples a
  // jump at the ends or in the middle, so square waves come out right.
  const N = Math.max(...orders, 0);
  const steps = 8192;
  const h = T / steps;
  const a = new Array(N + 1).fill(0), b = new Array(N + 1).fill(0);
  for (let i = 0; i < steps; i++) {
    const x = start + (i + 0.5) * h;
    let y = g(x);
    if (!Number.isFinite(y)) y = 0;
    for (let n = 0; n <= N; n++) {
      const k = (2 * Math.PI * n * x) / T;
      a[n] += y * Math.cos(k);
      b[n] += y * Math.sin(k);
    }
  }
  const scale = (2 / T) * h;
  for (let n = 0; n <= N; n++) { a[n] *= scale; b[n] *= scale; }
  return orders.map((order) => (x: number) => {
    let s = a[0] / 2;
    for (let n = 1; n <= order; n++) {
      const k = (2 * Math.PI * n * x) / T;
      s += a[n] * Math.cos(k) + b[n] * Math.sin(k);
    }
    return s;
  });
}

type Seg = [number, number][];

/** Samples cut where the function is undefined or jumps (found by halving the step until the gap stays). */
export function segments(g: Compiled, x0: number, x1: number, ySpan: number, jumps: 'break' | 'vertical', view?: [number, number]): Seg[] {
  // Far above or below the window on the same side (near an asymptote): steep, but nothing to cut there.
  const side = (v: number) => (!view ? 0 : v > view[1] + ySpan ? 1 : v < view[0] - ySpan ? -1 : 0);
  const out: Seg[] = [];
  let cur: Seg = [];
  const step = (x1 - x0) / SAMPLES;
  let px = x0, py = g(x0);
  if (Number.isFinite(py)) cur.push([px, py]);
  const big = 0.08 * ySpan;
  for (let i = 1; i <= SAMPLES; i++) {
    const x = x0 + i * step, y = g(x);
    if (!Number.isFinite(y)) {
      if (cur.length > 1) out.push(cur);
      cur = [];
    } else if (Number.isFinite(py) && Math.abs(y - py) > big) {
      // Steep or a jump? Halve the interval where the change is, 40 times.
      let a = px, b = x, ya = py, yb = y;
      for (let k = 0; k < 40; k++) {
        const m = (a + b) / 2, ym = g(m);
        if (!Number.isFinite(ym)) { ya = NaN; break; }
        if (Math.abs(ym - ya) > Math.abs(yb - ym)) { b = m; yb = ym; } else { a = m; ya = ym; }
      }
      const jump = !Number.isFinite(ya) || (Math.abs(yb - ya) > 0.02 * ySpan && !(side(ya) !== 0 && side(ya) === side(yb)));
      if (jump) {
        if (Number.isFinite(ya)) cur.push([a, ya]);
        if (jumps === 'vertical' && Number.isFinite(ya) && Number.isFinite(yb) && Math.abs(yb - ya) < 50 * ySpan) {
          cur.push([b, yb]);
        } else {
          if (cur.length > 1) out.push(cur);
          cur = Number.isFinite(yb) ? [[b, yb]] : [];
        }
      }
      cur.push([x, y]);
    } else {
      if (!cur.length && Number.isFinite(py) === false) {
        // Entering the domain: find where it starts, so √x begins at 0 and not one step later.
        let a = px, b = x;
        for (let k = 0; k < 30; k++) { const m = (a + b) / 2; if (Number.isFinite(g(m))) b = m; else a = m; }
        if (b < x) cur.push([b, g(b)]);
      }
      cur.push([x, y]);
    }
    if (!Number.isFinite(y) && Number.isFinite(py) && cur.length === 0 && out.length) {
      // Leaving the domain: extend the last piece to its edge.
      let a = px, b = x;
      for (let k = 0; k < 30; k++) { const m = (a + b) / 2; if (Number.isFinite(g(m))) a = m; else b = m; }
      if (a > px) out[out.length - 1].push([a, g(a)]);
    }
    px = x; py = y;
  }
  if (cur.length > 1) out.push(cur);
  // A piece shorter than a step is the value at a jump itself (e.g. the 0 of a square wave): not drawn.
  return out.filter((s) => s[s.length - 1][0] - s[0][0] > 1.5 * step);
}

/**
 * Gaps a formula has at a single point though both sides meet there, like (x²−1)/(x−1) at 1 or sin(x)/x at 0.
 * The samples almost never land on such a point, so the usual suspects are tried: whole numbers, halves and
 * multiples of π/12 in the window.
 */
export function findHoles(g: Compiled, x0: number, x1: number, ySpan: number): { x: number; y: number }[] {
  const out: { x: number; y: number }[] = [];
  const tried = new Set<string>();
  const candidates: number[] = [];
  const add = (step: number) => {
    if ((x1 - x0) / step > 400) return;
    for (let k = Math.ceil(x0 / step); k * step <= x1; k++) candidates.push(k * step);
  };
  add(0.5);
  add(Math.PI / 12);
  for (const c of candidates) {
    const key = c.toFixed(9);
    if (tried.has(key) || c <= x0 || c >= x1) continue;
    tried.add(key);
    if (Number.isFinite(g(c))) continue;
    const eps = 1e-7 * Math.max(1, Math.abs(c));
    const l = g(c - eps), r = g(c + eps);
    if (Number.isFinite(l) && Number.isFinite(r) && Math.abs(l - r) < 1e-4 * Math.max(1, ySpan)) out.push({ x: c, y: (l + r) / 2 });
  }
  return out;
}

function niceStep(span: number, target: number): number {
  const raw = span / target, mag = Math.pow(10, Math.floor(Math.log10(raw))), n = raw / mag;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
}
function gcd(a: number, b: number): number { return b ? gcd(b, a % b) : Math.abs(a); }
function piLabel(v: number): string {
  const q = Math.round((v / Math.PI) * 12);
  if (q === 0) return '0';
  const g = gcd(q, 12), n = q / g, d = 12 / g;
  const num = n === 1 ? 'π' : n === -1 ? '−π' : `${fa(n)}π`;
  return d === 1 ? num : `${num}/${fa(d)}`;
}
function numLabel(v: number, step: number): string {
  const dec = Math.max(0, -Math.floor(Math.log10(step) + 1e-9));
  return fa((Math.abs(v) < step / 1e6 ? 0 : v).toFixed(dec));
}
function ticks(a: number, b: number, pi: boolean, target: number): { at: number; text: string }[] {
  let step: number;
  if (pi) {
    const choices = [1 / 6, 1 / 4, 1 / 2, 1, 2, 4, 8, 16].map((k) => k * Math.PI);
    step = choices.find((s) => (b - a) / s <= target + 1) ?? choices[choices.length - 1];
  } else step = niceStep(b - a, target);
  const out = [];
  for (let k = Math.ceil(a / step - 1e-9); k * step <= b + 1e-9; k++) {
    const at = k * step;
    out.push({ at, text: pi ? piLabel(at) : numLabel(at, step) });
  }
  return out;
}

let uid = 0;
const cache = new Map<string, string | null>();

/** The box's body as plot HTML, or null when it is not a plot. `inline` renders a caption or a name (with $…$). */
export function renderPlot(body: string, inline: (s: string) => string): string | null {
  const hit = cache.get(body);
  if (hit !== undefined) return hit;
  let html: string | null;
  try {
    const spec = parsePlot(body);
    html = !spec ? null : spec.bode ? drawBode(spec, inline) : spec.nyquist ? drawNyquist(spec, inline) : !spec.curves.length && !spec.impulses.length && !spec.trains.length && !spec.seq && (spec.zeros.length || spec.poles.length) ? drawPoleZero(spec, inline) : draw(spec, inline);
  } catch (e) {
    html = `<div class="plot-error">⚠ نمودار کشیده نشد: ${esc((e as Error).message)}</div>`;
  }
  if (cache.size > 60) cache.clear();
  cache.set(body, html);
  return html;
}

function draw(spec: PlotSpec, inline: (s: string) => string): string {
  const H = spec.height;
  // Every drawn thing: the curves (and their inverse or Fourier sums), each with its colour.
  type Drawn = { g: Compiled; color: string; line: Curve['line']; width: number; name?: string; inverse: boolean; on?: [number, number]; period?: number };
  const drawn: Drawn[] = [];
  let colorIndex = 0;
  const nextColor = () => PALETTE[colorIndex++ % PALETTE.length];
  for (const c of spec.curves) {
    const { g, period, start } = curveFunction(c);
    const color = c.color ?? nextColor();
    if (c.fourier.length) {
      // The period: the curve's own, or its interval, or 2π for a formula on the whole line (square(x), saw(x), …),
      // taken over (−π, π) then.
      const T = period ?? (c.on ? c.on[1] - c.on[0] : 2 * Math.PI);
      const base: Compiled = period || !c.on ? g : curveFunction({ ...c, extension: 'simple' }).g;
      const sums = fourierSums(base, T, start ?? (c.on ? c.on[0] : -T / 2), c.fourier);
      sums.forEach((s, i) => drawn.push({ g: s, color: nextColor(), line: 'solid', width: 1.6, name: `مجموع تا $n = ${c.fourier[i]}$`, inverse: false }));
    }
    drawn.push({ g, color, line: c.line, width: 2.4, name: c.name, inverse: c.inverse, on: c.on, period });
  }

  const discrete = spec.variable === 'n';
  const seqColor = spec.seq ? nextColor() : '';
  const pulseColor = spec.impulses.length || spec.trains.length ? (spec.curves.length || spec.seq ? nextColor() : 'ink') : '';
  // Places that must be in view: impulses and the listed values of a sequence (with the origin).
  const extraX = [...spec.impulses.map((i) => i.x), ...(spec.seq ? [spec.seq.start, spec.seq.start + spec.seq.values.length - 1] : [])];

  // x window: given, or the definition intervals, or −10…10 (−2π…2π on a π axis).
  let [x0, x1] = spec.x ?? (() => {
    // A periodic curve: two periods each side; curves only on an interval: that interval; otherwise a usual window.
    const T = Math.max(0, ...drawn.map((d) => d.period ?? 0));
    if (T) return [-2 * T, 2 * T] as [number, number];
    if (!spec.curves.length && !extraX.length && spec.trains.length) {
      const Tt = Math.max(...spec.trains.map((t) => t.T));
      return [-2.5 * Tt, 2.5 * Tt] as [number, number];
    }
    const ons = spec.curves.filter((c) => c.on).map((c) => c.on!);
    if (ons.length === spec.curves.length && (ons.length || extraX.length)) {
      const all = [...ons.flat(), ...extraX, ...(extraX.length ? [0] : [])];
      const lo = Math.min(...all), hi = Math.max(...all);
      const pad = discrete ? 1.5 : extraX.length ? Math.max(0.15 * (hi - lo), 1) : 0.05 * (hi - lo);
      return [lo - pad, hi + pad] as [number, number];
    }
    return spec.piAxis ? [-2 * Math.PI, 2 * Math.PI] : [-10, 10];
  })();
  // A given window for n: its ends are drawn too.
  if (discrete && spec.x) { x0 -= 0.5; x1 += 0.5; }
  if (x1 <= x0) x1 = x0 + 1;
  const whole = () => {
    const out: number[] = [];
    for (let n = Math.ceil(x0 - 1e-9); n <= x1 + 1e-9; n++) out.push(n);
    return out;
  };
  const trainAt = (t: { T: number }) => {
    const out: number[] = [];
    for (let k = Math.ceil(x0 / t.T - 1e-9); k * t.T <= x1 + 1e-9; k++) out.push(k * t.T);
    return out;
  };

  // y window: given, or from the values (ignoring the far ends near asymptotes).
  let y0: number, y1: number;
  const sample = (d: Drawn) => {
    const ys: number[] = [];
    if (discrete) for (const n of whole()) { const y = d.g(n); if (Number.isFinite(y)) ys.push(y); }
    else for (let i = 0; i <= 400; i++) { const y = d.g(x0 + ((x1 - x0) * i) / 400); if (Number.isFinite(y)) ys.push(y); }
    // An inverse's values are the curve's x: its definition interval must fit too.
    if (d.inverse) ys.push(...(d.on ?? [x0, x1]));
    return ys;
  };
  if (spec.y) [y0, y1] = spec.y;
  else {
    const stemsOrPulses = discrete || extraX.length || spec.trains.length;
    const vals = drawn
      .flatMap(sample)
      .concat(spec.points.map((p) => p.y), spec.impulses.map((i) => i.w), spec.trains.map((t) => t.w), spec.seq?.values ?? [], stemsOrPulses ? [0] : [])
      .sort((a, b) => a - b);
    if (!vals.length) { y0 = -1; y1 = 1; } else {
      const q = (p: number) => vals[Math.min(vals.length - 1, Math.max(0, Math.round(p * (vals.length - 1))))];
      let lo = vals[0], hi = vals[vals.length - 1];
      const qlo = q(0.03), qhi = q(0.97);
      if (hi - lo > 4 * (qhi - qlo || 1)) { lo = qlo; hi = qhi; }
      if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
      // Keep 0 in view when it is close, so the x axis shows.
      if (lo > 0 && lo < 0.35 * (hi - lo)) lo = 0;
      if (hi < 0 && -hi < 0.35 * (hi - lo)) hi = 0;
      // Impulses: room above the arrows for their weights.
      const pad = (spec.impulses.length || spec.trains.length ? 0.16 : 0.08) * (hi - lo);
      y0 = lo - pad; y1 = hi + pad;
    }
  }
  const ySpan = y1 - y0;
  const pw = W - M.l - M.r, ph = H - M.t - M.b;
  const sx = (x: number) => M.l + ((x - x0) / (x1 - x0)) * pw;
  const sy = (y: number) => M.t + ((y1 - y) / ySpan) * ph;
  const clampY = (v: number) => Math.max(-3 * H, Math.min(4 * H, v));
  const id = `pc${++uid}`;
  const parts: string[] = [];
  parts.push(`<rect class="pbg" x="0" y="0" width="${W}" height="${H}" rx="10"/>`);

  // Grid and ticks.
  const xNice = ticks(x0, x1, spec.piAxis, 8).filter((t) => !discrete || Math.abs(t.at - Math.round(t.at)) < 1e-9), yNice = ticks(y0, y1, false, 5);
  // A mark is written as a multiple of π when it is one (pi/2, 3pi/4), otherwise as a number.
  const piish = (v: number) => Math.abs(v) > 1e-12 && Math.abs(v / (Math.PI / 12) - Math.round(v / (Math.PI / 12))) < 1e-9;
  const label = (v: number) => (piish(v) ? piLabel(v) : fa(String(+v.toFixed(3))));
  const xt = [...(spec.numbers.x ? xNice : []), ...spec.marks.x.filter((v) => v >= x0 && v <= x1).map((at) => ({ at, text: label(at) }))];
  const yt = [...(spec.numbers.y ? yNice : []), ...spec.marks.y.filter((v) => v >= y0 && v <= y1).map((at) => ({ at, text: label(at) }))];
  const axisY = y0 <= 0 && 0 <= y1 ? sy(0) : sy(y0);
  const axisX = x0 <= 0 && 0 <= x1 ? sx(0) : sx(x0);
  if (spec.grid) {
    for (const t of xNice) parts.push(`<line class="grid" x1="${sx(t.at).toFixed(1)}" y1="${M.t}" x2="${sx(t.at).toFixed(1)}" y2="${M.t + ph}"/>`);
    for (const t of yNice) parts.push(`<line class="grid" x1="${M.l}" y1="${sy(t.at).toFixed(1)}" x2="${M.l + pw}" y2="${sy(t.at).toFixed(1)}"/>`);
  }
  // Axes with arrowheads.
  parts.push(`<line class="ax" x1="${M.l}" y1="${axisY.toFixed(1)}" x2="${M.l + pw + 6}" y2="${axisY.toFixed(1)}"/>`);
  parts.push(`<path class="axh" d="M${M.l + pw + 10},${axisY.toFixed(1)} l-7,-3.5 v7 z"/>`);
  parts.push(`<line class="ax" x1="${axisX.toFixed(1)}" y1="${M.t + ph}" x2="${axisX.toFixed(1)}" y2="${M.t - 6}"/>`);
  parts.push(`<path class="axh" d="M${axisX.toFixed(1)},${M.t - 10} l-3.5,7 h7 z"/>`);
  for (const t of xt) {
    if (Math.abs(t.at) < 1e-12 && x0 < 0 && y0 < 0) continue;
    parts.push(`<line class="ax" x1="${sx(t.at).toFixed(1)}" y1="${(axisY - 3).toFixed(1)}" x2="${sx(t.at).toFixed(1)}" y2="${(axisY + 3).toFixed(1)}"/>`);
    parts.push(`<text class="tk" x="${sx(t.at).toFixed(1)}" y="${Math.min(H - 4, axisY + 15).toFixed(1)}" text-anchor="middle">${t.text}</text>`);
  }
  for (const t of yt) {
    if (Math.abs(t.at) < ySpan * 1e-9) continue;
    parts.push(`<line class="ax" x1="${(axisX - 3).toFixed(1)}" y1="${sy(t.at).toFixed(1)}" x2="${(axisX + 3).toFixed(1)}" y2="${sy(t.at).toFixed(1)}"/>`);
    parts.push(`<text class="tk" x="${Math.max(12, axisX - 6).toFixed(1)}" y="${(sy(t.at) + 4).toFixed(1)}" text-anchor="end">${t.text}</text>`);
  }
  if ((spec.numbers.x || spec.numbers.y) && x0 < 0 && y0 < 0 && x1 > 0 && y1 > 0) parts.push(`<text class="tk" x="${(axisX - 5).toFixed(1)}" y="${(axisY + 14).toFixed(1)}" text-anchor="end">0</text>`);
  parts.push(`<text class="lab" x="${M.l + pw + 4}" y="${(axisY - 8).toFixed(1)}" text-anchor="end">${esc(spec.xLabel ?? spec.variable)}</text>`);
  parts.push(`<text class="lab" x="${(axisX + 8).toFixed(1)}" y="${M.t + 2}">${esc(spec.yLabel ?? (spec.variable === 't' ? 'x(t)' : spec.variable === 'n' ? 'x[n]' : 'y'))}</text>`);

  // Curves, clipped to the plot area.
  parts.push(`<clipPath id="${id}"><rect x="${M.l}" y="${M.t}" width="${pw}" height="${ph}"/></clipPath><g clip-path="url(#${id})">`);
  for (const a of spec.asymptotes) {
    parts.push(
      a.axis === 'x'
        ? `<line class="asym" x1="${sx(a.at).toFixed(1)}" y1="${M.t}" x2="${sx(a.at).toFixed(1)}" y2="${M.t + ph}"/>`
        : `<line class="asym" x1="${M.l}" y1="${sy(a.at).toFixed(1)}" x2="${M.l + pw}" y2="${sy(a.at).toFixed(1)}"/>`,
    );
  }
  if (drawn.some((d) => d.inverse)) {
    const lo = Math.max(x0, y0), hi = Math.min(x1, y1);
    if (hi > lo) parts.push(`<line class="asym" x1="${sx(lo).toFixed(1)}" y1="${sy(lo).toFixed(1)}" x2="${sx(hi).toFixed(1)}" y2="${sy(hi).toFixed(1)}"/>`);
  }
  for (const d of drawn) {
    if (d.inverse) {
      // The curve faint, and its inverse: the same points with x and y swapped (a mirror in y = x).
      const [a, b] = d.on ?? [Math.min(x0, y0), Math.max(x1, y1)];
      const orig = segments(d.g, a, b, ySpan, spec.jumps, [y0, y1]);
      parts.push(...orig.map((s) => path(s, d, true)));
      parts.push(...orig.map((s) => path(s.map(([x, y]) => [y, x] as [number, number]), d, false)));
    } else if (discrete) parts.push(...whole().map((n) => stem(n, d.g(n), d.color)));
    else parts.push(...segments(d.g, x0, x1, ySpan, spec.jumps, [y0, y1]).map((s) => path(s, d, false)));
  }
  if (spec.seq) spec.seq.values.forEach((v, i) => parts.push(stem(spec.seq!.start + i, v, seqColor)));
  // Impulses: arrows from the axis, as tall as their weight; the weight written by the tip unless it is 1.
  const pulses = [...spec.impulses, ...spec.trains.flatMap((t) => trainAt(t).map((x) => ({ x, w: t.w })))];
  const weighted = pulses.some((p) => Math.abs(p.w - 1) > 1e-12);
  for (const p of pulses) {
    if (p.x < x0 || p.x > x1 || Math.abs(p.w) < 1e-12) continue;
    const X = sx(p.x).toFixed(1), base = sy(0), tip = sy(p.w), dir = p.w > 0 ? 1 : -1;
    parts.push(`<line class="cv c-${pulseColor}" x1="${X}" y1="${base.toFixed(1)}" x2="${X}" y2="${(tip + dir * 6).toFixed(1)}" stroke-width="2"/>`);
    parts.push(`<path class="f-${pulseColor}" d="M${X},${tip.toFixed(1)} l-4.5,${dir * 9} h9 z"/>`);
    if (weighted) parts.push(`<text class="ptl" x="${(sx(p.x) + 6).toFixed(1)}" y="${(tip + (dir > 0 ? 4 : 10)).toFixed(1)}">(${label(p.w) || '0'})</text>`);
  }
  parts.push('</g>');
  // Discrete signals: a small tick at every whole n (numbers only when asked).
  if (discrete && !spec.numbers.x && whole().length <= 41) {
    for (const n of whole()) parts.push(`<line class="ax" x1="${sx(n).toFixed(1)}" y1="${(axisY - 2.5).toFixed(1)}" x2="${sx(n).toFixed(1)}" y2="${(axisY + 2.5).toFixed(1)}"/>`);
  }
  function stem(n: number, v: number, color: string) {
    if (!Number.isFinite(v)) return '';
    const X = sx(n).toFixed(1), Y = sy(v).toFixed(1);
    const line = Math.abs(v) > 1e-12 ? `<line class="cv c-${color}" x1="${X}" y1="${sy(0).toFixed(1)}" x2="${X}" y2="${Y}" stroke-width="1.8"/>` : '';
    return `${line}<circle class="f-${color}" cx="${X}" cy="${Y}" r="3.3"/>`;
  }
  function path(s: Seg, d: Drawn, faint: boolean) {
    const pts = s.map(([x, y], i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)},${clampY(sy(y)).toFixed(1)}`).join('');
    const dash = d.line === 'dash' ? ' stroke-dasharray="7 5"' : d.line === 'dot' ? ' stroke-dasharray="1.5 4" stroke-linecap="round"' : '';
    const w = faint ? 1.4 : d.width;
    return `<path class="cv c-${d.color}${faint ? ' faint' : ''}" d="${pts}" stroke-width="${w}"${dash}/>`;
  }
  const holes = spec.autoHoles ? drawn.filter((d) => !d.inverse).flatMap((d) => findHoles(d.g, x0, x1, ySpan)) : [];
  const given = (h: { x: number }) => spec.points.some((p) => Math.abs(p.x - h.x) < 1e-6 * (x1 - x0));
  for (const h of holes.filter((h) => !given(h) && h.y >= y0 && h.y <= y1)) {
    parts.push(`<circle class="pt-open" cx="${sx(h.x).toFixed(1)}" cy="${sy(h.y).toFixed(1)}" r="4"/>`);
  }
  for (const p of spec.points) {
    const cx = sx(p.x).toFixed(1), cy = sy(p.y).toFixed(1);
    parts.push(`<circle class="${p.open ? 'pt-open' : 'pt'}" cx="${cx}" cy="${cy}" r="4"/>`);
    if (p.label) parts.push(`<text class="ptl" x="${(sx(p.x) + 7).toFixed(1)}" y="${(sy(p.y) - 7).toFixed(1)}">${esc(p.label)}</text>`);
  }

  const svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img">${parts.join('')}</svg>`;
  const legend = drawn.filter((d) => d.name);
  const legendHtml = legend.length
    ? `<div class="plot-legend">${legend
        .map((d) => `<span><svg width="22" height="8" viewBox="0 0 22 8"><line class="cv c-${d.color}" x1="1" y1="4" x2="21" y2="4" stroke-width="2.4"${d.line === 'dash' ? ' stroke-dasharray="5 3"' : d.line === 'dot' ? ' stroke-dasharray="1.5 3" stroke-linecap="round"' : ''}/></svg>${inline(d.name!)}</span>`)
        .join('')}</div>`
    : '';
  const caption = spec.caption.length ? `<div class="plot-caption">${inline(spec.caption.join(' '))}</div>` : '';
  return `<div class="plot"><div class="plot-svg" dir="ltr">${svg}</div>${legendHtml}${caption}</div>`;
}

const circlePath = (cx: number, cy: number, r: number) =>
  `M${(cx + r).toFixed(1)},${cy.toFixed(1)}A${r.toFixed(1)},${r.toFixed(1)} 0 1 0 ${(cx - r).toFixed(1)},${cy.toFixed(1)}A${r.toFixed(1)},${r.toFixed(1)} 0 1 0 ${(cx + r).toFixed(1)},${cy.toFixed(1)}Z`;

/** Poles and zeros (× and ○) in the z plane with its unit circle, or in the s plane; the ROC shaded. */
function drawPoleZero(spec: PlotSpec, inline: (s: string) => string): string {
  const plane = spec.plane ?? spec.roc?.plane ?? 'z';
  const roc = spec.roc && { ...spec.roc, plane };
  const pts = [...spec.zeros, ...spec.poles];
  const finite = (v: number) => Number.isFinite(v) && v !== 0;
  const reach = Math.max(
    plane === 'z' ? 1.3 : 1,
    ...pts.map((p) => 1.25 * Math.max(Math.abs(p.re), Math.abs(p.im))),
    ...(roc ? [roc.lo, roc.hi].filter(finite).map((v) => 1.2 * Math.abs(v)) : []),
  );
  const H = 300, pw = W - M.l - M.r, ph = H - M.t - M.b;
  // The same scale both ways, so a circle is round.
  const k = ph / (2 * reach), xr = pw / (2 * k);
  const sx = (x: number) => M.l + pw / 2 + x * k, sy = (y: number) => M.t + ph / 2 - y * k;
  const id = `pc${++uid}`;
  const parts: string[] = [`<rect class="pbg" x="0" y="0" width="${W}" height="${H}" rx="10"/>`];
  parts.push(`<clipPath id="${id}"><rect x="${M.l}" y="${M.t}" width="${pw}" height="${ph}"/></clipPath><g clip-path="url(#${id})">`);
  if (roc) {
    // The region, then its edges dashed.
    if (plane === 'z') {
      const outer = Number.isFinite(roc.hi) ? circlePath(sx(0), sy(0), roc.hi * k) : `M0,0H${W}V${H}H0Z`;
      const inner = roc.lo > 0 ? circlePath(sx(0), sy(0), roc.lo * k) : '';
      parts.push(`<path class="roc" fill-rule="evenodd" d="${outer}${inner}"/>`);
      for (const r of [roc.lo, roc.hi]) if (finite(r) && Number.isFinite(r)) parts.push(`<circle class="roc-edge" cx="${sx(0).toFixed(1)}" cy="${sy(0).toFixed(1)}" r="${(r * k).toFixed(1)}"/>`);
    } else {
      const a = Math.max(roc.lo, -xr - 1), b = Math.min(roc.hi, xr + 1);
      parts.push(`<rect class="roc" x="${sx(a).toFixed(1)}" y="${M.t}" width="${(sx(b) - sx(a)).toFixed(1)}" height="${ph}"/>`);
      for (const r of [roc.lo, roc.hi]) if (Number.isFinite(r)) parts.push(`<line class="roc-edge" x1="${sx(r).toFixed(1)}" y1="${M.t}" x2="${sx(r).toFixed(1)}" y2="${M.t + ph}"/>`);
    }
  }
  if (spec.grid) {
    for (const t of ticks(-xr, xr, false, 8)) parts.push(`<line class="grid" x1="${sx(t.at).toFixed(1)}" y1="${M.t}" x2="${sx(t.at).toFixed(1)}" y2="${M.t + ph}"/>`);
    for (const t of ticks(-reach, reach, false, 6)) parts.push(`<line class="grid" x1="${M.l}" y1="${sy(t.at).toFixed(1)}" x2="${M.l + pw}" y2="${sy(t.at).toFixed(1)}"/>`);
  }
  if (plane === 'z') parts.push(`<circle class="unit" cx="${sx(0).toFixed(1)}" cy="${sy(0).toFixed(1)}" r="${k.toFixed(1)}"/>`);
  parts.push('</g>');
  // Axes through the origin.
  parts.push(`<line class="ax" x1="${M.l}" y1="${sy(0).toFixed(1)}" x2="${M.l + pw + 6}" y2="${sy(0).toFixed(1)}"/>`);
  parts.push(`<path class="axh" d="M${M.l + pw + 10},${sy(0).toFixed(1)} l-7,-3.5 v7 z"/>`);
  parts.push(`<line class="ax" x1="${sx(0).toFixed(1)}" y1="${M.t + ph}" x2="${sx(0).toFixed(1)}" y2="${M.t - 6}"/>`);
  parts.push(`<path class="axh" d="M${sx(0).toFixed(1)},${M.t - 10} l-3.5,7 h7 z"/>`);
  parts.push(`<text class="lab" x="${M.l + pw + 4}" y="${(sy(0) - 8).toFixed(1)}" text-anchor="end">${plane === 'z' ? 'Re{z}' : 'σ'}</text>`);
  parts.push(`<text class="lab" x="${(sx(0) + 8).toFixed(1)}" y="${M.t + 2}">${plane === 'z' ? 'Im{z}' : 'jω'}</text>`);
  const tick = (x: number, text: string, onY = false) =>
    onY
      ? `<line class="ax" x1="${(sx(0) - 3).toFixed(1)}" y1="${sy(x).toFixed(1)}" x2="${(sx(0) + 3).toFixed(1)}" y2="${sy(x).toFixed(1)}"/><text class="tk" x="${(sx(0) - 6).toFixed(1)}" y="${(sy(x) + 4).toFixed(1)}" text-anchor="end">${text}</text>`
      : `<line class="ax" x1="${sx(x).toFixed(1)}" y1="${(sy(0) - 3).toFixed(1)}" x2="${sx(x).toFixed(1)}" y2="${(sy(0) + 3).toFixed(1)}"/><text class="tk" x="${(sx(x) + (x === 1 ? 7 : 0)).toFixed(1)}" y="${(sy(0) + 15).toFixed(1)}" text-anchor="middle">${text}</text>`;
  // Numbers on the real axis, never two on top of each other (the first one asked for wins).
  const placed: number[] = [];
  const mark = (x: number, text: string) => {
    if (placed.some((p) => Math.abs(sx(p) - sx(x)) < 20)) return;
    placed.push(x);
    parts.push(tick(x, text));
  };
  for (const x of spec.marks.x) mark(x, fa(+x.toFixed(3)));
  // The edges of the ROC and the unit circle's 1 are always marked.
  if (roc) for (const r of [roc.lo, roc.hi]) if (finite(r) && Number.isFinite(r)) mark(r, fa(+r.toFixed(3)));
  if (plane === 'z') mark(1, '1');
  if (spec.numbers.x) for (const t of ticks(-xr, xr, false, 8)) if (Math.abs(t.at) > 1e-12) mark(t.at, t.text);
  if (spec.numbers.y) for (const t of ticks(-reach, reach, false, 6)) if (Math.abs(t.at) > 1e-12) parts.push(tick(t.at, t.text, true));
  // Zeros ○ and poles ×; a repeated one is drawn once with its count.
  const draw = (list: Cx[], pole: boolean) => {
    const seen = new Map<string, { p: Cx; n: number }>();
    for (const p of list) {
      const key = `${p.re.toFixed(6)},${p.im.toFixed(6)}`;
      const hit = seen.get(key);
      if (hit) hit.n++;
      else seen.set(key, { p, n: 1 });
    }
    for (const { p, n } of seen.values()) {
      const X = sx(p.re), Y = sy(p.im);
      parts.push(
        pole
          ? `<path class="pole" d="M${(X - 5).toFixed(1)},${(Y - 5).toFixed(1)}l10,10M${(X + 5).toFixed(1)},${(Y - 5).toFixed(1)}l-10,10"/>`
          : `<circle class="zero" cx="${X.toFixed(1)}" cy="${Y.toFixed(1)}" r="5"/>`,
      );
      if (n > 1) parts.push(`<text class="ptl" x="${(X + 7).toFixed(1)}" y="${(Y - 6).toFixed(1)}">(${n})</text>`);
    }
  };
  draw(spec.zeros, false);
  draw(spec.poles, true);
  const svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img">${parts.join('')}</svg>`;
  const legend: string[] = [];
  if (spec.zeros.length) legend.push(`<span><svg width="14" height="14" viewBox="0 0 14 14"><circle class="zero" cx="7" cy="7" r="5"/></svg>صفر</span>`);
  if (spec.poles.length) legend.push(`<span><svg width="14" height="14" viewBox="0 0 14 14"><path class="pole" d="M2,2l10,10M12,2l-10,10"/></svg>قطب</span>`);
  if (roc) legend.push(`<span><svg width="16" height="12" viewBox="0 0 16 12"><rect class="roc" x="1" y="1" width="14" height="10" rx="2"/></svg>ناحیه‌ی همگرایی</span>`);
  const caption = spec.caption.length ? `<div class="plot-caption">${inline(spec.caption.join(' '))}</div>` : '';
  return `<div class="plot"><div class="plot-svg" dir="ltr">${svg}</div><div class="plot-legend">${legend.join('')}</div>${caption}</div>`;
}

/** H(jω) of H(s) = K ∏(s − z) / ∏(s − p): magnitude in dB, its straight-line (asymptotic) form, and phase in degrees. */
export function bodeAt(spec: Pick<PlotSpec, 'zeros' | 'poles' | 'gain'>, w: number): { db: number; straight: number; phase: number } {
  let mag = Math.abs(spec.gain), straight = Math.abs(spec.gain), phase = spec.gain < 0 ? 180 : 0;
  const factor = (c: Cx, sign: 1 | -1) => {
    const re = -c.re, im = w - c.im;
    mag *= Math.hypot(re, im) ** sign;
    const r = Math.hypot(c.re, c.im);
    straight *= (r > 0 ? Math.max(w, r) : w) ** sign;
    phase += sign * (Math.atan2(im, re) * 180) / Math.PI;
  };
  spec.zeros.forEach((z) => factor(z, 1));
  spec.poles.forEach((p) => factor(p, -1));
  return { db: 20 * Math.log10(mag), straight: 20 * Math.log10(straight), phase };
}

function decadeLabel(k: number): string {
  if (k >= -3 && k <= 3) return fa(String(10 ** k >= 1 ? 10 ** k : (10 ** k).toFixed(-k)));
  return `10<tspan dy="-5" font-size="8">${fa(k)}</tspan>`;
}

/** Bode plot: magnitude (exact, and the straight lines) and phase over a logarithmic ω axis. */
function drawBode(spec: PlotSpec, inline: (s: string) => string): string {
  const corners = [...spec.zeros, ...spec.poles].map((c) => Math.hypot(c.re, c.im)).filter((r) => r > 0);
  const [w0, w1] = spec.x && spec.x[0] > 0
    ? spec.x
    : [10 ** (Math.floor(Math.log10(Math.min(...corners, 1))) - 1), 10 ** (Math.ceil(Math.log10(Math.max(...corners, 1))) + 1)];
  const L = { l: 46, r: 14 };
  const pw = W - L.l - L.r;
  const lx0 = Math.log10(w0), lx1 = Math.log10(w1);
  const sx = (w: number) => L.l + ((Math.log10(w) - lx0) / (lx1 - lx0)) * pw;
  const N = 480;
  const ws = Array.from({ length: N + 1 }, (_, i) => 10 ** (lx0 + ((lx1 - lx0) * i) / N));
  const vals = ws.map((w) => {
    const v = bodeAt(spec, w);
    if (!spec.tf) return v;
    // Written as H(s): the exact curve straight from it (the roots only give the straight lines).
    const h = evalAt(spec.tf, w);
    const p = (Math.atan2(h.im, h.re) * 180) / Math.PI;
    // The same branch as the phase added up from the roots (so 1/s² starts at −180°, not +180°).
    return { ...v, db: 20 * Math.log10(Math.hypot(h.re, h.im)), phase: p + 360 * Math.round((v.phase - p) / 360) };
  });
  // Phase without the jumps of ±360° that atan2 makes.
  for (let i = 1; i < vals.length; i++) {
    while (vals[i].phase - vals[i - 1].phase > 180) vals[i].phase -= 360;
    while (vals[i].phase - vals[i - 1].phase < -180) vals[i].phase += 360;
  }
  const panels: { title: string; ys: number[][]; step: (span: number) => number; h: number }[] = [
    { title: '|H| (dB)', ys: [vals.map((v) => v.db), ...(spec.straight ? [vals.map((v) => v.straight)] : [])], h: 190, step: (span) => (span > 120 ? 40 : span > 60 ? 20 : span > 24 ? 10 : niceStep(span, 5)) },
  ];
  if (spec.phase) panels.push({ title: '∠H (°)', ys: [vals.map((v) => v.phase)], h: 160, step: (span) => [15, 30, 45, 90, 180].find((s) => span / s <= 6) ?? 360 });
  const gap = 26, top = 18;
  const H = top + panels.reduce((n, p) => n + p.h, 0) + gap * (panels.length - 1) + 30;
  const id = `pc${++uid}`;
  const parts: string[] = [`<rect class="pbg" x="0" y="0" width="${W}" height="${H}" rx="10"/>`];
  let y = top;
  panels.forEach((panel, pi) => {
    const finite = panel.ys.flat().filter(Number.isFinite);
    let lo = Math.min(...finite), hi = Math.max(...finite);
    if (hi - lo < 1e-6) { lo -= 10; hi += 10; }
    const step = panel.step(hi - lo);
    lo = Math.floor(lo / step - 0.15) * step; hi = Math.ceil(hi / step + 0.15) * step;
    const sy = (v: number) => y + ((hi - v) / (hi - lo)) * panel.h;
    // Decades: solid lines; 2…9 in between: faint.
    for (let k = Math.ceil(lx0 - 1e-9); k <= lx1 + 1e-9; k++) {
      parts.push(`<line class="grid strong" x1="${sx(10 ** k).toFixed(1)}" y1="${y}" x2="${sx(10 ** k).toFixed(1)}" y2="${y + panel.h}"/>`);
      if (pi === panels.length - 1) parts.push(`<text class="tk" x="${sx(10 ** k).toFixed(1)}" y="${y + panel.h + 14}" text-anchor="middle">${decadeLabel(k)}</text>`);
      for (let m = 2; m <= 9; m++) {
        const w = m * 10 ** k;
        if (w > w0 && w < w1) parts.push(`<line class="grid" x1="${sx(w).toFixed(1)}" y1="${y}" x2="${sx(w).toFixed(1)}" y2="${y + panel.h}"/>`);
      }
    }
    for (let v = lo; v <= hi + 1e-9; v += step) {
      parts.push(`<line class="grid${Math.abs(v) < 1e-9 ? ' strong' : ''}" x1="${L.l}" y1="${sy(v).toFixed(1)}" x2="${L.l + pw}" y2="${sy(v).toFixed(1)}"/>`);
      parts.push(`<text class="tk" x="${L.l - 5}" y="${(sy(v) + 3.5).toFixed(1)}" text-anchor="end">${fa(+v.toFixed(1))}</text>`);
    }
    parts.push(`<rect class="frame" x="${L.l}" y="${y}" width="${pw}" height="${panel.h}"/>`);
    parts.push(`<text class="tk" x="${L.l + 4}" y="${y - 5}">${panel.title}</text>`);
    parts.push(`<clipPath id="${id}-${pi}"><rect x="${L.l}" y="${y}" width="${pw}" height="${panel.h}"/></clipPath><g clip-path="url(#${id}-${pi})">`);
    panel.ys.forEach((ys, j) => {
      // A zero on the jω axis sends the magnitude to −∞ there: held just below the panel instead.
      const clamp = (v: number) => (Number.isFinite(v) ? Math.max(lo - (hi - lo), Math.min(hi + (hi - lo), v)) : lo - (hi - lo));
      const d = ys.map((v, i) => `${i ? 'L' : 'M'}${sx(ws[i]).toFixed(1)},${sy(clamp(v)).toFixed(1)}`).join('');
      parts.push(j === 0 ? `<path class="cv c-blue" d="${d}" stroke-width="2.2"/>` : `<path class="cv c-red" d="${d}" stroke-width="1.6" stroke-dasharray="6 4"/>`);
    });
    parts.push('</g>');
    y += panel.h + gap;
  });
  parts.push(`<text class="lab" x="${L.l + pw}" y="${H - 4}" text-anchor="end">ω (rad/s)</text>`);
  const svg = `<svg viewBox="0 0 ${W} ${H}" xmlns="http://www.w3.org/2000/svg" role="img">${parts.join('')}</svg>`;
  const legend = spec.straight
    ? `<div class="plot-legend"><span><svg width="22" height="8" viewBox="0 0 22 8"><line class="cv c-blue" x1="1" y1="4" x2="21" y2="4" stroke-width="2.2"/></svg>دقیق</span><span><svg width="22" height="8" viewBox="0 0 22 8"><line class="cv c-red" x1="1" y1="4" x2="21" y2="4" stroke-width="1.6" stroke-dasharray="5 3"/></svg>مجانبی (خط‌های راست)</span></div>`
    : '';
  const caption = spec.caption.length ? `<div class="plot-caption">${inline(spec.caption.join(' '))}</div>` : '';
  return `<div class="plot"><div class="plot-svg" dir="ltr">${svg}</div>${legend}${caption}</div>`;
}

/** Nyquist plot: H(jω) in the complex plane for ω from 0 to ∞ (solid, with arrows) and its mirror for ω < 0 (dashed),
 * with the point −1 marked. Same scale both ways. */
function drawNyquist(spec: PlotSpec, inline: (s: string) => string): string {
  const H = (w: number) => {
    if (spec.tf) return evalAt(spec.tf, w);
    const b = bodeAt(spec, w);
    const m = 10 ** (b.db / 20), a = (b.phase * Math.PI) / 180;
    return { re: m * Math.cos(a), im: m * Math.sin(a) };
  };
  const corners = [...spec.zeros, ...spec.poles].map((c) => Math.hypot(c.re, c.im)).filter((r) => r > 0);
  const lo = 10 ** (Math.floor(Math.log10(Math.min(...corners, 1))) - 3), hi = 10 ** (Math.ceil(Math.log10(Math.max(...corners, 1))) + 3);
  const N = 900;
  const pts = Array.from({ length: N + 1 }, (_, i) => H(10 ** (Math.log10(lo) + ((Math.log10(hi) - Math.log10(lo)) * i) / N))).filter(
    (p) => Number.isFinite(p.re) && Number.isFinite(p.im),
  );
  // The window: the curve around the corners (a decade either side), and −1 and 0. With a pole on the jω axis the curve
  // runs off to infinity at low ω: then three quarters of it, so −1 and the turn near the origin stay readable.
  const cmin = Math.min(...corners, 1), cmax = Math.max(...corners, 1);
  const near = Array.from({ length: 200 }, (_, i) => H(10 ** (Math.log10(cmin / 10) + ((Math.log10(cmax * 10) - Math.log10(cmin / 10)) * i) / 199)))
    .filter((p) => Number.isFinite(p.re) && Number.isFinite(p.im))
    .map((p) => Math.max(Math.abs(p.re), Math.abs(p.im)))
    .sort((a, b) => a - b);
  const onAxis = spec.poles.some((p) => Math.abs(p.re) < 1e-9);
  const big = near.length ? (onAxis ? near[Math.floor(0.75 * (near.length - 1))] : near[near.length - 1]) : 1;
  const reach = Math.max(1.3, 1.15 * big);
  const Hh = 300, pw = W - M.l - M.r, ph = Hh - M.t - M.b;
  const k = ph / (2 * reach), xr = pw / (2 * k);
  const sx = (x: number) => M.l + pw / 2 + x * k, sy = (y: number) => M.t + ph / 2 - y * k;
  const id = `pc${++uid}`;
  const clampP = (v: number) => Math.max(-4 * Hh, Math.min(5 * Hh, v));
  const line = (list: { re: number; im: number }[], mirror: boolean) =>
    list.map((p, i) => `${i ? 'L' : 'M'}${clampP(sx(p.re)).toFixed(1)},${clampP(sy(mirror ? -p.im : p.im)).toFixed(1)}`).join('');
  const parts: string[] = [`<rect class="pbg" x="0" y="0" width="${W}" height="${Hh}" rx="10"/>`];
  if (spec.grid) {
    for (const t of ticks(-xr, xr, false, 8)) parts.push(`<line class="grid" x1="${sx(t.at).toFixed(1)}" y1="${M.t}" x2="${sx(t.at).toFixed(1)}" y2="${M.t + ph}"/>`);
    for (const t of ticks(-reach, reach, false, 6)) parts.push(`<line class="grid" x1="${M.l}" y1="${sy(t.at).toFixed(1)}" x2="${M.l + pw}" y2="${sy(t.at).toFixed(1)}"/>`);
  }
  parts.push(`<line class="ax" x1="${M.l}" y1="${sy(0).toFixed(1)}" x2="${M.l + pw + 6}" y2="${sy(0).toFixed(1)}"/>`);
  parts.push(`<path class="axh" d="M${M.l + pw + 10},${sy(0).toFixed(1)} l-7,-3.5 v7 z"/>`);
  parts.push(`<line class="ax" x1="${sx(0).toFixed(1)}" y1="${M.t + ph}" x2="${sx(0).toFixed(1)}" y2="${M.t - 6}"/>`);
  parts.push(`<path class="axh" d="M${sx(0).toFixed(1)},${M.t - 10} l-3.5,7 h7 z"/>`);
  parts.push(`<text class="lab" x="${M.l + pw + 4}" y="${(sy(0) - 8).toFixed(1)}" text-anchor="end">Re</text>`);
  parts.push(`<text class="lab" x="${(sx(0) + 8).toFixed(1)}" y="${M.t + 2}">Im</text>`);
  parts.push(`<clipPath id="${id}"><rect x="${M.l}" y="${M.t}" width="${pw}" height="${ph}"/></clipPath><g clip-path="url(#${id})">`);
  parts.push(`<path class="cv c-blue" d="${line(pts, true)}" stroke-width="1.6" stroke-dasharray="6 4" opacity=".6"/>`);
  parts.push(`<path class="cv c-blue" d="${line(pts, false)}" stroke-width="2.2"/>`);
  // Arrows along ω > 0 (and the mirrored way on the dashed half), at a third and two thirds of the visible path.
  const inView = pts.map((p, i) => ({ p, i })).filter(({ p }) => Math.abs(p.re) <= reach * 1.2 && Math.abs(p.im) <= reach * 1.2);
  for (const f of [0.33, 0.66]) {
    const at = inView[Math.floor(f * (inView.length - 1))];
    if (!at || at.i + 1 >= pts.length) continue;
    for (const mirror of [false, true]) {
      const a = pts[at.i], b = pts[Math.min(pts.length - 1, at.i + 3)];
      const x = sx(a.re), y = sy(mirror ? -a.im : a.im);
      // On the mirrored half ω runs from −∞ up to 0, so its arrow points back along the drawn path.
      const dx = (sx(b.re) - x) * (mirror ? -1 : 1), dy = (sy(mirror ? -b.im : b.im) - y) * (mirror ? -1 : 1);
      const ang = (Math.atan2(dy, dx) * 180) / Math.PI;
      parts.push(`<path class="f-blue" transform="translate(${x.toFixed(1)},${y.toFixed(1)}) rotate(${ang.toFixed(1)})" d="M5,0 L-4,-4 L-4,4 Z"${mirror ? ' opacity=".6"' : ''}/>`);
    }
  }
  parts.push('</g>');
  // −1: what the plot is about (the critical point).
  if (-1 >= -xr) {
    parts.push(`<path class="pole" d="M${(sx(-1) - 4.5).toFixed(1)},${(sy(0) - 4.5).toFixed(1)}l9,9M${(sx(-1) + 4.5).toFixed(1)},${(sy(0) - 4.5).toFixed(1)}l-9,9"/>`);
    parts.push(`<text class="tk" x="${sx(-1).toFixed(1)}" y="${(sy(0) + 16).toFixed(1)}" text-anchor="middle">−1</text>`);
  }
  if (spec.numbers.x) for (const t of ticks(-xr, xr, false, 8)) if (Math.abs(t.at) > 1e-12 && Math.abs(t.at + 1) > 1e-9) parts.push(`<text class="tk" x="${sx(t.at).toFixed(1)}" y="${(sy(0) + 15).toFixed(1)}" text-anchor="middle">${t.text}</text>`);
  if (spec.numbers.y) for (const t of ticks(-reach, reach, false, 6)) if (Math.abs(t.at) > 1e-12) parts.push(`<text class="tk" x="${(sx(0) - 6).toFixed(1)}" y="${(sy(t.at) + 4).toFixed(1)}" text-anchor="end">${t.text}</text>`);
  const svg = `<svg viewBox="0 0 ${W} ${Hh}" xmlns="http://www.w3.org/2000/svg" role="img">${parts.join('')}</svg>`;
  const legend = `<div class="plot-legend"><span><svg width="22" height="8" viewBox="0 0 22 8"><line class="cv c-blue" x1="1" y1="4" x2="21" y2="4" stroke-width="2.2"/></svg>ω &gt; 0</span><span><svg width="22" height="8" viewBox="0 0 22 8"><line class="cv c-blue" x1="1" y1="4" x2="21" y2="4" stroke-width="1.6" stroke-dasharray="5 3" opacity=".6"/></svg>ω &lt; 0</span></div>`;
  const caption = spec.caption.length ? `<div class="plot-caption">${inline(spec.caption.join(' '))}</div>` : '';
  return `<div class="plot"><div class="plot-svg" dir="ltr">${svg}</div>${legend}${caption}</div>`;
}

const FILLS: Record<string, [string, string]> = {
  blue: ['#2F6BD8', '#7FA8F5'], red: ['#D6453A', '#F28A80'], green: ['#23945A', '#6FD39B'], orange: ['#E07B1F', '#F5B26B'],
  purple: ['#7E4FD0', '#B79AF0'], pink: ['#C93F8E', '#EE8CC3'], gray: ['#6B7A70', '#A9B4AD'], yellow: ['#B89400', '#F5C518'], ink: ['#17201A', '#E4E9E2'],
};
const FILL_CSS = Object.entries(FILLS).map(([k, [light, dark]]) => `.f-${k} { fill: ${light}; } .lesson.dark .f-${k} { fill: ${dark}; }`).join('\n');

export const PLOT_CSS = `
.plot { margin: 4px 0 6px; }
.plot-svg svg { display: block; width: 100%; max-width: 560px; height: auto; margin: 0 auto; }
.plot .pbg { fill: #FFFFFF; }
.plot .grid { stroke: #E9ECF4; stroke-width: 1; }
.plot .ax { stroke: #6B7A70; stroke-width: 1.1; }
.plot .axh { fill: #6B7A70; }
.plot .tk { fill: #56655B; font-size: 10.5px; }
.plot .lab { fill: #17201A; font-size: 13px; font-style: italic; font-family: Georgia, 'Times New Roman', serif; }
.plot .asym { stroke: #9AA59E; stroke-width: 1.1; stroke-dasharray: 5 4; }
.plot .cv { fill: none; stroke-linejoin: round; stroke-linecap: round; }
.plot .cv.faint { opacity: .35; }
.plot .pt { fill: #17201A; } .plot .pt-open { fill: #FFFFFF; stroke: #17201A; stroke-width: 1.6; }
.plot .ptl { fill: #17201A; font-size: 12px; font-style: italic; font-family: Georgia, serif; }
.c-blue { stroke: #2F6BD8; } .c-red { stroke: #D6453A; } .c-green { stroke: #23945A; } .c-orange { stroke: #E07B1F; }
.c-purple { stroke: #7E4FD0; } .c-pink { stroke: #C93F8E; } .c-gray { stroke: #6B7A70; } .c-yellow { stroke: #B89400; } .c-ink { stroke: #17201A; }
.plot-legend { display: flex; flex-wrap: wrap; gap: 4px 14px; justify-content: center; font-size: .85em; margin-top: 6px; }
.plot-legend span { display: inline-flex; align-items: center; gap: 6px; }
.plot-caption { text-align: center; font-size: .88em; color: #56655B; margin-top: 4px; }
.plot-error { background: #FFF0EE; color: #9E2F2A; border-radius: 10px; padding: 8px 10px; font-size: .88em; }
.lesson.dark .plot .pbg { fill: #161E19; } .lesson.dark .plot .grid { stroke: #26302A; }
.lesson.dark .plot .ax { stroke: #8C9A90; } .lesson.dark .plot .axh { fill: #8C9A90; } .lesson.dark .plot .tk { fill: #A9B4AD; }
.lesson.dark .plot .lab, .lesson.dark .plot .ptl { fill: #E4E9E2; } .lesson.dark .plot .pt { fill: #E4E9E2; }
.lesson.dark .plot .pt-open { fill: #161E19; stroke: #E4E9E2; } .lesson.dark .plot-caption { color: #A9B4AD; }
.lesson.dark .c-blue { stroke: #7FA8F5; } .lesson.dark .c-red { stroke: #F28A80; } .lesson.dark .c-green { stroke: #6FD39B; }
.lesson.dark .c-orange { stroke: #F5B26B; } .lesson.dark .c-purple { stroke: #B79AF0; } .lesson.dark .c-pink { stroke: #EE8CC3; }
.lesson.dark .c-gray { stroke: #A9B4AD; } .lesson.dark .c-yellow { stroke: #F5C518; } .lesson.dark .c-ink { stroke: #E4E9E2; }
.lesson.dark .plot-error { background: #2E1F1E; color: #F28A80; }
.lesson.sepia .plot .pbg { fill: #FFFBF0; } .lesson.sepia .plot .pt-open { fill: #FFFBF0; }
.plot .grid.strong { stroke: #D3D9E4; } .plot .frame { fill: none; stroke: #9AA59E; stroke-width: 1; }
.plot .unit { fill: none; stroke: #6B7A70; stroke-width: 1.2; stroke-dasharray: 4 3; }
.plot .roc { fill: rgba(47, 107, 216, .13); stroke: none; } .plot .roc-edge { fill: none; stroke: #2F6BD8; stroke-width: 1.2; stroke-dasharray: 5 4; }
.plot .pole { stroke: #D6453A; stroke-width: 2.2; stroke-linecap: round; fill: none; }
.plot .zero { fill: #FFFFFF; stroke: #2F6BD8; stroke-width: 2; }
.lesson.dark .plot .grid.strong { stroke: #34403A; } .lesson.dark .plot .frame { stroke: #5D6B62; } .lesson.dark .plot .unit { stroke: #8C9A90; }
.lesson.dark .plot .roc { fill: rgba(127, 168, 245, .16); } .lesson.dark .plot .roc-edge { stroke: #7FA8F5; }
.lesson.dark .plot .pole { stroke: #F28A80; } .lesson.dark .plot .zero { fill: #161E19; stroke: #7FA8F5; }
.lesson.sepia .plot .zero { fill: #FFFBF0; }
${FILL_CSS}
`;
