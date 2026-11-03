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
 * Formulas: lib/expr.ts. Checked by scripts/plot-check.ts.
 */
import { compile, ExprError, value, type Compiled } from './expr';

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
export type PlotSpec = {
  curves: Curve[];
  x?: [number, number];
  y?: [number, number];
  piAxis: boolean;
  variable: 'x' | 't';
  xLabel?: string;
  yLabel?: string;
  jumps: 'break' | 'vertical';
  grid: boolean;
  height: number;
  points: Point[];
  asymptotes: { axis: 'x' | 'y'; at: number }[];
  caption: string[];
};

export const COLORS: Record<string, string> = {
  آبی: 'blue', قرمز: 'red', سبز: 'green', نارنجی: 'orange', بنفش: 'purple', صورتی: 'pink', خاکستری: 'gray',
  زرد: 'yellow', مشکی: 'ink', سیاه: 'ink',
};
const PALETTE = ['blue', 'red', 'green', 'orange', 'purple', 'pink', 'yellow', 'gray'];

const W = 360;
const M = { l: 34, r: 14, t: 14, b: 24 };
const SAMPLES = 1400;

const FA = '۰۱۲۳۴۵۶۷۸۹';
const fa = (s: string | number) => String(s).replace(/\d/g, (d) => FA[Number(d)]).replace(/-/g, '−').replace(/\./g, '٫');
const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);

export class PlotError extends Error {}

function key(raw: string): string {
  return raw.replace(/[‌\s]/g, '').replace(/ي/g, 'ی').replace(/ك/g, 'ک').toLowerCase();
}
const KEYS: Record<string, string> = {
  تابع: 'fn', روی: 'on', دامنه: 'on', گسترش: 'ext', تناوب: 'period', دوره: 'period', فوریه: 'fourier', سریفوریه: 'fourier',
  رنگ: 'color', خط: 'line', نام: 'name', معکوس: 'inverse', وارون: 'inverse',
  بازه: 'x', بازهx: 'x', بازهیx: 'x', بازهی: 'x', بازهy: 'y', بازهیy: 'y', محدودهy: 'y', محدودهیy: 'y',
  محور: 'axis', متغیر: 'var', برچسبx: 'xlabel', برچسبy: 'ylabel', پرش: 'jumps', شبکه: 'grid', ارتفاع: 'height',
  نقطه: 'point', مجانب: 'asym',
};
const CURVE_KEYS = new Set(['on', 'ext', 'period', 'fourier', 'color', 'line', 'name', 'inverse']);

/** A box's lines → a plot description, or null when the box has no «تابع:» line (an ordinary box, e.g. a picture). */
export function parsePlot(body: string): PlotSpec | null {
  const lines = (body ?? '').split('\n');
  const keyed = lines.map((l) => {
    const m = /^\s*([^:：]{1,20}?)\s*[:：]\s*(.*)$/.exec(l);
    const k = m ? KEYS[key(m[1])] : undefined;
    return k ? { k, v: m![2].trim() } : null;
  });
  if (!keyed.some((x) => x?.k === 'fn')) return null;
  const spec: PlotSpec = {
    curves: [], piAxis: false, variable: 'x', jumps: 'break', grid: true, height: 225, points: [], asymptotes: [], caption: [],
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
        case 'axis': spec.piAxis = /pi|π/i.test(v); break;
        case 'var': spec.variable = /t/i.test(v) ? 't' : 'x'; break;
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
      if (e instanceof PlotError || e instanceof ExprError) throw new PlotError(e.message + where);
      throw e;
    }
  });
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

function niceStep(span: number, target: number): number {
  const raw = span / target, mag = Math.pow(10, Math.floor(Math.log10(raw))), n = raw / mag;
  return (n < 1.5 ? 1 : n < 3 ? 2 : n < 7 ? 5 : 10) * mag;
}
function gcd(a: number, b: number): number { return b ? gcd(b, a % b) : Math.abs(a); }
function piLabel(v: number): string {
  const q = Math.round((v / Math.PI) * 12);
  if (q === 0) return '۰';
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
    html = spec ? draw(spec, inline) : null;
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
      sums.forEach((s, i) => drawn.push({ g: s, color: nextColor(), line: 'solid', width: 1.6, name: `مجموع تا n = ${fa(c.fourier[i])}`, inverse: false }));
    }
    drawn.push({ g, color, line: c.line, width: 2.4, name: c.name, inverse: c.inverse, on: c.on, period });
  }

  // x window: given, or the definition intervals, or −10…10 (−2π…2π on a π axis).
  let [x0, x1] = spec.x ?? (() => {
    // A periodic curve: two periods each side; curves only on an interval: that interval; otherwise a usual window.
    const T = Math.max(0, ...drawn.map((d) => d.period ?? 0));
    if (T) return [-2 * T, 2 * T] as [number, number];
    const ons = spec.curves.filter((c) => c.on).map((c) => c.on!);
    if (ons.length === spec.curves.length && ons.length) {
      const lo = Math.min(...ons.map((o) => o[0])), hi = Math.max(...ons.map((o) => o[1])), pad = 0.05 * (hi - lo);
      return [lo - pad, hi + pad] as [number, number];
    }
    return spec.piAxis ? [-2 * Math.PI, 2 * Math.PI] : [-10, 10];
  })();
  if (x1 <= x0) x1 = x0 + 1;

  // y window: given, or from the values (ignoring the far ends near asymptotes).
  let y0: number, y1: number;
  const sample = (d: Drawn) => {
    const ys: number[] = [];
    for (let i = 0; i <= 400; i++) { const y = d.g(x0 + ((x1 - x0) * i) / 400); if (Number.isFinite(y)) ys.push(y); }
    // An inverse's values are the curve's x: its definition interval must fit too.
    if (d.inverse) ys.push(...(d.on ?? [x0, x1]));
    return ys;
  };
  if (spec.y) [y0, y1] = spec.y;
  else {
    const vals = drawn.flatMap(sample).concat(spec.points.map((p) => p.y)).sort((a, b) => a - b);
    if (!vals.length) { y0 = -1; y1 = 1; } else {
      const q = (p: number) => vals[Math.min(vals.length - 1, Math.max(0, Math.round(p * (vals.length - 1))))];
      let lo = vals[0], hi = vals[vals.length - 1];
      const qlo = q(0.03), qhi = q(0.97);
      if (hi - lo > 4 * (qhi - qlo || 1)) { lo = qlo; hi = qhi; }
      if (hi - lo < 1e-9) { lo -= 1; hi += 1; }
      // Keep 0 in view when it is close, so the x axis shows.
      if (lo > 0 && lo < 0.35 * (hi - lo)) lo = 0;
      if (hi < 0 && -hi < 0.35 * (hi - lo)) hi = 0;
      const pad = 0.08 * (hi - lo);
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
  const xt = ticks(x0, x1, spec.piAxis, 8), yt = ticks(y0, y1, false, 5);
  const axisY = y0 <= 0 && 0 <= y1 ? sy(0) : sy(y0);
  const axisX = x0 <= 0 && 0 <= x1 ? sx(0) : sx(x0);
  if (spec.grid) {
    for (const t of xt) parts.push(`<line class="grid" x1="${sx(t.at).toFixed(1)}" y1="${M.t}" x2="${sx(t.at).toFixed(1)}" y2="${M.t + ph}"/>`);
    for (const t of yt) parts.push(`<line class="grid" x1="${M.l}" y1="${sy(t.at).toFixed(1)}" x2="${M.l + pw}" y2="${sy(t.at).toFixed(1)}"/>`);
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
  if (x0 < 0 && y0 < 0 && x1 > 0 && y1 > 0) parts.push(`<text class="tk" x="${(axisX - 5).toFixed(1)}" y="${(axisY + 14).toFixed(1)}" text-anchor="end">۰</text>`);
  parts.push(`<text class="lab" x="${M.l + pw + 4}" y="${(axisY - 8).toFixed(1)}" text-anchor="end">${esc(spec.xLabel ?? spec.variable)}</text>`);
  parts.push(`<text class="lab" x="${(axisX + 8).toFixed(1)}" y="${M.t + 2}">${esc(spec.yLabel ?? (spec.variable === 't' ? 'x(t)' : 'y'))}</text>`);

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
    } else parts.push(...segments(d.g, x0, x1, ySpan, spec.jumps, [y0, y1]).map((s) => path(s, d, false)));
  }
  parts.push('</g>');
  function path(s: Seg, d: Drawn, faint: boolean) {
    const pts = s.map(([x, y], i) => `${i ? 'L' : 'M'}${sx(x).toFixed(1)},${clampY(sy(y)).toFixed(1)}`).join('');
    const dash = d.line === 'dash' ? ' stroke-dasharray="7 5"' : d.line === 'dot' ? ' stroke-dasharray="1.5 4" stroke-linecap="round"' : '';
    const w = faint ? 1.4 : d.width;
    return `<path class="cv c-${d.color}${faint ? ' faint' : ''}" d="${pts}" stroke-width="${w}"${dash}/>`;
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
`;
