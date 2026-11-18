/* LimooKhan panel: Markdown editor with a phone-sized live preview, and the chapter manager.
 * The preview uses the app's own renderer (limo-preview.js), so it looks exactly like the app. */
(function () {
  'use strict';
  var P = window.LimoPreview;
  var STATIC = (document.currentScript && document.currentScript.src.replace(/panel\.js.*$/, '')) || '/static/catalog/';
  var MEDIA = '/media/';

  // ---------- small helpers ----------
  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      var v = attrs[k];
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k === 'html') el.innerHTML = v;
      else if (k.slice(0, 2) === 'on') el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked') el.checked = !!v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (var i = 2; i < arguments.length; i++) add(el, arguments[i]);
    return el;
  }
  function add(el, child) {
    if (child == null || child === false) return;
    if (Array.isArray(child)) { child.forEach(function (c) { add(el, c); }); return; }
    el.appendChild(typeof child === 'string' || typeof child === 'number' ? document.createTextNode(String(child)) : child);
  }
  function fa(n) { return String(n).replace(/\d/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'[d]; }); }
  function csrf() { var m = document.cookie.match(/csrftoken=([^;]+)/); return m ? m[1] : (document.querySelector('[name=csrfmiddlewaretoken]') || {}).value; }
  function media(text) { return (text || '').replace(/\]\(media:/g, '](' + MEDIA); }
  function plain(s) { return (s || '').replace(/[*_`]/g, '').replace(/\s+/g, ' '); }

  // The chapter file starts with its own details between two «---» lines (شناسه-کتاب، فصل، عنوان …). They are the
  // panel's business, not the reader's: «ویرایش کل فایل» shows the file, so it must show them, but the PREVIEW must
  // not — rendered as Markdown they become a giant heading and push the lesson down (that is what a professor saw).
  // A «---» further down the file is a horizontal rule and stays; only the header at the very top is taken.
  var FRONT_KEYS = /^(شناسه-کتاب|کتاب|قیمت-کتاب|رشته‌ها|شناسه-فصل|فصل|عنوان|عنوان-انگلیسی|رایگان)\s*:/;
  function stripFrontMatter(text) {
    var body = String(text || '').replace(/^\uFEFF/, '').replace(/\r\n/g, '\n');
    var m = /^[ \t]*---[ \t]*\n([\s\S]*?)\n[ \t]*---[ \t]*(?:\n|$)/.exec(body);
    if (!m) return body;
    // Only when the block really holds the chapter's keys: a bare «---» pair around prose is not a header.
    var lines = m[1].split('\n').filter(function (line) { return line.trim(); });
    if (!lines.length || !lines.every(function (line) { return FRONT_KEYS.test(line.trim()); })) return body;
    return body.slice(m[0].length);
  }

  // «## مفهوم حد {#limit-idea}»: the {#slug} is how the file remembers a section's id, not part of its title. The
  // markdown renderer has no heading rule of its own (headings in the app come from the section list, not from the
  // text), so the marker would be printed inside the heading. Taken off here, in the preview only — the text box
  // keeps the file exactly as the server gave it.
  function stripHeadingIds(text) {
    return String(text || '').replace(/^(#{1,6}[ \t]+.*?)[ \t]*\{#[^}\s]+\}[ \t]*$/gm, '$1');
  }

  // The learner's reading setting (profile: «متن درس تراز باشد», on by default). The preview follows it, so what the
  // professor sees is what the learner sees — a line broken at a different place, never aligned differently.
  function readingJustify() {
    try { var v = localStorage.getItem('limo.panel.justify'); if (v !== null) return v === '1'; } catch (e) { /* ignore */ }
    return true;
  }
  function previewDoc(html, extraCss) {
    var lesson = 'lesson' + (readingJustify() ? '' : ' ragged');
    return '<!doctype html><html dir="rtl"><head><meta charset="utf-8"><style>' +
      '@font-face{font-family:Vazirmatn;font-weight:400;src:url("' + STATIC + 'fonts/Vazirmatn_400Regular.ttf")}' +
      '@font-face{font-family:Vazirmatn;font-weight:700;src:url("' + STATIC + 'fonts/Vazirmatn_700Bold.ttf")}' +
      P.CONTENT_CSS + 'body{background:#F6F7F2;padding:14px 0}.lesson{padding:4px 16px 24px}' + (extraCss || '') +
      '</style></head><body><div class="' + lesson + '">' + html + '</div></body></html>';
  }
  function render(source, variant) {
    if (variant === 'summary') return P.renderSummary(media(source), { hasCards: false });
    return P.renderMarkdown(media(source));
  }
  // Grow an iframe to its content (same origin, so this works).
  function autoHeight(frame, min) {
    function fit() {
      try { frame.style.height = Math.max(min || 200, frame.contentDocument.documentElement.scrollHeight + 4) + 'px'; } catch (e) { /* ignore */ }
    }
    frame.addEventListener('load', function () { fit(); setTimeout(fit, 300); });
  }

  // ---------- the preview's own controls: how wide, and aligned which way ----------
  // A phone, a tablet, or the whole panel. «دقیقاً مثل اپ» is only true at a phone's width: the same text breaks its
  // lines elsewhere. Choosing the width is the honest answer — the professor sees the layout a learner gets.
  var WIDTHS = [['phone', 'گوشی', 390], ['tablet', 'تبلت', 768], ['wide', 'تمام عرض', 0]];
  function previewWidth() {
    try { var v = localStorage.getItem('limo.panel.width'); if (v) return v; } catch (e) { /* ignore */ }
    return 'phone';
  }
  function widthPx(name) {
    for (var i = 0; i < WIDTHS.length; i++) if (WIDTHS[i][0] === name) return WIDTHS[i][2];
    return 390;
  }
  // The controls that sit above a preview: width buttons and the justify switch. `onChange` redraws it.
  function previewControls(onChange) {
    var row = h('div', { class: 'pv-ctl' });
    var widthBtns = {};
    function paint() {
      var name = previewWidth();
      for (var k in widthBtns) widthBtns[k].classList.toggle('on', k === name);
      justifyBtn.classList.toggle('on', readingJustify());
      onChange();
    }
    WIDTHS.forEach(function (w) {
      widthBtns[w[0]] = h('button', { type: 'button', title: 'عرض پیش‌نمایش: ' + w[1], onclick: function (e) {
        e.preventDefault();
        try { localStorage.setItem('limo.panel.width', w[0]); } catch (err) { /* ignore */ }
        paint();
      } }, w[1]);
      row.appendChild(widthBtns[w[0]]);
    });
    var justifyBtn = h('button', { type: 'button', class: 'pv-just', title: 'متن درس تراز باشد (مثل تنظیم پروفایل در اپ)',
      onclick: function (e) {
        e.preventDefault();
        try { localStorage.setItem('limo.panel.justify', readingJustify() ? '0' : '1'); } catch (err) { /* ignore */ }
        paint();
      } }, '⇔ تراز دو طرفه');
    row.appendChild(justifyBtn);
    paint();
    return { el: row, repaint: paint };
  }

  // ---------- The preview as a window you can move ----------
  // The preview used to live inside the editor's right-hand column, so «تمام عرض» could never be wider than that
  // column and «تبلت» was cut off. A professor asked for a real window: a title bar, an × to close, movable by its
  // bar, and the width buttons on the EDITOR's toolbar rather than above the lesson (they are settings of the frame,
  // not part of what the reader sees).
  //
  // Built on <dialog>: the browser already handles Escape, focus and the backdrop, so the only things written here are
  // the ones it does not have — dragging and resizing.
  var WIN_POS_KEY = 'limo.panel.win';
  function savedWin() {
    try { var v = localStorage.getItem(WIN_POS_KEY); return v ? JSON.parse(v) : null; } catch (e) { return null; }
  }
  function saveWin(x, y, w, h) {
    try { localStorage.setItem(WIN_POS_KEY, JSON.stringify({ x: x, y: y, w: w, h: h })); } catch (e) { /* ignore */ }
  }
  function previewWindow(opts) {
    var frame = opts.frame;                // the iframe that is moved inside the window
    var dialog = document.createElement('dialog');
    dialog.className = 'pv-win';
    var title = h('span', { class: 'pv-win-title' }, opts.title || 'پیش‌نمایش فصل');
    var closeBtn = h('button', { type: 'button', class: 'pv-win-x', title: 'بستن (Esc)', onclick: function () { close(); } }, '×');
    var bar = h('div', { class: 'pv-win-bar' }, title, closeBtn);
    var body = h('div', { class: 'pv-win-body' });
    var grip = h('div', { class: 'pv-win-grip', title: 'برای تغییر اندازه بکشید' });
    dialog.appendChild(bar);
    dialog.appendChild(body);
    dialog.appendChild(grip);
    document.body.appendChild(dialog);
    // The frame may not be in the page at all (the whole-file editor keeps it out of the layout until the window
    // opens); the placeholder then goes into the dialog's body, which is where it will be handed back to.
    var placeholder = document.createComment('preview window closed');
    var host = frame.parentNode || body;
    if (host === body) { body.appendChild(placeholder); body.appendChild(frame); }
    else host.insertBefore(placeholder, frame);

    function place(x, y, w, hgt) {
      var maxW = Math.max(320, window.innerWidth - 24), maxH = Math.max(240, window.innerHeight - 24);
      w = Math.min(Math.max(320, w || 0), maxW);
      hgt = Math.min(Math.max(240, hgt || 0), maxH);
      if (typeof x !== 'number' || isNaN(x)) x = (window.innerWidth - w) / 2;
      if (typeof y !== 'number' || isNaN(y)) y = Math.max(12, (window.innerHeight - hgt) / 2);
      dialog.style.left = Math.max(0, Math.min(x, window.innerWidth - w)) + 'px';
      dialog.style.top = Math.max(0, Math.min(y, window.innerHeight - hgt)) + 'px';
      dialog.style.width = w + 'px';
      dialog.style.height = hgt + 'px';
    }
    var saved = savedWin();
    place(saved && saved.x, saved && saved.y, saved && saved.w, saved && saved.h);
    var api;   // filled at the end; close() reads `api.onClosed` at call time

    // --- dragging by the title bar ---
    var drag = null;
    bar.addEventListener('pointerdown', function (e) {
      if (e.target === closeBtn) return;
      drag = { dx: e.clientX - parseFloat(dialog.style.left || 0), dy: e.clientY - parseFloat(dialog.style.top || 0) };
      bar.setPointerCapture(e.pointerId);
      dialog.classList.add('dragging');
    });
    bar.addEventListener('pointermove', function (e) {
      if (!drag) return;
      place(e.clientX - drag.dx, e.clientY - drag.dy, dialog.offsetWidth, dialog.offsetHeight);
    });
    bar.addEventListener('pointerup', function (e) { drag = null; dialog.classList.remove('dragging'); try { bar.releasePointerCapture(e.pointerId); } catch (err) { /* ignore */ } });

    // --- resizing from the bottom-left corner (the side a Persian window grows from) ---
    var resize = null;
    grip.addEventListener('pointerdown', function (e) {
      e.preventDefault();
      resize = { x: e.clientX, y: e.clientY, l: parseFloat(dialog.style.left || 0), t: parseFloat(dialog.style.top || 0),
                 w: dialog.offsetWidth, h: dialog.offsetHeight };
      grip.setPointerCapture(e.pointerId);
    });
    grip.addEventListener('pointermove', function (e) {
      if (!resize) return;
      var dw = resize.x - e.clientX;            // RTL: the grip is on the left, so a leftward drag makes it wider
      place(resize.l - dw, resize.t, resize.w + dw, resize.h + (e.clientY - resize.y));
    });
    grip.addEventListener('pointerup', function (e) { resize = null; try { grip.releasePointerCapture(e.pointerId); } catch (err) { /* ignore */ } });

    function keep() {
      if (!dialog.open) return;
      saveWin(parseFloat(dialog.style.left || 0), parseFloat(dialog.style.top || 0), dialog.offsetWidth, dialog.offsetHeight);
    }
    dialog.addEventListener('pointerup', keep);
    window.addEventListener('resize', function () { if (dialog.open) place(parseFloat(dialog.style.left), parseFloat(dialog.style.top), dialog.offsetWidth, dialog.offsetHeight); });

    function open() {
      body.appendChild(frame);
      if (typeof dialog.showModal === 'function') dialog.showModal(); else dialog.setAttribute('open', '');
      if (opts.onOpen) opts.onOpen();
    }
    function close() {
      if (dialog.close) dialog.close(); else dialog.removeAttribute('open');
      // Back where it came from, so the editor is unchanged when the window is closed.
      if (placeholder.parentNode && frame.parentNode === body) {
        placeholder.parentNode.insertBefore(frame, placeholder.nextSibling);
      }
      if (opts.onClose) opts.onClose();
      // Read from `api` and not `opts`: the caller assigns `win.onClosed` after this function returns (it needs the
      // toolbar button to exist first), so a copy taken now would still be undefined at close time.
      if (api.onClosed) api.onClosed();
    }
    dialog.addEventListener('close', function () {
      if (placeholder.parentNode && frame.parentNode === body) {
        placeholder.parentNode.insertBefore(frame, placeholder.nextSibling);
      }
      if (opts.onClose) opts.onClose();
      if (api.onClosed) api.onClosed();
    });
    api = {
      el: dialog, open: open, close: close,
      isOpen: function () { return !!dialog.open; },
      frame: frame,
    };
    return api;
  }

  // ---------- labels («برچسب‌های متن», managed in admin) ----------
  // The same list as the app's renderer. In «درسنامه» a label is a box (:::تعریف … :::); in «چکیده» a part (تعریف: - …).
  function labelList() { return (P && P.allLabels ? P.allLabels() : []).filter(function (l) { return !l.hidden; }); }
  function labelRow(pick, filter, title) {
    var row = h('div', { class: 'lbl-row' });
    if (title) row.appendChild(h('span', { class: 'lbl-title' }, title));
    var groups = [], by = {};
    labelList().filter(filter || function () { return true; }).forEach(function (l) {
      var g = l.group || 'دیگر';
      if (!by[g]) { by[g] = h('span', { class: 'lbl-group' }, h('small', null, g)); groups.push(by[g]); }
      by[g].appendChild(h('button', { type: 'button', class: 'lbl lbl-' + l.style, onmousedown: function (e) { e.preventDefault(); },
        onclick: function (e) { e.preventDefault(); pick(l); } }, l.name));
    });
    groups.forEach(function (g) { row.appendChild(g); });
    return row;
  }
  // The panel's text boxes are CodeMirror editors (limo-editor.js): Persian lines right to left, formulas left to right.
  function cmUpgrade(ta, lines) { if (window.LimoCM) window.LimoCM.upgrade(ta, lines ? { minLines: lines } : {}); return ta; }
  // Text put in as one edit, so Ctrl+Z can take it back (setting .value would wipe the history).
  function typeIn(ta, text) {
    if (window.LimoCM && window.LimoCM.insert(ta, text)) return true;
    try { return document.execCommand('insertText', false, text); } catch (e) { return false; }
  }
  function insertText(ta, text, selFrom, selTo) {
    var start = ta.selectionStart, end = ta.selectionEnd;
    ta.focus();
    ta.setSelectionRange(start, end);
    var ok = typeIn(ta, text);
    if (!ok) { ta.setRangeText(text, start, end, 'end'); ta.dispatchEvent(new Event('input')); }
    if (selFrom != null) ta.setSelectionRange(start + selFrom, start + selTo);
  }
  // A summary part at the cursor: «تعریف:» on its own line, then «- » ready for the first item.
  function insertSummaryLabel(ta, l) {
    var v = ta.value, at = ta.selectionStart;
    var lead = at > 0 && v[at - 1] !== '\n' ? '\n\n' : (at > 1 && v[at - 2] !== '\n' ? '\n' : '');
    var sample = l.role === 'glance' ? '' : l.columns && l.columns.length ? l.columns.join(' | ') : '';
    var text = lead + l.name + ':' + (l.role === 'glance' ? ' ' : '\n- ') + sample;
    var from = text.length - sample.length;
    ta.setSelectionRange(at, ta.selectionEnd);
    insertText(ta, text + (v[ta.selectionEnd] && v[ta.selectionEnd] !== '\n' ? '\n' : ''), from, from + sample.length);
  }

  // ---------- editor tools (every text box of the panel) ----------
  // What the page knows about the chapter: [[#name]] targets, «دستورهای فرمول», konkur names already in use.
  var CTX = { refs: {}, macros: {}, sources: [] };
  function setCtx(st) {
    if (!st) return;
    CTX.refs = st.refs || {};
    CTX.macros = st.macros || {};
    CTX.sources = st.source_names || [];
    if (P && P.setLabels && st.labels) P.setLabels(st.labels);
    if (P && P.setMacros) P.setMacros(CTX.macros);
    var dl = document.getElementById('limo-src-names');
    if (!dl) { dl = h('datalist', { id: 'limo-src-names' }); document.body.appendChild(dl); }
    dl.innerHTML = '';
    CTX.sources.forEach(function (n) { dl.appendChild(h('option', { value: n })); });
  }

  function undoRedo(ta, back) {
    var cm = window.LimoCM;
    if (cm && cm.undo && (back ? cm.undo(ta) : cm.redo(ta))) return;
    ta.focus();
    try { document.execCommand(back ? 'undo' : 'redo'); } catch (e) { /* ignore */ }
  }
  // The whole text (or a part of it) replaced as one edit, so Ctrl+Z takes it back.
  function replaceRange(ta, from, to, text) {
    ta.focus();
    ta.setSelectionRange(from, to);
    if (!typeIn(ta, text)) { ta.setRangeText(text, from, to, 'end'); ta.dispatchEvent(new Event('input')); }
  }

  // The formula the cursor is in ($…$ or $$…$$), looked for in the cursor's paragraph.
  var MATH_RE = /\$\$([\s\S]+?)\$\$|\$((?:\\.|[^$\n\\])+?)\$/g;
  function formulaAt(text, pos) {
    var a = text.lastIndexOf('\n\n', pos - 1); a = a < 0 ? 0 : a;
    var b = text.indexOf('\n\n', pos); b = b < 0 ? text.length : b;
    var part = text.slice(a, b), m;
    MATH_RE.lastIndex = 0;
    while ((m = MATH_RE.exec(part))) {
      var s = a + m.index, e = s + m[0].length;
      if (pos > s && pos < e) return { from: s, to: e, tex: (m[1] != null ? m[1] : m[2]).trim(), display: m[1] != null };
      if (s >= pos) break;
    }
    return null;
  }

  // ----- formula toolbox -----
  // Each button: [what goes in, what the button shows (default: the same), title]. «‸» is where the cursor (or the
  // selected text) goes. Outside a formula the button's text comes inside $…$.
  function cmds(list) { return list.split(' ').map(function (c) { return ['\\' + c]; }); }
  var FX_TABS = [
    ['یونانی', cmds('alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota kappa varkappa lambda mu nu xi omicron pi varpi rho varrho sigma varsigma tau upsilon phi varphi chi psi omega digamma')
      .concat(cmds('Alpha Beta Gamma Delta Epsilon Zeta Eta Theta Iota Kappa Lambda Mu Nu Xi Omicron Pi Rho Sigma Tau Upsilon Phi Chi Psi Omega'))
      .concat(cmds('varGamma varDelta varTheta varLambda varXi varPi varSigma varUpsilon varPhi varPsi varOmega'))],
    ['اعداد رومی', 'Ⅰ Ⅱ Ⅲ Ⅳ Ⅴ Ⅵ Ⅶ Ⅷ Ⅸ Ⅹ Ⅺ Ⅻ ⅰ ⅱ ⅲ ⅳ ⅴ ⅵ ⅶ ⅷ ⅸ ⅹ ⅺ ⅻ'.split(' ').map(function (c) { return [c, c, 'عدد رومی (در متن، بیرون از فرمول)', 'text']; })],
    ['ساختار', [['\\frac{‸}{}', null, 'کسر'], ['\\dfrac{‸}{}', null, 'کسر بزرگ'], ['^{‸}', 'x^{\\square}', 'توان'], ['_{‸}', 'x_{\\square}', 'زیرنویس'],
      ['_{‸}^{}', 'x_{\\square}^{\\square}', 'زیرنویس و توان'], ['\\sqrt{‸}', null, 'رادیکال'], ['\\sqrt[3]{‸}', null, 'ریشه‌ی سوم'], ['\\sqrt[n]{‸}', null, 'ریشه‌ی n‌ام'],
      ['\\left( ‸ \\right)', null, 'پرانتز هم‌اندازه'], ['\\left[ ‸ \\right]', null, 'کروشه'], ['\\left\\{ ‸ \\right\\}', null, 'آکولاد'], ['\\left| ‸ \\right|', null, 'قدر مطلق'],
      ['\\left\\| ‸ \\right\\|', null, 'نُرم'], ['\\langle ‸ \\rangle', null, 'ضرب داخلی'], ['\\lfloor ‸ \\rfloor', null, 'جزء صحیح'], ['\\lceil ‸ \\rceil', null, 'سقف'],
      ['\\binom{‸}{}', null, 'ترکیب'], ['\\overline{‸}', null, 'خط رو'], ['\\underbrace{‸}_{}', null, 'آکولاد زیر'], ['\\overbrace{‸}^{}', null, 'آکولاد رو'],
      ['\\stackrel{‸}{=}', null, 'چیزی روی علامت'], ['\\boxed{‸}', null, 'در کادر']]],
    ['حسابان', [['\\int'], ['\\int_{‸}^{}', null, 'انتگرال معین'], ['\\iint'], ['\\iiint'], ['\\oint'], ['\\sum_{‸}^{}', null, 'سیگما'], ['\\sum_{i=1}^{n}'], ['\\prod_{‸}^{}', null, 'ضرب'],
      ['\\lim_{‸ \\to }', '\\lim_{x \\to a}', 'حد'], ['\\lim_{x \\to \\infty}'], ['\\frac{d‸}{dx}', '\\frac{d}{dx}', 'مشتق'], ['\\frac{d^2‸}{dx^2}', '\\frac{d^2}{dx^2}', 'مشتق دوم'],
      ['\\frac{\\partial ‸}{\\partial x}', '\\frac{\\partial}{\\partial x}', 'مشتق جزئی'], ['\\partial'], ['\\nabla'], ['\\infty'], ['\\mathrm{d}x'], ["f'(x)"], ["f''(x)"],
      ['\\dot{‸}', '\\dot{x}'], ['\\ddot{‸}', '\\ddot{x}'], ['\\left. ‸ \\right|_{}', '\\left. f \\right|_{a}^{b}', 'جای‌گذاری حدود'], ['\\Delta'], ['\\delta']]],
    ['ماتریس و بردار', [['\\begin{pmatrix} ‸ & \\\\ & \\end{pmatrix}', '\\begin{pmatrix} a & b \\\\ c & d \\end{pmatrix}', 'ماتریس ۲×۲'],
      ['\\begin{pmatrix} ‸ & & \\\\ & & \\\\ & & \\end{pmatrix}', '\\begin{pmatrix} 1&0&0\\\\0&1&0\\\\0&0&1 \\end{pmatrix}', 'ماتریس ۳×۳'],
      ['\\begin{bmatrix} ‸ & \\\\ & \\end{bmatrix}', '\\begin{bmatrix} a & b \\\\ c & d \\end{bmatrix}', 'ماتریس با کروشه'],
      ['\\begin{vmatrix} ‸ & \\\\ & \\end{vmatrix}', '\\begin{vmatrix} a & b \\\\ c & d \\end{vmatrix}', 'دترمینان'],
      ['\\begin{bmatrix} ‸ \\\\ \\\\ \\end{bmatrix}', '\\begin{bmatrix} x \\\\ y \\\\ z \\end{bmatrix}', 'بردار ستونی'],
      ['\\vec{‸}', '\\vec{v}'], ['\\mathbf{‸}', '\\mathbf{v}', 'بردار پررنگ'], ['\\hat{‸}', '\\hat{i}', 'بردار یکه'], ['\\cdot'], ['\\times'], ['\\otimes'], ['\\oplus'],
      ['^{T}', 'A^{T}', 'ترانهاده'], ['^{-1}', 'A^{-1}', 'وارون'], ['^{H}', 'A^{H}', 'ترانهاده‌ی مزدوج'], ['\\det'], ['\\operatorname{tr}'], ['\\operatorname{rank}'],
      ['\\ldots'], ['\\cdots'], ['\\vdots'], ['\\ddots']]],
    ['حالت‌ها و هم‌ترازی', [['\\begin{cases} ‸ & x > 0 \\\\  & x \\le 0 \\end{cases}', '\\begin{cases} a & x>0 \\\\ b & x\\le 0 \\end{cases}', 'تابع چندضابطه‌ای'],
      ['\\begin{aligned} ‸ &= \\\\ &= \\end{aligned}', '\\begin{aligned} a &= b \\\\ &= c \\end{aligned}', 'چند خط هم‌تراز با ='],
      ['\\begin{array}{cc} ‸ & \\\\ & \\end{array}', '\\begin{array}{cc} a & b \\\\ c & d \\end{array}', 'جدول در فرمول'],
      ['\\\\', '\\backslash\\backslash', 'خط بعد (در cases و aligned)'], ['&', '\\&', 'ستون بعد / نقطه‌ی هم‌ترازی'],
      ['\\,', 'a\\,b', 'فاصله‌ی کوچک'], ['\\quad', 'a\\quad b', 'فاصله'], ['\\qquad', 'a\\qquad b', 'فاصله‌ی بزرگ']]],
    ['رابطه‌ها', [['='], ['\\neq'], ['<'], ['>'], ['\\le'], ['\\ge'], ['\\ll'], ['\\gg'], ['\\approx'], ['\\sim'], ['\\simeq'], ['\\cong'], ['\\equiv'], ['\\propto'],
      ['\\pm'], ['\\mp'], ['\\triangleq'], ['\\coloneqq'], ['\\doteq'], ['\\perp'], ['\\parallel'], ['\\mid'], ['\\nmid']]],
    ['مجموعه و منطق', [['\\mathbb{R}'], ['\\mathbb{N}'], ['\\mathbb{Z}'], ['\\mathbb{Q}'], ['\\mathbb{C}'], ['\\in'], ['\\notin'], ['\\ni'], ['\\subset'], ['\\subseteq'], ['\\supset'],
      ['\\supseteq'], ['\\cup'], ['\\cap'], ['\\bigcup_{‸}', '\\bigcup_{i}'], ['\\bigcap_{‸}', '\\bigcap_{i}'], ['\\setminus'], ['\\emptyset'], ['\\varnothing'], ['A^{c}'],
      ['\\{ ‸ \\}', '\\{\\square\\}', 'مجموعه'], ['\\{ x \\mid ‸ \\}', '\\{x \\mid \\square\\}', 'مجموعه با شرط'], ['\\forall'], ['\\exists'], ['\\nexists'], ['\\neg'], ['\\land'], ['\\lor'],
      ['\\Rightarrow'], ['\\Leftrightarrow'], ['\\therefore'], ['\\because']]],
    ['پیکان‌ها', cmds('to rightarrow leftarrow leftrightarrow Rightarrow Leftarrow Leftrightarrow implies iff mapsto longrightarrow Longrightarrow longleftrightarrow uparrow downarrow updownarrow nearrow searrow rightleftharpoons hookrightarrow')
      .concat([['\\xrightarrow{‸}', '\\xrightarrow{f}', 'پیکان با نوشته'], ['\\xleftarrow{‸}', '\\xleftarrow{f}']])],
    ['تابع‌ها', cmds('sin cos tan cot sec csc arcsin arccos arctan sinh cosh tanh log ln exp max min sup inf arg deg gcd det')
      .concat([['\\log_{‸}', '\\log_{a}'], ['\\operatorname{sgn}'], ['\\operatorname{Re}'], ['\\operatorname{Im}'], ['\\operatorname{sinc}'], ['\\operatorname{‸}', '\\operatorname{f}', 'تابعی با نام دلخواه']])],
    ['نشانه‌ها', [['\\hat{‸}', '\\hat{a}'], ['\\bar{‸}', '\\bar{a}'], ['\\tilde{‸}', '\\tilde{a}'], ['\\vec{‸}', '\\vec{a}'], ['\\dot{‸}', '\\dot{a}'], ['\\ddot{‸}', '\\ddot{a}'],
      ['\\overline{‸}', '\\overline{ab}'], ['\\underline{‸}', '\\underline{ab}'], ['\\widehat{‸}', '\\widehat{ab}'], ['\\widetilde{‸}', '\\widetilde{ab}'],
      ['\\overrightarrow{‸}', '\\overrightarrow{AB}'], ['\\cancel{‸}', '\\cancel{x}', 'خط خورده'], ['^{\\circ}', '30^{\\circ}', 'درجه'], ['\\angle'], ['\\triangle'], ['\\%'],
      ['\\star'], ['\\ast'], ['\\dagger'], ['\\prime'], ['\\ell'], ['\\hbar'], ['\\Re'], ['\\Im'], ['\\aleph']]],
    ['آمار و احتمال', [['\\bar{x}'], ['\\hat{\\theta}'], ['\\mu'], ['\\sigma^{2}'], ['E[‸]', 'E[X]', 'امید ریاضی'], ['\\operatorname{Var}(‸)', '\\operatorname{Var}(X)'],
      ['\\operatorname{Cov}(‸, )', '\\operatorname{Cov}(X,Y)'], ['P(‸)', 'P(A)'], ['P(‸ \\mid )', 'P(A \\mid B)', 'احتمال شرطی'], ['\\binom{n}{k}'], ['n!'],
      ['\\sim \\mathcal{N}(\\mu, \\sigma^{2})', null, 'توزیع نرمال'], ['\\sum_{i=1}^{n} x_i'], ['\\overline{X}'], ['\\rho'], ['\\chi^{2}'], ['\\lambda'], ['f_X(x)'], ['F_X(x)']]],
    ['متن و قلم', [['\\text{‸}', '\\text{متن}', 'نوشته‌ی فارسی یا انگلیسی داخل فرمول'], ['\\mathrm{‸}', '\\mathrm{abc}', 'ایستاده'], ['\\mathbf{‸}', '\\mathbf{abc}', 'پررنگ'],
      ['\\boldsymbol{‸}', '\\boldsymbol{\\alpha}', 'پررنگ (برای یونانی هم)'], ['\\mathit{‸}', '\\mathit{abc}'], ['\\mathcal{‸}', '\\mathcal{L}'], ['\\mathbb{‸}', '\\mathbb{R}'],
      ['\\mathfrak{‸}', '\\mathfrak{g}'], ['\\mathsf{‸}', '\\mathsf{abc}'], ['\\textcolor{red}{‸}', '\\textcolor{red}{a}', 'رنگی'], ['\\textcolor{blue}{‸}', '\\textcolor{blue}{a}']]],
  ];
  function fxShow(item) {
    var t = item[1] || item[0];
    return t.replace(/‸/g, '\\square').replace(/\{\}/g, '{\\square}');
  }
  function insertTex(ta, item) {
    var snip = item[0];
    if (item[3] === 'text') { insertText(ta, snip); return; }
    var v = ta.value, at = ta.selectionStart, end = ta.selectionEnd, sel = v.slice(at, end);
    var inside = formulaAt(v, at);
    if (/\\[a-zA-Z]+$/.test(snip)) snip += ' ';
    var caret = snip.indexOf('‸');
    var body = caret < 0 ? snip + (sel ? ' ' + sel : '') : snip.replace('‸', sel);
    var text = inside ? body : '$' + body + '$';
    var off = inside ? 0 : 1;
    var c = off + (caret < 0 ? body.length : caret + sel.length);
    ta.setSelectionRange(at, end);
    insertText(ta, text, c, c);
  }
  // The user's «دستورهای فرمول»: \name, with {} for each #1, #2 of the definition.
  function macroItems() {
    return Object.keys(CTX.macros || {}).sort().map(function (name) {
      var args = 0, m, re = /#(\d)/g, def = CTX.macros[name] || '';
      while ((m = re.exec(def))) args = Math.max(args, +m[1]);
      var snip = name + (args ? '{‸}' + new Array(args).join('{}') : '');
      return [snip, null, name + ' = ' + def];
    });
  }
  var lastFxTab = 0;
  function fxBox(ta) {
    var box = h('div', { class: 'fx-box' });
    var tabs = h('div', { class: 'fx-tabs' }), grid = h('div', { class: 'fx-grid' });
    var all = FX_TABS.concat([['دستورهای من', null]]);
    function show(i) {
      lastFxTab = i;
      tabs.querySelectorAll('button').forEach(function (b, j) { b.classList.toggle('on', i === j); });
      grid.innerHTML = '';
      var items = all[i][1] || macroItems();
      if (!items.length) grid.appendChild(h('span', { class: 'hint' }, 'هنوز دستوری تعریف نشده؛ از «دستورهای فرمول» در پنل اضافه کنید (مثلاً \\R برای ℝ).'));
      items.forEach(function (it) {
        var b = h('button', { type: 'button', title: (it[2] ? it[2] + '\n' : '') + it[0].replace(/‸/g, ''),
          onmousedown: function (e) { e.preventDefault(); }, onclick: function (e) { e.preventDefault(); insertTex(ta, it); } });
        if (it[3] === 'text' || !P || !P.mathHtml) b.textContent = it[1] || it[0];
        else { try { b.innerHTML = P.mathHtml(fxShow(it)); } catch (er) { b.textContent = it[0]; } }
        grid.appendChild(b);
      });
    }
    all.forEach(function (t, i) {
      tabs.appendChild(h('button', { type: 'button', onmousedown: function (e) { e.preventDefault(); }, onclick: function (e) { e.preventDefault(); show(i); } }, t[0]));
    });
    box.appendChild(tabs);
    box.appendChild(grid);
    box.appendChild(h('div', { class: 'hint' }, 'بیرون از فرمول، دکمه‌ها فرمول تازه‌ای با $…$ می‌سازند؛ داخل فرمول، همان‌جا می‌نشینند. اگر متنی انتخاب شده باشد، داخل ساختار می‌رود.'));
    show(Math.min(lastFxTab, all.length - 1));
    return box;
  }

  // ----- «مرتب‌سازی فارسی» -----
  // ي→ی، ك→ک، ارقام عربی→فارسی، فاصله‌های اضافه، نیم‌فاصله‌ی «می/نمی»، «ها/های/تر/ترین» و «ه ی». Formulas, links,
  // images, {#names}, [[links]] and code stay exactly as they are.
  var ZW = '\u200c';
  function tidyFa(text) {
    var keep = [], n = 0;
    var t = text.replace(/\$\$[\s\S]*?\$\$|\$(?:\\.|[^$\n\\])+?\$|`[^`\n]*`|!?\[[^\]\n]*\]\([^)\n]*\)|\[\[[^\]\n]*\]\]|\{#[^}\n]*\}|https?:\/\/\S+/g,
      function (m) { keep.push(m); return '\uE000' + (keep.length - 1) + '\uE001'; });
    function rep(re, by) { t = t.replace(re, function () { n++; return typeof by === 'function' ? by.apply(null, arguments) : by; }); }
    rep(/ي/g, 'ی'); rep(/ى/g, 'ی'); rep(/ك/g, 'ک');
    rep(/[٠-٩]/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'['٠١٢٣٤٥٦٧٨٩'.indexOf(d)]; });
    rep(/[ \t]+$/gm, '');
    rep(/(\S)[ \t]{2,}(?=\S)/g, function (m, a) { return a + ' '; });
    rep(/[ \t]+([،؛؟])/g, function (m, p) { return p; });
    var L = 'آ-ی';
    rep(new RegExp('(^|[\\s(«])(ن?می)[ ]+(?=[' + L + '])', 'gm'), function (m, a, b) { return a + b + ZW; });
    rep(new RegExp('([' + L + '])[ ]+(ها|های|هایی|هایم|هایت|هایش|هایمان|هایتان|هایشان|تر|ترین)(?=$|[\\s.،؛؟!:)»\\]])', 'gm'), function (m, a, b) { return a + ZW + b; });
    rep(new RegExp('(ه)[ ]+(ی)(?=$|[\\s.،؛؟!:)»])', 'gm'), function (m, a, b) { return a + ZW + b; });
    t = t.replace(/\uE000(\d+)\uE001/g, function (m, i) { return keep[+i]; });
    return { text: t, changes: n };
  }
  function tidyIn(ta) {
    var v = ta.value, a = ta.selectionStart, b = ta.selectionEnd;
    var whole = a === b;
    var from = whole ? 0 : a, to = whole ? v.length : b;
    var r = tidyFa(v.slice(from, to));
    if (r.text === v.slice(from, to)) { toast('همه‌چیز مرتب بود.'); return; }
    replaceRange(ta, from, to, r.text);
    ta.setSelectionRange(Math.min(a, from + r.text.length), Math.min(a, from + r.text.length));
    toast((whole ? 'کل متن' : 'متن انتخاب‌شده') + ' مرتب شد (' + fa(r.changes) + ' مورد). با Ctrl+Z برمی‌گردد.');
  }

  // ----- find and replace -----
  function findRe(needle, whole) {
    if (!needle) return null;
    var src = needle.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
      .replace(/[یيى]/g, '[یيى]').replace(/[کك]/g, '[کك]').replace(/[ \u200c]/g, '[ \\u200c]');
    if (whole) src = '(?<![\\p{L}\\p{N}])' + src + '(?![\\p{L}\\p{N}])';
    try { return new RegExp(src, 'giu'); } catch (e) { return null; }
  }
  function findBar(ta, opts) {
    var q = h('input', { type: 'text', placeholder: 'جست‌وجو…' });
    var r = h('input', { type: 'text', placeholder: 'جایگزین با…' });
    var whole = h('input', { type: 'checkbox' });
    var count = h('span', { class: 'hint' });
    function matches() {
      var re = findRe(q.value, whole.checked), out = [], m;
      if (!re) return out;
      while ((m = re.exec(ta.value))) { out.push([m.index, m.index + m[0].length]); if (!m[0].length) re.lastIndex++; }
      return out;
    }
    function upd() { var n = matches().length; count.textContent = q.value ? (n ? fa(n) + ' مورد' : 'پیدا نشد') : ''; return n; }
    function go(dir) {
      var all = matches();
      if (!all.length) { upd(); return; }
      var at = dir > 0 ? ta.selectionEnd : ta.selectionStart, pick = null;
      if (dir > 0) pick = all.filter(function (x) { return x[0] >= at; })[0] || all[0];
      else pick = all.filter(function (x) { return x[1] <= at; }).pop() || all[all.length - 1];
      ta.setSelectionRange(pick[0], pick[1]);
      count.textContent = fa(all.indexOf(pick) + 1) + ' از ' + fa(all.length);
    }
    function one() {
      var all = matches(), a = ta.selectionStart, b = ta.selectionEnd;
      var hit = all.filter(function (x) { return x[0] === a && x[1] === b; })[0];
      if (!hit) { go(1); return; }
      replaceRange(ta, a, b, r.value);
      ta.setSelectionRange(a + r.value.length, a + r.value.length);
      go(1);
    }
    function every() {
      var re = findRe(q.value, whole.checked); if (!re) return;
      var n = upd(); if (!n) return;
      var v = ta.value, out = v.replace(re, function () { return r.value; });
      replaceRange(ta, 0, v.length, out);
      ta.setSelectionRange(0, 0);
      upd();
      toast(fa(n) + ' مورد جایگزین شد. با Ctrl+Z برمی‌گردد.');
    }
    q.addEventListener('input', upd);
    whole.addEventListener('change', upd);
    q.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); go(e.shiftKey ? -1 : 1); } });
    r.addEventListener('keydown', function (e) { if (e.key === 'Enter') { e.preventDefault(); one(); } });
    function b(label, fn, title) { return h('button', { type: 'button', class: 'btn small', title: title, onmousedown: function (e) { e.preventDefault(); }, onclick: function (e) { e.preventDefault(); fn(); } }, label); }
    var el = h('div', { class: 'find-bar' }, q, b('▲', function () { go(-1); }, 'قبلی (Shift+Enter)'), b('▼', function () { go(1); }, 'بعدی (Enter)'), count,
      r, b('جایگزین', one), b('جایگزین همه', every), h('label', { class: 'hint' }, whole, ' کل کلمه'));
    if (opts && opts.fileUrl) el.appendChild(h('a', { class: 'hint', href: opts.fileUrl, title: 'جست‌وجو و جایگزینی در درسنامه، چکیده، تست‌ها و فلش‌کارت‌های همه‌ی بخش‌ها' }, 'در کل فصل…'));
    el.appendChild(h('span', { class: 'hint' }, 'ی/ي و ک/ك و فاصله/نیم‌فاصله یکی حساب می‌شوند.'));
    return { el: el, focus: function () { var s = ta.value.slice(ta.selectionStart, ta.selectionEnd); if (s && s.indexOf('\n') < 0) q.value = s; q.focus(); q.select(); upd(); } };
  }

  // ----- [[#name]] picker -----
  function refBox(ta) {
    var names = Object.keys(CTX.refs || {});
    var box = h('div', { class: 'ref-box' });
    if (!names.length) {
      box.appendChild(h('span', { class: 'hint' }, 'هنوز کادر یا فرمول نام‌داری در این کتاب نیست. به کادر شماره‌دار یا فرمول جدا یک نام بدهید: «:::مثال {#نام}» یا «$$…$$ {#نام}».'));
      return box;
    }
    var filter = h('input', { type: 'text', placeholder: 'پیدا کردن…' });
    var list = h('div', { class: 'ref-list' });
    function draw() {
      list.innerHTML = '';
      var f = filter.value.trim();
      names.filter(function (n) { var r = CTX.refs[n] || {}; return !f || n.indexOf(f) >= 0 || String(r.text || '').indexOf(f) >= 0; }).slice(0, 200).forEach(function (n) {
        var r = CTX.refs[n] || {};
        list.appendChild(h('button', { type: 'button', onmousedown: function (e) { e.preventDefault(); },
          onclick: function (e) { e.preventDefault(); insertText(ta, '[[#' + n + ']]'); } },
          h('b', null, r.text || n), ' ', h('span', { class: 'hint', dir: 'ltr' }, '#' + n)));
      });
    }
    filter.addEventListener('input', draw);
    box.appendChild(filter);
    box.appendChild(list);
    box.appendChild(h('div', { class: 'hint' }, 'در متن «[[#نام]]» می‌نشیند و اپ به جایش شماره را می‌نویسد (مثلاً «مثال ۳-۵»).'));
    draw();
    return box;
  }

  // ----- the tools on a toolbar -----
  // bar: the toolbar; host: where the panels open (under the toolbar). opts: { before (a node of the bar the tools go
  // in front of), fileUrl (the whole-file page, for «در کل فصل»), find, refs }.
  function addTools(ta, bar, host, opts) {
    opts = opts || {};
    var open = null, find = null;
    var panel = h('div', { class: 'md-panel' });
    var fx = h('div', { class: 'fx-prev', style: 'display:none', title: 'فرمولی که مکان‌نما در آن است' });
    host.appendChild(panel);
    host.appendChild(fx);
    function toggle(name, make, button) {
      bar.querySelectorAll('button.tool').forEach(function (x) { x.classList.remove('on'); });
      panel.innerHTML = '';
      if (open === name) { open = null; return null; }
      open = name;
      var made = make();
      panel.appendChild(made.el || made);
      if (button) button.classList.add('on');
      return made;
    }
    function tb(label, title, fn, cls) {
      return h('button', { type: 'button', class: cls || '', title: title, onmousedown: function (e) { e.preventDefault(); }, onclick: function (e) { e.preventDefault(); fn(e.currentTarget); } }, label);
    }
    var first = bar.firstChild;
    bar.insertBefore(tb('↶', 'برگرداندن (Ctrl+Z)', function () { undoRedo(ta, true); }), first);
    bar.insertBefore(tb('↷', 'دوباره (Ctrl+Y)', function () { undoRedo(ta, false); }), first);
    bar.insertBefore(h('span', { class: 'sep' }), first);
    var tools = h('span', { class: 'tools' });
    var fxBtn = tb('ƒ ابزار فرمول', 'حروف یونانی، کسر، انتگرال، ماتریس، مجموعه‌ها… (روی هر دکمه بزنید تا سر جای مکان‌نما بنشیند)', function (b) { toggle('fx', function () { return fxBox(ta); }, b); }, 'tool');
    tools.appendChild(fxBtn);
    if (opts.refs !== false) tools.appendChild(tb('# ارجاع', 'ارجاع به کادر یا فرمول نام‌دار: [[#نام]]', function (b) { toggle('ref', function () { return refBox(ta); }, b); }, 'tool'));
    tools.appendChild(tb('نیم‌فاصله', 'نیم‌فاصله (Ctrl+Shift+2)', function () { insertText(ta, ZW); }));
    tools.appendChild(tb('مرتب‌سازی فارسی', 'ي و ك عربی، فاصله‌های اضافه، نیم‌فاصله‌ی «می»، «ها»، «تر» و «ترین». روی متن انتخاب‌شده یا کل متن. فرمول‌ها دست نمی‌خورند.', function () { tidyIn(ta); }));
    function openFind() { var b = bar.querySelector('button.find'); if (open !== 'find') find = toggle('find', function () { return findBar(ta, opts); }, b); if (find) find.focus(); }
    if (opts.find !== false) tools.appendChild(tb('🔍 جست‌وجو', 'جست‌وجو و جایگزینی (Ctrl+F)', function (b) { if (open === 'find') toggle('find'); else openFind(); }, 'tool find'));
    bar.insertBefore(h('span', { class: 'sep' }), opts.before || null);
    bar.insertBefore(tools, opts.before || null);

    ta.addEventListener('keydown', function (e) {
      var k = e.ctrlKey || e.metaKey;
      if (k && e.shiftKey && e.code === 'Digit2') { e.preventDefault(); insertText(ta, ZW); }
      else if (k && !e.shiftKey && (e.code === 'KeyF' || e.code === 'KeyH') && opts.find !== false) { e.preventDefault(); openFind(); }
      else if (k && !e.shiftKey && e.code === 'KeyY') { e.preventDefault(); undoRedo(ta, false); }
      else if (e.key === 'Escape' && open) { toggle(open); }
    });
    // The formula under the cursor, drawn as the learner sees it.
    var pending = false, lastTex = null;
    function showFx() {
      pending = false;
      var f = formulaAt(ta.value, ta.selectionStart);
      if (!f || !f.tex || !P || !P.mathHtml) { fx.style.display = 'none'; lastTex = null; return; }
      if (f.tex === lastTex) { fx.style.display = ''; return; }
      lastTex = f.tex;
      try { fx.innerHTML = P.mathHtml(f.tex, true); } catch (e) { fx.textContent = e.message; }
      fx.style.display = '';
    }
    function later() { if (!pending) { pending = true; requestAnimationFrame(showFx); } }
    ['limo-cursor', 'input', 'keyup', 'click', 'select'].forEach(function (ev) { ta.addEventListener(ev, later); });
  }

  // ----- drafts -----
  // While typing, the text is kept in this browser; if the page is closed before «ذخیره», the next time the same box
  // opens it offers the draft back. A save, «دور بینداز» or getting the text back to the saved one forgets it.
  var Drafts = {
    k: function (key) { return 'limo.draft.' + key; },
    get: function (key) {
      try {
        var d = JSON.parse(localStorage.getItem(this.k(key)) || 'null');
        if (d && Date.now() - d.at > 30 * 864e5) { this.drop(key); return null; }
        return d;
      } catch (e) { return null; }
    },
    put: function (key, text, base) { try { localStorage.setItem(this.k(key), JSON.stringify({ text: text, base: base, at: Date.now() })); } catch (e) { /* full or blocked */ } },
    drop: function (key) { try { localStorage.removeItem(this.k(key)); } catch (e) { /* ignore */ } },
  };
  function whenFa(at) {
    var d = new Date(at), mins = Math.round((Date.now() - at) / 60000);
    if (mins < 1) return 'همین الان';
    if (mins < 60) return fa(mins) + ' دقیقه پیش';
    if (mins < 24 * 60) return fa(Math.round(mins / 60)) + ' ساعت پیش';
    try { return d.toLocaleDateString('fa-IR-u-ca-persian', { month: 'long', day: 'numeric' }); } catch (e) { return fa(Math.round(mins / 1440)) + ' روز پیش'; }
  }
  // key: one box; base: the saved text; get(): the text now; restore(text): put the draft back. Returns
  // { el (the offer, or null), changed() to call on every edit, saved() to call after a save }.
  function draftKeeper(key, base, get, restore) {
    var d = Drafts.get(key), el = null, t = null;
    if (d && d.text === base) { Drafts.drop(key); d = null; }
    if (d) {
      el = h('div', { class: 'msg warn draft-bar' },
        h('b', null, 'پیش‌نویس ذخیره‌نشده (' + whenFa(d.at) + ')'), ' ',
        d.base !== base ? h('span', null, 'متن ذخیره‌شده از آن موقع عوض شده؛ اگر برگردانید، روی آن نوشته می‌شود. ') : null,
        h('button', { class: 'btn small primary', type: 'button', onclick: function () { el.remove(); restore(d.text); } }, 'برگرداندن پیش‌نویس'), ' ',
        h('button', { class: 'btn small', type: 'button', onclick: function () { el.remove(); Drafts.drop(key); } }, 'دور بینداز'));
    }
    return {
      el: el,
      changed: function () {
        clearTimeout(t);
        t = setTimeout(function () { var v = get(); if (v === base) Drafts.drop(key); else Drafts.put(key, v, base); }, 600);
      },
      saved: function () { clearTimeout(t); Drafts.drop(key); },
    };
  }
  window.LimoDrafts = Drafts;

  // ---------- Markdown editor ----------

  // Starting plots for the «نمودار» button (the lines are explained in docs/content-format.md).
  var PLOT_TEMPLATES = [
    ['تابع', 'تابع: sin(x)\nبازه: -2pi تا 2pi\nعلامت x: pi', 'نمودار یک یا چند تابع'],
    ['ضربه δ', 'ضربه: 0، (2, -0.5)\nمتغیر: t', 'ضربه‌ها با وزن؛ «قطار ضربه: T» برای قطار ضربه'],
    ['گسسته x[n]', 'تابع: 0.8^n u(n)\nمتغیر: n\nبازه: -3 تا 10', 'سیگنال گسسته؛ یا «مقادیر: 1، 2، 3 از -1»'],
    ['صفر و قطب', 'صفر: 0\nقطب: 0.5، 0.8±0.4j\nناحیه: |z| > 0.89', 'صفحه‌ی z با ناحیه‌ی همگرایی؛ برای لاپلاس «ناحیه: Re(s) > -1»'],
    ['بُد', 'بود: 10/(s+10)', 'نمودار بُد: دامنه (دقیق و مجانبی) و فاز'],
    ['نایکوئیست', 'نایکوئیست: 10/((s+1)(s+2))', 'نمودار نایکوئیست H(jω)'],
  ];

  function MdEditor(textarea, opts) {
    opts = opts || {};
    var self = this;
    this.ta = textarea;
    this.variant = opts.variant || 'notes';
    this.onChange = opts.onChange || function () {};
    var wrap = h('div', { class: 'md-ed' + (opts.compact ? ' compact' : '') });
    var bar = h('div', { class: 'md-bar' });
    function btn(label, title, fn) { return h('button', { type: 'button', title: title, onclick: function (e) { e.preventDefault(); fn(); self.ta.focus(); } }, label); }
    bar.appendChild(btn('B', 'پررنگ (Ctrl+B)', function () { self.wrap('**', '**', 'متن پررنگ'); }));
    bar.appendChild(btn('I', 'کج', function () { self.wrap('*', '*', 'متن کج'); }));
    bar.appendChild(btn('S̶', 'خط روی متن', function () { self.wrap('~~', '~~', 'متن'); }));
    // Coloured words: «==قرمز:متن==» (red, blue, green).
    [['قرمز', '#C2413B'], ['آبی', '#2F5BC8'], ['سبز', '#23784A']].forEach(function (c) {
      var b = btn('●', 'متن ' + c[0] + ' (==' + c[0] + ':متن==)', function () { self.wrap('==' + c[0] + ':', '==', 'متن'); });
      b.style.color = c[1];
      bar.appendChild(b);
    });
    bar.appendChild(h('span', { class: 'sep' }));
    if (!opts.inline) {
      bar.appendChild(btn('تیتر', 'تیتر کوچک داخل متن (###)', function () { self.linePrefix('### '); }));
      bar.appendChild(btn('• فهرست', 'فهرست', function () { self.linePrefix('- '); }));
      bar.appendChild(btn('۱. فهرست', 'فهرست شماره‌دار', function () { self.linePrefix('1. '); }));
      bar.appendChild(h('span', { class: 'sep' }));
    }
    bar.appendChild(btn('𝑥 فرمول', 'فرمول درون خط ($…$)', function () { self.wrap('$', '$', 'x^2'); }));
    if (!opts.inline) {
      bar.appendChild(btn('∑ فرمول جدا', 'فرمول در خط جدا ($$…$$)', function () { self.block('$$\n', '\n$$', '\\frac{a}{b}'); }));
      bar.appendChild(h('span', { class: 'sep' }));
      if (this.variant !== 'summary') {
        bar.appendChild(btn('▦ جدول', 'جدول', function () { self.block('', '', '| ستون ۱ | ستون ۲ |\n| --- | --- |\n| … | … |'); }));
      }
      if (opts.uploadUrl) bar.appendChild(btn('🖼 عکس', 'افزودن عکس', function () { self.pickImage(opts.uploadUrl); }));
    }
    var modes = h('span', { class: 'modes' });
    var modeBtns = {};
    [['split', 'هر دو'], ['text', 'فقط متن'], ['preview', 'فقط پیش‌نمایش']].forEach(function (m) {
      modeBtns[m[0]] = h('button', { type: 'button', onclick: function (e) { e.preventDefault(); self.setMode(m[0]); } }, m[1]);
      modes.appendChild(modeBtns[m[0]]);
    });
    bar.appendChild(modes);
    var host = h('div', { class: 'md-host' });
    addTools(textarea, bar, host, { before: modes, fileUrl: opts.fileUrl, find: !opts.inline });
    // The width and the alignment of the preview, above it; both remembered between visits. Defined before setMode,
    // which the constructor calls at its end.
    var self2 = self;
    this.applyWidth = function () {
      var px = widthPx(previewWidth());
      self2.frame.style.width = px ? px + 'px' : '100%';
    };
    var ctl = previewControls(function () {
      self2.applyWidth();
      if (wrap.classList.contains('mode-split') || wrap.classList.contains('mode-preview')) self2.refresh();
    });
    this.setMode = function (m) {
      wrap.classList.remove('mode-split', 'mode-text', 'mode-preview');
      wrap.classList.add('mode-' + m);
      for (var k in modeBtns) modeBtns[k].classList.toggle('on', k === m);
      try { localStorage.setItem('limo.panel.mode', m); } catch (e) { /* ignore */ }
      if (m !== 'text') self.refresh();
      self.applyWidth();
    };
    this.frame = h('iframe', { title: 'پیش‌نمایش مثل گوشی' });
    var body = h('div', { class: 'md-body' });
    textarea.parentNode.insertBefore(wrap, textarea);
    body.appendChild(textarea);
    body.appendChild(h('div', { class: 'md-prev' }, ctl.el, this.frame));
    // A draft left from last time (closed before «ذخیره»): offered back above the toolbar.
    this.drafts = opts.draft ? draftKeeper(opts.draft, textarea.value, function () { return textarea.value; }, function (text) {
      replaceRange(textarea, 0, textarea.value.length, text);
    }) : { el: null, changed: function () {}, saved: function () {} };
    if (this.drafts.el) wrap.appendChild(this.drafts.el);
    wrap.appendChild(bar);
    wrap.appendChild(host);
    // Label buttons, only in the notes («درسنامه»): each one puts the selected text (or a sample) in a box
    // «:::تعریف … :::». Not in tests or flashcards: they are blocks themselves, and blocks cannot go inside blocks.
    if (opts.labels && !opts.inline && labelList().length) {
      wrap.appendChild(labelRow(function (l) {
        if (self.variant === 'summary') { insertSummaryLabel(self.ta, l); return; }
        // «نمودار»: a plot drawn from a description (app/src/lib/plot.ts); edit the lines and watch the preview.
        // A small menu of starting plots: a function, impulses, a discrete signal, poles and zeros, a Bode plot.
        if (l.name === 'نمودار') {
          var old = wrap.querySelector('.plot-menu');
          if (old) { old.remove(); return; }
          var menu = h('div', { class: 'plot-menu' });
          PLOT_TEMPLATES.forEach(function (t) {
            menu.appendChild(h('button', { type: 'button', title: t[2], onclick: function (e) {
              e.preventDefault();
              menu.remove();
              self.block(':::نمودار\n', '\n:::', t[1]);
              self.ta.focus();
            } }, t[0]));
          });
          wrap.insertBefore(menu, body);
          return;
        }
        var sample = l.name === 'پرسش و پاسخ' ? 'پرسش: …\nپاسخ: …'
          : l.name === 'تمرین' ? 'صورت تمرین…\nحل: …'
          : l.style === 'table' && l.columns && l.columns.length
          ? '| ' + l.columns.join(' | ') + ' |\n|' + l.columns.map(function () { return ' --- '; }).join('|') + '|\n|' + l.columns.map(function () { return ' … '; }).join('|') + '|'
          : 'متن ' + l.name;
        self.block(':::' + l.name + '\n', '\n:::', sample);
        self.ta.focus();
      }, function (l) { return self.variant === 'summary' || l.role !== 'glance'; }, self.variant === 'summary' ? 'برچسب:' : 'کادر:'));
    }
    wrap.appendChild(body);
    this.el = wrap;
    var timer = null;
    textarea.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () { self.refresh(); }, 250);
      self.onChange(textarea.value);
      self.drafts.changed();
    });
    textarea.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'b' || e.key === 'ذ')) { e.preventDefault(); self.wrap('**', '**', 'متن پررنگ'); }
    });
    cmUpgrade(textarea, opts.inline ? 1 : opts.compact ? 3 : 14);
    var saved = 'split';
    try { saved = localStorage.getItem('limo.panel.mode') || 'split'; } catch (e) { /* ignore */ }
    this.setMode(opts.mode || saved);
  }
  MdEditor.prototype.refresh = function () {
    var html;
    try { html = render(this.ta.value, this.variant); } catch (e) { html = '<p style="color:#ba2121">خطا در نمایش: ' + e.message + '</p>'; }
    var scroll = 0;
    try { scroll = this.frame.contentWindow.scrollY; } catch (e) { /* ignore */ }
    var frame = this.frame;
    frame.srcdoc = previewDoc(html);
    frame.onload = function () { try { frame.contentWindow.scrollTo(0, scroll); } catch (e) { /* ignore */ } };
  };
  MdEditor.prototype.insert = function (text, selectFrom, selectTo) {
    var ta = this.ta, start = ta.selectionStart, end = ta.selectionEnd;
    ta.focus();
    ta.setSelectionRange(start, end);
    var ok = typeIn(ta, text);
    if (!ok) { ta.setRangeText(text, start, end, 'end'); ta.dispatchEvent(new Event('input')); }
    if (selectFrom != null) ta.setSelectionRange(start + selectFrom, start + selectTo);
  };
  MdEditor.prototype.wrap = function (before, after, placeholder) {
    var ta = this.ta, sel = ta.value.slice(ta.selectionStart, ta.selectionEnd);
    if (sel && sel.slice(0, before.length) === before && sel.slice(-after.length) === after && sel.length >= before.length + after.length) {
      var inner = sel.slice(before.length, sel.length - after.length);
      this.insert(inner, 0, inner.length);
      return;
    }
    var text = sel || placeholder;
    this.insert(before + text + after, before.length, before.length + text.length);
  };
  MdEditor.prototype.linePrefix = function (prefix) {
    var ta = this.ta, v = ta.value;
    var start = v.lastIndexOf('\n', ta.selectionStart - 1) + 1;
    var end = v.indexOf('\n', ta.selectionEnd); if (end < 0) end = v.length;
    var lines = v.slice(start, end).split('\n');
    var all = lines.every(function (l) { return l.indexOf(prefix) === 0; });
    var out = lines.map(function (l, i) {
      if (all) return l.slice(prefix.length);
      var p = prefix === '1. ' ? (i + 1) + '. ' : prefix;
      return p + l.replace(/^(\d+\.|-|###)\s+/, '');
    }).join('\n');
    ta.setSelectionRange(start, end);
    this.insert(out, 0, out.length);
  };
  MdEditor.prototype.block = function (before, after, placeholder) {
    var ta = this.ta, v = ta.value, sel = v.slice(ta.selectionStart, ta.selectionEnd) || placeholder;
    var lead = ta.selectionStart > 0 && v[ta.selectionStart - 1] !== '\n' ? '\n\n' : (ta.selectionStart > 1 && v[ta.selectionStart - 2] !== '\n' && ta.selectionStart > 0 ? '\n' : '');
    var trail = v[ta.selectionEnd] && v[ta.selectionEnd] !== '\n' ? '\n\n' : '\n';
    var text = lead + before + sel + after + trail;
    this.insert(text, lead.length + before.length, lead.length + before.length + sel.length);
  };
  MdEditor.prototype.pickImage = function (url) {
    var self = this;
    var input = h('input', { type: 'file', accept: '.png,.jpg,.jpeg,.webp,.gif,.svg' });
    input.onchange = function () {
      if (!input.files.length) return;
      var form = new FormData();
      form.append('image', input.files[0]);
      fetch(url, { method: 'POST', body: form, headers: { 'X-CSRFToken': csrf() }, credentials: 'same-origin' })
        .then(function (r) { return r.json(); })
        .then(function (d) {
          if (d.errors) { toast(d.errors, 'err'); return; }
          var caption = prompt('زیرنویس عکس (برای دانشجو نشان داده می‌شود):', '') || 'عکس';
          self.block('', '', '![' + caption + '](' + d.ref + ')');
        })
        .catch(function () { toast(['بارگذاری عکس انجام نشد.'], 'err'); });
    };
    input.click();
  };
  window.LimoMdEditor = MdEditor;

  // ---------- toast ----------
  var toastEl = null;
  function toast(lines, kind, keep) {
    if (toastEl) toastEl.remove();
    lines = Array.isArray(lines) ? lines : [lines];
    toastEl = h('div', { class: 'lp' }, h('div', { class: 'msg toast ' + (kind || 'ok') },
      lines.length > 1 ? h('ul', null, lines.map(function (l) { return h('li', null, l); })) : lines[0],
      h('div', { style: 'margin-top:6px' }, h('button', { class: 'btn small', type: 'button', onclick: function () { toastEl.remove(); toastEl = null; } }, 'بستن'))));
    document.body.appendChild(toastEl);
    if (!keep && kind !== 'err') { var el = toastEl; setTimeout(function () { if (toastEl === el) { el.remove(); toastEl = null; } }, 4000); }
  }
  window.LimoToast = toast;

  // Editors on plain admin forms (e.g. «درباره‌ی کتاب»).
  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('textarea[data-md-editor]').forEach(function (ta) {
      if (!P) return;
      var box = h('div', { class: 'lp', style: 'flex:1;min-width:0;width:100%;max-width:1100px' });
      ta.parentNode.insertBefore(box, ta);
      box.appendChild(ta);
      new MdEditor(ta, { variant: 'notes' });
    });
  });

  // ---------- Chapter manager ----------
  var DIFF = [['easy', 'آسان'], ['medium', 'متوسط'], ['hard', 'سخت']];
  var KINDS = [['', '—'], ['recall', 'حفظی'], ['concept', 'مفهومی'], ['calc', 'محاسباتی'], ['analysis', 'تحلیلی']];
  var DOMAINS = [['', '—'], ['general', 'عمومی'], ['specialized', 'تخصصی']];
  function label(list, v) { var x = list.filter(function (i) { return i[0] === v; })[0]; return x ? x[1] : v; }

  function Manager(root, api) {
    this.root = root;
    this.api = api;
    this.state = null;
    this.sel = null;      // selected section slug ('' = introduction)
    this.tab = 'notes';
    this.open = null;     // open item editor: {kind, slug|null}
    this.dirty = null;    // description of unsaved work
    var self = this;
    window.addEventListener('beforeunload', function (e) { if (self.dirty) { e.preventDefault(); e.returnValue = ''; } });
    window.addEventListener('hashchange', function () { self.fromHash(); });
    this.load();
  }

  Manager.prototype.call = function (payload) {
    var self = this;
    payload.version = this.state && this.state.version;
    this.root.classList.add('busy');
    var done = function (x) { self.root.classList.remove('busy'); return x; };
    var fail = function (e) { self.root.classList.remove('busy'); throw e; };
    return fetch(this.api, {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() },
      body: JSON.stringify(payload),
    }).then(function (r) { return r.json().then(function (d) { return { status: r.status, data: d }; }); })
      .then(function (res) {
        if (res.data.errors) {
          toast(res.data.errors, 'err');
          if (res.data.conflict) {
            toast([res.data.errors[0], 'برای دیدن آخرین نسخه صفحه را تازه کنید.'], 'err');
          }
          throw new Error('rejected');
        }
        if (res.data.state) {
          self.state = res.data.state;
          setCtx(self.state);
          MEDIA = self.state.media_url;
        }
        if (res.data.warnings && res.data.warnings.length) {
          var useful = res.data.warnings.filter(function (w) { return w.indexOf('مقدمه‌ی فصل ذخیره می‌شود') < 0; });
          if (useful.length) toast(['ذخیره شد، با این هشدارها:'].concat(useful), 'warn', true);
        }
        return res.data;
      }).then(done, fail);
  };
  Manager.prototype.load = function () {
    var self = this;
    // A failure here used to be silent: no .catch, so the page sat on «در حال باز کردن فصل…» forever — a blank
    // screen with no reason in it, and nothing to tell the professor, or us, what went wrong. Say it instead.
    fetch(this.api, { credentials: 'same-origin' })
      .then(function (r) {
        if (r.status === 403) throw new Error('اجازه‌ی نوشتن در این کتاب را ندارید. از مدیر کل بخواهید شما را در «استادان کتاب» اضافه کند.');
        if (r.status === 404) throw new Error('این فصل پیدا نشد؛ شاید پاک شده باشد.');
        if (!r.ok) throw new Error('سرور خطا داد (' + r.status + '). کمی بعد دوباره تلاش کنید.');
        return r.json();
      })
      .then(function (d) {
        if (!d || !d.state) throw new Error('پاسخ سرور خوانده نشد. صفحه را تازه کنید.');
        self.state = d.state;
        setCtx(self.state);
        MEDIA = d.state.media_url;
        if (!self.fromHash()) { self.sel = d.state.sections.length ? d.state.sections[0].slug : ''; self.render(); }
      })
      .catch(function (e) {
        self.root.classList.remove('busy');
        self.root.innerHTML = '';
        var box = h('div', { class: 'msg err', style: 'margin:20px' },
          h('b', null, 'فصل باز نشد'),
          h('p', null, (e && e.message) || 'خطای نامشخص.'),
          h('p', null, h('button', { class: 'btn', type: 'button', onclick: function () { location.reload(); } }, 'تلاش دوباره')));
        self.root.appendChild(box);
      });
  };
  Manager.prototype.fromHash = function () {
    var m = location.hash.match(/^#([sqf])=([^&]*)(.*)$/);
    if (!m || !this.state) return false;
    // A hand-edited or cut link must not stop the page.
    function safeDecode(x) { try { return decodeURIComponent(x); } catch (e) { return x; } }
    var key = m[1], slug = safeDecode(m[2]);
    // A learner's report: «&m=summary» opens the summary, «&find=…» selects the reported words in the text.
    var extra = {};
    m[3].split('&').forEach(function (kv) { var i = kv.indexOf('='); if (i > 0) extra[kv.slice(0, i)] = safeDecode(kv.slice(i + 1)); });
    if (key === 's') {
      this.sel = slug; this.open = null;
      this.tab = extra.m === 'summary' && slug ? 'summary' : 'notes';
      if (extra.m === 'summary') this.summaryMode = 'raw';
      this.find = extra.find || null;
    }
    else {
      var all = [this.state.intro].concat(this.state.sections);
      for (var i = 0; i < all.length; i++) {
        var list = key === 'q' ? all[i].questions : all[i].flashcards;
        if (list.some(function (x) { return x.slug === slug; })) {
          this.sel = all[i].slug; this.tab = key === 'q' ? 'questions' : 'flashcards'; this.open = { kind: key === 'q' ? 'question' : 'flashcard', slug: slug };
        }
      }
    }
    // A report on a section archived since: it is no longer in the chapter, so say so (with the report's words).
    if (extra.gone) {
      this.find = null; this.open = null;
      toast(['این بخش بایگانی شده؛ متن گزارش: ' + (extra.r ? '«' + extra.r + '»' : '(بدون متن)')], 'warn', true);
    }
    this.render();
    var target = document.getElementById('item-' + slug);
    if (target) target.scrollIntoView({ block: 'center' });
    return true;
  };
  Manager.prototype.guard = function () {
    if (!this.dirty) return true;
    if (confirm('تغییرات «' + this.dirty + '» ذخیره نشده‌اند. بدون ذخیره ادامه می‌دهید؟')) { this.dirty = null; return true; }
    return false;
  };
  Manager.prototype.section = function () {
    var s = this.state;
    if (this.sel === '') return s.intro;
    return s.sections.filter(function (x) { return x.slug === this.sel; }, this)[0] || s.sections[0] || s.intro;
  };
  // Selects a learner's reported words in a text box. The quote is the text as read (no ** or ==, formulas as $tex$),
  // so both are compared without Markdown marks and with spaces folded; failing the whole, its start is tried.
  function findInSource(src, quote) {
    var drop = /[*_=~`#>]/;
    var norm = '', map = [];
    for (var i = 0; i < src.length; i++) {
      var c = src[i];
      if (drop.test(c)) continue;
      if (/\s/.test(c) || c === '\u200c') { if (norm && norm[norm.length - 1] === ' ') continue; c = ' '; }
      norm += c; map.push(i);
    }
    var q = quote.replace(/[*_=~`#>]/g, '').replace(/[\s\u200c]+/g, ' ').trim();
    var tries = [q, q.slice(0, 80), q.slice(0, 40), q.slice(0, 20)];
    for (var t = 0; t < tries.length; t++) {
      if (tries[t].length < 6) break;
      var at = norm.indexOf(tries[t]);
      if (at >= 0) return [map[at], map[at + tries[t].length - 1] + 1];
    }
    return null;
  }
  Manager.prototype.selectFind = function (ta) {
    var self = this, quote = this.find;
    if (!quote) return;
    setTimeout(function () {
      // The page may have been drawn again meanwhile: the newest box takes it.
      if (!ta.isConnected || self.find !== quote) return;
      self.find = null;
      var r = findInSource(ta.value, quote);
      if (!r) { toast(['متن گزارش‌شده پیدا نشد (شاید قبلاً اصلاح شده): «' + quote.slice(0, 120) + '»'], 'err'); return; }
      ta.focus();
      ta.setSelectionRange(r[0], r[1]);
      if (ta.scrollIntoView) ta.scrollIntoView({ block: 'center' });
    }, 300);
  };
  Manager.prototype.go = function (slug, tab) {
    if (!this.guard()) return;
    this.sel = slug; this.tab = tab || 'notes'; this.open = null;
    history.replaceState(null, '', '#s=' + encodeURIComponent(slug));
    this.render();
  };

  Manager.prototype.render = function () {
    var root = this.root;
    root.innerHTML = '';
    root.appendChild(this.renderHead());
    var grid = h('div', { class: 'cm' });
    grid.appendChild(this.renderTree());
    var main = h('div', { class: 'cm-main' });
    main.appendChild(this.renderSection());
    grid.appendChild(main);
    root.appendChild(grid);
  };

  Manager.prototype.renderHead = function () {
    var self = this, st = this.state, c = st.chapter;
    var base = this.api.replace(/api\/$/, '');
    if (st.inbox) {
      // «صندوق تست»: no publishing, no chapter details; tests wait here until they are moved.
      return h('div', null, h('div', { class: 'cm-head' },
        h('h2', null, '📥 صندوق تست'),
        h('a', { class: 'btn primary', href: base + 'file/', title: 'تست‌ها را با قالب :::تست … ::: پشت سر هم بچسبانید' }, 'افزودن یکجای تست‌ها (ویرایش کل فایل)'),
        h('a', { class: 'btn', href: base + 'history/' }, 'نسخه‌ها (' + fa(st.revisions) + ')'),
        h('a', { class: 'btn', href: '../../' }, 'کتاب‌ها')),
        h('p', { class: 'hint' }, 'اینجا در اپ دیده نمی‌شود. تست‌ها را یکجا وارد کنید، بعد تیک بزنید و به هر بخشِ هر کتاب منتقل کنید. ' +
          'جواب‌ها و آمار هر تست همراهش می‌رود.'));
    }
    return h('div', { class: 'cm-head' },
      h('h2', null, (c.number ? 'فصل ' + fa(c.number) + ': ' : '') + c.title),
      (function () {
        var p = self.publishBox(c.is_published, function (e) {
          self.call({ op: 'chapter.publish', value: e.target.checked }).then(function () { self.load(); })
            .catch(function (err) { e.target.checked = !e.target.checked; alert((err && err.message) || 'منتشر نشد.'); });
        });
        return p.el;
      })(),
      h('button', { class: 'btn', type: 'button', onclick: function () { self.editChapter(); } }, 'مشخصات فصل'),
      h('a', { class: 'btn', href: base + 'file/' }, 'ویرایش کل فایل'),
      h('a', { class: 'btn', href: base + 'export/' }, 'دریافت فایل فصل'),
      h('a', { class: 'btn', href: base + 'history/' }, 'نسخه‌ها (' + fa(st.revisions) + ')'),
      h('a', { class: 'btn', href: '../../' + st.book.id + '/change/#chapters' }, 'کتاب «' + st.book.title + '»'),
      h('a', { class: 'btn', href: '../../inbox/', title: 'تست‌هایی که هنوز جایشان معلوم نیست' }, '📥 صندوق تست'));
  };

  // ----- publishing --------------------------------------------------------------
  // Writing and releasing are separate gates (access.can_publish_book). The state comes with the chapter, so the
  // checkbox is disabled — and says why — instead of ticking, failing on the server, and reloading to the same value.
  Manager.prototype.publishBox = function (isPublished, onChange) {
    var allowed = this.state.can_publish;
    var box = h('input', { type: 'checkbox', checked: isPublished, disabled: !allowed, onchange: onChange });
    var label = h('label', { class: 'btn', title: allowed ? 'منتشرنشده در اپ دیده نمی‌شود'
      : (this.state.publish_why || 'اجازه‌ی انتشار ندارید') }, box, ' منتشر شده');
    if (!allowed) label.style.opacity = '.55';
    return { el: label, why: allowed ? null : h('span', { class: 'hint' }, this.state.publish_why || '') };
  };

  // ----- moving tests anywhere (any section of any book, and the «صندوق تست») -----
  Manager.prototype.destSelect = function (current, onPick, placeholder) {
    var self = this;
    var sel = h('select', { class: 'btn small', onchange: function () { if (sel.value) onPick(sel.value); } },
      h('option', { value: '', selected: true, disabled: true }, placeholder || 'انتقال به…'));
    if (!this.dest) {
      sel.appendChild(h('option', { value: '', disabled: true }, 'در حال گرفتن فهرست…'));
      if (!this.destLoading) {
        this.destLoading = true;
        this.call({ op: 'destinations' }).then(function (d) { self.dest = d.destinations; self.destLoading = false; self.render(); })
          .catch(function () { self.destLoading = false; });
      }
      return sel;
    }
    this.dest.forEach(function (b) {
      var g = h('optgroup', { label: b.inbox ? '📥 صندوق تست' : '📘 ' + b.title });
      b.chapters.forEach(function (c) {
        var ch = (b.inbox ? '' : (c.number ? 'فصل ' + fa(c.number) + ': ' : '') + c.title);
        if (!b.inbox) g.appendChild(h('option', { value: c.id, disabled: c.id === current }, ch + ' › مقدمه‌ی فصل'));
        c.sections.forEach(function (s) {
          g.appendChild(h('option', { value: s.id, disabled: s.id === current }, (ch ? ch + ' › ' : '') + s.title));
        });
      });
      sel.appendChild(g);
    });
    return sel;
  };
  // A whole section to another chapter of any book (with its tests, flashcards and learners' data).
  Manager.prototype.chapterSelect = function (onPick) {
    var self = this, here = this.state.chapter.id;
    var sel = h('select', { class: 'btn small', title: 'بخش با تست‌ها، فلش‌کارت‌ها و پیشرفت کاربران به آخر فصل دیگری می‌رود',
      onchange: function () { if (sel.value) onPick(sel.value, sel.options[sel.selectedIndex].text); sel.value = ''; } },
      h('option', { value: '', selected: true, disabled: true }, 'انتقال بخش به فصل…'));
    if (!this.dest) {
      sel.appendChild(h('option', { value: '', disabled: true }, 'در حال گرفتن فهرست…'));
      if (!this.destLoading) {
        this.destLoading = true;
        this.call({ op: 'destinations' }).then(function (d) { self.dest = d.destinations; self.destLoading = false; self.render(); })
          .catch(function () { self.destLoading = false; });
      }
      return sel;
    }
    this.dest.forEach(function (b) {
      var g = h('optgroup', { label: b.inbox ? '📥 صندوق' : '📘 ' + b.title });
      b.chapters.forEach(function (c) {
        if (c.id === here) return;
        g.appendChild(h('option', { value: c.id }, (c.number ? 'فصل ' + fa(c.number) + ': ' : '') + c.title));
      });
      if (g.children.length) sel.appendChild(g);
    });
    return sel;
  };
  Manager.prototype.moveSectionTo = function (s, to, label) {
    if (!this.guard()) return;
    var self = this;
    this.call({ op: 'section.relocate', slug: s.slug, to: Number(to), dry: true }).then(function (d) {
      var lines = ['بخش «' + s.title + '» با تست‌ها، فلش‌کارت‌ها و پیشرفت کاربرانش به آخر «' + label + '» برود؟'];
      if (d.warnings.length) lines = lines.concat(['', 'توجه:'], d.warnings.map(function (w) { return '• ' + w; }));
      if (!confirm(lines.join('\n'))) return;
      return self.call({ op: 'section.relocate', slug: s.slug, to: Number(to) }).then(function (r) {
        self.sel = self.state.sections.length ? self.state.sections[0].slug : '';
        self.dest = null;
        self.render();
        if (!(r.warnings && r.warnings.length)) toast(r.note || 'منتقل شد.');
      });
    }).catch(function () {});
  };

  Manager.prototype.relocate = function (slugs, to, kind) {
    var self = this;
    this.call({ op: (kind || 'question') + '.relocate', slugs: slugs, to: Number(to) }).then(function (d) {
      self.pickedBy = {};
      self.dest = null;  // counts and new sections
      self.render();
      if (!(d.warnings && d.warnings.length)) toast(d.note || 'منتقل شد.');
    }).catch(function () { self.render(); });
  };

  Manager.prototype.editChapter = function () {
    var self = this, c = this.state.chapter;
    var title = prompt('عنوان فصل:', c.title);
    if (title == null) return;
    var number = prompt('شماره‌ی فصل (عدد):', c.number == null ? '' : c.number);
    if (number == null) return;
    var free = confirm('این فصل رایگان باشد؟ (تأیید = رایگان، انصراف = پولی)');
    this.call({ op: 'chapter.update', title: title, number: number, is_free: free }).then(function () { self.render(); toast('مشخصات فصل ذخیره شد.'); }).catch(function () {});
  };

  Manager.prototype.renderTree = function () {
    var self = this, st = this.state;
    var tree = h('div', { class: 'cm-tree' });
    function row(s, isIntro, i) {
      var counts = fa(s.questions.length) + ' تست، ' + fa(s.flashcards.length) + ' کارت';
      var mv = isIntro ? null : h('span', { class: 'mv' },
        h('button', { type: 'button', title: 'بالا', onclick: function (e) { e.stopPropagation(); self.moveSection(i, -1); } }, '▲'),
        h('button', { type: 'button', title: 'پایین', onclick: function (e) { e.stopPropagation(); self.moveSection(i, 1); } }, '▼'));
      return h('div', { class: 'it' + (self.sel === s.slug ? ' sel' : ''), onclick: function () { self.go(s.slug); } },
        isIntro ? null : h('span', { class: 'dot' + (s.is_published ? '' : ' off'), title: s.is_published ? 'منتشر شده' : 'منتشر نشده' }),
        h('span', { class: 't' }, isIntro ? 'مقدمه‌ی فصل' : s.title),
        h('span', { class: 'cnt' }, counts), mv);
    }
    tree.appendChild(row(st.intro, true));
    var group = null;
    st.sections.forEach(function (s, i) {
      if (s.group !== group) { group = s.group; if (group) tree.appendChild(h('div', { class: 'grp' }, group)); }
      tree.appendChild(row(s, false, i));
    });
    tree.appendChild(h('div', { style: 'margin-top:10px' }, h('button', { class: 'btn primary', type: 'button', onclick: function () { self.newSection(); } }, '+ بخش تازه')));
    var ar = st.archived;
    if (ar.sections.length || ar.questions.length || ar.flashcards.length) {
      var d = h('details', null, h('summary', null, 'بایگانی (' + fa(ar.sections.length + ar.questions.length + ar.flashcards.length) + ')'));
      var ul = h('ul', { style: 'padding-right:16px' });
      ar.sections.forEach(function (x) { ul.appendChild(h('li', null, 'بخش «' + x.title + '» ', h('button', { class: 'btn small', type: 'button', onclick: function () { self.restore('section', x.slug); } }, 'بازگرداندن'))); });
      ar.questions.forEach(function (x) { ul.appendChild(h('li', null, 'تست ' + x.slug + ': ' + x.text.slice(0, 40) + '… ', h('button', { class: 'btn small', type: 'button', onclick: function () { self.restore('question', x.slug); } }, 'بازگرداندن'))); });
      ar.flashcards.forEach(function (x) { ul.appendChild(h('li', null, 'فلش‌کارت «' + x.text + '» ', h('button', { class: 'btn small', type: 'button', onclick: function () { self.restore('flashcard', x.slug); } }, 'بازگرداندن'))); });
      d.appendChild(ul);
      d.appendChild(h('p', { class: 'hint' }, 'بایگانی یعنی پنهان از اپ؛ آمار و یادداشت‌های کاربران حفظ می‌شود.'));
      tree.appendChild(d);
    }
    return tree;
  };

  Manager.prototype.moveSection = function (i, delta) {
    var list = this.state.sections.map(function (s) { return s.slug; });
    var j = i + delta;
    if (j < 0 || j >= list.length || !this.guard()) return;
    var t = list[i]; list[i] = list[j]; list[j] = t;
    var self = this;
    this.call({ op: 'section.reorder', order: list }).then(function () { self.render(); }).catch(function () {});
  };
  Manager.prototype.newSection = function () {
    if (!this.guard()) return;
    var self = this;
    var title = prompt('عنوان بخش تازه:');
    if (!title) return;
    var cur = this.section();
    var group = prompt('گروه (سرتیتر بالای بخش‌ها؛ خالی = بدون گروه):', cur.group || '');
    if (group == null) return;
    var slug = prompt('شناسه‌ی ثابت بخش (لاتین؛ بعداً عوض نمی‌شود):', this.state.suggest.section);
    if (!slug) return;
    this.call({ op: 'section.create', title: title, group: group, slug: slug, after: cur.slug || null }).then(function () {
      self.sel = slug; self.tab = 'notes'; self.render(); toast('بخش ساخته شد.');
    }).catch(function () {});
  };
  Manager.prototype.restore = function (kind, slug) {
    if (!this.guard()) return;
    var self = this;
    this.call({ op: kind + '.restore', slug: slug }).then(function () { self.render(); toast('برگردانده شد.'); }).catch(function () {});
  };

  Manager.prototype.renderSection = function () {
    var self = this, s = this.section(), isIntro = s.slug === '';
    this.numbering(s);
    var wrap = h('div');
    var card = h('div', { class: 'cm-card' });
    if (isIntro) {
      card.appendChild(h('h3', { style: 'margin:0' }, 'مقدمه‌ی فصل'));
      card.appendChild(h('p', { class: 'hint' }, 'متن قبل از اولین بخش: در اپ صفحه‌ی «مقدمه‌ی فصل» است (بالای فهرست بخش‌ها). می‌تواند خالی باشد. مقدمه چکیده ندارد.'));
    } else {
      var title = h('input', { type: 'text', value: s.title });
      var group = h('input', { type: 'text', value: s.group, list: 'cm-groups', placeholder: 'بدون گروه' });
      var dl = h('datalist', { id: 'cm-groups' }, this.state.groups.map(function (g) { return h('option', { value: g }); }));
      card.appendChild(h('div', { class: 'row' },
        h('div', { class: 'grow' }, h('label', { class: 'f' }, 'عنوان بخش'), title),
        h('div', { style: 'width:240px' }, h('label', { class: 'f' }, 'گروه ', h('span', { class: 'hint' }, '(سرتیتر در فهرست کتاب)')), group, dl)));
      card.appendChild(h('div', { class: 'row', style: 'margin-top:10px' },
        h('span', { class: 'hint' }, 'شناسه: ' + s.slug),
        (function () {
          var p = self.publishBox(s.is_published, function (e) {
            self.call({ op: 'section.publish', slug: s.slug, value: e.target.checked }).then(function () { self.load(); })
              .catch(function (err) { e.target.checked = !e.target.checked; alert((err && err.message) || 'منتشر نشد.'); });
          });
          p.el.className = 'btn small';
          return p.el;
        })(),
        h('span', { class: 'grow' }),
        this.chapterSelect(function (to, label) { self.moveSectionTo(s, to, label); }),
        h('button', { class: 'btn', type: 'button', onclick: function () {
          self.call({ op: 'section.update', slug: s.slug, title: title.value, group: group.value }).then(function () { self.render(); toast('ذخیره شد.'); }).catch(function () {});
        } }, 'ذخیره‌ی عنوان و گروه'),
        h('button', { class: 'btn danger', type: 'button', onclick: function () {
          if (!confirm('بخش «' + s.title + '» با تست‌ها و فلش‌کارت‌هایش بایگانی شود؟ (پاک نمی‌شود و از «بایگانی» برمی‌گردد)')) return;
          self.call({ op: 'section.archive', slug: s.slug }).then(function () { self.sel = self.state.sections[0].slug; self.render(); toast('بایگانی شد.'); }).catch(function () {});
        } }, 'بایگانی بخش')));
    }
    var tabs = h('div', { class: 'cm-tabs' });
    if (isIntro && this.tab === 'summary') this.tab = 'notes';
    [['notes', isIntro ? 'متن مقدمه' : 'درسنامه']].concat(isIntro ? [] : [['summary', 'چکیده (کارت مرور)']]).concat([ ['questions', 'تست‌ها (' + fa(s.questions.length) + ')'], ['flashcards', 'فلش‌کارت‌ها (' + fa(s.flashcards.length) + ')']]).forEach(function (t) {
      tabs.appendChild(h('button', { type: 'button', class: self.tab === t[0] ? 'on' : '', onclick: function () {
        if (self.tab === t[0] || !self.guard()) return; self.tab = t[0]; self.open = null; self.render();
      } }, t[1]));
    });
    card.appendChild(tabs);
    var body = h('div');
    if (this.tab === 'notes') this.renderNotes(body, s);
    else if (this.tab === 'summary') this.renderSummary(body, s);
    else if (this.tab === 'questions') this.renderItems(body, s, 'question');
    else this.renderItems(body, s, 'flashcard');
    card.appendChild(body);
    wrap.appendChild(card);
    return wrap;
  };

  Manager.prototype.saveBar = function (onSave, label, opts) {
    var dirty = h('span', { class: 'dirty' });
    var btn = h('button', { class: 'btn primary', type: 'button', onclick: onSave }, label || 'ذخیره');
    var el = h('div', { class: 'cm-save' }, btn, dirty);
    var fresh = freshControls();
    if (opts && opts.fresh) el.appendChild(fresh.el);
    return { el: el, fresh: fresh.value, mark: function (on, what) { var t = on ? '● ذخیره نشده' : ''; if (dirty.textContent !== t) dirty.textContent = t; } };
  };

  // «مطلب تازه»: this save is worth a second look; learners see «به‌روز شده» and a line in «تغییرات کتاب».
  function freshControls() {
    var box = h('input', { type: 'checkbox' });
    var note = h('input', { type: 'text', placeholder: 'یک جمله برای «تغییرات کتاب» (اختیاری)', style: 'display:none;min-width:280px' });
    box.onchange = function () { note.style.display = box.checked ? '' : 'none'; if (box.checked) note.focus(); };
    var el = h('span', { class: 'fresh', title: 'برای اصلاح غلط تایپی نزنید؛ برای نکته‌ی تازه یا اصلاح مهم بزنید.' },
      h('label', null, box, ' مطلب تازه'), note);
    return { el: el, value: function () { return box.checked ? { fresh: true, fresh_note: note.value.trim() } : {}; } };
  }
  window.LimoFreshControls = freshControls;

  // «مثال ۳-۵»: the previews number this section's boxes from where the chapter's count is, and show [[#names]].
  Manager.prototype.numbering = function (s) {
    if (P && P.setNumbering) P.setNumbering({ chapter: this.state.chapter.number, start: (s && s.numbering_start) || {}, refs: this.state.refs || {} });
  };

  // Drafts are kept per chapter page and box; «در کل فصل» opens the whole-file page.
  Manager.prototype.draftKey = function (what) { return this.api + '|' + what; };
  Manager.prototype.fileUrl = function () { return this.api.replace(/api\/$/, '') + 'file/'; };

  Manager.prototype.renderNotes = function (body, s) {
    var self = this;
    this.numbering(s);
    var ta = h('textarea', { rows: 22 });
    ta.value = s.full_body;
    body.appendChild(ta);
    var ed = null;
    var bar = this.saveBar(function () {
      self.call(Object.assign({ op: 'section.update', slug: s.slug, full_body: ta.value }, bar.fresh())).then(function (d) { ed.drafts.saved(); self.dirty = null; self.render(); toast(['درسنامه ذخیره شد.'].concat(d && d.note ? [d.note] : [])); }).catch(function () {});
    }, 'ذخیره‌ی درسنامه', { fresh: true });
    ed = new MdEditor(ta, { variant: 'notes', labels: true, uploadUrl: this.api, fileUrl: this.fileUrl(), draft: this.draftKey('notes:' + s.slug),
      onChange: function () { self.dirty = 'درسنامه'; bar.mark(true); } });
    this.selectFind(ta);
    body.appendChild(bar.el);
    if (s.missing_phrases.length) body.appendChild(h('div', { class: 'msg warn' }, 'این عبارت‌های پرش چکیده در درسنامه پیدا نمی‌شوند: ' + s.missing_phrases.join('، ')));
  };

  // ----- review card (summary, «چکیده») -----
  // The form and the raw text are the same thing: the form writes the raw text. Parts are labels («برچسب‌های متن»);
  // a table label has columns («فارسی | English | معنی»), any other item can jump to the notes with «[[phrase]]».
  function findLabel(name) { return (P.findLabel && P.findLabel(name)) || { name: name, style: 'note', role: '', columns: [] }; }
  function itemToForm(label, item) {
    if (label.style === 'table') {
      var c = P.cells(item), n = Math.max((label.columns || []).length, 2);
      if (c.length > n) c = c.slice(0, n - 1).concat([c.slice(n - 1).join(' | ')]);
      while (c.length < n) c.push('');
      return { cells: c };
    }
    var m = item.match(/\[\[([^\]]+)\]\]/);
    return { text: item.replace(/\s*\[\[[^\]]+\]\]\s*/g, ' ').trim(), phrase: m ? m[1].trim() : '' };
  }
  function summaryToForm(text) {
    var parsed = P.parseSummary(text || '');
    // Plain text without labels stays as it is, at the top (switching to the form never drops text).
    if (!parsed) return { lead: (text || '').trim(), glance: '', parts: [] };
    return {
      lead: parsed.lead || '',
      glance: parsed.glance || '',
      parts: parsed.parts.map(function (p) { return { label: p.label, items: p.items.map(function (i) { return itemToForm(p.label, i); }) }; }),
    };
  }
  function itemText(label, x) {
    if (label.style === 'table') return x.cells.map(function (c) { return c.trim(); }).join(' | ').replace(/( \| )+$/, '');
    return x.text.trim() + (x.phrase.trim() ? ' [[' + x.phrase.trim() + ']]' : '');
  }
  function formToSummary(f) {
    var out = [];
    // Lines written before the first label are kept, word for word.
    if ((f.lead || '').trim()) { out.push(f.lead.trim()); out.push(''); }
    var glance = (P.allLabels ? P.allLabels() : []).filter(function (l) { return l.role === 'glance'; })[0];
    if (f.glance.trim()) out.push((glance ? glance.name : 'در یک نگاه') + ': ' + f.glance.trim().replace(/\s*\n\s*/g, ' '));
    f.parts.forEach(function (p) {
      var items = p.items.map(function (x) { return itemText(p.label, x); }).filter(function (t) { return t.trim(); });
      if (!items.length) return;
      out.push(p.label.name + ':');
      items.forEach(function (t) { out.push('- ' + t); });
    });
    return out.join('\n');
  }
  function boldPhrases(notes) {
    var out = [], re = /\*\*(.+?)\*\*/g, m;
    while ((m = re.exec(notes || ''))) if (out.indexOf(m[1]) < 0) out.push(m[1]);
    return out;
  }

  Manager.prototype.renderSummary = function (body, s) {
    var self = this;
    var isCard = !s.summary_body || s.is_review_card;
    var mode = this.summaryMode || (isCard ? 'form' : 'raw');
    var raw = s.summary_body;
    var form = summaryToForm(raw);
    var frame = h('iframe', { class: 'phone', title: 'پیش‌نمایش کارت مرور' });
    autoHeight(frame, 300);
    function current() { return mode === 'form' ? formToSummary(form) : rawTa.value; }
    function refresh() { frame.srcdoc = previewDoc(render(current(), 'summary')); }
    var keeper = null;
    var bar = this.saveBar(function () {
      self.call(Object.assign({ op: 'section.update', slug: s.slug, summary_body: current() }, bar.fresh())).then(function (d) { keeper.saved(); self.dirty = null; self.render(); toast(['چکیده ذخیره شد.'].concat(d && d.note ? [d.note] : [])); }).catch(function () {});
    }, 'ذخیره‌ی چکیده', { fresh: true });
    var formEdited = false;
    function changed() { if (mode === 'form') formEdited = true; self.dirty = 'چکیده'; bar.mark(true); keeper.changed(); clearTimeout(changed.t); changed.t = setTimeout(refresh, 250); }
    // Back to the raw text: untouched if nothing was changed in the form (so Ctrl+Z keeps its history); otherwise the
    // new text goes in as one edit, which Ctrl+Z can take back too.
    function backToRaw() {
      if (!formEdited) return;
      var text = formToSummary(form);
      if (text === rawTa.value) return;
      rawTa.focus();
      rawTa.select();
      insertText(rawTa, text);
      rawTa.setSelectionRange(0, 0);
    }

    var switcher = h('div', { class: 'row', style: 'margin-bottom:10px' },
      h('button', { class: 'btn small' + (mode === 'form' ? ' primary' : ''), type: 'button', onclick: function () { if (mode !== 'form') { form = summaryToForm(rawTa.value); formEdited = false; self.summaryMode = 'form'; mode = 'form'; draw(); } } }, 'فرم کارت مرور'),
      h('button', { class: 'btn small' + (mode === 'raw' ? ' primary' : ''), type: 'button', onclick: function () { if (mode !== 'raw') { self.summaryMode = 'raw'; mode = 'raw'; draw(); backToRaw(); } } }, 'متن خام'),
      h('span', { class: 'hint' }, 'هر دو یکی‌اند؛ فرم همان متن خام را می‌سازد.'));
    var rawTa = h('textarea', { rows: 16, oninput: changed });
    setTimeout(function () { if (mode === 'raw') self.selectFind(rawTa); }, 0);
    rawTa.value = raw;
    // A draft comes back as raw text (the form is drawn from it when switching back).
    keeper = draftKeeper(this.draftKey('summary:' + s.slug), raw, current, function (text) {
      if (mode !== 'raw') { self.summaryMode = 'raw'; mode = 'raw'; draw(); }
      replaceRange(rawTa, 0, rawTa.value.length, text);
    });
    if (keeper.el) body.appendChild(keeper.el);
    var left = h('div');
    var grid = h('div', { class: 'two' }, left, h('div', { class: 'phone-wrap' }, frame));
    body.appendChild(switcher);
    body.appendChild(grid);
    body.appendChild(bar.el);
    var phrases = boldPhrases(s.full_body);
    var notesPlain = plain(s.full_body);

    // The raw text box stays in the page the whole time (only hidden while the form is shown): taking it out of the
    // page would wipe its Ctrl+Z history.
    var rawBar = h('div', { class: 'md-bar' }), rawHost = h('div', { class: 'md-host' });
    addTools(rawTa, rawBar, rawHost, { fileUrl: this.fileUrl() });
    var rawBox = h('div', null,
      labelRow(function (l) { insertSummaryLabel(rawTa, l); }, null, 'برچسب:'),
      h('div', { class: 'md-ed tools-only' }, rawBar, rawHost, rawTa),
      h('p', { class: 'hint' }, 'هر برچسب در خطی جدا با «:» (مثلاً «تعریف:») و هر مورد با «- ». با «[[عبارتی از درسنامه]]» در آخر هر مورد، لمسش اپ را به همان‌جای درسنامه می‌برد. ' +
        'چکیده‌ی بدون برچسب مثل متن معمولی نشان داده می‌شود؛ متنی که پیش از اولین برچسب بیاید، بالای کارت می‌آید. مثال‌های مفصل جایشان در درسنامه است.'));
    var formBox = h('div');
    left.appendChild(rawBox);
    cmUpgrade(rawTa, 14);
    left.appendChild(formBox);
    var focusLast = null;

    function addPart(l) {
      var part = form.parts.filter(function (p) { return p.label.name === l.name; })[0];
      if (!part) { part = { label: l, items: [] }; form.parts.push(part); }
      part.items.push(l.style === 'table' ? itemToForm(l, '') : { text: '', phrase: '' });
      focusLast = l.name;
      changed();
      draw();
    }

    function draw() {
      switcher.querySelectorAll('button').forEach(function (b, i) { b.classList.toggle('primary', (i === 0) === (mode === 'form')); });
      rawBox.style.display = mode === 'raw' ? '' : 'none';
      formBox.style.display = mode === 'raw' ? 'none' : '';
      formBox.innerHTML = '';
      if (mode === 'raw') {
        refresh();
        return;
      }
      var f = h('div', { class: 'rc-form' });
      var glance = h('textarea', { rows: 2, oninput: function () { form.glance = glance.value; changed(); } });
      glance.value = form.glance;
      // Text before the first label (shown at the top of the card): only when there is some, so nothing is ever lost.
      if ((form.lead || '').trim()) {
        var lead = h('textarea', { rows: 3, oninput: function () { form.lead = lead.value; changed(); } });
        lead.value = form.lead;
        f.appendChild(h('div', { class: 'part' }, h('h4', null, 'متن بدون برچسب ', h('span', { class: 'hint' }, '(بالای کارت، همان‌طور که نوشته شده)')), lead));
      }
      f.appendChild(h('div', { class: 'part' }, h('h4', null, 'در یک نگاه ', h('span', { class: 'hint' }, '(یک یا دو جمله: این بخش درباره‌ی چیست)')), glance));
      form.parts.forEach(function (p, pi) {
        var l = p.label;
        var tools = h('span', { class: 'row', style: 'gap:2px;flex-wrap:nowrap;margin-right:auto' },
          pi ? h('button', { class: 'btn small', type: 'button', title: 'این بخش بالاتر از بخش قبلی بیاید', onclick: function () { form.parts.splice(pi - 1, 0, form.parts.splice(pi, 1)[0]); changed(); draw(); } }, '▲ بخش') : null,
          h('button', { class: 'btn small danger', type: 'button', title: 'حذف این بخش', onclick: function () {
            if (p.items.some(function (x) { return itemText(l, x).trim(); }) && !confirm('بخش «' + l.name + '» با همه‌ی موردهایش حذف شود؟')) return;
            form.parts.splice(pi, 1); changed(); draw();
          } }, 'حذف بخش'));
        var part = h('div', { class: 'part lbl-part lbl-' + l.style }, h('h4', { class: 'row' }, l.name,
          l.role === 'important' ? h('span', { class: 'hint' }, ' (هر مورد با لمس به درسنامه می‌رود)') : null, tools));
        var list = h('div');
        var cols = l.style === 'table' ? (l.columns && l.columns.length ? l.columns : ['ستون ۱', 'ستون ۲']) : null;
        function drawList() {
          list.innerHTML = '';
          p.items.forEach(function (item, i) {
            var del = h('span', { class: 'row', style: 'gap:2px;flex-wrap:nowrap' },
              h('button', { class: 'btn icon', type: 'button', title: 'بالا', onclick: function () { if (i) { var t = p.items[i - 1]; p.items[i - 1] = p.items[i]; p.items[i] = t; drawList(); changed(); } } }, '▲'),
              h('button', { class: 'btn icon danger', type: 'button', title: 'حذف', onclick: function () { p.items.splice(i, 1); drawList(); changed(); } }, '✕'));
            if (cols) {
              var inputs = item.cells.map(function (c, ci) {
                var inp = h('input', { type: 'text', value: c, placeholder: cols[ci] || '', dir: /English/i.test(cols[ci] || '') ? 'ltr' : null,
                  oninput: function () { item.cells[ci] = inp.value; changed(); } });
                return inp;
              });
              var line = h('div', { class: 'line cols', style: 'grid-template-columns:repeat(' + inputs.length + ',1fr) auto' }, inputs, del);
              list.appendChild(line);
            } else {
              var t = h('input', { type: 'text', value: item.text, placeholder: l.role === 'important' ? 'اشاره‌ی کوتاه به نکته' : 'متن', oninput: function () { item.text = t.value; changed(); } });
              var ok = h('span', { title: '' });
              var ph = h('input', { type: 'text', value: item.phrase, list: 'cm-bold', placeholder: 'پرش: عبارتی از درسنامه (اختیاری)', oninput: function () { item.phrase = ph.value; mark(); changed(); } });
              function mark() {
                var found = !item.phrase.trim() || notesPlain.indexOf(plain(item.phrase).trim()) >= 0;
                ok.textContent = item.phrase.trim() ? (found ? '✓' : '⚠') : '';
                ok.style.color = found ? '#1f7a55' : '#ba2121';
                ok.title = found ? 'در درسنامه پیدا شد' : 'در درسنامه پیدا نشد؛ پرش کار نمی‌کند';
              }
              mark();
              list.appendChild(h('div', { class: 'line imp' }, t, ph, ok, del));
            }
          });
        }
        drawList();
        part.appendChild(list);
        part.appendChild(h('button', { class: 'btn small', type: 'button', onclick: function () {
          p.items.push(l.style === 'table' ? itemToForm(l, '') : { text: '', phrase: '' });
          drawList();
          var all = list.querySelectorAll('input');
          if (all.length) all[all.length - (cols ? cols.length : 2)].focus();
        } }, '+ افزودن'));
        f.appendChild(part);
      });
      f.appendChild(labelRow(addPart, function (l) { return l.role !== 'glance'; }, 'افزودن بخش:'));
      f.appendChild(h('datalist', { id: 'cm-bold' }, phrases.map(function (x) { return h('option', { value: x }); })));
      formBox.appendChild(f);
      if (focusLast) {
        var idx = form.parts.map(function (p) { return p.label.name; }).indexOf(focusLast);
        var partEl = f.querySelectorAll('.lbl-part')[idx];
        var inputs = partEl ? partEl.querySelectorAll('input') : [];
        var lab = form.parts[idx] && form.parts[idx].label;
        if (inputs.length) inputs[inputs.length - (lab && lab.style === 'table' ? inputs.length / form.parts[idx].items.length : 2)].focus();
        focusLast = null;
      }
      refresh();
    }
    draw();
  };

  // ----- tests and flashcards -----
  Manager.prototype.renderItems = function (body, s, kind) {
    var self = this;
    var list = kind === 'question' ? s.questions : s.flashcards;
    var top = h('div', { class: 'row', style: 'margin-bottom:10px' },
      h('button', { class: 'btn primary', type: 'button', onclick: function () { if (self.guard()) { self.open = { kind: kind, slug: null }; self.render(); } } },
        kind === 'question' ? '+ تست تازه' : '+ فلش‌کارت تازه'),
      h('span', { class: 'hint' }, kind === 'question' ? 'ترتیب این فهرست، ترتیب تست‌ها در اپ است.' : 'فلش‌کارت نکته است، نه سؤال: رو = عنوان، پشت = نکته.'));
    body.appendChild(top);
    this.pickedBy = this.pickedBy || {};
    var picked = this.pickedBy[kind] = this.pickedBy[kind] || {};
    var current = s.id;
    var noun = kind === 'question' ? 'تست' : 'فلش‌کارت';
    if (list.length) {
      var chosen = list.filter(function (x) { return picked[x.slug]; });
      var all = h('input', { type: 'checkbox', checked: chosen.length === list.length, onchange: function () {
        list.forEach(function (x) { if (all.checked) picked[x.slug] = true; else delete picked[x.slug]; });
        self.render();
      } });
      body.appendChild(h('div', { class: 'cm-bulk' + (chosen.length ? ' on' : '') },
        h('label', null, all, ' همه'),
        h('span', null, chosen.length ? fa(chosen.length) + ' ' + noun + ' انتخاب شده' : 'برای انتقال گروهی، کنار ' + noun + '‌ها تیک بزنید.'),
        chosen.length ? this.destSelect(current, function (to) { self.relocate(chosen.map(function (x) { return x.slug; }), to, kind); }, 'انتقال همه به…') : null));
    }
    if (this.open && this.open.kind === kind && this.open.slug === null) body.appendChild(this.itemEditor(s, kind, null));
    if (!list.length && !(this.open && this.open.slug === null)) body.appendChild(h('p', { class: 'hint' }, 'هنوز چیزی در این بخش نیست.'));
    list.forEach(function (item, i) {
      if (self.open && self.open.kind === kind && self.open.slug === item.slug) { body.appendChild(self.itemEditor(s, kind, item)); return; }
      var move = self.destSelect(current, function (to) { self.relocate([item.slug], to, kind); });
      var acts = h('div', { class: 'acts' },
        h('button', { class: 'btn small', type: 'button', onclick: function () { if (self.guard()) { self.open = { kind: kind, slug: item.slug }; self.render(); } } }, 'ویرایش'),
        h('button', { class: 'btn small icon', type: 'button', title: 'بالا', onclick: function () { self.reorder(s, kind, i, -1); } }, '▲'),
        h('button', { class: 'btn small icon', type: 'button', title: 'پایین', onclick: function () { self.reorder(s, kind, i, 1); } }, '▼'),
        move,
        kind === 'question' ? h('button', {
          class: 'btn small' + (item.is_sample ? ' primary' : ''), type: 'button',
          title: 'کاربر می‌تواند تصویر این تست را (بدون جواب) برای دیگران بفرستد',
          onclick: function () {
            self.call({ op: 'question.sample', slug: item.slug, value: !item.is_sample })
              .then(function () { self.render(); toast(item.is_sample ? 'دیگر قابل اشتراک نیست.' : 'قابل اشتراک شد.'); }).catch(function () {});
          } }, item.is_sample ? '✓ قابل اشتراک' : 'قابل اشتراک کن') : null,
        h('button', { class: 'btn small danger', type: 'button', onclick: function () {
          if (!confirm('بایگانی شود؟ (از اپ پنهان می‌شود؛ آمار کاربران می‌ماند)')) return;
          self.call({ op: kind + '.archive', slug: item.slug }).then(function () { self.render(); toast('بایگانی شد.'); }).catch(function () {});
        } }, 'بایگانی'));
      var content;
      if (kind === 'question') {
        var right = item.choices.filter(function (c) { return c.correct; })[0];
        var pos = item.choices.indexOf(right) + 1;
        var meta = h('div', { class: 'meta' },
          h('span', { class: 'pill' }, label(DIFF, item.difficulty)),
          item.kind ? h('span', { class: 'pill' }, label(KINDS, item.kind)) : null,
          item.is_extra ? h('span', { class: 'pill', title: 'در پیشرفت بخش حساب نمی‌شود' }, 'تکمیلی') : null,
          h('span', { class: 'pill' }, item.sources.length ? item.sources.map(function (x) { return x.name + (x.year ? ' ' + fa(x.year) : ''); }).join('، ') : 'تألیفی'),
          item.flashcards.length ? h('span', { class: 'pill' }, fa(item.flashcards.length) + ' فلش‌کارت') : null,
          item.answers ? h('span', { class: 'pill' }, fa(item.answers) + ' پاسخ' + (item.correct_rate != null ? '، ' + fa(item.correct_rate) + '٪ درست' : '')) : null,
          item.reports ? h('span', { class: 'pill err' }, fa(item.reports) + ' گزارش خطا') : null,
          h('span', { class: 'pill', title: 'شناسه' }, item.slug));
        content = h('div', { class: 'body' },
          h('div', { class: 'stem', html: P.renderMarkdown(media(item.stem)) }),
          right ? h('div', { class: 'ans', html: 'جواب: گزینه‌ی ' + fa(pos) + ' — ' + P.renderMarkdown(media(right.text)).replace(/<\/?p>/g, '') }) : null,
          meta);
      } else {
        content = h('div', { class: 'body' }, h('b', null, item.title), h('div', { class: 'stem', html: P.renderMarkdown(media(item.point)) }),
          item.formula ? h('div', { html: P.renderMarkdown('$$' + item.formula + '$$') }) : null,
          h('div', { class: 'meta' }, h('span', { class: 'pill' }, item.slug)));
      }
      var tick = h('input', { type: 'checkbox', class: 'pick', checked: !!picked[item.slug], title: 'انتخاب برای انتقال گروهی',
        onchange: function () { if (tick.checked) picked[item.slug] = true; else delete picked[item.slug]; self.render(); } });
      body.appendChild(h('div', { class: 'item' + (picked[item.slug] ? ' picked' : ''), id: 'item-' + item.slug },
        h('div', { class: 'head' }, h('span', { class: 'num' }, tick, fa(i + 1)), content, acts)));
    });
  };

  Manager.prototype.reorder = function (s, kind, i, delta) {
    var list = (kind === 'question' ? s.questions : s.flashcards).map(function (x) { return x.slug; });
    var j = i + delta;
    if (j < 0 || j >= list.length || !this.guard()) return;
    var t = list[i]; list[i] = list[j]; list[j] = t;
    var self = this;
    this.call({ op: kind + '.reorder', section: s.slug, order: list }).then(function () { self.render(); }).catch(function () {});
  };

  Manager.prototype.allFlashcards = function () {
    var out = [];
    [this.state.intro].concat(this.state.sections).forEach(function (s) { s.flashcards.forEach(function (f) { out.push({ slug: f.slug, title: f.title, section: s.title || 'مقدمه' }); }); });
    return out;
  };

  Manager.prototype.itemEditor = function (s, kind, item) {
    var self = this, isNew = !item;
    var data = item ? JSON.parse(JSON.stringify(item)) : (kind === 'question'
      ? { stem: '', choices: [{ text: '', correct: true }, { text: '', correct: false }, { text: '', correct: false }, { text: '', correct: false }], explanation: '', solutions: [], similar: [], difficulty: 'medium', kind: '', domain: '', seconds: '', is_free: false, fixed_order: false, is_extra: false, is_original: true, sources: [], flashcards: [] }
      : { title: '', point: '', formula: '', is_free: false });
    var box = h('div', { class: 'item open', id: 'item-' + (item ? item.slug : 'new') });
    var mode = 'form';
    var slugInput = h('input', { type: 'text', value: item ? item.slug : this.state.suggest[kind], dir: 'ltr', disabled: !isNew });
    var frame = h('iframe', { class: 'phone', title: 'پیش‌نمایش' });
    autoHeight(frame, 260);
    var left = h('div');
    var rawTa = h('textarea', { rows: 18, dir: 'rtl' });
    // Form and raw text both stay in the page (one hidden at a time), so switching keeps each one's Ctrl+Z history.
    var formBox = h('div');
    var rawBox = h('div', { style: 'display:none' }, rawTa, h('p', { class: 'hint' }, 'همان قالب فایل. خط اول و آخر (:::) لازم نیست.'));
    left.appendChild(formBox);
    left.appendChild(rawBox);
    cmUpgrade(rawTa, 14);
    var formTouched = true, rawTouched = false; // what changed since the other view was last filled
    var keeper = null;
    function changed() {
      if (mode === 'form') formTouched = true; else rawTouched = true;
      self.dirty = kind === 'question' ? 'تست' : 'فلش‌کارت'; if (keeper) keeper.changed(); clearTimeout(changed.t); changed.t = setTimeout(preview, 250);
    }
    rawTa.oninput = changed;
    function intoRaw(text) {
      // As one edit, so Ctrl+Z can take back the change made in the form too (setting .value would wipe the history).
      if (text === rawTa.value) return;
      if (!rawTa.value) { rawTa.value = text; return; }
      rawTa.focus(); rawTa.select();
      var ok = typeIn(rawTa, text);
      if (!ok) rawTa.value = text;
      rawTa.setSelectionRange(0, 0);
    }

    function preview() {
      var html = '';
      if (mode === 'raw') { html = '<p style="color:#56655B">پیش‌نمایش در حالت متن خام بعد از «برگشت به فرم» دیده می‌شود.</p>'; }
      else if (kind === 'question') {
        html = render(data.stem) + '<ol style="padding-right:22px">' + data.choices.map(function (c) {
          return '<li style="margin:6px 0;padding:6px 10px;border-radius:12px;background:' + (c.correct ? '#E3F3E9' : '#fff') + ';border:1px solid #E3E8DE">' + render(c.text).replace(/<\/?p>/g, '') + '</li>';
        }).join('') + '</ol>' + (data.explanation ? '<div class="box box-0"><div class="box-title">پاسخ تشریحی</div>' + render(data.explanation) + '</div>' : '') +
          (data.solutions || []).filter(function (x) { return x.body; }).map(function (x, i) {
            return '<div class="box box-' + (i % 2 ? '1' : '3') + '"><div class="box-title">' + (x.title || 'راه‌حل').replace(/</g, '&lt;') + '</div>' + render(x.body) + '</div>';
          }).join('');
      } else {
        html = '<div style="background:#17201A;color:#F5C518;border-radius:18px;padding:22px;text-align:center;font-weight:800;font-size:1.1em;margin-bottom:12px">' +
          (data.title || 'عنوان') + '</div><div style="background:#fff;border-radius:18px;padding:16px;border:1px solid #E3E8DE">' + render(data.point) +
          (data.formula ? render('$$' + data.formula + '$$') : '') + '</div>';
      }
      frame.srcdoc = previewDoc(html);
    }

    function field(title, el, hint) { return h('div', null, h('label', { class: 'f' }, title, hint ? h('span', { class: 'hint' }, ' ' + hint) : null), el); }
    function mdField(title, key, rows, hint) {
      var ta = h('textarea', { rows: rows || 3 });
      ta.value = data[key] || '';
      var wrapEl = field(title, ta, hint);
      setTimeout(function () { new MdEditor(ta, { compact: true, inline: rows <= 2, mode: 'text', uploadUrl: self.api, onChange: function () { data[key] = ta.value; changed(); } }); }, 0);
      return wrapEl;
    }

    function drawForm() {
      formBox.innerHTML = '';
      var left = formBox; // the fields below are added to the form box
      if (kind === 'question') {
        left.appendChild(mdField('صورت سؤال', 'stem', 4));
        var choices = h('div');
        (function drawChoices() {
          choices.innerHTML = '';
          data.choices.forEach(function (c, i) {
            var radio = h('input', { type: 'radio', name: 'correct-' + (item ? item.slug : 'new'), checked: c.correct, title: 'گزینه‌ی درست', onchange: function () {
              data.choices.forEach(function (x, j) { x.correct = j === i; }); changed();
            } });
            var t = h('input', { type: 'text', value: c.text, placeholder: 'گزینه‌ی ' + fa(i + 1) + ' (فرمول با $…$)', oninput: function () { c.text = t.value; changed(); } });
            choices.appendChild(h('div', { class: 'choice-row' }, radio, t, h('span', { class: 'row', style: 'gap:2px;flex-wrap:nowrap' },
              h('button', { class: 'btn icon', type: 'button', title: 'بالا', onclick: function () { if (i) { var x = data.choices[i - 1]; data.choices[i - 1] = c; data.choices[i] = x; drawChoices(); changed(); } } }, '▲'),
              h('button', { class: 'btn icon danger', type: 'button', title: 'حذف', onclick: function () { if (data.choices.length > 2) { data.choices.splice(i, 1); drawChoices(); changed(); } } }, '✕'))));
          });
          if (data.choices.length < 6) choices.appendChild(h('button', { class: 'btn small', type: 'button', onclick: function () { data.choices.push({ text: '', correct: false }); drawChoices(); } }, '+ گزینه'));
        })();
        left.appendChild(field('گزینه‌ها', choices, '(دایره = گزینه‌ی درست؛ جای گزینه‌ی درست را متنوع کنید)'));
        left.appendChild(mdField('توضیح (پاسخ تشریحی)', 'explanation', 4));
        // «راه‌حل‌ها»: any number, each with its own title («راه‌حل تستی», «حل دیگر»…), in this order in the app.
        if (!data.solutions) data.solutions = [];
        var sols = h('div');
        (function drawSols() {
          sols.innerHTML = '';
          data.solutions.forEach(function (x, i) {
            var t = h('input', { type: 'text', value: x.title || '', placeholder: 'عنوان، مثلاً «راه‌حل تستی»', list: 'cm-sol-titles', style: 'max-width:260px',
              oninput: function () { x.title = t.value; changed(); } });
            var ta = h('textarea', { rows: 2 });
            ta.value = x.body || '';
            var row = h('div', { class: 'sol-row', style: 'border:1px solid var(--line);border-radius:10px;padding:8px;margin-bottom:8px' },
              h('div', { class: 'row', style: 'flex-wrap:nowrap;margin-bottom:4px' }, t, h('span', { class: 'grow' }),
                h('button', { class: 'btn icon', type: 'button', title: 'بالا', onclick: function () { if (i) { var y = data.solutions[i - 1]; data.solutions[i - 1] = x; data.solutions[i] = y; drawSols(); changed(); } } }, '▲'),
                h('button', { class: 'btn icon danger', type: 'button', title: 'حذف این راه‌حل', onclick: function () { data.solutions.splice(i, 1); drawSols(); changed(); } }, '✕')),
              ta);
            sols.appendChild(row);
            setTimeout(function () { new MdEditor(ta, { compact: true, inline: true, mode: 'text', uploadUrl: self.api, onChange: function () { x.body = ta.value; changed(); } }); }, 0);
          });
          sols.appendChild(h('button', { class: 'btn small', type: 'button', onclick: function () { data.solutions.push({ title: '', body: '' }); drawSols(); } }, '+ راه‌حل'));
          sols.appendChild(h('datalist', { id: 'cm-sol-titles' }, ['راه‌حل تستی', 'راه‌حل سریع', 'حل دیگر', 'زاویه‌ی دیگر', 'روش هندسی'].map(function (v) { return h('option', { value: v }); })));
        })();
        left.appendChild(field('راه‌حل‌های دیگر', sols, '(اختیاری؛ هر کدام با عنوان خودش، در اپ زیر پاسخ تشریحی)'));
        var sel = function (list, key) {
          var el = h('select', { onchange: function () { data[key] = el.value; changed(); } }, list.map(function (o) { return h('option', { value: o[0], selected: data[key] === o[0] }, o[1]); }));
          return el;
        };
        var secs = h('input', { type: 'number', min: 0, value: data.seconds || '', oninput: function () { data.seconds = secs.value; } });
        var free = h('input', { type: 'checkbox', checked: data.is_free, onchange: function () { data.is_free = free.checked; } });
        var fixed = h('input', { type: 'checkbox', checked: data.fixed_order, onchange: function () { data.fixed_order = fixed.checked; } });
        left.appendChild(h('label', { class: 'btn small', style: 'margin:4px 0', title: 'برای گزینه‌هایی مثل «۱ و ۳» یا «همه‌ی موارد» خودکار ثابت می‌ماند' },
          fixed, ' ترتیب گزینه‌ها ثابت بماند (اپ جابه‌جایشان نکند)'));
        var extra = h('input', { type: 'checkbox', checked: data.is_extra, onchange: function () { data.is_extra = extra.checked; changed(); } });
        left.appendChild(h('label', { class: 'btn small', style: 'margin:4px 0 4px 6px', title: 'تست پایه در دایره‌ی پیشرفت بخش حساب می‌شود؛ تست تکمیلی فقط در «تمرین بیشتر»، آزمون و مرورها می‌آید' },
          extra, ' تست تکمیلی (بانک تست)'));
        left.appendChild(h('div', { class: 'row' },
          h('div', { class: 'grow' }, field('سطح', sel(DIFF, 'difficulty'))),
          h('div', { class: 'grow' }, field('نوع', sel(KINDS, 'kind'))),
          h('div', { class: 'grow' }, field('حوزه', sel(DOMAINS, 'domain'))),
          h('div', { style: 'width:110px' }, field('زمان (ثانیه)', secs)),
          h('label', { class: 'btn', style: 'margin-top:30px' }, free, ' رایگان در فصل پولی')));
        // sources
        var src = h('div');
        (function drawSrc() {
          src.innerHTML = '';
          var orig = h('input', { type: 'checkbox', checked: data.is_original, onchange: function () { data.is_original = orig.checked; } });
          src.appendChild(h('label', { class: 'btn small', style: 'margin-bottom:6px' }, orig, ' تألیفی (از کنکور واقعی نیست)'));
          data.sources.forEach(function (x, i) {
            var n = h('input', { type: 'text', value: x.name, list: 'limo-src-names', placeholder: 'نام کنکور، مثلاً «کنکور ارشد مهندسی پزشکی»، یا «کتاب ایساک مارون» (بی‌سال)', oninput: function () { x.name = n.value; } });
            var y = h('input', { type: 'text', value: x.year || '', placeholder: 'سال', oninput: function () { x.year = y.value; } });
            var q = h('input', { type: 'text', value: x.number || '', placeholder: 'سؤال', oninput: function () { x.number = q.value; } });
            src.appendChild(h('div', { class: 'src-row' }, n, y, q, h('button', { class: 'btn icon danger', type: 'button', onclick: function () { data.sources.splice(i, 1); drawSrc(); } }, '✕')));
          });
          src.appendChild(h('button', { class: 'btn small', type: 'button', onclick: function () { data.sources.push({ name: '', year: '', number: '' }); drawSrc(); } }, '+ منبع کنکور'));
        })();
        left.appendChild(field('منبع', src, '(هرگز منبع کنکور از خودتان نسازید؛ تستی که عیناً در چند کنکور آمده، چند منبع دارد. نام کنکور را از فهرست انتخاب کنید تا همه‌جا یکسان نوشته شود)'));
        // «مشابه»: the same test that came back in another exam with a change (a separate test of this book).
        var sim = h('input', { type: 'text', value: (data.similar || []).join('، '), placeholder: 'شناسه‌ی تست‌های مشابه، جدا با «،» (مثلاً q-1401-23)',
          oninput: function () { data.similar = sim.value.split(/[,،\s]+/).filter(Boolean); changed(); } });
        left.appendChild(field('تست مشابه', sim, '(اختیاری؛ همان تست با کمی تغییر در کنکور دیگر. در اپ زیر پاسخ نشان داده می‌شود و در یک آزمون با هم نمی‌آیند)'));
        // flashcards
        var cards = self.allFlashcards();
        var fc = h('div', { style: 'max-height:180px;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:6px 10px' },
          cards.length ? cards.map(function (c) {
            var cb = h('input', { type: 'checkbox', checked: data.flashcards.indexOf(c.slug) >= 0, onchange: function () {
              if (cb.checked) data.flashcards.push(c.slug); else data.flashcards = data.flashcards.filter(function (x) { return x !== c.slug; });
            } });
            return h('label', { style: 'display:block;margin:3px 0' }, cb, ' ', c.title, h('span', { class: 'hint' }, ' — ' + c.section));
          }) : h('span', { class: 'hint' }, 'این فصل هنوز فلش‌کارت ندارد.'));
        // Cards of the book's other chapters: a test may link to any card of its book.
        var mine = cards.map(function (c) { return c.slug; });
        var others = self.state.book_cards || [];
        var ext = h('div', { style: 'margin-top:6px' });
        (function drawExt() {
          ext.innerHTML = '';
          data.flashcards.filter(function (x) { return mine.indexOf(x) < 0; }).forEach(function (slug) {
            var c = others.filter(function (o) { return o.slug === slug; })[0];
            ext.appendChild(h('span', { class: 'pill', style: 'margin:2px' }, (c ? c.title + ' — ' + c.chapter : slug) + ' ',
              h('button', { class: 'btn icon danger', type: 'button', title: 'برداشتن پیوند', onclick: function () {
                data.flashcards = data.flashcards.filter(function (x) { return x !== slug; }); drawExt();
              } }, '✕')));
          });
          if (others.length) {
            var pick = h('input', { type: 'text', list: 'cm-book-cards', placeholder: 'افزودن فلش‌کارت از فصل‌های دیگر کتاب (نام یا شناسه)…' });
            var addBtn = h('button', { class: 'btn small', type: 'button', onclick: function () {
              var v = pick.value.trim(), hit = others.filter(function (o) { return o.slug === v || o.title + ' — ' + o.chapter === v; })[0];
              if (!hit) { toast(['این فلش‌کارت در کتاب پیدا نشد.'], 'err'); return; }
              if (data.flashcards.indexOf(hit.slug) < 0) data.flashcards.push(hit.slug);
              drawExt();
            } }, '+ پیوند');
            ext.appendChild(h('div', { class: 'row', style: 'margin-top:4px;flex-wrap:nowrap' }, pick, addBtn,
              h('datalist', { id: 'cm-book-cards' }, others.map(function (o) { return h('option', { value: o.title + ' — ' + o.chapter }); }))));
          }
        })();
        fc.appendChild(ext);
        left.appendChild(field('فلش‌کارت‌های مرتبط', fc));
      } else {
        var title = h('input', { type: 'text', value: data.title, placeholder: 'عنوان کوتاه (روی کارت)', oninput: function () { data.title = title.value; changed(); } });
        left.appendChild(field('عنوان (رو)', title));
        left.appendChild(mdField('نکته (پشت)', 'point', 3));
        var formula = h('input', { type: 'text', value: data.formula, dir: 'ltr', placeholder: 'E = h\\nu  (بدون $)', oninput: function () { data.formula = formula.value; changed(); } });
        left.appendChild(field('فرمول', formula, '(اختیاری؛ LaTeX بدون علامت $)'));
        var free2 = h('input', { type: 'checkbox', checked: data.is_free, onchange: function () { data.is_free = free2.checked; } });
        left.appendChild(h('label', { class: 'btn', style: 'margin-top:10px' }, free2, ' رایگان در فصل پولی'));
      }
      preview();
    }

    function payload() {
      if (mode === 'raw') return { raw: rawTa.value };
      var copy = {}; for (var k in data) if (k !== 'raw') copy[k] = data[k];
      return copy;
    }
    function showRaw() { mode = 'raw'; formBox.style.display = 'none'; rawBox.style.display = ''; modeBtn.textContent = 'برگشت به فرم'; preview(); }
    function showForm() { mode = 'form'; rawBox.style.display = 'none'; formBox.style.display = ''; modeBtn.textContent = 'متن خام'; preview(); }
    var modeBtn = h('button', { class: 'btn small', type: 'button', onclick: function () {
      // Nothing changed on this side since the other view was filled: just switch, both views keep their history.
      if (mode === 'form' && !formTouched) return showRaw();
      if (mode === 'raw' && !rawTouched) return showForm();
      self.call({ op: kind + '.convert', slug: slugInput.value, data: payload() }).then(function (res) {
        if (mode === 'form') { showRaw(); intoRaw(res.item.raw); formTouched = false; rawTouched = false; }
        else { var it = res.item; for (var k in it) data[k] = it[k]; drawForm(); showForm(); formTouched = false; rawTouched = false; }
      }).catch(function () {});
    } }, 'متن خام');

    var head = h('div', { class: 'row', style: 'margin-bottom:6px' },
      h('b', null, isNew ? (kind === 'question' ? 'تست تازه' : 'فلش‌کارت تازه') : 'ویرایش ' + (kind === 'question' ? 'تست' : 'فلش‌کارت')),
      h('span', { class: 'hint' }, 'شناسه:'), h('span', { style: 'width:150px' }, slugInput), h('span', { class: 'grow' }), modeBtn);
    box.appendChild(head);
    // A draft left from last time: the form's fields (or the raw text) come back as they were.
    keeper = draftKeeper(this.draftKey(kind + ':' + (item ? item.slug : 'new:' + s.slug)), JSON.stringify(payload()),
      function () { return JSON.stringify(payload()); },
      function (text) {
        var d; try { d = JSON.parse(text); } catch (e) { return; }
        if (d.raw != null) { if (mode !== 'raw') showRaw(); intoRaw(d.raw); rawTouched = true; }
        else { for (var k in d) data[k] = d[k]; if (mode !== 'form') showForm(); drawForm(); formTouched = true; }
        changed();
      });
    if (keeper.el) box.appendChild(keeper.el);
    box.appendChild(h('div', { class: 'two' }, left, h('div', { class: 'phone-wrap' }, frame)));
    var bar = this.saveBar(function () {
      var req = Object.assign({ op: kind + '.save', slug: slugInput.value.trim(), data: payload(), section: s.slug }, isNew ? {} : bar.fresh());
      if (isNew) req.new = true;
      self.call(req).then(function (d) { keeper.saved(); self.dirty = null; self.open = null; self.render(); toast(['ذخیره شد.'].concat(d && d.note ? [d.note] : [])); }).catch(function () {});
    }, 'ذخیره', { fresh: !isNew });
    bar.el.appendChild(h('button', { class: 'btn', type: 'button', onclick: function () { if (self.guard()) { keeper.saved(); self.dirty = null; self.open = null; self.render(); } } }, 'انصراف'));
    box.appendChild(bar.el);
    drawForm();
    return box;
  };

  window.LimoChapterManager = Manager;

  // ---------- Whole-file editor ----------
  // «ویرایش کل فایل»: «↑ ابتدای فایل», «↓ انتهای فایل» (the cursor on an empty line after the last section, ready for a
  // pasted new section) and «برو به بخش…» (every «## …» section of the chapter, read from the text as it is now).
  function fileNav(ta, bar) {
    function go(at) { ta.focus(); ta.setSelectionRange(at, at); }
    function btn(label, title, fn) {
      return h('button', { type: 'button', title: title, onmousedown: function (e) { e.preventDefault(); }, onclick: function (e) { e.preventDefault(); fn(); } }, label);
    }
    var top = btn('↑ ابتدای فایل', 'رفتن به اول متن', function () { go(0); });
    var bottom = btn('↓ انتهای فایل', 'رفتن به آخر متن، روی یک خط خالی برای چسباندن بخش تازه', function () {
      var v = ta.value, tail = (v.match(/\n*$/) || [''])[0].length;
      if (v.length && tail < 2) replaceRange(ta, v.length, v.length, tail ? '\n' : '\n\n');
      go(ta.value.length);
    });
    var pick = h('select', { class: 'file-go', title: 'رفتن به یک بخش' });
    function sections() {
      var list = [], at = 0, fence = false;
      ta.value.split('\n').forEach(function (line) {
        if (/^\s*(```|~~~)/.test(line)) fence = !fence;
        var m = !fence && line.match(/^##\s+(.+?)\s*(?:\{#[^}]*\})?\s*$/);
        if (m) list.push({ title: m[1], at: at });
        at += line.length + 1;
      });
      return list;
    }
    function fill() {
      pick.innerHTML = '';
      pick.appendChild(h('option', { value: '' }, 'برو به بخش…'));
      sections().forEach(function (x, i) { pick.appendChild(h('option', { value: String(x.at) }, fa(i + 1) + '. ' + x.title)); });
      pick.value = '';
    }
    pick.addEventListener('focus', fill);
    pick.addEventListener('mousedown', fill);
    pick.addEventListener('change', function () { if (pick.value !== '') go(Number(pick.value)); pick.value = ''; });
    fill();
    bar.appendChild(h('span', { class: 'sep' }));
    bar.appendChild(top);
    bar.appendChild(bottom);
    bar.appendChild(pick);
  }

  window.LimoFileEditor = function (opts) {
    var ta = document.getElementById('file-text'), out = document.getElementById('file-result');
    // The same tools as the chapter manager's boxes (find and replace here is over the whole chapter), and the same
    // live preview. Rendering a whole chapter is cheap (11 ms for 6000 characters, measured), so the preview is the
    // chapter — not a part of it: what a professor checks here is the chapter as a reader will get it.
    var edBar = h('div', { class: 'md-bar' }), edHost = h('div', { class: 'md-host' });
    var frame = h('iframe', { class: 'file-prev', title: 'پیش‌نمایش فصل' });
    var edBody = h('div', { class: 'md-body' });
    var edWrap = h('div', { class: 'md-ed mode-split file' }, edBar, edHost, edBody);
    ta.parentNode.insertBefore(edWrap, ta);
    edBody.appendChild(ta);
    addTools(ta, edBar, edHost, {});
    fileNav(ta, edBar);

    // The mode of this editor is remembered on its own: «فقط متن» over a whole chapter is a usual habit, and it must
    // not be the same switch as the section editors'.
    function savedMode() {
      try { return localStorage.getItem('limo.panel.file.mode') || 'split'; } catch (e) { return 'split'; }
    }
    var startMode = savedMode();
    var modes = h('span', { class: 'modes' });

    var prevTimer = null;
    function refresh(now) {
      clearTimeout(prevTimer);
      var draw = function () {
        var html;
        try { html = render(stripHeadingIds(stripFrontMatter(ta.value)), 'notes'); }
        catch (e) { html = '<p style="color:#ba2121">خطا در نمایش: ' + e.message + '</p>'; }
        frame.srcdoc = previewDoc(html);
      };
      if (now) draw(); else prevTimer = setTimeout(draw, 350);
    }
    function applyWidth() {
      var name = previewWidth(), px = widthPx(name);
      // No cap and no max-width: a tablet is 768px even when its column is narrower — the column scrolls instead,
      // otherwise «تبلت» and «گوشی» would look the same and the buttons would be a lie.
      frame.style.width = px ? px + 'px' : '100%';
      frame.style.maxWidth = 'none';
      // «تمام عرض» means the whole panel, not the whole of a 460px column: the split itself is released while it is
      // chosen, otherwise all three buttons would give the same size and none of them would do anything visible.
      edWrap.classList.toggle('wide-preview', !px);
    }
    // The width buttons belong on the toolbar, not above the lesson: they are settings of the frame, not part of what
    // the reader sees (a professor said so about the buttons sitting over the text).
    var ctl = previewControls(function () { applyWidth(); refresh(true); });
    edBar.appendChild(h('span', { class: 'sep' }));
    edBar.appendChild(ctl.el);
    // The window: the preview out of the 460px column, free on the page, movable and resizable.
    var win = previewWindow({ frame: frame, title: 'پیش‌نمایش فصل', onOpen: function () { applyWidth(); refresh(true); } });
    var winBtn = h('button', { class: 'btn small pv-open', type: 'button', title: 'پیش‌نمایش در پنجره‌ی جدا',
      onclick: function (e) {
        e.preventDefault();
        if (win.isOpen()) win.close(); else win.open();
        winBtn.classList.toggle('on', win.isOpen());
        rememberWin();
      } }, 'پیش‌نمایش در پنجره');
    edBar.appendChild(winBtn);
    function rememberWin() {
      try { localStorage.setItem('limo.panel.file.mode', win.isOpen() ? 'preview' : 'text'); } catch (err) { /* ignore */ }
    }
    ta.addEventListener('input', function () { refresh(false); });
    // With the preview in its own window there is no column to split, so «هر دو / فقط متن / فقط پیش‌نمایش» no longer
    // means anything here: the text always fills the page, and the preview is either open in its window or not.
    // The section editors keep their three modes (they still have the side-by-side column).
    edWrap.classList.remove('mode-split');
    edWrap.classList.add('mode-text');
    applyWidth();
    refresh(true);
    // A window left open last time is reopened: a professor who works with it open should not have to open it daily.
    try { if (localStorage.getItem('limo.panel.file.mode') === 'preview') win.open(); } catch (err) { /* ignore */ }
    // Closing with × or Escape must remember that too, not just the toolbar button.
    win.onClosed = function () { winBtn.classList.remove('on'); rememberWin(); };
    if (win.isOpen()) winBtn.classList.add('on');
    fetch(opts.api, { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (d) { setCtx(d.state); }).catch(function () {});
    var keeper = opts.restore ? { el: null, changed: function () {}, saved: function () {} }
      : draftKeeper(opts.api + '|file', ta.value, function () { return ta.value; }, function (text) { replaceRange(ta, 0, ta.value.length, text); });
    if (keeper.el) edWrap.parentNode.insertBefore(keeper.el, edWrap);
    ta.addEventListener('input', function () { keeper.changed(); });
    cmUpgrade(ta, 24);
    var checkBtn = document.getElementById('file-check'), saveBtn = document.getElementById('file-save');
    var fresh = freshControls();
    if (!opts.restore) saveBtn.parentNode.insertBefore(fresh.el, saveBtn.nextSibling);
    var checked = null, hides = [];
    function post(body) {
      return fetch(opts.api, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }, body: JSON.stringify(body) })
        .then(function (r) { return r.json(); });
    }
    // Restoring a version: «فقط متن بخش‌ها را برگردان» puts back the texts of the sections that still exist, and hides
    // nothing (no section, test or flashcard is archived).
    var textOnly = null;
    if (opts.restore) {
      textOnly = h('button', { class: 'btn', type: 'button', onclick: function () {
        if (!confirm('متن درسنامه و چکیده‌ی بخش‌هایی که الان هستند به این نسخه برمی‌گردد. هیچ بخش، تست یا فلش‌کارتی پنهان نمی‌شود. ادامه می‌دهید؟')) return;
        textOnly.disabled = true;
        post({ op: 'file.restore_text', text: ta.value, version: opts.version, note: opts.note + ' (فقط متن بخش‌ها)' }).then(function (d) {
          textOnly.disabled = false;
          if (d.errors) { out.prepend(h('div', { class: 'msg err' }, d.errors.join(' '))); return; }
          location.href = opts.done;
        });
      } }, 'فقط متن بخش‌ها را برگردان، چیزی پنهان نشود');
      saveBtn.parentNode.insertBefore(textOnly, saveBtn.nextSibling);
    }
    ta.addEventListener('input', function () { if (checked !== null) { checked = null; saveBtn.disabled = true; } });
    checkBtn.onclick = function () {
      out.innerHTML = 'در حال بررسی…';
      post({ op: 'file.check', text: ta.value }).then(function (d) {
        out.innerHTML = '';
        hides = [];
        if (d.plan) ['sections', 'questions', 'flashcards'].forEach(function (k) {
          d.plan[k].forEach(function (r) { if (typeof r !== 'string' && r[0] === 'archived') hides.push({ sections: 'بخش', questions: 'تست', flashcards: 'فلش‌کارت' }[k] + ' ' + r[1]); });
        });
        if (opts.restore && hides.length) {
          out.appendChild(h('div', { class: 'msg err big-warn' },
            h('b', null, 'هشدار: با «ذخیره» ' + fa(hides.length) + ' مورد از دید کاربران پنهان می‌شود'),
            h('p', null, 'این‌ها در نسخه‌ای که برمی‌گردانید نبودند. پاک نمی‌شوند و آمار کاربران می‌ماند؛ از «بایگانی» در «مدیریت فصل» یا با بازگرداندن نسخه‌ی جدیدتر برمی‌گردند. اگر فقط متن‌ها را می‌خواهید، دکمه‌ی «فقط متن بخش‌ها را برگردان» را بزنید.'),
            h('ul', null, hides.map(function (x) { return h('li', null, x); }))));
        }
        out.appendChild(window.LimoReport(d));
        checked = d.errors.length ? null : ta.value;
        saveBtn.disabled = !!d.errors.length || !d.plan || (!d.plan.count && !d.plan.notes.length);
        if (!d.errors.length && d.plan && !d.plan.count && !d.plan.notes.length) out.appendChild(h('div', { class: 'msg ok' }, 'با فصل فعلی فرقی ندارد.'));
      });
    };
    saveBtn.onclick = function () {
      if (checked === null || checked !== ta.value) return;
      if (opts.restore && hides.length && !confirm(fa(hides.length) + ' مورد از دید کاربران پنهان می‌شود (پاک نمی‌شود و برمی‌گردد). کل نسخه برگردد؟')) return;
      saveBtn.disabled = true;
      post(Object.assign({ op: 'file.apply', text: ta.value, version: opts.version, restore: opts.restore, note: opts.note }, fresh.value())).then(function (d) {
        if (d.errors) { out.prepend(h('div', { class: 'msg err' }, d.errors.join(' '))); return; }
        keeper.saved();
        location.href = opts.done;
      });
    };
  };

  // ---------- The import page's preview ----------
  // «فصل از فایل» used to ask a professor to upload, read a list of changes, and press «اعمال تغییرات» — the only way
  // to see what the chapter would look like was to save it first, and by then a mis-read \note or a lost table was
  // already in the database. This draws the result before anything is saved, with the same renderer as the app.
  function drawImportPreview() {
    var el = document.getElementById('import-md'), out = document.getElementById('import-pv');
    if (!el || !out) return;
    var markdown;
    try { markdown = JSON.parse(el.textContent); } catch (e) { return; }
    // The chapter's own header (شناسه-کتاب، فصل …) is the panel's business, not the reader's — same rule as the
    // whole-file editor.
    function draw() {
      var html;
      try { html = render(stripHeadingIds(stripFrontMatter(markdown)), 'notes'); }
      catch (e) { html = '<p style="color:#ba2121">خطا در نمایش: ' + e.message + '</p>'; }
      out.srcdoc = previewDoc(html, 'body{padding:0}.lesson{padding:14px 18px 24px}');
    }
    var ctl = document.getElementById('import-pv-ctl');
    function applyWidth() {
      var px = widthPx(previewWidth());
      out.style.width = px ? px + 'px' : '100%';
      out.style.maxWidth = 'none';
    }
    if (ctl) ctl.appendChild(previewControls(function () { applyWidth(); draw(); }).el);
    applyWidth();
    draw();
  }
  // The chapter's text arrives in a <script id="import-md"> that the template writes BELOW the frame, so the file
  // is not in the DOM yet when this code runs. Waiting for DOMContentLoaded is what makes it findable — without it
  // the preview stayed an empty grey box (found by running the real page, not by reading the code).
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', drawImportPreview);
  else drawImportPreview();

  // Shared rendering of a check result: errors, warnings, what will change, and the line diff.
  window.LimoReport = function (d) {
    var box = h('div');
    if (d.errors && d.errors.length) box.appendChild(h('div', { class: 'msg err' }, h('b', null, fa(d.errors.length) + ' خطا؛ تا درست نشوند ذخیره نمی‌شود.'), h('ul', null, d.errors.map(function (e) { return h('li', null, e); }))));
    if (d.warnings && d.warnings.length) box.appendChild(h('div', { class: 'msg warn' }, h('b', null, 'هشدارها'), h('ul', null, d.warnings.map(function (e) { return h('li', null, e); }))));
    if (d.plan) box.appendChild(window.LimoPlan(d.plan));
    if (d.diff && d.diff.length) {
      var diff = h('div', { class: 'diff' }, d.diff.map(function (x) { return h('div', { class: x[0] === '+' ? 'a' : x[0] === '-' ? 'd' : x[0] === '@' ? 'g' : '' }, (x[0] === '+' ? '+ ' : x[0] === '-' ? '− ' : '  ') + x[1]); }));
      box.appendChild(h('details', null, h('summary', null, 'تغییرات خط‌به‌خط'), diff));
    }
    return box;
  };
  window.LimoPlan = function (plan) {
    var box = h('div', { class: 'cm-card plan' }, h('b', null, plan.count ? 'با ذخیره این تغییرات انجام می‌شود:' : 'تغییری در محتوا نیست.'));
    var names = { new: 'تازه', changed: 'تغییر', archived: 'بایگانی' };
    function list(title, rows) {
      if (!rows.length) return;
      box.appendChild(h('div', { style: 'margin-top:8px;font-weight:700' }, title + ' (' + fa(rows.length) + ')'));
      box.appendChild(h('ul', null, rows.map(function (r) {
        return typeof r === 'string' ? h('li', null, r) : h('li', { class: r[0] }, h('b', null, names[r[0]] + ': '), r[1], h('span', { class: 'hint' }, ' — ' + r[2]));
      })));
    }
    list('فصل', plan.chapter); list('بخش‌ها', plan.sections); list('تست‌ها', plan.questions); list('فلش‌کارت‌ها', plan.flashcards);
    if (plan.notes.length) box.appendChild(h('div', { class: 'msg warn' }, h('ul', null, plan.notes.map(function (n) { return h('li', null, n); }))));
    return box;
  };
})();

/* Book covers in the panel: thumbnails in the books list, a live preview (dark and light) on the book form, and
 * «دریافت جلد» — the same cover as a 960×1440 PNG (for a channel post, a print, or a later redesign). */
(function () {
  'use strict';
  var P = window.LimoPreview;
  if (!P || !P.coverHtml) return;
  var FONTS = ((document.currentScript && document.currentScript.src.replace(/panel\.js.*$/, '')) || '/static/catalog/') + 'fonts/';

  function val(id) { var el = document.getElementById(id); return el ? el.value : ''; }

  var fontCss = null;
  function inlineFonts() {
    if (fontCss !== null) return Promise.resolve(fontCss);
    var faces = [['Vazirmatn_400Regular.ttf', 400], ['Vazirmatn_700Bold.ttf', 700], ['Vazirmatn_700Bold.ttf', 900]];
    return Promise.all(faces.map(function (f) {
      return fetch(FONTS + f[0]).then(function (r) { return r.arrayBuffer(); }).then(function (buf) {
        var bin = '', bytes = new Uint8Array(buf);
        for (var i = 0; i < bytes.length; i += 0x8000) bin += String.fromCharCode.apply(null, bytes.subarray(i, i + 0x8000));
        return '@font-face{font-family:Vazirmatn;font-weight:' + f[1] + ';src:url(data:font/ttf;base64,' + btoa(bin) + ')}';
      });
    })).then(function (rules) { fontCss = rules.join(''); return fontCss; }, function () { fontCss = ''; return ''; });
  }

  function downloadCover(book, theme, button) {
    if (!book) return;
    button.disabled = true;
    inlineFonts().then(function (css) {
      var img = new Image();
      img.onload = function () {
        var c = document.createElement('canvas');
        c.width = 960; c.height = 1440;
        c.getContext('2d').drawImage(img, 0, 0, 960, 1440);
        c.toBlob(function (blob) {
          var a = document.createElement('a');
          a.href = URL.createObjectURL(blob);
          a.download = (val('id_slug') || 'cover') + '-' + theme + '.png';
          document.body.appendChild(a); a.click(); a.remove();
          setTimeout(function () { URL.revokeObjectURL(a.href); }, 2000);
          button.disabled = false;
        }, 'image/png');
      };
      img.onerror = function () { button.disabled = false; button.textContent = 'ساخت عکس جلد نشد'; };
      img.src = 'data:image/svg+xml;charset=utf-8,' + encodeURIComponent(P.coverSvg(book, theme, css));
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    document.querySelectorAll('.lp-cover').forEach(function (el) {
      var d = el.dataset;
      var drawing = null;
      try { drawing = d.drawing ? JSON.parse(d.drawing) : null; } catch (e) { drawing = null; }
      el.innerHTML = P.coverHtml({ title: d.title, title_en: d.en, author: d.author, edition: d.edition, motif: d.motif, major: d.major, strip: d.strip, drawing: drawing }, 'dark', Number(d.width || 44));
      el.style.display = 'inline-block';
    });
    var motif = document.getElementById('id_cover_motif');
    if (!motif) return;
    var majors = {};
    try {
      majors = JSON.parse(document.getElementById('lp-majors').textContent);
      if (typeof majors === 'string') majors = JSON.parse(majors); // json_script of an already-encoded string
    } catch (e) { majors = {}; }
    var savedDrawing = null;
    try { var raw = JSON.parse(document.getElementById('lp-drawing').textContent); savedDrawing = raw ? JSON.parse(raw) : null; } catch (e) { /* ignore */ }
    var box = document.createElement('div');
    box.style.cssText = 'display:flex;gap:18px;margin:12px 0 4px;flex-wrap:wrap;align-items:flex-start';
    var hint = document.createElement('p');
    hint.className = 'help';
    hint.textContent = 'پیش‌نمایش جلد در اپ (تیره و روشن؛ هر کاربر در پروفایل یکی را انتخاب می‌کند). اگر «عکس جلد» بگذارید، عکس جای این جلد را می‌گیرد.';
    // Below the whole field row (Django wraps the select in a flex row, which would squeeze the preview).
    var panel = document.createElement('div');
    panel.style.cssText = 'margin:8px 0 0;width:100%';
    var row = motif.closest('.flex-container') || motif.parentNode;
    row.parentNode.insertBefore(panel, row.nextSibling);
    panel.appendChild(box);
    var current = null;
    if (P.coverSvg) {
      var dl = document.createElement('div');
      dl.style.cssText = 'display:flex;gap:8px;margin:6px 0 2px;flex-wrap:wrap';
      [['dark', 'دریافت جلد تیره (PNG)'], ['light', 'دریافت جلد روشن (PNG)']].forEach(function (t) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'button lp-cover-download';
        b.textContent = t[1];
        b.addEventListener('click', function () { downloadCover(current, t[0], b); });
        dl.appendChild(b);
      });
      panel.appendChild(dl);
    }
    panel.appendChild(hint);
    function draw() {
      var checked = document.querySelector('input[name=majors]:checked');
      var m = checked && majors[checked.value] || { name: 'پزشکی', color: '#3FB8A9' };
      current = { title: val('id_title'), title_en: val('id_title_en'), author: val('id_author'), edition: val('id_edition'), motif: motif.value, major: m.name, strip: m.color, drawing: savedDrawing };
      box.innerHTML = P.coverHtml(current, 'dark', 180) + P.coverHtml(current, 'light', 180);
    }
    ['id_title', 'id_title_en', 'id_author', 'id_edition', 'id_cover_motif'].forEach(function (id) {
      var el = document.getElementById(id);
      if (el) el.addEventListener('input', draw), el.addEventListener('change', draw);
    });
    document.querySelectorAll('input[name=majors]').forEach(function (el) { el.addEventListener('change', draw); });
    draw();
  });
})();

/* Banners: live preview of the template on the banner form. */
(function () {
  'use strict';
  var P = window.LimoPreview;
  if (!P || !P.bannerHtml) return;
  document.addEventListener('DOMContentLoaded', function () {
    var tpl = document.getElementById('id_template');
    if (!tpl || !document.getElementById('lp-banner-books')) return;
    var books = {};
    try { books = JSON.parse(document.getElementById('lp-banner-books').textContent) || {}; } catch (e) { books = {}; }
    var box = document.createElement('div');
    box.style.cssText = 'margin:12px 0;display:flex;gap:16px;flex-wrap:wrap;align-items:flex-start';
    var help = document.createElement('p');
    help.className = 'help';
    help.textContent = 'پیش‌نمایش بنر در اپ (پهن و گوشی). اگر «تصویر» بگذارید، عکس جای قالب را می‌گیرد.';
    var row = tpl.closest('.form-row') || tpl.parentNode;
    row.appendChild(box);
    row.appendChild(help);
    function val(id) { var el = document.getElementById(id); return el ? el.value : ''; }
    function left() {
      var cd = document.getElementById('id_countdown');
      if (!cd || !cd.checked) return null;
      var d = val('id_ends_at_0');
      return d ? 'مثلاً ۲ روز و ۵ ساعت مانده' : 'اول «پایان» را پر کنید';
    }
    function draw() {
      var b = { template: tpl.value, title: val('id_title'), subtitle: val('id_subtitle'), button: val('id_button'), motif: val('id_motif'),
        left: left(), book: books[(val('id_target_value') || '').trim()] || null };
      box.innerHTML = P.bannerHtml(b, 420) + P.bannerHtml(b, 300);
    }
    document.querySelectorAll('input, select, textarea').forEach(function (el) { el.addEventListener('input', draw); el.addEventListener('change', draw); });
    draw();
  });
})();
