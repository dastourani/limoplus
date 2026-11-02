/* LimoKhan panel: Markdown editor with a phone-sized live preview, and the chapter manager.
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

  function previewDoc(html, extraCss) {
    return '<!doctype html><html dir="rtl"><head><meta charset="utf-8"><style>' +
      '@font-face{font-family:Vazirmatn;font-weight:400;src:url("' + STATIC + 'fonts/Vazirmatn_400Regular.ttf")}' +
      '@font-face{font-family:Vazirmatn;font-weight:700;src:url("' + STATIC + 'fonts/Vazirmatn_700Bold.ttf")}' +
      P.CONTENT_CSS + 'body{background:#F6F7F2;padding:14px 0}.lesson{padding:4px 16px 24px}' + (extraCss || '') +
      '</style></head><body><div class="lesson">' + html + '</div></body></html>';
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

  // ---------- Markdown editor ----------
  var BOXES = [['نکته', 'نکته'], ['تله', 'تله'], ['هشدار', 'هشدار'], ['مثال', 'مثال']];

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
        BOXES.forEach(function (b) { bar.appendChild(btn('▣ ' + b[1], 'کادر ' + b[1], function () { self.block(':::' + b[0] + '\n', '\n:::', 'متن کادر'); })); });
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
    this.setMode = function (m) {
      wrap.classList.remove('mode-split', 'mode-text', 'mode-preview');
      wrap.classList.add('mode-' + m);
      for (var k in modeBtns) modeBtns[k].classList.toggle('on', k === m);
      try { localStorage.setItem('limo.panel.mode', m); } catch (e) { /* ignore */ }
      if (m !== 'text') self.refresh();
    };
    this.frame = h('iframe', { title: 'پیش‌نمایش مثل گوشی' });
    var body = h('div', { class: 'md-body' });
    textarea.parentNode.insertBefore(wrap, textarea);
    body.appendChild(textarea);
    body.appendChild(h('div', { class: 'md-prev' }, this.frame));
    wrap.appendChild(bar);
    wrap.appendChild(body);
    this.el = wrap;
    var timer = null;
    textarea.addEventListener('input', function () {
      clearTimeout(timer);
      timer = setTimeout(function () { self.refresh(); }, 250);
      self.onChange(textarea.value);
    });
    textarea.addEventListener('keydown', function (e) {
      if ((e.ctrlKey || e.metaKey) && (e.key === 'b' || e.key === 'ذ')) { e.preventDefault(); self.wrap('**', '**', 'متن پررنگ'); }
    });
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
    var ok = false;
    try { ok = document.execCommand('insertText', false, text); } catch (e) { ok = false; }
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
    fetch(this.api, { credentials: 'same-origin' }).then(function (r) { return r.json(); }).then(function (d) {
      self.state = d.state;
      MEDIA = d.state.media_url;
      if (!self.fromHash()) { self.sel = d.state.sections.length ? d.state.sections[0].slug : ''; self.render(); }
    });
  };
  Manager.prototype.fromHash = function () {
    var m = location.hash.match(/^#([sqf])=(.*)$/);
    if (!m || !this.state) return false;
    var key = m[1], slug = decodeURIComponent(m[2]);
    if (key === 's') { this.sel = slug; this.tab = 'notes'; this.open = null; }
    else {
      var all = [this.state.intro].concat(this.state.sections);
      for (var i = 0; i < all.length; i++) {
        var list = key === 'q' ? all[i].questions : all[i].flashcards;
        if (list.some(function (x) { return x.slug === slug; })) {
          this.sel = all[i].slug; this.tab = key === 'q' ? 'questions' : 'flashcards'; this.open = { kind: key === 'q' ? 'question' : 'flashcard', slug: slug };
        }
      }
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
    return h('div', { class: 'cm-head' },
      h('h2', null, (c.number ? 'فصل ' + fa(c.number) + ': ' : '') + c.title),
      h('label', { class: 'btn', title: 'فصل منتشرنشده در اپ دیده نمی‌شود' },
        h('input', { type: 'checkbox', checked: c.is_published, onchange: function (e) {
          self.call({ op: 'chapter.publish', value: e.target.checked }).then(function () { self.load(); });
        } }), ' منتشر شده'),
      h('button', { class: 'btn', type: 'button', onclick: function () { self.editChapter(); } }, 'مشخصات فصل'),
      h('a', { class: 'btn', href: base + 'file/' }, 'ویرایش کل فایل'),
      h('a', { class: 'btn', href: base + 'export/' }, 'دریافت فایل فصل'),
      h('a', { class: 'btn', href: base + 'history/' }, 'نسخه‌ها (' + fa(st.revisions) + ')'),
      h('a', { class: 'btn', href: '../../' + st.book.id + '/change/#chapters' }, 'کتاب «' + st.book.title + '»'));
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
    var wrap = h('div');
    var card = h('div', { class: 'cm-card' });
    if (isIntro) {
      card.appendChild(h('h3', { style: 'margin:0' }, 'مقدمه‌ی فصل'));
      card.appendChild(h('p', { class: 'hint' }, 'متن قبل از اولین بخش: در اپ با «نمای کلی فصل» باز می‌شود. می‌تواند خالی باشد.'));
    } else {
      var title = h('input', { type: 'text', value: s.title });
      var group = h('input', { type: 'text', value: s.group, list: 'cm-groups', placeholder: 'بدون گروه' });
      var dl = h('datalist', { id: 'cm-groups' }, this.state.groups.map(function (g) { return h('option', { value: g }); }));
      card.appendChild(h('div', { class: 'row' },
        h('div', { class: 'grow' }, h('label', { class: 'f' }, 'عنوان بخش'), title),
        h('div', { style: 'width:240px' }, h('label', { class: 'f' }, 'گروه ', h('span', { class: 'hint' }, '(سرتیتر در فهرست کتاب)')), group, dl)));
      card.appendChild(h('div', { class: 'row', style: 'margin-top:10px' },
        h('span', { class: 'hint' }, 'شناسه: ' + s.slug),
        h('label', { class: 'btn small' }, h('input', { type: 'checkbox', checked: s.is_published, onchange: function (e) {
          self.call({ op: 'section.publish', slug: s.slug, value: e.target.checked }).then(function () { self.load(); }).catch(function () {});
        } }), ' منتشر شده'),
        h('span', { class: 'grow' }),
        h('button', { class: 'btn', type: 'button', onclick: function () {
          self.call({ op: 'section.update', slug: s.slug, title: title.value, group: group.value }).then(function () { self.render(); toast('ذخیره شد.'); }).catch(function () {});
        } }, 'ذخیره‌ی عنوان و گروه'),
        h('button', { class: 'btn danger', type: 'button', onclick: function () {
          if (!confirm('بخش «' + s.title + '» با تست‌ها و فلش‌کارت‌هایش بایگانی شود؟ (پاک نمی‌شود و از «بایگانی» برمی‌گردد)')) return;
          self.call({ op: 'section.archive', slug: s.slug }).then(function () { self.sel = self.state.sections[0].slug; self.render(); toast('بایگانی شد.'); }).catch(function () {});
        } }, 'بایگانی بخش')));
    }
    var tabs = h('div', { class: 'cm-tabs' });
    [['notes', 'جزوه'], ['summary', 'خلاصه (کارت مرور)'], ['questions', 'تست‌ها (' + fa(s.questions.length) + ')'], ['flashcards', 'فلش‌کارت‌ها (' + fa(s.flashcards.length) + ')']].forEach(function (t) {
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

  Manager.prototype.saveBar = function (onSave, label) {
    var dirty = h('span', { class: 'dirty' });
    var btn = h('button', { class: 'btn primary', type: 'button', onclick: onSave }, label || 'ذخیره');
    return { el: h('div', { class: 'cm-save' }, btn, dirty), mark: function (on, what) { dirty.textContent = on ? '● ذخیره نشده' : ''; } };
  };

  Manager.prototype.renderNotes = function (body, s) {
    var self = this;
    var ta = h('textarea', { rows: 22 });
    ta.value = s.full_body;
    body.appendChild(ta);
    var bar = this.saveBar(function () {
      self.call({ op: 'section.update', slug: s.slug, full_body: ta.value }).then(function () { self.dirty = null; self.render(); toast('جزوه ذخیره شد.'); }).catch(function () {});
    }, 'ذخیره‌ی جزوه');
    new MdEditor(ta, { variant: 'notes', uploadUrl: this.api, onChange: function () { self.dirty = 'جزوه'; bar.mark(true); } });
    body.appendChild(bar.el);
    if (s.missing_phrases.length) body.appendChild(h('div', { class: 'msg warn' }, 'این عبارت‌های «مهم» خلاصه در جزوه پیدا نمی‌شوند: ' + s.missing_phrases.join('، ')));
  };

  // ----- review card (summary) -----
  var PARTS = [['important', 'مهم (هر مورد با عبارتی از جزوه که با لمسش اپ به همان‌جا می‌رود)'], ['terms', 'واژه‌ها (فارسی، انگلیسی، معنی)'],
    ['rules', 'قاعده و فرمول'], ['memorize', 'حفظی'], ['traps', 'تله']];
  var PART_LABEL = { important: 'مهم', terms: 'واژه', rules: 'قاعده', memorize: 'حفظی', traps: 'تله' };

  function splitImportant(item) { var j = P.jumpTarget(item); return { text: j.text, phrase: j.phrase }; }
  function summaryToForm(text) {
    var parts = P.parseParts(text || '') || {};
    return {
      glance: (parts.glance || []).join(' '),
      important: (parts.important || []).map(splitImportant),
      terms: (parts.terms || []).map(function (t) { var c = t.split('|').map(function (x) { return x.trim(); }); return { fa: c[0] || '', en: c[1] || '', meaning: c.slice(2).join(' | ') }; }),
      rules: parts.rules || [], memorize: parts.memorize || [], traps: parts.traps || [],
    };
  }
  function formToSummary(f) {
    var out = [];
    if (f.glance.trim()) out.push('در یک نگاه: ' + f.glance.trim().replace(/\s*\n\s*/g, ' '));
    PARTS.forEach(function (p) {
      var key = p[0], items = f[key].filter(function (x) { return key === 'important' ? x.text.trim() : key === 'terms' ? x.fa.trim() : String(x).trim(); });
      if (!items.length) return;
      out.push(PART_LABEL[key] + ':');
      items.forEach(function (x) {
        if (key === 'important') out.push('- ' + x.text.trim() + (x.phrase.trim() ? ' [[' + x.phrase.trim() + ']]' : ''));
        else if (key === 'terms') out.push('- ' + [x.fa, x.en, x.meaning].map(function (c) { return c.trim(); }).join(' | ').replace(/( \| )+$/, ''));
        else out.push('- ' + String(x).trim());
      });
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
    var bar = this.saveBar(function () {
      self.call({ op: 'section.update', slug: s.slug, summary_body: current() }).then(function () { self.dirty = null; self.render(); toast('خلاصه ذخیره شد.'); }).catch(function () {});
    }, 'ذخیره‌ی خلاصه');
    function changed() { self.dirty = 'خلاصه'; bar.mark(true); clearTimeout(changed.t); changed.t = setTimeout(refresh, 250); }

    var switcher = h('div', { class: 'row', style: 'margin-bottom:10px' },
      h('button', { class: 'btn small' + (mode === 'form' ? ' primary' : ''), type: 'button', onclick: function () { if (mode !== 'form') { form = summaryToForm(rawTa.value); self.summaryMode = 'form'; mode = 'form'; draw(); } } }, 'فرم کارت مرور'),
      h('button', { class: 'btn small' + (mode === 'raw' ? ' primary' : ''), type: 'button', onclick: function () { if (mode !== 'raw') { rawTa.value = formToSummary(form); self.summaryMode = 'raw'; mode = 'raw'; draw(); } } }, 'متن خام'),
      h('span', { class: 'hint' }, 'هر دو یکی‌اند؛ فرم همان متن خام را می‌سازد.'));
    var rawTa = h('textarea', { rows: 16, oninput: changed });
    rawTa.value = raw;
    var left = h('div');
    var grid = h('div', { class: 'two' }, left, h('div', { class: 'phone-wrap' }, frame));
    body.appendChild(switcher);
    body.appendChild(grid);
    body.appendChild(bar.el);
    var phrases = boldPhrases(s.full_body);
    var notesPlain = plain(s.full_body);

    function draw() {
      left.innerHTML = '';
      switcher.querySelectorAll('button').forEach(function (b, i) { b.classList.toggle('primary', (i === 0) === (mode === 'form')); });
      if (mode === 'raw') {
        left.appendChild(rawTa);
        left.appendChild(h('p', { class: 'hint' }, 'برچسب‌ها: «در یک نگاه:»، «مهم:»، «واژه:»، «قاعده:»، «حفظی:»، «تله:» و هر مورد با «- ». خلاصه‌ی بدون برچسب هم مثل متن معمولی نشان داده می‌شود.'));
        refresh();
        return;
      }
      var f = h('div', { class: 'rc-form' });
      var glance = h('textarea', { rows: 2, oninput: function () { form.glance = glance.value; changed(); } });
      glance.value = form.glance;
      f.appendChild(h('div', { class: 'part' }, h('h4', null, 'در یک نگاه ', h('span', { class: 'hint' }, '(یک یا دو جمله: این بخش درباره‌ی چیست)')), glance));
      PARTS.forEach(function (p) {
        var key = p[0];
        var part = h('div', { class: 'part' }, h('h4', null, p[1]));
        var list = h('div');
        function drawList() {
          list.innerHTML = '';
          form[key].forEach(function (item, i) {
            var del = h('span', { class: 'row', style: 'gap:2px;flex-wrap:nowrap' },
              h('button', { class: 'btn icon', type: 'button', title: 'بالا', onclick: function () { if (i) { var t = form[key][i - 1]; form[key][i - 1] = form[key][i]; form[key][i] = t; drawList(); changed(); } } }, '▲'),
              h('button', { class: 'btn icon danger', type: 'button', title: 'حذف', onclick: function () { form[key].splice(i, 1); drawList(); changed(); } }, '✕'));
            if (key === 'important') {
              var t = h('input', { type: 'text', value: item.text, placeholder: 'اشاره‌ی کوتاه به نکته', oninput: function () { item.text = t.value; changed(); } });
              var ok = h('span', { title: '' });
              var ph = h('input', { type: 'text', value: item.phrase, list: 'cm-bold', placeholder: 'عبارت دقیق از جزوه', oninput: function () { item.phrase = ph.value; mark(); changed(); } });
              function mark() {
                var found = !item.phrase.trim() || notesPlain.indexOf(plain(item.phrase).trim()) >= 0;
                ok.textContent = item.phrase.trim() ? (found ? '✓' : '⚠') : '';
                ok.style.color = found ? '#1f7a55' : '#ba2121';
                ok.title = found ? 'در جزوه پیدا شد' : 'در جزوه پیدا نشد؛ پرش کار نمی‌کند';
              }
              mark();
              list.appendChild(h('div', { class: 'line imp' }, t, ph, ok, del));
            } else if (key === 'terms') {
              var a = h('input', { type: 'text', value: item.fa, placeholder: 'فارسی (همان که در جزوه آمده)', oninput: function () { item.fa = a.value; changed(); } });
              var b = h('input', { type: 'text', value: item.en, placeholder: 'English', dir: 'ltr', oninput: function () { item.en = b.value; changed(); } });
              var c = h('input', { type: 'text', value: item.meaning, placeholder: 'معنی کوتاه', oninput: function () { item.meaning = c.value; changed(); } });
              list.appendChild(h('div', { class: 'line term' }, a, b, c, del));
            } else {
              var x = h('input', { type: 'text', value: item, oninput: function () { form[key][i] = x.value; changed(); } });
              list.appendChild(h('div', { class: 'line' }, x, del));
            }
          });
        }
        drawList();
        part.appendChild(list);
        part.appendChild(h('button', { class: 'btn small', type: 'button', onclick: function () {
          form[key].push(key === 'important' ? { text: '', phrase: '' } : key === 'terms' ? { fa: '', en: '', meaning: '' } : '');
          drawList();
        } }, '+ افزودن'));
        f.appendChild(part);
      });
      f.appendChild(h('datalist', { id: 'cm-bold' }, phrases.map(function (x) { return h('option', { value: x }); })));
      left.appendChild(f);
      refresh();
    }
    draw();
  };

  // ----- tests and flashcards -----
  Manager.prototype.renderItems = function (body, s, kind) {
    var self = this;
    var list = kind === 'question' ? s.questions : s.flashcards;
    var others = [{ slug: '', title: 'مقدمه‌ی فصل' }].concat(this.state.sections).filter(function (x) { return x.slug !== s.slug; });
    var top = h('div', { class: 'row', style: 'margin-bottom:10px' },
      h('button', { class: 'btn primary', type: 'button', onclick: function () { if (self.guard()) { self.open = { kind: kind, slug: null }; self.render(); } } },
        kind === 'question' ? '+ تست تازه' : '+ فلش‌کارت تازه'),
      h('span', { class: 'hint' }, kind === 'question' ? 'ترتیب این فهرست، ترتیب تست‌ها در اپ است.' : 'فلش‌کارت نکته است، نه سؤال: رو = عنوان، پشت = نکته.'));
    body.appendChild(top);
    if (this.open && this.open.kind === kind && this.open.slug === null) body.appendChild(this.itemEditor(s, kind, null));
    if (!list.length && !(this.open && this.open.slug === null)) body.appendChild(h('p', { class: 'hint' }, 'هنوز چیزی در این بخش نیست.'));
    list.forEach(function (item, i) {
      if (self.open && self.open.kind === kind && self.open.slug === item.slug) { body.appendChild(self.itemEditor(s, kind, item)); return; }
      var move = h('select', { class: 'btn small', onchange: function () {
        if (!move.value && move.value !== '') return;
        var to = move.value === '__intro' ? '' : move.value;
        self.call({ op: kind + '.move', slug: item.slug, to: to }).then(function () { self.render(); toast('منتقل شد.'); }).catch(function () {});
      } }, h('option', { value: '', selected: true, disabled: true }, 'انتقال به…'), others.map(function (o) { return h('option', { value: o.slug || '__intro' }, o.title); }));
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
          h('span', { class: 'pill' }, item.sources.length ? item.sources.map(function (x) { return x.name + ' ' + fa(x.year); }).join('، ') : 'تألیفی'),
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
      body.appendChild(h('div', { class: 'item', id: 'item-' + item.slug }, h('div', { class: 'head' }, h('span', { class: 'num' }, fa(i + 1)), content, acts)));
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
      ? { stem: '', choices: [{ text: '', correct: true }, { text: '', correct: false }, { text: '', correct: false }, { text: '', correct: false }], explanation: '', quick_solution: '', alternative_view: '', difficulty: 'medium', kind: '', domain: '', seconds: '', is_free: false, fixed_order: false, is_original: true, sources: [], flashcards: [] }
      : { title: '', point: '', formula: '', is_free: false });
    var box = h('div', { class: 'item open', id: 'item-' + (item ? item.slug : 'new') });
    var mode = 'form';
    var slugInput = h('input', { type: 'text', value: item ? item.slug : this.state.suggest[kind], dir: 'ltr', disabled: !isNew });
    var frame = h('iframe', { class: 'phone', title: 'پیش‌نمایش' });
    autoHeight(frame, 260);
    var left = h('div');
    var rawTa = h('textarea', { rows: 18, dir: 'rtl' });
    function changed() { self.dirty = kind === 'question' ? 'تست' : 'فلش‌کارت'; clearTimeout(changed.t); changed.t = setTimeout(preview, 250); }
    rawTa.oninput = changed;

    function preview() {
      var html = '';
      if (mode === 'raw') { html = '<p style="color:#56655B">پیش‌نمایش در حالت متن خام بعد از «برگشت به فرم» دیده می‌شود.</p>'; }
      else if (kind === 'question') {
        html = render(data.stem) + '<ol style="padding-right:22px">' + data.choices.map(function (c) {
          return '<li style="margin:6px 0;padding:6px 10px;border-radius:12px;background:' + (c.correct ? '#E3F3E9' : '#fff') + ';border:1px solid #E3E8DE">' + render(c.text).replace(/<\/?p>/g, '') + '</li>';
        }).join('') + '</ol>' + (data.explanation ? '<div class="box box-0"><div class="box-title">پاسخ تشریحی</div>' + render(data.explanation) + '</div>' : '') +
          (data.quick_solution ? '<div class="box box-3"><div class="box-title">راه‌حل سریع</div>' + render(data.quick_solution) + '</div>' : '') +
          (data.alternative_view ? '<div class="box box-1"><div class="box-title">زاویه‌ی دیگر</div>' + render(data.alternative_view) + '</div>' : '');
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
      left.innerHTML = '';
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
        left.appendChild(mdField('راه‌حل سریع', 'quick_solution', 2, '(اختیاری)'));
        left.appendChild(mdField('زاویه‌ی دیگر', 'alternative_view', 2, '(اختیاری)'));
        var sel = function (list, key) {
          var el = h('select', { onchange: function () { data[key] = el.value; changed(); } }, list.map(function (o) { return h('option', { value: o[0], selected: data[key] === o[0] }, o[1]); }));
          return el;
        };
        var secs = h('input', { type: 'number', min: 0, value: data.seconds || '', oninput: function () { data.seconds = secs.value; } });
        var free = h('input', { type: 'checkbox', checked: data.is_free, onchange: function () { data.is_free = free.checked; } });
        var fixed = h('input', { type: 'checkbox', checked: data.fixed_order, onchange: function () { data.fixed_order = fixed.checked; } });
        left.appendChild(h('label', { class: 'btn small', style: 'margin:4px 0', title: 'برای گزینه‌هایی مثل «۱ و ۳» یا «همه‌ی موارد» خودکار ثابت می‌ماند' },
          fixed, ' ترتیب گزینه‌ها ثابت بماند (اپ جابه‌جایشان نکند)'));
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
            var n = h('input', { type: 'text', value: x.name, placeholder: 'نام کنکور، مثلاً «کنکور ارشد مهندسی پزشکی»', oninput: function () { x.name = n.value; } });
            var y = h('input', { type: 'text', value: x.year || '', placeholder: 'سال', oninput: function () { x.year = y.value; } });
            var q = h('input', { type: 'text', value: x.number || '', placeholder: 'سؤال', oninput: function () { x.number = q.value; } });
            src.appendChild(h('div', { class: 'src-row' }, n, y, q, h('button', { class: 'btn icon danger', type: 'button', onclick: function () { data.sources.splice(i, 1); drawSrc(); } }, '✕')));
          });
          src.appendChild(h('button', { class: 'btn small', type: 'button', onclick: function () { data.sources.push({ name: '', year: '', number: '' }); drawSrc(); } }, '+ منبع کنکور'));
        })();
        left.appendChild(field('منبع', src, '(هرگز منبع کنکور از خودتان نسازید)'));
        // flashcards
        var cards = self.allFlashcards();
        var fc = h('div', { style: 'max-height:180px;overflow:auto;border:1px solid var(--line);border-radius:8px;padding:6px 10px' },
          cards.length ? cards.map(function (c) {
            var cb = h('input', { type: 'checkbox', checked: data.flashcards.indexOf(c.slug) >= 0, onchange: function () {
              if (cb.checked) data.flashcards.push(c.slug); else data.flashcards = data.flashcards.filter(function (x) { return x !== c.slug; });
            } });
            return h('label', { style: 'display:block;margin:3px 0' }, cb, ' ', c.title, h('span', { class: 'hint' }, ' — ' + c.section));
          }) : h('span', { class: 'hint' }, 'این فصل هنوز فلش‌کارت ندارد.'));
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
    var modeBtn = h('button', { class: 'btn small', type: 'button', onclick: function () {
      self.call({ op: kind + '.convert', slug: slugInput.value, data: payload() }).then(function (res) {
        if (mode === 'form') { rawTa.value = res.item.raw; mode = 'raw'; left.innerHTML = ''; left.appendChild(rawTa); left.appendChild(h('p', { class: 'hint' }, 'همان قالب فایل. خط اول و آخر (:::) لازم نیست.')); modeBtn.textContent = 'برگشت به فرم'; preview(); }
        else { var it = res.item; for (var k in it) data[k] = it[k]; mode = 'form'; modeBtn.textContent = 'متن خام'; drawForm(); }
      }).catch(function () {});
    } }, 'متن خام');

    var head = h('div', { class: 'row', style: 'margin-bottom:6px' },
      h('b', null, isNew ? (kind === 'question' ? 'تست تازه' : 'فلش‌کارت تازه') : 'ویرایش ' + (kind === 'question' ? 'تست' : 'فلش‌کارت')),
      h('span', { class: 'hint' }, 'شناسه:'), h('span', { style: 'width:150px' }, slugInput), h('span', { class: 'grow' }), modeBtn);
    box.appendChild(head);
    box.appendChild(h('div', { class: 'two' }, left, h('div', { class: 'phone-wrap' }, frame)));
    var bar = this.saveBar(function () {
      var req = { op: kind + '.save', slug: slugInput.value.trim(), data: payload(), section: s.slug };
      if (isNew) req.new = true;
      self.call(req).then(function () { self.dirty = null; self.open = null; self.render(); toast('ذخیره شد.'); }).catch(function () {});
    }, 'ذخیره');
    bar.el.appendChild(h('button', { class: 'btn', type: 'button', onclick: function () { if (self.guard()) { self.dirty = null; self.open = null; self.render(); } } }, 'انصراف'));
    box.appendChild(bar.el);
    drawForm();
    return box;
  };

  window.LimoChapterManager = Manager;

  // ---------- Whole-file editor ----------
  window.LimoFileEditor = function (opts) {
    var ta = document.getElementById('file-text'), out = document.getElementById('file-result');
    var checkBtn = document.getElementById('file-check'), saveBtn = document.getElementById('file-save');
    var checked = null;
    function post(body) {
      return fetch(opts.api, { method: 'POST', credentials: 'same-origin', headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrf() }, body: JSON.stringify(body) })
        .then(function (r) { return r.json(); });
    }
    ta.addEventListener('input', function () { if (checked !== null) { checked = null; saveBtn.disabled = true; } });
    checkBtn.onclick = function () {
      out.innerHTML = 'در حال بررسی…';
      post({ op: 'file.check', text: ta.value }).then(function (d) {
        out.innerHTML = '';
        out.appendChild(window.LimoReport(d));
        checked = d.errors.length ? null : ta.value;
        saveBtn.disabled = !!d.errors.length || !d.plan || (!d.plan.count && !d.plan.notes.length);
        if (!d.errors.length && d.plan && !d.plan.count && !d.plan.notes.length) out.appendChild(h('div', { class: 'msg ok' }, 'با فصل فعلی فرقی ندارد.'));
      });
    };
    saveBtn.onclick = function () {
      if (checked === null || checked !== ta.value) return;
      saveBtn.disabled = true;
      post({ op: 'file.apply', text: ta.value, version: opts.version, restore: opts.restore, note: opts.note }).then(function (d) {
        if (d.errors) { out.prepend(h('div', { class: 'msg err' }, d.errors.join(' '))); return; }
        location.href = opts.done;
      });
    };
  };

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
