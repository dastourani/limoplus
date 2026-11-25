/* لیموخوان website: draws the covers and formulas with the app's own code (catalog/limo-preview.js), filters the
   shelves by major, and lets a visitor try the sample tests (answers come from the server, as in the app). */
(function () {
  var P = window.LimoPreview;

  function formatRating(rating, count) {
    if (typeof rating !== 'number' || !isFinite(rating) || rating <= 0 || !count) return '';
    var rounded = Math.round(rating * 10) / 10;
    var text = (rounded % 1 === 0 ? String(rounded) : rounded.toFixed(1).replace('.', '٫'))
      .replace(/\d/g, function (d) { return '۰۱۲۳۴۵۶۷۸۹'[Number(d)]; });
    return text;
  }

  function covers() {
    document.querySelectorAll('.cover[data-cover]').forEach(function (el) {
      var data;
      try { data = JSON.parse(el.getAttribute('data-cover')); } catch (e) { return; }
      var w = Number(el.getAttribute('data-w')) || el.clientWidth || 170;
      if (el.clientWidth && el.clientWidth < w) w = el.clientWidth;
      var ratingText = w >= 100 ? formatRating(data.rating, data.rating_count) : '';
      var ratingChip = function (cls) {
        return ratingText
          ? '<span class="' + cls + '" aria-label="امتیاز ' + ratingText + ' از ۵"><span class="cover-rating-star" aria-hidden="true">★</span><span>' + ratingText + '</span></span>'
          : '';
      };
      if (data.image) {
        el.innerHTML = '<img alt="" loading="lazy" src="' + data.image.replace(/"/g, '&quot;') + '">' + ratingChip('cover-rating');
      } else if (P && P.coverHtml) {
        el.innerHTML = P.coverHtml(data, 'dark', w) + ratingChip('cover-rating cover-rating-dark');
      }
    });
  }

  function md(text) {
    if (!P || !P.renderMarkdown) return null;
    return '<div class="lesson compact justify">' + P.renderMarkdown(text || '') + '</div>';
  }

  function formulas() {
    if (!P || !P.renderMarkdown) return;
    var m = document.getElementById('limo-macros');
    if (m && P.setMacros) { try { P.setMacros(JSON.parse(m.textContent)); } catch (e) { /* ignore */ } }
    var l = document.getElementById('limo-labels');
    if (l && P.setLabels) { try { P.setLabels(JSON.parse(l.textContent)); } catch (e) { /* ignore */ } }
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
    document.querySelectorAll('[data-fold]').forEach(function (box) {
      var body = box.querySelector('.about-body');
      var btn = box.querySelector('.fold-btn');
      if (!body || !btn) return;
      if (body.scrollHeight > 260) {
        box.classList.add('folded');
        btn.hidden = false;
        btn.addEventListener('click', function () {
          var open = box.classList.toggle('folded');
          btn.textContent = open ? 'نمایش کامل معرفی کتاب ▾' : 'بستن ▴';
        });
      }
    });
  }

  var activeMajor = '';
  var showSampleForMajor = null;

  function filters() {
    document.querySelectorAll('[data-filter]').forEach(function (bar) {
      var shelf = bar.closest('section').querySelector('.shelf');
      bar.addEventListener('click', function (e) {
        var b = e.target.closest('.chip');
        if (!b) return;
        bar.querySelectorAll('.chip').forEach(function (c) { c.classList.toggle('on', c === b); });
        var m = b.getAttribute('data-major') || '';
        shelf.querySelectorAll('.bk').forEach(function (bk) {
          var ms = (bk.getAttribute('data-majors') || '').split(' ');
          bk.classList.toggle('hide', !!m && ms.indexOf(m) < 0);
        });
        if (showSampleForMajor) showSampleForMajor(m, true);
      });
    });
  }

  function bookShelves() {
    document.querySelectorAll('[data-book-index]').forEach(function (index) {
      var shelf = index.querySelector('.book-index-track');
      var button = index.querySelector('[data-shelf-scroll]');
      if (!shelf || !button) return;
      index.classList.add('is-enhanced');

      function syncArrow() {
        var cards = Array.prototype.filter.call(shelf.querySelectorAll('.bk'), function (card) {
          return !card.hidden && !card.classList.contains('hide');
        });
        var leftmost = cards[cards.length - 1];
        button.hidden = !leftmost || leftmost.getBoundingClientRect().left >= shelf.getBoundingClientRect().left - 1;
      }

      var updateQueued = false;
      function queueUpdate() {
        if (updateQueued) return;
        updateQueued = true;
        var schedule = window.requestAnimationFrame || function (callback) { window.setTimeout(callback, 16); };
        schedule(function () { updateQueued = false; syncArrow(); });
      }

      button.addEventListener('click', function () {
        var distance = Math.max(170, Math.floor(shelf.clientWidth * 0.75));
        if (typeof shelf.scrollBy === 'function') shelf.scrollBy({ left: -distance, behavior: 'smooth' });
        else shelf.scrollLeft -= distance;
      });
      shelf.addEventListener('scroll', queueUpdate, { passive: true });
      window.addEventListener('resize', queueUpdate);
      if (window.ResizeObserver) {
        shelf.__bookIndexObserver = new window.ResizeObserver(queueUpdate);
        shelf.__bookIndexObserver.observe(shelf);
      }
      syncArrow();
    });
  }

  function samples() {
    document.querySelectorAll('.sample').forEach(function (box) {
      if (box.__bound) return;
      box.__bound = true;
      box.addEventListener('click', function (e) {
        var btn = e.target.closest('.choice');
        if (!btn || btn.disabled) return;
        var id = box.getAttribute('data-id');
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
          var esc = function (t) { return String(t).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };
          if (res.explanation) parts.push('<h4>پاسخ تشریحی</h4>' + (md(res.explanation) || esc(res.explanation)));
          (res.solutions || []).forEach(function (x) { if (x.body) parts.push('<h4>' + esc(x.title || 'راه‌حل') + '</h4>' + (md(x.body) || esc(x.body))); });
          if (parts.length) { ex.innerHTML = parts.join(''); ex.hidden = false; }
        }).catch(function () { buttons.forEach(function (b) { b.disabled = false; }); });
      });
    });
  }

  function homeRandomSample() {
    var script = document.getElementById('limo-home-samples');
    var btn = document.querySelector('[data-next-sample]');
    var box = document.getElementById('home-sample-box');
    var filterBar = document.querySelector('[data-sample-filter]');
    if (!script || !box) return;
    var pool;
    try { pool = JSON.parse(script.textContent); } catch (e) { return; }
    if (!pool || !pool.length) return;
    var idx = 0;
    var esc = function (t) { return String(t || '').replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; }); };

    function matching() {
      if (!activeMajor) return pool;
      var sub = pool.filter(function (q) { return (q.majors || []).indexOf(activeMajor) >= 0; });
      return sub.length ? sub : pool;
    }

    function renderQuestion(q) {
      if (!q) return;
      box.setAttribute('data-id', q.id);
      var place = box.querySelector('[data-sample-place]');
      if (place) place.textContent = (q.book_title || '') + (q.section ? '، ' + q.section : '');
      var src = box.querySelector('[data-sample-src]');
      if (src) { src.textContent = q.source || ''; src.hidden = !q.source; }
      var bookLink = document.querySelector('[data-sample-book-link]');
      if (bookLink && q.book_url) { bookLink.href = q.book_url; bookLink.textContent = 'از کتاب «' + q.book_title + '» ←'; }
      var stem = box.querySelector('.stem');
      if (stem) { stem.setAttribute('data-md', q.stem); stem.innerHTML = md(q.stem) || esc(q.stem); }
      var choices = box.querySelector('.choices');
      if (choices) {
        choices.innerHTML = (q.choices || []).map(function (c) {
          return '<button class="choice" data-choice="' + c.id + '"><span class="cnum">' + esc(c.num) + '</span><span class="ctext">' + (md(c.text) || esc(c.text)) + '</span></button>';
        }).join('');
      }
      var ex = box.querySelector('.explain');
      if (ex) { ex.hidden = true; ex.innerHTML = ''; }
    }

    showSampleForMajor = function (majorSlug, fromBooksBar) {
      activeMajor = majorSlug || '';
      if (filterBar && fromBooksBar) {
        filterBar.querySelectorAll('.chip').forEach(function (c) {
          c.classList.toggle('on', (c.getAttribute('data-major') || '') === activeMajor);
        });
      }
      var list = matching();
      idx = 0;
      renderQuestion(list[0]);
    };

    if (filterBar) {
      filterBar.addEventListener('click', function (e) {
        var b = e.target.closest('.chip');
        if (!b) return;
        filterBar.querySelectorAll('.chip').forEach(function (c) { c.classList.toggle('on', c === b); });
        showSampleForMajor(b.getAttribute('data-major') || '', false);
      });
    }

    if (btn) {
      btn.addEventListener('click', function () {
        var list = matching();
        if (!list.length) return;
        idx = (idx + 1) % list.length;
        renderQuestion(list[idx]);
      });
    }
  }

  function device() {
    var cards = document.querySelectorAll('.dl-card[data-device]');
    if (!cards.length || typeof navigator === 'undefined') return;
    var isAndroid = /android/i.test(navigator.userAgent || '');
    var target = isAndroid ? 'android' : 'web';
    cards.forEach(function (c) {
      if (c.getAttribute('data-device') === target) {
        c.classList.add('rec');
        var b = c.querySelector('.dev-badge');
        if (b) b.hidden = false;
      }
    });
  }

  function start() {
    P = window.LimoPreview;
    covers();
    formulas();
    filters();
    bookShelves();
    samples();
    homeRandomSample();
    device();
  }
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
