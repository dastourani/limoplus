/**
 * A small parser for the formulas of «:::نمودار» boxes: numbers only, no strings or objects, nothing but the
 * functions listed below (all from JavaScript's own Math, or defined here and tested in scripts/plot-check.ts).
 *
 *   sin(x)^2 + 2cos(3x)      implicit multiplication («2x», «2pi», «x(x+1)») binds tighter than * and /,
 *   x/2pi = x/(2π)           so «1/2x» is 1/(2x), as written in textbooks
 *   -x^2 = -(x²)             ^ is right-associative: 2^3^2 = 2^9
 *   |x|                      absolute value bars
 *   ۲π، ×، ÷، −              Persian digits and signs are accepted
 * Functions need brackets: «sin(x)», not «sin x».
 */
export type Compiled = (x: number) => number;

const TAU = 2 * Math.PI;
const frac = (v: number) => v - Math.floor(v);

/** Waves of period T (2π by default), amplitude 1, shaped like sin: 0 at x = 0 and rising. */
const WAVES = {
  /** ±1; duty = the share of the period at +1 (½ by default). Jumps take the middle value 0. */
  square: (x: number, T = TAU, duty = 0.5) => {
    const p = frac(x / T);
    if (p === 0 || Math.abs(p - duty) < 1e-12) return duty === 0.5 ? 0 : p === 0 ? 1 : -1;
    return p < duty ? 1 : -1;
  },
  triangle: (x: number, T = TAU) => (2 / Math.PI) * Math.asin(Math.sin((TAU * x) / T)),
  /** Rises from −1 to 1, jumps at ±T/2. */
  saw: (x: number, T = TAU) => 2 * frac(x / T + 0.5) - 1,
};

const FUNCS: Record<string, (...a: number[]) => number> = {
  sin: Math.sin, cos: Math.cos, tan: Math.tan,
  cot: (v) => 1 / Math.tan(v), sec: (v) => 1 / Math.cos(v), csc: (v) => 1 / Math.sin(v),
  asin: Math.asin, acos: Math.acos, atan: Math.atan,
  acot: (v) => (v === 0 ? Math.PI / 2 : Math.atan(1 / v) + (v < 0 ? Math.PI : 0)),
  asec: (v) => Math.acos(1 / v), acsc: (v) => Math.asin(1 / v),
  sinh: Math.sinh, cosh: Math.cosh, tanh: Math.tanh,
  coth: (v) => 1 / Math.tanh(v), sech: (v) => 1 / Math.cosh(v), csch: (v) => 1 / Math.sinh(v),
  asinh: Math.asinh, acosh: Math.acosh, atanh: Math.atanh,
  acoth: (v) => Math.atanh(1 / v), asech: (v) => Math.acosh(1 / v), acsch: (v) => Math.asinh(1 / v),
  exp: Math.exp, ln: Math.log,
  /** log(x) is base 10 (as in Iranian textbooks); log(x, b) is base b. */
  log: (v, b = 10) => Math.log(v) / Math.log(b),
  sqrt: Math.sqrt, cbrt: Math.cbrt, abs: Math.abs,
  sign: Math.sign, sgn: Math.sign,
  floor: Math.floor, ceil: Math.ceil, round: Math.round,
  /** Floored: mod(-1, 3) = 2. */
  mod: (a, b) => a - b * Math.floor(a / b),
  frac,
  min: Math.min, max: Math.max,
  /** Unit step u(x) (1 from 0 on), ramp r(x), rect (1 for |x| < ½), normalized sinc. */
  u: (v) => (v >= 0 ? 1 : 0),
  /** δ[n] of discrete signals: 1 at 0, else 0 (an impulse δ(t) is drawn with «ضربه:», not as a formula). */
  delta: (v) => (Math.abs(v) < 1e-9 ? 1 : 0),
  r: (v) => (v > 0 ? v : 0),
  rect: (v) => (Math.abs(v) < 0.5 ? 1 : Math.abs(v) === 0.5 ? 0.5 : 0),
  sinc: (v) => (v === 0 ? 1 : Math.sin(Math.PI * v) / (Math.PI * v)),
  ...WAVES,
};
const ALIASES: Record<string, string> = {
  arcsin: 'asin', arccos: 'acos', arctan: 'atan', arccot: 'acot', arcsec: 'asec', arccsc: 'acsc',
  arsinh: 'asinh', arcosh: 'acosh', artanh: 'atanh', arcoth: 'acoth', arcsinh: 'asinh', arccosh: 'acosh',
  arctanh: 'atanh', arccoth: 'acoth', tg: 'tan', ctg: 'cot', cotg: 'cot', step: 'u', ramp: 'r',
  tri: 'triangle', sawtooth: 'saw', sq: 'square',
};
const CONSTS: Record<string, number> = { pi: Math.PI, e: Math.E };
/** Names that stand for the variable. */
const VARS = new Set(['x', 't', 'n']);

export const FUNCTION_NAMES = Object.keys(FUNCS);

export class ExprError extends Error {}

/** Persian and look-alike characters → plain ones. */
export function normalizeExpr(src: string): string {
  return (src ?? '')
    .replace(/[۰-۹]/g, (d) => String('۰۱۲۳۴۵۶۷۸۹'.indexOf(d)))
    .replace(/[٠-٩]/g, (d) => String('٠١٢٣٤٥٦٧٨٩'.indexOf(d)))
    .replace(/π/g, 'pi')
    .replace(/δ/g, 'delta')
    .replace(/[×·∙]/g, '*')
    .replace(/÷/g, '/')
    .replace(/[−–—]/g, '-')
    .replace(/[،؛]/g, ',')
    .replace(/٫/g, '.')
    .replace(/²/g, '^2')
    .replace(/³/g, '^3');
}

type Tok = { k: 'num'; v: number } | { k: 'id'; v: string } | { k: 'op'; v: string };

function tokenize(src: string): Tok[] {
  const out: Tok[] = [];
  let i = 0;
  while (i < src.length) {
    const c = src[i];
    if (/\s/.test(c)) { i++; continue; }
    const num = /^(\d+\.?\d*|\.\d+)(e[+-]?\d+)?/i.exec(src.slice(i));
    if (num && /[\d.]/.test(c)) {
      // «2e» is 2·e, not an unfinished exponent.
      const text = /e$/i.test(num[0]) ? num[0].slice(0, -1) : num[0];
      out.push({ k: 'num', v: Number(text) });
      i += text.length;
      continue;
    }
    const id = /^[a-zA-Z_][a-zA-Z_0-9]*/.exec(src.slice(i));
    if (id) { out.push({ k: 'id', v: id[0].toLowerCase() }); i += id[0].length; continue; }
    if ('+-*/^(),|'.includes(c)) { out.push({ k: 'op', v: c }); i++; continue; }
    throw new ExprError(`نویسه‌ی «${c}» در فرمول شناخته نشد.`);
  }
  return out;
}

/** Splits a run of letters like «xsin» or «pix» into known names, longest first («2pix» = 2·π·x). */
function splitName(name: string): string[] | null {
  if (name in FUNCS || name in ALIASES || name in CONSTS || VARS.has(name)) return [name];
  const known = [...Object.keys(FUNCS), ...Object.keys(ALIASES), ...Object.keys(CONSTS), ...VARS].sort((a, b) => b.length - a.length);
  for (const k of known) {
    if (name.startsWith(k)) {
      const rest = splitName(name.slice(k.length));
      if (rest) return [k, ...rest];
    }
  }
  return null;
}

type Node = (x: number) => number;

export function compile(source: string): Compiled {
  const toks: Tok[] = [];
  for (const t of tokenize(normalizeExpr(source))) {
    if (t.k !== 'id') { toks.push(t); continue; }
    const parts = splitName(t.v);
    if (!parts) throw new ExprError(`«${t.v}» شناخته نشد. متغیر x، t یا n است و تابع‌ها مثل sin(x) با پرانتز نوشته می‌شوند.`);
    parts.forEach((p) => toks.push({ k: 'id', v: p }));
  }
  let i = 0;
  let absDepth = 0;
  const peek = () => toks[i];
  const isOp = (v: string) => toks[i]?.k === 'op' && toks[i].v === v;
  const expect = (v: string) => {
    if (!isOp(v)) throw new ExprError(`در فرمول «${v}» کم است.`);
    i++;
  };

  // sum := product (('+'|'-') product)*
  function sum(): Node {
    let left = product();
    while (isOp('+') || isOp('-')) {
      const op = toks[i++].v;
      const a = left, b = product();
      left = op === '+' ? (x) => a(x) + b(x) : (x) => a(x) - b(x);
    }
    return left;
  }
  // product := signed (('*'|'/') signed)*
  function product(): Node {
    let left = signed();
    while (isOp('*') || isOp('/')) {
      const op = toks[i++].v;
      const a = left, b = signed();
      left = op === '*' ? (x) => a(x) * b(x) : (x) => a(x) / b(x);
    }
    return left;
  }
  // signed := ('-'|'+') signed | implicit
  function signed(): Node {
    if (isOp('-')) { i++; const a = signed(); return (x) => -a(x); }
    if (isOp('+')) { i++; return signed(); }
    return implicit();
  }
  // implicit := power power*   («2x», «2pi x», «x(x+1)»; a bar opens a new |…| only when none is open)
  function startsPrimary(): boolean {
    const t = peek();
    if (!t) return false;
    if (t.k === 'num' || t.k === 'id') return true;
    return t.v === '(' || (t.v === '|' && absDepth === 0);
  }
  function implicit(): Node {
    let left = power();
    while (startsPrimary()) {
      const a = left, b = power();
      left = (x) => a(x) * b(x);
    }
    return left;
  }
  // power := primary ('^' signedPower)?   right-associative, the exponent may carry a sign: x^-1
  function power(): Node {
    const base = primary();
    if (!isOp('^')) return base;
    i++;
    const exp = isOp('-') ? (i++, ((p) => (x: number) => -p(x))(power())) : power();
    return (x) => Math.pow(base(x), exp(x));
  }
  function primary(): Node {
    const t = peek();
    if (!t) throw new ExprError('فرمول ناتمام است.');
    if (t.k === 'num') { i++; const v = t.v; return () => v; }
    if (t.k === 'op' && t.v === '(') { i++; const e = sum(); expect(')'); return e; }
    if (t.k === 'op' && t.v === '|') {
      i++; absDepth++;
      const e = sum();
      absDepth--;
      expect('|');
      return (x) => Math.abs(e(x));
    }
    if (t.k === 'id') {
      i++;
      const name = ALIASES[t.v] ?? t.v;
      if (VARS.has(name)) return (x) => x;
      if (name in CONSTS) { const v = CONSTS[name]; return () => v; }
      const fn = FUNCS[name];
      // «sin^2(x)» as in textbooks: (sin x)².
      let outer: number | null = null;
      if (isOp('^') && toks[i + 1]?.k === 'num' && toks[i + 2]?.k === 'op' && toks[i + 2].v === '(') {
        outer = (toks[i + 1] as { v: number }).v;
        i += 2;
      }
      if (!isOp('(')) throw new ExprError(`بعد از ${t.v} پرانتز بگذارید: ${t.v}(x)`);
      i++;
      const args: Node[] = [sum()];
      while (isOp(',')) { i++; args.push(sum()); }
      expect(')');
      const call: Node = args.length === 1 ? ((a) => (x: number) => fn(a(x)))(args[0]) : (x) => fn(...args.map((a) => a(x)));
      if (outer === null) return call;
      const k = outer;
      return (x) => Math.pow(call(x), k);
    }
    throw new ExprError(`«${t.v}» این‌جا بی‌جاست.`);
  }

  if (!toks.length) throw new ExprError('فرمول خالی است.');
  const root = sum();
  if (i < toks.length) throw new ExprError(`«${(toks[i] as { v: unknown }).v}» این‌جا بی‌جاست.`);
  return (x) => {
    const v = root(x);
    return typeof v === 'number' && Number.isFinite(v) ? v : NaN;
  };
}

/** A constant such as «2pi» or «-3/2» (ranges, periods). */
export function value(source: string): number {
  const v = compile(source)(0);
  if (Number.isNaN(v)) throw new ExprError(`«${source}» عدد نیست.`);
  return v;
}
