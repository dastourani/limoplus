/**
 * Transfer functions written as in the book, «10(s+1)/((s+10)(s+100))», for the Bode and Nyquist plots (lib/plot.ts).
 * The text is read into a ratio of two polynomials in s (numbers, s, pi, e, brackets, + − × ÷ and whole powers, with
 * implicit multiplication), so H(jω) is exact, and the poles and zeros (for the straight-line Bode plot) come from the
 * roots of the two polynomials. Checked by scripts/plot-check.ts.
 */
import { normalizeExpr } from './expr';

export type Cx = { re: number; im: number };
/** Coefficients, lowest power first: [a0, a1, a2] is a0 + a1·s + a2·s². */
export type Poly = number[];
export type Rational = { num: Poly; den: Poly };

export class TransferError extends Error {}

const trim = (p: Poly): Poly => {
  const out = [...p];
  while (out.length > 1 && Math.abs(out[out.length - 1]) < 1e-14) out.pop();
  return out;
};
const add = (a: Poly, b: Poly): Poly => trim(Array.from({ length: Math.max(a.length, b.length) }, (_, i) => (a[i] ?? 0) + (b[i] ?? 0)));
const mul = (a: Poly, b: Poly): Poly => {
  const out = new Array(a.length + b.length - 1).fill(0);
  a.forEach((x, i) => b.forEach((y, j) => (out[i + j] += x * y)));
  return trim(out);
};
const scale = (a: Poly, k: number): Poly => trim(a.map((x) => x * k));

const R = {
  add: (a: Rational, b: Rational): Rational => ({ num: add(mul(a.num, b.den), mul(b.num, a.den)), den: mul(a.den, b.den) }),
  neg: (a: Rational): Rational => ({ num: scale(a.num, -1), den: a.den }),
  mul: (a: Rational, b: Rational): Rational => ({ num: mul(a.num, b.num), den: mul(a.den, b.den) }),
  div: (a: Rational, b: Rational): Rational => {
    if (b.num.every((x) => Math.abs(x) < 1e-14)) throw new TransferError('تقسیم بر صفر در تابع تبدیل');
    return { num: mul(a.num, b.den), den: mul(a.den, b.num) };
  },
  pow: (a: Rational, n: number): Rational => {
    let out: Rational = { num: [1], den: [1] };
    for (let i = 0; i < n; i++) out = R.mul(out, a);
    return out;
  },
};

/** «10/(s+10)» → H(s) as a ratio of polynomials. */
export function parseTransfer(src: string): Rational {
  const text = normalizeExpr(src).replace(/^\s*h\s*\(\s*s\s*\)\s*=/i, '').trim();
  const toks: string[] = [];
  const re = /\s*(\d+\.?\d*(?:e[+-]?\d+)?|\.\d+|[a-z]+|[-+*/^()])/giy;
  let m: RegExpExecArray | null;
  let at = 0;
  while (at < text.length) {
    re.lastIndex = at;
    m = re.exec(text);
    if (!m) {
      if (/^\s*$/.test(text.slice(at))) break;
      throw new TransferError(`نویسه‌ی «${text[at]}» در تابع تبدیل شناخته نشد`);
    }
    toks.push(m[1].toLowerCase());
    at = re.lastIndex;
  }
  let i = 0;
  const peek = () => toks[i];
  const take = (t?: string) => {
    const x = toks[i];
    if (t && x !== t) throw new TransferError(`در تابع تبدیل «${t}» لازم است`);
    i++;
    return x;
  };
  const constant = (v: number): Rational => ({ num: [v], den: [1] });
  const startsFactor = (t: string | undefined) => t !== undefined && (t === '(' || /^[\d.a-z]/.test(t));

  function expr(): Rational {
    let left = term();
    while (peek() === '+' || peek() === '-') {
      const op = take();
      const right = term();
      left = op === '+' ? R.add(left, right) : R.add(left, R.neg(right));
    }
    return left;
  }
  function term(): Rational {
    let left = unary();
    for (;;) {
      if (peek() === '*') { take(); left = R.mul(left, unary()); }
      else if (peek() === '/') { take(); left = R.div(left, unary()); }
      else if (startsFactor(peek())) left = R.mul(left, power()); // «10(s+1)», «2s»
      else return left;
    }
  }
  function unary(): Rational {
    if (peek() === '-') { take(); return R.neg(unary()); }
    if (peek() === '+') { take(); return unary(); }
    return power();
  }
  function power(): Rational {
    const base = atom();
    if (peek() !== '^') return base;
    take();
    const neg = peek() === '-';
    if (neg) take();
    const t = take();
    const n = Number(t);
    if (!Number.isInteger(n) || n > 20) throw new TransferError('توان در تابع تبدیل باید عدد صحیح کوچک باشد');
    const p = R.pow(base, n);
    return neg ? R.div(constant(1), p) : p;
  }
  function atom(): Rational {
    const t = take();
    if (t === undefined) throw new TransferError('تابع تبدیل ناتمام است');
    if (t === '(') {
      const v = expr();
      take(')');
      return v;
    }
    if (/^[\d.]/.test(t)) return constant(Number(t));
    if (t === 's') return { num: [0, 1], den: [1] };
    if (t === 'pi') return constant(Math.PI);
    if (t === 'e') return constant(Math.E);
    // «2s», «10ss»: letters run together.
    if (/^s+$/.test(t)) return { num: [...new Array(t.length).fill(0), 1], den: [1] };
    throw new TransferError(`«${t}» در تابع تبدیل شناخته نشد؛ فقط s، عدد، pi و e`);
  }
  const out = expr();
  if (i < toks.length) throw new TransferError(`«${toks[i]}» اضافه است`);
  return { num: trim(out.num), den: trim(out.den) };
}

export function evalPoly(p: Poly, z: Cx): Cx {
  let re = 0, im = 0;
  for (let k = p.length - 1; k >= 0; k--) {
    const r = re * z.re - im * z.im + p[k];
    im = re * z.im + im * z.re;
    re = r;
  }
  return { re, im };
}

/** H(jω). */
export function evalAt(h: Rational, w: number): Cx {
  const n = evalPoly(h.num, { re: 0, im: w }), d = evalPoly(h.den, { re: 0, im: w });
  const q = d.re * d.re + d.im * d.im;
  return { re: (n.re * d.re + n.im * d.im) / q, im: (n.im * d.re - n.re * d.im) / q };
}

/** Roots of a polynomial (Durand–Kerner), tidied: tiny imaginary parts dropped. */
export function roots(p: Poly): Cx[] {
  const c = trim(p);
  const n = c.length - 1;
  if (n < 1) return [];
  const lead = c[n];
  const a = c.map((x) => x / lead);
  const f = (z: Cx) => evalPoly(a, z);
  let zs: Cx[] = Array.from({ length: n }, (_, k) => {
    const r = Math.pow(0.4, k) ;
    const ang = 0.9 * k + 0.3;
    return { re: Math.cos(ang) * (1 + r), im: Math.sin(ang) * (1 + r) };
  });
  // Scale the starting circle to the size of the roots.
  const size = Math.max(1, ...a.slice(0, n).map((x, k) => Math.pow(Math.abs(x), 1 / (n - k))));
  zs = zs.map((z) => ({ re: z.re * size, im: z.im * size }));
  for (let it = 0; it < 800; it++) {
    let moved = 0;
    zs = zs.map((z, i) => {
      let d: Cx = { re: 1, im: 0 };
      zs.forEach((w, j) => {
        if (i === j) return;
        const t = { re: z.re - w.re, im: z.im - w.im };
        d = { re: d.re * t.re - d.im * t.im, im: d.re * t.im + d.im * t.re };
      });
      const v = f(z);
      const q = d.re * d.re + d.im * d.im || 1e-300;
      const step = { re: (v.re * d.re + v.im * d.im) / q, im: (v.im * d.re - v.re * d.im) / q };
      moved = Math.max(moved, Math.hypot(step.re, step.im));
      return { re: z.re - step.re, im: z.im - step.im };
    });
    if (moved < 1e-13) break;
  }
  return zs.map((z) => {
    const mag = Math.max(1, Math.hypot(z.re, z.im));
    return { re: Math.abs(z.re) < 1e-9 * mag ? 0 : z.re, im: Math.abs(z.im) < 1e-7 * mag ? 0 : z.im };
  });
}

/** H(s) = gain · ∏(s − zero) / ∏(s − pole). */
export function factor(h: Rational): { zeros: Cx[]; poles: Cx[]; gain: number } {
  return { zeros: roots(h.num), poles: roots(h.den), gain: h.num[h.num.length - 1] / h.den[h.den.length - 1] };
}
