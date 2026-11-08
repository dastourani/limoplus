/* لیموخوان website: draws the covers and formulas with the app's own code (catalog/limo-preview.js), filters the
   shelves by major, and lets a visitor try the sample tests (answers come from the server, as in the app). */
(function () {
  var P = window.LimoPreview;

  function covers() {
    document.querySelectorAll('.cover[data-cover]').forEach(function (el) {
      var data;
      try { data = JSON.parse(el.getAttribute('data-cover')); } catch (e) { return; }
      var w = Number(el.getAttribute('data-w')) || el.clientWidth || 170;
      if (el.clientWidth && el.clientWidth < w) w = el.clientWidth;
      if (data.image) {
        el.innerHTML = '<img alt="" loading="lazy" src="' + data.image.replace(/"/g, '&quot;') + '">';
      } else if (P && P.coverHtml) {
        el.innerHTML = P.coverHtml(data, 'dark', w);
      }
    });
  }

  function md(text) {
    if (!P || !P.renderMarkdown) return null;
    return '<div class="lesson compact">' + P.renderMarkdown(text || '') + '</div>';
  }

  function formulas() {
    if (!P || !P.renderMarkdown) return;
    var m = document.getElementById('limo-macros');
    if (m && P.setMacros) { try { P.setMacros(JSON.parse(m.textContent)); } catch (e) { /* ignore */ } }
    if (P.CONTENT_CSS && !document.getElementById('limo-css')) {
      var st = document.createElement('style');
      st.id = 'limo-css';
      st.textContent = P.CONTENT_CSS;
      document.head.appendChild(st);
    }
    document.querySelectorAll('[data-md]').forEach(function (el) {
      var html = md(el.getAttribute('data-md'));
      if (html) el.innerHTML = html;
    });
  }

  function filters() {
    document.querySelectorAll('[data-filter]').forEach(function (bar) {
      var shelf = bar.closest('section').querySelector('.shelf');
      bar.addEventListener('click', function (e) {
        var b = e.target.closest('.chip');
        if (!b) return;
        bar.querySelectorAll('.chip').forEach(function (c) { c.classList.toggle('on', c === b); });
        var m = b.getAttribute('data-major');
        shelf.querySelectorAll('.bk').forEach(function (bk) {
          var ms = (bk.getAttribute('data-majors') || '').split(' ');
          bk.classList.toggle('hide', !!m && ms.indexOf(m) < 0);
        });
      });
    });
  }

  function samples() {
    document.querySelectorAll('.sample').forEach(function (box) {
      var id = box.getAttribute('data-id');
      box.addEventListener('click', function (e) {
        var btn = e.target.closest('.choice');
        if (!btn || btn.disabled) return;
        var buttons = box.querySelectorAll('.choice');
        buttons.forEach(function (b) { b.disabled = true; });
        fetch('/api/v1/questions/' + id + '/answer/', {
          method: 'POST', headers: { 'Content-Type': 'application/json' }, credentials: 'omit',
          body: JSON.stringify({ choice_id: Number(btn.getAttribute('data-choice')) }),
        }).then(function (r) { return r.json(); }).then(function (res) {
          buttons.forEach(function (b) {
            var c = Number(b.getAttribute('data-choice'));
            if (c === res.correct_choice_id) b.classList.add('right');
            else if (b === btn) b.classList.add('wrong');
          });
          var ex = box.querySelector('.explain');
          var parts = [];
          if (res.quick_solution) parts.push('<h4>راه‌حل سریع</h4>' + (md(res.quick_solution) || res.quick_solution));
          if (res.explanation) parts.push('<h4>پاسخ تشریحی</h4>' + (md(res.explanation) || res.explanation));
          if (parts.length) { ex.innerHTML = parts.join(''); ex.hidden = false; }
        }).catch(function () { buttons.forEach(function (b) { b.disabled = false; }); });
      });
    });
  }

  function start() {
    P = window.LimoPreview;
    covers();
    formulas();
    filters();
    samples();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
