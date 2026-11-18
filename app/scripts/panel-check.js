#!/usr/bin/env node
/**
 * Runs the panel's chapter manager the way a browser does, without a browser.
 *
 * Why: the panel's bugs do not reach the server, so Django tests cannot see them. «فصل باز نشد» on every chapter was
 * one (applyWidth() ran before this.frame existed) and a runaway re-render was another (a missing `destinations`).
 * Reading the code did not show either; running it did.
 *
 *   cd app && npm i --no-save jsdom      (once; jsdom is not a build dependency)
 *   cd backend && python manage.py load_samples          (once; a book to open)
 *   cd app && node scripts/panel-check.js
 *
 * It builds the real chapter page and the real API payload through Django, then loads panel.js in jsdom: the chapter
 * tree must be drawn, every tab must open, and a sentinel stops a runaway loop. Exit code 1 = something is wrong.
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

// The page and the API's state, made by Django itself: the same HTML the admin serves and the same JSON panel.js gets.
const dump = `
import json
from django.test import Client
from django.urls import reverse
from apps.accounts.models import User
from apps.catalog.models import ContentNode
user = User.objects.filter(is_superuser=True).first()
chapter = ContentNode.objects.filter(depth=2).first()
if not user or not chapter:
    raise SystemExit("no book: run «python manage.py load_samples» first, and make a superuser")
client = Client()
client.force_login(user)
page = client.get(reverse("admin:catalog_chapter_manager", args=[chapter.pk]))
state = client.get(reverse("admin:catalog_chapter_api", args=[chapter.pk])).json()
print(json.dumps({"page": page.content.decode(), "state": state, "url": "http://localhost:8000" + page.request["PATH_INFO"]}))
`;
let payload;
try {
  payload = JSON.parse(execFileSync(python, ['manage.py', 'shell', '-c', dump], {
    cwd: backend, encoding: 'utf8',
    // The test client uses «testserver» as its host; ALLOWED_HOSTS in a laptop .env may not list it.
    env: { SECRET_KEY: 'panel-check', DEBUG: 'True', ALLOWED_HOSTS: '*', ...process.env },
  }).trim().split('\n').pop());
} catch (e) {
  console.error('could not build the chapter page:', String(e.stderr || e.message || e).slice(0, 600));
  process.exit(2);
}

const problems = [];
const vc = new VirtualConsole();
vc.on('jsdomError', (e) => { if (!/Not implemented|Could not load/.test(e.message)) problems.push(e.message); });
const html = payload.page.replace(/<script>\s*document\.addEventListener[\s\S]*?<\/script>/, '');  // started below, by hand
const dom = new JSDOM(html, {
  url: payload.url, runScripts: 'dangerously', virtualConsole: vc, pretendToBeVisual: true,
  beforeParse(win) {
    win.fetch = (u, o) => {
      let body = {};
      try { body = o && o.body ? JSON.parse(o.body) : {}; } catch (err) { /* a GET */ }
      const answer = { state: payload.state.state };
      if (body.op === 'destinations') answer.destinations = [];
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

let appends = 0;
const appendChild = dom.window.Node.prototype.appendChild;
dom.window.Node.prototype.appendChild = function (child) { appends += 1; return appendChild.call(this, child); };

const wait = (ms) => new Promise((r) => setTimeout(r, ms));
const norm = (s) => String(s).replace(/\s+/g, ' ').trim();

(async () => {
  const w = dom.window;
  const rootEl = w.document.getElementById('cm-root');
  new w.LimoChapterManager(rootEl, '/api/');
  await wait(700);
  const fails = [];
  const err = rootEl.querySelector('.msg.err');
  if (err) fails.push('error box: ' + norm(err.textContent));
  if (appends > 20000) fails.push('runaway re-render: ' + appends + ' DOM inserts');
  if (!rootEl.querySelector('.cm-tree')) fails.push('the chapter tree was not drawn');
  const rows = [...rootEl.querySelectorAll('.cm-tree .it')];
  if (rows[1]) { rows[1].click(); await wait(400); }
  const tabs = [...rootEl.querySelectorAll('.cm-tabs button')];
  if (!tabs.length) fails.push('no tabs on the section');
  for (const tab of tabs) {
    if (!/درسنامه|چکیده|تست|فلش/.test(norm(tab.textContent))) continue;
    tab.click();
    await wait(350);
    if (rootEl.querySelector('.msg.err')) fails.push('tab «' + norm(tab.textContent) + '» showed an error');
  }
  const report = [
    'DOM inserts: ' + appends,
    'chapter tree: ' + !!rootEl.querySelector('.cm-tree'),
    'tabs: ' + tabs.map((t) => norm(t.textContent)).join(' | '),
    'problems: ' + (problems.length ? problems.join(' ; ') : 'none'),
  ];
  console.log(report.join('\n'));
  if (fails.length) { console.log('FAILED:\n- ' + fails.join('\n- ')); process.exit(1); }
  console.log('OK');
  process.exit(0);
})();
