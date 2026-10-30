/**
 * One practice question drawn as a single page (stem, choices, feedback), instead of one web view per formula.
 * Much smoother on low-end phones. Shared by the phone (WebView) and web (DOM) versions of QuizView.
 */
import { __iconData as BrainIcon } from 'lucide-react-native/icons/brain';
import { __iconData as CalculatorIcon } from 'lucide-react-native/icons/calculator';
import { __iconData as CheckIcon } from 'lucide-react-native/icons/circle-check';
import { __iconData as FlagIcon } from 'lucide-react-native/icons/flag';
import { __iconData as GaugeIcon } from 'lucide-react-native/icons/gauge';
import { __iconData as CapIcon } from 'lucide-react-native/icons/graduation-cap';
import { __iconData as BookIcon } from 'lucide-react-native/icons/book-open';
import { __iconData as PenIcon } from 'lucide-react-native/icons/pen-line';
import { __iconData as SearchIcon } from 'lucide-react-native/icons/search-check';

import type { AnswerResult, Question } from '../api/endpoints';
import { toPersianDigits } from '../theme';
import { renderMarkdown } from './renderMarkdown';

type IconData = { node: [string, Record<string, string>][] };

function svg(icon: IconData, size = 14) {
  const parts = icon.node
    .map(([tag, attrs]) => `<${tag} ${Object.entries(attrs).filter(([k]) => k !== 'key').map(([k, v]) => `${k}="${v}"`).join(' ')}/>`)
    .join('');
  return `<svg width="${size}" height="${size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round">${parts}</svg>`;
}

const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' })[c]!);
const KEYS = ['الف', 'ب', 'ج', 'د', 'ه', 'و'];
const DIFF: Record<string, [string, string]> = { easy: ['آسان', 'easy'], medium: ['متوسط', 'medium'], hard: ['سخت', 'hard'] };
const KIND: Record<string, [string, IconData]> = {
  recall: ['حفظی', BookIcon as IconData],
  concept: ['مفهومی', BrainIcon as IconData],
  calc: ['محاسباتی', CalculatorIcon as IconData],
  analysis: ['تحلیلی', SearchIcon as IconData],
};

export function questionHtml(q: Question): string {
  const tags: string[] = [];
  for (const s of q.sources) {
    tags.push(`<span class="tag t-konkur">${svg(CapIcon as IconData)}${esc(s.name)} ${toPersianDigits(s.year)}${s.number ? ` · سؤال ${toPersianDigits(s.number)}` : ''}</span>`);
  }
  if (q.is_original) tags.push(`<span class="tag t-orig">${svg(PenIcon as IconData)}تألیفی</span>`);
  const d = DIFF[q.difficulty];
  if (d) tags.push(`<span class="tag t-${d[1]}">${svg(GaugeIcon as IconData)}${d[0]}</span>`);
  const k = q.kind ? KIND[q.kind] : null;
  if (k) tags.push(`<span class="tag t-kind">${svg(k[1])}${k[0]}</span>`);
  const choices = q.choices
    .map((c, i) => `<button class="choice" data-id="${c.id}"><span class="key">${KEYS[i]}</span><span class="ctext">${renderMarkdown(c.text)}</span></button>`)
    .join('');
  return `<div class="tags">${tags.join('')}</div>
<div class="stem">${renderMarkdown(q.stem)}</div>
<div class="choices">${choices}</div>
<div class="feedback" hidden></div>
<div class="err" hidden></div>
<div class="report-row" hidden><button class="report">${svg(FlagIcon as IconData, 16)}گزارش اشکال در این تست</button><span class="reported" hidden>${svg(CheckIcon as IconData, 16)}گزارش داده شد</span></div>`;
}

export type QuizViewState = {
  picked: number | null;
  sending: boolean;
  error: string | null;
  reported: boolean;
  result: (Pick<AnswerResult, 'correct_choice_id' | 'is_correct'> & { tabs: { key: string; label: string; html: string }[]; flashcards: string }) | null;
};

export function resultForView(r: AnswerResult): NonNullable<QuizViewState['result']> {
  const tabs = (
    [
      ['explanation', 'پاسخ تشریحی'],
      ['quick_solution', 'راه‌حل سریع'],
      ['alternative_view', 'زاویه‌ی دیگر'],
    ] as const
  )
    .filter(([key]) => !!r[key])
    .map(([key, label]) => ({ key, label, html: renderMarkdown(r[key]) }));
  return {
    correct_choice_id: r.correct_choice_id,
    is_correct: r.is_correct,
    tabs,
    flashcards: r.flashcards.length ? `فلش‌کارت مرتبط: ${r.flashcards.map((f) => esc(f.title)).join('، ')}` : '',
  };
}

export const QUIZ_CSS = `
.quiz { direction: rtl; text-align: right; font-family: Vazirmatn, Tahoma, sans-serif; color: #17201A; padding: 6px 16px 28px;
  font-size: 16px; line-height: 1.9; -webkit-user-select: none; user-select: none; -webkit-tap-highlight-color: transparent; }
.quiz .tags { display: flex; flex-wrap: wrap; gap: 6px; margin-bottom: 12px; }
.quiz .tag { display: inline-flex; align-items: center; gap: 4px; border-radius: 999px; padding: 3px 10px; font-size: 12px; font-weight: 700; line-height: 1.6; }
.quiz .t-konkur { background: #F5C518; color: #17201A; } .quiz .t-orig { background: #E3F3E9; color: #1F5E3A; }
.quiz .t-easy { background: #E3F3E9; color: #1F5E3A; } .quiz .t-medium { background: #FFF1B8; color: #6B5200; }
.quiz .t-hard { background: #FBE7E6; color: #9E2F2A; } .quiz .t-kind { background: #EEF0FC; color: #3B44B8; }
.quiz .stem { font-size: 17px; margin-bottom: 14px; } .quiz .stem p { margin: 0 0 8px; }
.quiz .choices { display: flex; flex-direction: column; gap: 10px; }
.quiz .choice { display: flex; align-items: center; gap: 12px; width: 100%; min-height: 58px; padding: 10px 12px; border-radius: 18px;
  border: 2px solid #E3E8DE; background: #fff; font: inherit; color: inherit; text-align: right; cursor: pointer; }
.quiz .choice .key { flex: none; width: 30px; height: 30px; border-radius: 10px; background: #F1F3EC; display: flex; align-items: center;
  justify-content: center; font-weight: 800; }
.quiz .ctext { flex: 1; } .quiz .ctext p { margin: 0; }
.quiz .choice.picked { border-color: #17201A; }
.quiz .choice.right { background: #E3F3E9; border-color: #2F7D4F; } .quiz .choice.right .key { background: #2F7D4F; color: #fff; }
.quiz .choice.wrong { background: #FBE7E6; border-color: #C2413B; } .quiz .choice.wrong .key { background: #C2413B; color: #fff; }
.quiz .choice:disabled { cursor: default; }
.quiz .feedback { margin-top: 16px; border-radius: 18px; padding: 14px; }
.quiz .feedback.ok { background: #E3F3E9; } .quiz .feedback.no { background: #FFF1EF; }
.quiz .fb-title { font-weight: 800; font-size: 16px; margin-bottom: 8px; } .quiz .ok .fb-title { color: #1F5E3A; } .quiz .no .fb-title { color: #9E2F2A; }
.quiz .tabs { display: flex; gap: 6px; flex-wrap: wrap; margin-bottom: 8px; }
.quiz .tab { border: 0; border-radius: 999px; padding: 5px 12px; background: #FFFFFF88; font: inherit; font-size: 13px; font-weight: 700; color: #56655B; }
.quiz .tab.on { background: #fff; color: #17201A; }
.quiz .pane p { margin: 0 0 8px; }
.quiz .related { font-size: 12px; color: #56655B; margin-top: 6px; }
.quiz .err { color: #9E2F2A; margin-top: 10px; }
.quiz .report-row { display: flex; justify-content: flex-start; margin-top: 14px; }
.quiz .report, .quiz .reported { display: inline-flex; align-items: center; gap: 6px; border-radius: 999px; padding: 7px 12px; font: inherit;
  font-size: 13px; font-weight: 700; }
.quiz .report { border: 1px solid #F2C7C4; background: #FFF6F5; color: #9E2F2A; }
.quiz .reported { border: 1px solid #BFE8CF; background: #E3F3E9; color: #1F5E3A; }
[hidden] { display: none !important; }
`;

/** Runs inside the question page as a function body with (root, post). */
export const QUIZ_SCRIPT = `
var state = null, tab = 0;
root.addEventListener('click', function (e) {
  var t = e.target;
  var choice = t.closest && t.closest('.choice');
  if (choice && !choice.disabled) { post({ type: 'choose', id: Number(choice.getAttribute('data-id')) }); return; }
  if (t.closest && t.closest('.report')) { post({ type: 'report' }); return; }
  var tb = t.closest && t.closest('.tab');
  if (tb) { tab = Number(tb.getAttribute('data-i')); render(); }
});
var x0 = null, y0 = null;
root.addEventListener('touchstart', function (e) { x0 = e.touches[0].clientX; y0 = e.touches[0].clientY; }, { passive: true });
root.addEventListener('touchend', function (e) {
  if (x0 === null) return;
  var dx = e.changedTouches[0].clientX - x0, dy = e.changedTouches[0].clientY - y0; x0 = null;
  // Persian book: drag the page from left to right to go forward.
  if (Math.abs(dx) > 60 && Math.abs(dy) < 50) post({ type: 'swipe', dir: dx > 0 ? 'next' : 'prev' });
}, { passive: true });
function render() {
  if (!state) return;
  var r = state.result;
  var choices = root.querySelectorAll('.choice');
  for (var i = 0; i < choices.length; i++) {
    var c = choices[i], id = Number(c.getAttribute('data-id'));
    c.className = 'choice' + (state.picked === id && !r ? ' picked' : '') + (r && id === r.correct_choice_id ? ' right' : '') +
      (r && id === state.picked && !r.is_correct ? ' wrong' : '');
    c.disabled = !!r || state.sending;
  }
  var fb = root.querySelector('.feedback');
  if (r) {
    if (tab >= r.tabs.length) tab = 0;
    var tabs = r.tabs.length > 1 ? '<div class="tabs">' + r.tabs.map(function (t, i) {
      return '<button class="tab' + (i === tab ? ' on' : '') + '" data-i="' + i + '">' + t.label + '</button>';
    }).join('') + '</div>' : '';
    fb.className = 'feedback ' + (r.is_correct ? 'ok' : 'no');
    fb.innerHTML = '<div class="fb-title">' + (r.is_correct ? 'آفرین، درست بود!' : 'نزدیک بودی؛ ببین چرا:') + '</div>' + tabs +
      '<div class="pane">' + (r.tabs[tab] ? r.tabs[tab].html : '') + '</div>' + (r.flashcards ? '<div class="related">' + r.flashcards + '</div>' : '');
    fb.hidden = false;
  } else { fb.hidden = true; }
  var err = root.querySelector('.err'); err.hidden = !state.error; err.textContent = state.error || '';
  var row = root.querySelector('.report-row'); row.hidden = !r;
  row.querySelector('.report').hidden = state.reported; row.querySelector('.reported').hidden = !state.reported;
}
root.__setState = function (s) { var fresh = !state || !state.result; state = s; if (fresh && s.result) tab = 0; render(); };
`;
