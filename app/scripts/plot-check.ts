/**
 * Checks of the «:::نمودار» plots (lib/expr.ts, lib/plot.ts) against values known from the mathematics.
 * Run: npx --yes esbuild@0.28.2 scripts/plot-check.ts --bundle --platform=node --outfile=/tmp/plot-check.js && node /tmp/plot-check.js
 */
import { compile, ExprError } from '../src/lib/expr';
import { evalAt, parseTransfer, roots } from '../src/lib/transfer';
import { bodeAt, curveFunction, findHoles, fourierSums, parseComplex, parsePlot, renderPlot, segments } from '../src/lib/plot';

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
ok(/π\/2|2π/.test(renderPlot('تابع: sin(x)\nمحور: pi', (s) => s)!), 'π axis labels, in English digits');
const plain = renderPlot('تابع: x^2', (s) => s)!;
ok(!/class="tk"/.test(plain) && !/class="grid"/.test(plain), 'clean by default: no numbers, no grid');
const nums = renderPlot('تابع: x^2\nعدد: بله\nشبکه: بله', (s) => s)!;
ok(/class="tk"/.test(nums) && /class="grid"/.test(nums) && !/[۰-۹]/.test(nums), 'numbers and grid on request, English digits');
const marks = renderPlot('تابع: x\nعلامت x: 1، pi/2\nعلامت y: 2', (s) => s)!;
ok((marks.match(/class="tk"/g) ?? []).length === 3 && />π\/2</.test(marks) && />1</.test(marks) && />2</.test(marks), 'only the marked values');
ok(/plot-error/.test(renderPlot('تابع: sin x', (s) => s)!), 'a wrong formula shows an error, not a wrong picture');
ok(renderPlot('یک عکس', (s) => s) === null, 'a box without «تابع:» is not a plot');
ok(/c-red/.test(renderPlot('تابع: x\nرنگ: قرمز', (s) => s)!), 'colour by name');
const sqLine = renderPlot('تابع: square(x)\nفوریه: 1، 3', (s) => s)!;
ok(!/plot-error/.test(sqLine) && (sqLine.match(/class="cv /g) ?? []).length >= 3, 'Fourier of square(x) on the whole line: period 2π');
ok((renderPlot('تابع: sin(x)\nروی: 0 تا pi\nگسترش: زوج\nفوریه: 1، 3', (s) => s)!.match(/class="cv /g) ?? []).length >= 3, 'Fourier sums drawn with the curve');

const holes = (src: string, a: number, b: number) => findHoles(compile(src), a, b, 4);
ok(JSON.stringify(holes('(x^2-1)/(x-1)', -2, 3).map((h) => [h.x, +h.y.toFixed(6)])) === '[[1,2]]', 'hole of (x²−1)/(x−1) at (1, 2) found');
ok(holes('sin(x)/x', -5, 5).length === 1 && Math.abs(holes('sin(x)/x', -5, 5)[0].y - 1) < 1e-6, 'hole of sin(x)/x at (0, 1)');
ok(holes('1/x', -2, 2).length === 0 && holes('tan(x)', -3, 3).length === 0 && holes('sqrt(x)', -2, 2).length === 0, 'no holes at poles or domain edges');
ok(holes('(x^2-pi^2/4)/(x-pi/2)', -3, 3).length === 1, 'hole at π/2');
ok(/pt-open/.test(renderPlot('تابع: (x^2-1)/(x-1)\nبازه: -2 تا 3', (s) => s)!), 'hole drawn without a «نقطه:» line');
ok(!/pt-open/.test(renderPlot('تابع: (x^2-1)/(x-1)\nبازه: -2 تا 3\nحفره: خیر', (s) => s)!), '«حفره: خیر» turns it off');

// --- signals and systems ---
const cx = (s: string) => parseComplex(s).map((c) => [+c.re.toFixed(6), +c.im.toFixed(6)]);
ok(JSON.stringify(cx('0.5+0.3j')) === '[[0.5,0.3]]', 'complex a+bj');
ok(JSON.stringify(cx('0.8±0.4j')) === '[[0.8,0.4],[0.8,-0.4]]', '± gives the conjugate pair');
ok(JSON.stringify(cx('-2j')) === '[[0,-2]]' && JSON.stringify(cx('j')) === '[[0,1]]' && JSON.stringify(cx('-1')) === '[[-1,0]]', 'pure imaginary and real');
ok(JSON.stringify(cx('1-i')) === '[[1,-1]]' && JSON.stringify(cx('pi')) === `[[${+PI.toFixed(6)},0]]`, 'i, but not the i of pi');
ok(near(parseComplex('1∠pi/2')[0].im, 1) && Math.abs(parseComplex('1∠pi/2')[0].re) < 1e-12, 'polar form');
ok(near(parseComplex('1e-3+2j')[0].re, 0.001), 'exponent sign is not the split');
const pz = parsePlot('صفر: 0\nقطب: 0.5، 0.8±0.4j\nناحیه: |z| > 0.9')!;
ok(pz.zeros.length === 1 && pz.poles.length === 3 && pz.roc!.lo === 0.9 && pz.roc!.hi === Infinity, 'pole-zero description');
const ring = parsePlot('قطب: 0.5، 2\nناحیه: 0.5 < |z| < 2')!.roc!;
ok(ring.lo === 0.5 && ring.hi === 2 && ring.plane === 'z', 'ring ROC');
const half = parsePlot('قطب: -1\nناحیه: Re(s) < -1')!.roc!;
ok(half.plane === 's' && half.hi === -1 && half.lo === -Infinity, 'left half-plane ROC');
const pzSvg = renderPlot('صفر: 0\nقطب: 0.5\nناحیه: |z| > 0.5', (s) => s)!;
ok(/class="unit"/.test(pzSvg) && /class="pole"/.test(pzSvg) && /class="zero"/.test(pzSvg) && /class="roc"/.test(pzSvg), 'z plane: unit circle, ×, ○ and ROC');
ok(!/class="unit"/.test(renderPlot('قطب: -1\nصفحه: s', (s) => s)!), 's plane: no unit circle');
ok(/>\(2\)</.test(renderPlot('قطب: 0.5، 0.5', (s) => s)!), 'a double pole shows (2)');
ok(/plot-error/.test(renderPlot('قطب: 1\nناحیه: بزرگ', (s) => s)!) && /plot-error/.test(renderPlot('قطب: 1\nناحیه: |z| > 2 و |z| < 1', (s) => s)!), 'a wrong ROC shows an error');
// Bode: H(s) = 10/(s+10): 0 dB at low ω, −3 dB and −45° at the corner, −20 dB/decade after.
const lp = { zeros: [], poles: [{ re: -10, im: 0 }], gain: 10 };
ok(near(bodeAt(lp, 0.01).db, 0, 1e-4) && near(bodeAt(lp, 10).db, -3.0103, 1e-3) && near(bodeAt(lp, 10).phase, -45, 1e-9), 'Bode first order: −3 dB, −45° at the corner');
ok(near(bodeAt(lp, 1000).db - bodeAt(lp, 10000).db, 20, 1e-3), '−20 dB per decade');
ok(near(bodeAt(lp, 10).straight, 0, 1e-9) && near(bodeAt(lp, 100).straight, -20, 1e-9), 'straight lines meet at the corner');
const integ = { zeros: [], poles: [{ re: 0, im: 0 }], gain: 1 };
ok(near(bodeAt(integ, 1).db, 0) && near(bodeAt(integ, 10).db, -20) && near(bodeAt(integ, 3).phase, -90), 'integrator 1/s');
const res = bodeAt({ zeros: [], poles: parseComplex('-0.2±3j'), gain: 9 }, 3);
ok(res.db > 15 && res.db < 18, `resonance peak of a lightly damped pair (got ${res.db.toFixed(2)} dB)`);
ok(/class="frame"/.test(renderPlot('بود: بله\nقطب: -10\nبهره: 10', (s) => s)!), 'Bode drawn');
ok(((renderPlot('بود: بله\nقطب: -10\nفاز: خیر', (s) => s)!).match(/class="frame"/g) ?? []).length === 1, '«فاز: خیر» leaves the magnitude only');
// Impulses and discrete signals.
const imp = parsePlot('ضربه: 0، (2, -0.5)')!;
ok(imp.impulses.length === 2 && imp.impulses[1].x === 2 && imp.impulses[1].w === -0.5, 'impulses with weights');
const impSvg = renderPlot('ضربه: 0، (2, -0.5)', (s) => s)!;
ok((impSvg.match(/class="f-/g) ?? []).length === 2 && /\(−0.5\)/.test(impSvg), 'two arrows, weight written');
ok((renderPlot('قطار ضربه: 1\nبازه: -2.5 تا 2.5', (s) => s)!.match(/class="f-/g) ?? []).length === 5, 'impulse train: one arrow per period in view');
const seq = parsePlot('مقادیر: 1، 2، 3 از -1')!;
ok(seq.seq!.start === -1 && seq.seq!.values.join() === '1,2,3' && seq.variable === 'n', 'listed sequence');
const stems = renderPlot('تابع: u(n)\nمتغیر: n\nبازه: -3 تا 3', (s) => s)!;
ok((stems.match(/<circle class="f-/g) ?? []).length === 7, 'stems at every whole n in view');
ok(f('delta(n)', 0) === 1 && f('δ(n)', 1) === 0, 'δ[n]');

// Transfer functions written as in the book.
const tf = parseTransfer('10(s+1)/((s+10)(s+100))');
ok(JSON.stringify(tf.num) === '[10,10]' && JSON.stringify(tf.den) === '[1000,110,1]', `H(s) read into polynomials (got ${JSON.stringify(tf)})`);
ok(near(Math.hypot(evalAt(tf, 0).re, evalAt(tf, 0).im), 0.01), 'H(0) = 10/1000');
const rts = roots([1000, 110, 1]).map((z) => z.re).sort((a, b) => a - b);
ok(near(rts[0], -100, 1e-9) && near(rts[1], -10, 1e-9), 'roots of s² + 110s + 1000: −100 and −10');
const cr = roots([1, 0, 1]).map((z) => +z.im.toFixed(9)).sort((a, b) => a - b);
ok(cr[0] === -1 && cr[1] === 1, 'roots of s² + 1: ±j');
ok(JSON.stringify(parseTransfer('1/s^2').den) === '[0,0,1]' && JSON.stringify(parseTransfer('H(s) = 2s/(s+1)').num) === '[0,2]', 'powers, «H(s) =», 2s');
ok(/plot-error/.test(renderPlot('بود: 10/(x+1)', (s) => s)!), 'a letter other than s is an error');
const bodeTf = renderPlot('بود: 10/(s+10)', (s) => s)!;
ok(!/plot-error/.test(bodeTf) && /class="frame"/.test(bodeTf), 'Bode from H(s)');
const p2 = parsePlot('بود: 100/(s(s+10))')!;
ok(p2.poles.length === 2 && near(p2.gain, 100), 'poles and gain from H(s)');
ok(near(bodeAt(p2, 1).phase, -90 - (Math.atan(0.1) * 180) / PI, 1e-6), 'phase of 100/(s(s+10)) at ω = 1');
const nyq = renderPlot('نایکوئیست: 10/((s+1)(s+2))', (s) => s)!;
ok(!/plot-error/.test(nyq) && /−1/.test(nyq) && /stroke-dasharray="6 4"/.test(nyq), 'Nyquist: curve, mirror and −1');
ok(/class="pole"/.test(renderPlot('تابع تبدیل: (s+1)/(s^2+s+1)', (s) => s)!), 'pole-zero plot from H(s)');

console.log(`${passed} passed, ${failed} failed`);
if (failed) process.exit(1);
