/* LimooKhan panel: the docked live-preview pane shared by the whole-file editor and the section editors.
 *
 * Why this exists: the preview used to be a floating, draggable dialog and before that a button soup on the editor’s
 * toolbar. A professor could not switch device width without closing the window, and both bugs made the editor feel
 * broken. The pane is part of the layout instead: it can be hidden (editor takes the full width), split (editor and
 * preview side by side), or expanded (preview only). The module owns the iframe, the width buttons and the fit-to-column
 * logic; the caller owns the editor text and the check/save flow.
 */
(function () {
  'use strict';

  var DEVICES = [
    { id: 'phone', label: 'گوشی', width: 390 },
    { id: 'tablet', label: 'تبلت', width: 768 },
    { id: 'web', label: 'وب', width: 0 },          // 0 = flexible, capped by CSS at 1024px
  ];
  var WIDTH_KEY = 'limo.panel.width';

  function h(tag, attrs) {
    var el = document.createElement(tag);
    if (attrs) for (var k in attrs) {
      var v = attrs[k];
      if (v == null || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k === 'text') el.textContent = v;
      else if (k.indexOf('on') === 0) el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
      else if (k === 'checked') el.checked = !!v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (var i = 2; i < arguments.length; i++) {
      var child = arguments[i];
      if (child == null || child === false) continue;
      el.appendChild(typeof child === 'string' || typeof child === 'number' ? document.createTextNode(String(child)) : child);
    }
    return el;
  }

  function validDevice(name) {
    for (var i = 0; i < DEVICES.length; i++) if (DEVICES[i].id === name) return name;
    return 'phone';
  }

  // «تمام‌عرض» used to be persisted as a fourth device; it meant "fill the window", which is what «وب» now does.
  function getWidth() {
    try {
      var v = localStorage.getItem(WIDTH_KEY);
      if (v === 'wide') return 'web';
      return validDevice(v || 'phone');
    } catch (e) { return 'phone'; }
  }

  function setWidth(name) {
    name = validDevice(name);
    try { localStorage.setItem(WIDTH_KEY, name); } catch (e) { /* ignore */ }
    return name;
  }

  function logicalWidth(name) {
    for (var i = 0; i < DEVICES.length; i++) if (DEVICES[i].id === name) return DEVICES[i].width;
    return 390;
  }

  // The pane is the column; the stage is the visually scaled lesson inside it. Phone and tablet always lay out at
  // their logical CSS width (so the line breaks are honest) and shrink with `transform` only when the column is too
  // narrow. The editor's own font size is never involved: the lesson has the app's stylesheet, not the panel's.
  function create(options) {
    options = options || {};
    var device = getWidth();
    var expanded = !!options.expanded;
    var frame = options.frame || h('iframe', { title: options.frameTitle || 'پیش‌نمایش', class: options.frameClass || '' });
    frame.classList.add('pv-frame');

    var buttons = {};
    function paintButtons() {
      for (var id in buttons) {
        var on = id === device;
        buttons[id].classList.toggle('on', on);
        buttons[id].setAttribute('aria-pressed', on ? 'true' : 'false');
      }
    }

    var seg = h('div', { class: 'pv-devices', role: 'group', 'aria-label': 'اندازه‌ی نمایش زنده' });
    DEVICES.forEach(function (item) {
      buttons[item.id] = h('button', {
        type: 'button',
        class: 'pv-device',
        title: item.id === 'web' ? 'نمایش زنده در عرض وب' : 'نمایش زنده در اندازه‌ی ' + item.label,
        'aria-pressed': 'false',
        onclick: function (e) {
          e.preventDefault();
          setDevice(item.id);
          if (options.onDeviceChange) options.onDeviceChange(item.id);
        },
      }, item.label);
      seg.appendChild(buttons[item.id]);
    });

    var expandBtn = h('button', {
      type: 'button', class: 'pv-expand', title: 'فقط پیش‌نمایش (پنهان‌کردن ویرایشگر)', 'aria-pressed': expanded ? 'true' : 'false',
      onclick: function (e) {
        e.preventDefault();
        setExpanded(!expanded);
        if (options.onExpandChange) options.onExpandChange(expanded);
      },
    }, '⛶');

    var closeBtn = h('button', {
      type: 'button', class: 'pv-pane-x', title: 'بستن نمایش زنده (همان دکمه‌ی نمایش زنده در نوار ابزار)',
      onclick: function (e) {
        e.preventDefault();
        if (options.onClose) options.onClose();
      },
    }, '×');

    var title = h('span', { class: 'pv-pane-title' }, options.title || 'پیش‌نمایش');
    // RTL: title is the first (right-most) item; × is the last (left-most). The segmented control sits in between.
    var bar = h('div', { class: 'pv-pane-bar' }, title, seg, expandBtn, closeBtn);

    var stage = h('div', { class: 'pv-pane-stage' }, frame);
    var body = h('div', { class: 'pv-pane-body' }, stage);
    var pane = h('div', { class: 'md-prev pv-pane', 'data-device': device, 'data-expanded': expanded ? 'true' : 'false' }, bar, body);

    function setDevice(name) {
      device = setWidth(name);
      pane.setAttribute('data-device', device);
      paintButtons();
      applyLayout();
    }

    function setExpanded(value) {
      expanded = !!value;
      pane.setAttribute('data-expanded', expanded ? 'true' : 'false');
      expandBtn.classList.toggle('on', expanded);
      expandBtn.setAttribute('aria-pressed', expanded ? 'true' : 'false');
      expandBtn.title = expanded ? 'برگشت به ویرایشگر و پیش‌نمایش' : 'فقط پیش‌نمایش (پنهان‌کردن ویرایشگر)';
      applyLayout();
    }

    // The iframe is sized to the rendered lesson, not to the editor's height. Otherwise a short preview inside a
    // very long chapter leaves a full column of white and a pointless scrollbar. The page itself may grow, exactly
    // like the text editor does; there is no useless inner scroll.
    function contentHeight() {
      try {
        var doc = frame.contentDocument;
        if (!doc) return 240;
        var body = doc.body, root = doc.documentElement;
        return Math.max(240, Math.ceil(Math.max(
          body ? body.scrollHeight : 0,
          body ? body.offsetHeight : 0,
          root ? root.scrollHeight : 0,
          root ? root.offsetHeight : 0
        )) + 4);
      } catch (e) {
        return 240;
      }
    }

    function applyLayout() {
      var w = logicalWidth(device);
      var available = Math.max(260, (body.clientWidth || options.minWidth || 320) - 20);
      var height = contentHeight();
      pane.setAttribute('data-device', device);
      frame.style.height = height + 'px';

      if (!w) {                       // web: fill the column, never scale and never reflow beyond 1024px
        stage.style.width = '100%';
        stage.style.maxWidth = '1024px';
        stage.style.height = height + 'px';
        frame.style.width = '100%';
        frame.style.maxWidth = '1024px';
        frame.style.transform = '';
        frame.style.margin = '0 auto';
        return;
      }

      var scale = Math.min(1, available / w);
      stage.style.width = Math.round(w * scale) + 'px';
      stage.style.maxWidth = 'none';
      stage.style.height = Math.round(height * scale) + 'px';
      frame.style.width = w + 'px';
      frame.style.maxWidth = 'none';
      frame.style.margin = '0';
      frame.style.transformOrigin = 'top left';
      frame.style.transform = scale < 0.999 ? 'scale(' + scale + ')' : '';
    }

    var scheduled = 0;
    function scheduleLayout() {
      if (scheduled) return;
      var raf = window.requestAnimationFrame || function (fn) { return setTimeout(fn, 16); };
      scheduled = raf(function () { scheduled = 0; applyLayout(); });
    }

    if (window.ResizeObserver) {
      try { new ResizeObserver(scheduleLayout).observe(body); } catch (e) { window.addEventListener('resize', scheduleLayout); }
    } else {
      window.addEventListener('resize', scheduleLayout);
    }
    frame.addEventListener('load', function () {
      scheduleLayout();
      setTimeout(scheduleLayout, 250);
      // Web fonts swap in after `load`, and the swapped glyphs set different line breaks. The document inside the
      // frame cannot scroll (see previewDoc), so a stale, shorter frame would clip the lesson instead of offering a
      // scrollbar — measure again when the fonts are ready.
      try {
        var doc = frame.contentDocument;
        if (doc && doc.fonts && doc.fonts.ready && doc.fonts.ready.then) {
          doc.fonts.ready.then(function () { scheduleLayout(); setTimeout(scheduleLayout, 150); });
        }
      } catch (e) { /* ignore */ }
    });

    paintButtons();
    setExpanded(expanded);
    // The pane may be hidden at creation time; the first visible frame will correct the measurements.
    setTimeout(applyLayout, 0);

    return {
      el: pane,
      body: body,
      stage: stage,
      frame: frame,
      bar: bar,
      setDevice: setDevice,
      getDevice: function () { return device; },
      setExpanded: setExpanded,
      isExpanded: function () { return expanded; },
      refreshScale: applyLayout,
      destroy: function () {
        window.removeEventListener('resize', scheduleLayout);
        pane.remove();
      },
    };
  }

  window.LimoPreviewPane = { create: create, devices: DEVICES.slice(), getWidth: getWidth, setWidth: setWidth };
})();
