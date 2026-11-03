/**
 * Checks of the «:::نمودار» plots (lib/expr.ts, lib/plot.ts) against values known from the mathematics.
 * Run: npx --yes esbuild@0.28.2 scripts/plot-check.ts --bundle --platform=node --outfile=/tmp/plot-check.js && node /tmp/plot-check.js
 */
import { compile, ExprError } from '../src/lib/expr';
import { curveFunction, fourierSums, parsePlot, renderPlot, segments } from '../src/lib/plot';

let failed = 0, passed = 0;
function ok(cond: boolean, what: string) {
  if (cond) passed++;
  else { failed++; console.log('FAIL', what); }
}
const near = (a: number, b: number, tol = 1e-9) => Math.abs(a - b) <= tol * Math.max(1, Math.abs(b));
const f = (src: string, x = 0) => compile(src)(x);
const PI = Math.PI;

// --- formulas ---
ok(near(f('2pi'), 2 * PI), '2pi');
ok(near(f('x/2pi', 1), 1 / (2 * PI)), 'x/2pi = x/(2π)');
ok(near(f('1/2x', 2), 0.25), '1/2x = 1/(2x)');
ok(near(f('-x^2', 3), -9), '-x^2 = -(x²)');
ok(near(f('2^3^2'), 512), '^ right-associative');
ok(near(f('x^-1', 2), 0.5), 'x^-1');
ok(near(f('|x-3|', 1), 2), '|x-3|');
ok(near(f('2|x|+|x-1|', -1), 4), 'two bars');
ok(near(f('sin^2(x)', 1), Math.sin(1) ** 2), 'sin^2(x)');
ok(near(f('sin(x)^2', 1), Math.sin(1) ** 2), 'sin(x)^2');
ok(near(f('e^x', 1), Math.E), 'e^x');
ok(near(f('2e'), 2 * Math.E), '2e');
ok(near(f('xsin(x)', 2), 2 * Math.sin(2)), 'xsin(x)');
ok(near(f('2pix', 1), 2 * PI), '2pix');
ok(near(f('ln(e)'), 1), 'ln');
ok(near(f('log(100)'), 2), 'log base 10');
ok(near(f('log(8, 2)'), 3), 'log base b');
ok(near(f('۲π'), 2 * PI), 'Persian digits and π');
ok(near(f('3×x − 1', 2), 5), '× and −');
ok(near(f('acot(-1)'), (3 * PI) / 4), 'acot in (0, π)');
ok(near(f('arcsin(1)'), PI / 2), 'arcsin alias');
ok(near(f('asech(0.5)'), Math.acosh(2)), 'asech');
ok(near(f('coth(1)'), 1 / Math.tanh(1)), 'coth');
ok(near(f('(x+1)(x-1)', 3), 8), 'implicit between brackets');
ok(Number.isNaN(f('sqrt(x)', -1)), 'sqrt of negative is undefined');
ok(Number.isNaN(f('1/x', 0)), '1/0 is undefined');
for (const bad of ['sin x', 'foo(x)', '(x', 'x+', '2**3', 'y']) {
  let threw = false;
  try { compile(bad); } catch (e) { threw = e instanceof ExprError; }
  ok(threw, `error for «${bad}»`);
}

// --- signals (period 2π unless given, amplitude 1, like sin) ---
ok(f('square(x)', 0.5) === 1 && f('square(x)', -0.5) === -1 && f('square(x)', 0) === 0, 'square wave');
ok(f('square(x, 2)', 1.5) === -1 && f('square(x, 2, 0.25)', 0.4) === 1 && f('square(x, 2, 0.25)', 0.6) === -1, 'square period and duty');
ok(near(f('triangle(x)', PI / 2), 1) && near(f('triangle(x)', 0), 0) && near(f('triangle(x)', -PI / 2), -1), 'triangle');
ok(near(f('saw(x)', 0), 0) && f('saw(x)', PI - 1e-6) > 0.999 && f('saw(x)', PI + 1e-6) < -0.999, 'sawtooth jumps at π');
ok(near(f('saw(x)^2', PI / 2), 0.25), 'sawtooth squared');
ok(f('u(x)', 0) === 1 && f('u(x)', -1e-9) === 0, 'unit step');
ok(f('r(x)', -2) === 0 && f('r(x)', 3) === 3, 'ramp');
ok(f('rect(x)', 0.4) === 1 && f('rect(x)', 0.6) === 0, 'rect');
ok(f('sinc(x)', 0) === 1 && Math.abs(f('sinc(x)', 1)) < 1e-12 && Math.abs(f('sinc(x)', 2)) < 1e-12, 'normalized sinc');

// --- definition intervals and extensions ---
const curve = (body: string) => curveFunction(parsePlot(body)!.curves[0]).g;
const evenSin = curve('تابع: sin(x)\nروی: 0 تا pi\nگسترش: زوج');
ok(near(evenSin(-PI / 2), 1) && near(evenSin((3 * PI) / 2), 1) && near(evenSin(-PI / 4), Math.sin(PI / 4)), 'even extension of sin on (0, π) is |sin x|');
const oddSin = curve('تابع: sin(x)\nروی: 0 تا pi\nگسترش: فرد');
ok(near(oddSin(-PI / 2), -1) && near(oddSin((3 * PI) / 2), -1), 'odd extension of sin on (0, π) is sin x');
const even2pi = curve('تابع: sin(x)\nروی: 0 تا 2pi\nگسترش: زوج');
ok(near(even2pi(-PI / 2), 1) && near(even2pi(5 * PI), even2pi(PI)), 'even extension on (0, 2π): period 4π, not sin');
const repeat = curve('تابع: x\nروی: 0 تا 1\nتناوب: 1');
ok(near(repeat(1.25), 0.25) && near(repeat(-0.25), 0.75), 'simple repetition');
const gap = curve('تابع: x\nروی: 0 تا 1\nتناوب: 2');
ok(Number.isNaN(gap(1.5)) && near(gap(2.5), 0.5), 'period longer than the interval leaves gaps');
const only = curve('تابع: x^2\nروی: -1 تا 1');
ok(Number.isNaN(only(2)) && near(only(0.5), 0.25), 'no extension: only on the interval');

// --- Fourier series ---
const sq = parsePlot('تابع: 1\nروی: 0 تا pi\nگسترش: فرد')!.curves[0];
const sqf = curveFunction(sq);
const [s1, s51] = fourierSums(sqf.g, sqf.period!, sqf.start!, [1, 51]);
ok(near(s1(PI / 2), 4 / PI, 1e-4), 'square wave: b1 = 4/π');
let peak = 0;
for (let x = 0.001; x < 0.3; x += 0.0005) peak = Math.max(peak, s51(x));
ok(peak > 1.16 && peak < 1.2, `Gibbs overshoot of S51 near the jump ≈ 1.18 (got ${peak.toFixed(4)})`);
ok(near(s51(PI / 2), 1, 0.02), 'S51 close to 1 in the middle');
ok(Math.abs(s51(0)) < 1e-6, 'S51 = 0 at the jump (the middle value)');
const ab = curveFunction(parsePlot('تابع: sin(x)\nروی: 0 تا pi\nگسترش: زوج')!.curves[0]);
const [a0] = fourierSums(ab.g, ab.period!, ab.start!, [0]);
ok(near(a0(1), 2 / PI, 1e-5), '|sin x|: mean 2/π');
const lin = curveFunction(parsePlot('تابع: x\nروی: -pi تا pi\nگسترش: ساده')!.curves[0]);
const [l100] = fourierSums(lin.g, lin.period!, lin.start!, [100]);
ok(near(l100(1), 1, 0.03), 'series of x on (−π, π) converges to x');

// --- pieces: asymptotes, jumps, domains, holes ---
const piecesOf = (src: string, a: number, b: number, span: number, jumps: 'break' | 'vertical' = 'break') =>
  segments(compile(src), a, b, span, jumps, [-span / 2, span / 2]);
const tan = piecesOf('tan(x)', -PI, PI, 10);
ok(tan.length === 3, `tan over (−π, π): 3 pieces (got ${tan.length})`);
ok(tan.every((s) => !(s[0][0] < PI / 2 && s[s.length - 1][0] > PI / 2) && !(s[0][0] < -PI / 2 && s[s.length - 1][0] > -PI / 2)), 'tan: no piece crosses an asymptote');
ok(piecesOf('1/x', -2, 2, 10).length === 2, '1/x: two pieces');
ok(piecesOf('square(x)', -2 * PI, 2 * PI, 2.4).length === 4, 'square wave over (−2π, 2π): broken at its 3 jumps');
ok(piecesOf('square(x)', -2 * PI, 2 * PI, 2.4, 'vertical').length === 1, 'square wave, joined by vertical lines');
const root = piecesOf('sqrt(x)', -2, 2, 2);
ok(root.length === 1 && Math.abs(root[0][0][0]) < 1e-6, 'sqrt(x) starts exactly at 0');
const hole = piecesOf('(x^2-1)/(x-1)', -2, 4, 6);
ok(hole.length === 2 && hole[0][hole[0].length - 1][0] < 1 && hole[1][0][0] > 1, 'hole at x = 1 left open');
ok(piecesOf('sin(x)', -10, 10, 2).length === 1, 'sin: one piece');
ok(piecesOf('floor(x)', -2, 2, 4).length === 4, 'floor: a piece per step');

// --- drawing ---
const svg = renderPlot('تابع: x\nبازه: 0 تا 10', (s) => s)!;
const d = /class="cv[^"]*" d="M([\d.]+),([\d.]+)[^"]*L([\d.]+),([\d.]+)"/.exec(svg)!;
ok(Number(d[3]) > Number(d[1]) && Number(d[4]) < Number(d[2]), 'not mirrored: x grows to the right, y grows upwards');
ok(/dir="ltr"/.test(svg), 'plot is left-to-right inside the right-to-left page');
ok(/π\/۲|۲π/.test(renderPlot('تابع: sin(x)\nمحور: pi', (s) => s)!), 'π axis labels');
ok(/plot-error/.test(renderPlot('تابع: sin x', (s) => s)!), 'a wrong formula shows an error, not a wrong picture');
ok(renderPlot('یک عکس', (s) => s) === null, 'a box without «تابع:» is not a plot');
ok(/c-red/.test(renderPlot('تابع: x\nرنگ: قرمز', (s) => s)!), 'colour by name');
const sqLine = renderPlot('تابع: square(x)\nفوریه: 1، 3', (s) => s)!;
ok(!/plot-error/.test(sqLine) && (sqLine.match(/class="cv /g) ?? []).length >= 3, 'Fourier of square(x) on the whole line: period 2π');
ok((renderPlot('تابع: sin(x)\nروی: 0 تا pi\nگسترش: زوج\nفوریه: 1، 3', (s) => s)!.match(/class="cv /g) ?? []).length >= 3, 'Fourier sums drawn with the curve');

console.log(`${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
