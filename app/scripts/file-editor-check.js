#!/usr/bin/env node
/**
 * Runs «ویرایش کل فایل» the way a browser does, without a browser.
 *
 * Why: the header used to sit in the box as code and now sits above it as a card («مشخصات فصل»). What can go wrong
 * there does not reach the server — a save that drops the header (the book and the chapter's id with it), a card whose
 * fields do not become lines of the file, a preview that shows the header again. Django tests can pin the page and the
 * script's shape; only running the page shows that the whole thing works together.
 *
 *   cd app && npm i --no-save jsdom      (once; jsdom is not a build dependency)
 *   cd backend && python manage.py load_samples
 *   cd app && node scripts/file-editor-check.js
 *
 * It builds the real editor page and the real API payload through Django, loads panel.js in jsdom, and checks:
 *   - the box holds the body, with no header;
 *   - the card draws عنوان، شماره، رایگان and the fixed ids;
 *   - 「بررسی」 sends text whose header is exactly the one the server wrote (byte for byte);
 *   - a card edit reaches that header (title, number);
 *   - a duplicate number is said out loud;
 *   - the preview never shows the header;
 *   - the preview window opens, its title bar carries the device widths, and they apply without closing it;
 *   - dragging by the title bar moves the window in both axes.
 * Exit code 1 = something is wrong.
 */
'use strict';
const { execFileSync } = require('child_process');
const fs = require('fs');
const path = require('path');

let JSDOM, VirtualConsole;
try { ({ JSDOM, VirtualConsole } = require(process.env.JSDOM_DIR || 'jsdom')); } catch (e) {
  console.error('jsdom is missing:  cd app && npm i --no-save jsdom');
  process.exit(2);
}

const root = path.resolve(__dirname, '..', '..');
const backend = path.join(root, 'backend');
const python = process.env.PYTHON || path.join(backend, 'venv', 'bin', 'python');

const dump = `
import json
from django.test import Client
from django.urls import reverse
from apps.accounts.models import User
from apps.catalog.models import ContentNode
from apps.catalog.exporter import export_chapter
user = User.objects.filter(is_superuser=True).first()
chapter = ContentNode.objects.filter(depth=2).first()
if not user or not chapter:
    raise SystemExit("no book: run «python manage.py load_samples» first, and make a superuser")
client = Client()
client.force_login(user)
page = client.get(reverse("admin:catalog_chapter_file", args=[chapter.pk]))
print(json.dumps({"page": page.content.decode(), "text": export_chapter(chapter),
                  "url": "http://localhost:8000" + page.request["PATH_INFO"]}))
`;
let payload;
try {
  payload = JSON.parse(execFileSync(python, ['manage.py', 'shell', '-c', dump], {
    cwd: backend, encoding: 'utf8',
    env: { SECRET_KEY: 'file-editor-check', DEBUG: 'True', ALLOWED_HOSTS: '*', ...process.env },
  }).trim().split('\n').pop());
} catch (e) {
  console.error('could not build the editor page:', String(e.stderr || e.message || e).slice(0, 600));
  process.exit(2);
}

const problems = [];
const vc = new VirtualConsole();
vc.on('jsdomError', (e) => { if (!/Not implemented|Could not load/.test(e.message)) problems.push(e.message); });
const sent = [];           // every POST body the page sends
const bareStarts = [...payload.page.matchAll(/<script>/g)].map((m) => m.index);
const starterStart = bareStarts[bareStarts.length - 1];
const starterEnd = starterStart < 0 ? -1 : payload.page.indexOf('</script>', starterStart);
if (starterStart < 0 || starterEnd < 0) { console.error('the page has no inline starter'); process.exit(2); }
const starter = payload.page.slice(starterStart + '<script>'.length, starterEnd);
const html = payload.page.slice(0, starterStart) + payload.page.slice(starterEnd + '</script>'.length);
const dom = new JSDOM(html, {
  url: payload.url, runScripts: 'dangerously', virtualConsole: vc, pretendToBeVisual: true,
  beforeParse(win) {
    win.fetch = (u, o) => {
      let body = {};
      try { body = o && o.body ? JSON.parse(o.body) : {}; } catch (err) { /* a GET */ }
      if (o && o.body) sent.push(body);
      const answer = body.op === 'file.check'
        ? { errors: [], warnings: [], plan: { chapter: [], sections: [], questions: [], flashcards: [], notes: [], count: 1 }, diff: [],
            meta: { clash: 'شماره‌ی ۲ الان به فصل «فصل دو» داده شده؛ با ذخیره ترتیب فصل‌های کتاب عوض می‌شود.' } }
        : { state: { version: 'x' } };
      return Promise.resolve({ ok: true, status: 200, json: () => Promise.resolve(answer) });
    };
    win.alert = (m) => problems.push('alert: ' + m);
    win.confirm = () => true;
    win.scrollTo = () => {};
    win.Element.prototype.scrollIntoView = function () {};
  },
});

const staticDir = path.join(backend, 'apps/catalog/static/catalog');
for (const file of ['limo-preview.js', 'limo-editor.js', 'panel.js']) {
  const s = dom.window.document.createElement('script');
  s.textContent = fs.readFileSync(path.join(staticDir, file), 'utf8');
  dom.window.document.head.appendChild(s);
}

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const norm = (s) => String(s).replace(/\s+/g, ' ').trim();
const headerOf = (text) => { const i = text.indexOf('\n---', 4); return text.slice(0, i + 5); };

(async () => {
  const w = dom.window, doc = w.document;
  const fails = [];

  // The page's own starter (below the box in the real HTML).
  const s = doc.createElement('script');
  s.textContent = starter;
  doc.body.appendChild(s);
  await wait(500);

  const ta = doc.getElementById('file-text');
  if (!ta) { console.error('no text box'); process.exit(2); }
  if (sent.length && sent[0].op && sent[0].op.indexOf('file.') !== 0) fails.push('unexpected first request: ' + sent[0].op);

  // 1. The box is the body; the header is not in it.
  const body = payload.text.slice(payload.text.indexOf('\n---', 4) + 5);
  if (norm(ta.value) !== norm(body)) fails.push('the box is not the body:\n  box:  ' + JSON.stringify(ta.value.slice(0, 80)));
  for (const key of ['شناسه-کتاب', 'شناسه-فصل', 'رشته‌ها']) {
    if (ta.value.includes(key)) fails.push('the header key «' + key + '» is still in the box');
  }

  // 2. The card is drawn with its fields.
  const card = doc.querySelector('.ch-head');
  if (!card) fails.push('no «مشخصات فصل» card');
  else {
    for (const want of ['عنوان', 'شماره‌ی فصل', 'رایگان', 'شناسه‌های ثابت']) {
      if (!norm(card.textContent).includes(want)) fails.push('the card has no «' + want + '»');
    }
    if (!card.querySelector('input[type=text]')) fails.push('the card has no title field');
    if (!card.querySelector('input[type=checkbox]')) fails.push('the card has no «رایگان» switch');
    if (!card.querySelector('a[href*="/admin/catalog/book/"]')) fails.push('the book title is not linked to its book page');
    const cfg = JSON.parse(doc.getElementById('file-meta').textContent);
    if (!card.textContent.includes('شناسه‌های ثابت') || !card.textContent.includes(cfg.chapter_slug)) fails.push('the locked chapter id is not shown');
  }

  // 3. «بررسی» carries the whole file: body + the header exactly as the server wrote it.
  const check = doc.getElementById('file-check');
  if (!check) { console.error('no «بررسی» button'); process.exit(2); }
  check.click();
  await wait(600);
  const checked = sent.filter((b) => b.op === 'file.check').pop();
  if (!checked) fails.push('«بررسی» sent nothing');
  else {
    if (!checked.text.startsWith(headerOf(payload.text))) {
      fails.push('the header in the request differs from the server\'s:\n  sent:   ' + JSON.stringify(checked.text.slice(0, 90)) +
        '\n  server: ' + JSON.stringify(headerOf(payload.text).slice(0, 90)));
    }
    if (norm(checked.text.slice(checked.text.indexOf('\n---', 4) + 5)) !== norm(ta.value)) fails.push('the body in the request is not the box: full=' + JSON.stringify(checked.text.slice(0, 240)) + ' body=' + JSON.stringify(checked.text.slice(checked.text.indexOf('\n---', 4) + 5, checked.text.indexOf('\n---', 4) + 100)) + ' box=' + JSON.stringify(ta.value.slice(0, 90)));
    if (!checked.meta || checked.meta.chapter_slug) fails.push('the card sent its ids (it must send only what it edits)');
  }
  // 4. The duplicate-number sentence the server sent is shown.
  const note = card && card.querySelector('.ch-note');
  if (!note || note.style.display === 'none' || !norm(note.textContent).includes('فصل دو')) fails.push('the duplicate number was not reported');

  // 5. A card edit reaches the header of the next request.
  const titleIn = card && card.querySelector('input[type=text]');
  if (titleIn) {
    titleIn.value = 'عنوان از کارت';
    titleIn.dispatchEvent(new w.Event('input', { bubbles: true }));
    check.click();
    await wait(600);
    const again = sent.filter((b) => b.op === 'file.check').pop();
    if (!again.text.includes('عنوان: عنوان از کارت')) fails.push('a title typed in the card did not reach the file header');
    if (again.meta.chapter_title !== 'عنوان از کارت') fails.push('the card did not send its title');
    const save = doc.getElementById('file-save');
    if (!save || save.disabled) fails.push('a successful «بررسی» did not enable «ذخیره»');
    else {
      save.click();
      await wait(300);
      const applied = sent.filter((b) => b.op === 'file.apply').pop();
      if (!applied) fails.push('«ذخیره» sent nothing');
      else {
        const expectedHeader = headerOf(payload.text).replace(/(^|\n)عنوان:[^\n]*/, '$1عنوان: عنوان از کارت');
        if (!applied.text.startsWith(expectedHeader)) fails.push('«ذخیره» did not send the header with the card title: sent=' + JSON.stringify(applied.text.slice(0, 180)) + ' expected=' + JSON.stringify(expectedHeader.slice(0, 180)));
        if (applied.meta.chapter_title !== 'عنوان از کارت') fails.push('«ذخیره» did not send the card title');
      }
    }
  }

  // 6. The preview never shows the header.
  const frame = doc.querySelector('iframe.file-prev');
  if (!frame) fails.push('no preview frame');
  else if (frame.srcdoc && frame.srcdoc.includes('شناسه-کتاب')) fails.push('the preview shows the file header');

  // 7. The preview window: it opens from the toolbar, its title bar carries the device widths, they apply without
  //    closing it, and dragging by the bar moves the window in both axes.
  const winBtn = Array.from(doc.querySelectorAll('.md-bar .pv-open')).pop();
  const dialog = doc.querySelector('dialog.pv-win');
  if (!winBtn) fails.push('no «پیش‌نمایش در پنجره» button on the editor toolbar');
  else if (!dialog) fails.push('no preview window in the page');
  else {
    // The width buttons are NOT in the editor's toolbar any more (they travel with the window); the justify switch is.
    if (doc.querySelector('.md-bar .pv-ctl') && /گوشی|تبلت|تمام‌عرض/.test(doc.querySelector('.md-bar .pv-ctl').textContent)) {
      fails.push('the device widths are still on the editor toolbar');
    }
    winBtn.click();
    await wait(400);
    const devices = dialog.querySelectorAll('.pv-devices .pv-device');
    if (devices.length !== 4) fails.push('the window title bar has ' + devices.length + ' device widths, not 4');
    else {
      const tablet = Array.from(devices).find((b) => b.textContent.trim() === 'تبلت');
      const label = (el) => el && el.textContent.trim();
      if (!tablet) fails.push('no «تبلت» among the window device widths (' + Array.from(devices).map(label).join('، ') + ')');
      else {
        tablet.click();
        await wait(200);
        if (w.localStorage.getItem('limo.panel.width') !== 'tablet') fails.push('clicking «تبلت» did not remember the width');
        if (tablet.getAttribute('aria-pressed') !== 'true') fails.push('the chosen width is not marked pressed');
        if (frame && frame.style.width !== '768px') fails.push('the chosen width did not reach the frame (width=' + (frame && frame.style.width) + ')');
        // And back to phone, to prove the switch applies again without closing the window.
        const phone = Array.from(devices).find((b) => b.textContent.trim() === 'گوشی');
        phone.click();
        await wait(200);
        if (frame && frame.style.width !== '390px') fails.push('switching to «گوشی» did not resize the frame (width=' + (frame && frame.style.width) + ')');
      }
    }
    // Drag the title bar: the window must follow the pointer horizontally AND vertically.
    const bar = dialog.querySelector('.pv-win-bar');
    const ptr = (target, type, x, y) => {
      const e = new w.Event(type, { bubbles: true, cancelable: true });
      e.clientX = x; e.clientY = y; e.pointerId = 1; e.button = 0;
      target.dispatchEvent(e);
    };
    const left = parseFloat(dialog.style.left), top = parseFloat(dialog.style.top);
    ptr(bar, 'pointerdown', 500, 40);
    ptr(w, 'pointermove', 640, 160);
    await wait(120);
    ptr(w, 'pointerup', 640, 160);
    await wait(120);
    if (Math.abs(parseFloat(dialog.style.left) - left - 140) > 1) fails.push('dragging did not move the window horizontally (' + dialog.style.left + ' vs ' + left + ')');
    if (Math.abs(parseFloat(dialog.style.top) - top - 120) > 1) fails.push('dragging did not move the window vertically (' + dialog.style.top + ' vs ' + top + ')');
    winBtn.click();   // close again
    await wait(200);
  }

  const report = [
    'sent: ' + sent.map((b) => b.op).join(' | '),
    'card: ' + !!card,
    'body in box: ' + !ta.value.includes('شناسه-فصل'),
    'header kept on save: ' + !!(checked && checked.text.startsWith(headerOf(payload.text))),
    'problems: ' + (problems.length ? problems.join(' ; ') : 'none'),
  ];
  console.log(report.join('\n'));
  if (fails.length || problems.length) {
    console.log('FAILED:\n- ' + (fails.concat(problems)).join('\n- '));
    process.exit(1);
  }
  console.log('OK');
  process.exit(0);
})();
