/* Lightweight, dependency-free Jalali date picker for Django admin and custom report date fields. */
(function () {
  'use strict';

  var MONTHS = ['فروردین', 'اردیبهشت', 'خرداد', 'تیر', 'مرداد', 'شهریور', 'مهر', 'آبان', 'آذر', 'دی', 'بهمن', 'اسفند'];
  var WEEKDAYS = ['ش', 'ی', 'د', 'س', 'چ', 'پ', 'ج']; // Saturday first
  var FA_DIGITS = '۰۱۲۳۴۵۶۷۸۹';
  var DIGIT_MAP = { '۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9',
    '٠': '0', '١': '1', '٢': '2', '٣': '3', '٤': '4', '٥': '5', '٦': '6', '٧': '7', '٨': '8', '٩': '9' };

  function latinDigits(value) {
    return String(value).replace(/[۰-۹٠-٩]/g, function (digit) { return DIGIT_MAP[digit] || digit; });
  }

  function latinNumber(value) {
    return latinDigits(value).replace(/\u066B/g, '.').replace(/\u066C/g, '');
  }

  function faDigits(value) {
    return String(value).replace(/\d/g, function (digit) { return FA_DIGITS[Number(digit)]; });
  }

  function toJalali(gy, gm, gd) {
    var gdm = [0, 31, 59, 90, 120, 151, 181, 212, 243, 273, 304, 334];
    var gy2 = gm > 2 ? gy + 1 : gy;
    var days = 355666 + 365 * gy + Math.floor((gy2 + 3) / 4) - Math.floor((gy2 + 99) / 100) + Math.floor((gy2 + 399) / 400) + gd + gdm[gm - 1];
    var jy = -1595 + 33 * Math.floor(days / 12053);
    days %= 12053;
    jy += 4 * Math.floor(days / 1461);
    days %= 1461;
    if (days > 365) {
      jy += Math.floor((days - 1) / 365);
      days = (days - 1) % 365;
    }
    var jm = days < 186 ? 1 + Math.floor(days / 31) : 7 + Math.floor((days - 186) / 30);
    var jd = 1 + (days < 186 ? days % 31 : (days - 186) % 30);
    return [jy, jm, jd];
  }

  function fromJalali(jy, jm, jd) {
    jy += 1595;
    var days = -355668 + 365 * jy + Math.floor(jy / 33) * 8 + Math.floor(((jy % 33) + 3) / 4) + jd +
      (jm < 7 ? (jm - 1) * 31 : (jm - 7) * 30 + 186);
    var gy = 400 * Math.floor(days / 146097);
    days %= 146097;
    if (days > 36524) {
      days -= 1;
      gy += 100 * Math.floor(days / 36524);
      days %= 36524;
      if (days >= 365) days += 1;
    }
    gy += 4 * Math.floor(days / 1461);
    days %= 1461;
    if (days > 365) {
      gy += Math.floor((days - 1) / 365);
      days = (days - 1) % 365;
    }
    var gd = days + 1;
    var leap = (gy % 4 === 0 && gy % 100 !== 0) || gy % 400 === 0;
    var months = [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
    var gm = 0;
    while (gm < 12 && gd > months[gm]) {
      gd -= months[gm];
      gm += 1;
    }
    return [gy, gm + 1, gd];
  }

  function isValidJalali(year, month, day) {
    if (!(year >= 1 && year <= 3177 && month >= 1 && month <= 12 && day >= 1 && day <= 31)) return false;
    var gregorian = fromJalali(year, month, day);
    var roundTrip = toJalali(gregorian[0], gregorian[1], gregorian[2]);
    return roundTrip[0] === year && roundTrip[1] === month && roundTrip[2] === day;
  }

  function parseJalali(value) {
    var match = /^\s*(\d{1,4})\s*[/.\-]\s*(\d{1,2})\s*[/.\-]\s*(\d{1,2})\s*$/.exec(latinDigits(value));
    if (!match) return null;
    var date = [Number(match[1]), Number(match[2]), Number(match[3])];
    return isValidJalali(date[0], date[1], date[2]) ? date : null;
  }

  function formatJalali(date) {
    return faDigits(String(date[0]).padStart(4, '0') + '/' + String(date[1]).padStart(2, '0') + '/' + String(date[2]).padStart(2, '0'));
  }

  function tehranGregorianToday() {
    try {
      var parts = new Intl.DateTimeFormat('en-US-u-ca-gregory-nu-latn', {
        timeZone: 'Asia/Tehran', year: 'numeric', month: 'numeric', day: 'numeric'
      }).formatToParts(new Date());
      var found = {};
      parts.forEach(function (part) { if (part.type !== 'literal') found[part.type] = Number(part.value); });
      if (found.year && found.month && found.day) return [found.year, found.month, found.day];
    } catch (_error) { /* Use the browser's local date on older engines without IANA time-zone support. */ }
    var now = new Date();
    return [now.getFullYear(), now.getMonth() + 1, now.getDate()];
  }

  function todayJalali() {
    return toJalali.apply(null, tehranGregorianToday());
  }

  function weekdaySaturdayFirst(jalaliDate) {
    var gregorian = fromJalali(jalaliDate[0], jalaliDate[1], jalaliDate[2]);
    return (new Date(Date.UTC(gregorian[0], gregorian[1] - 1, gregorian[2])).getUTCDay() + 1) % 7;
  }

  function monthLength(year, month) {
    for (var day = 31; day >= 28; day -= 1) {
      if (isValidJalali(year, month, day)) return day;
    }
    return 0;
  }

  function shiftMonth(year, month, by) {
    var serial = year * 12 + month - 1 + by;
    return [Math.floor(serial / 12), serial % 12 + 1];
  }

  function addDays(date, amount) {
    var gregorian = fromJalali(date[0], date[1], date[2]);
    var moved = new Date(Date.UTC(gregorian[0], gregorian[1] - 1, gregorian[2] + amount));
    return toJalali(moved.getUTCFullYear(), moved.getUTCMonth() + 1, moved.getUTCDate());
  }

  function element(tag, className, text) {
    var node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  }

  function close(wrapper) {
    var picker = wrapper._lpJalaliPicker;
    if (!picker) return;
    picker.panel.hidden = true;
    picker.trigger.setAttribute('aria-expanded', 'false');
    window.removeEventListener('scroll', picker.position, true);
    window.removeEventListener('resize', picker.position);
    if (window.visualViewport) {
      window.visualViewport.removeEventListener('scroll', picker.position);
      window.visualViewport.removeEventListener('resize', picker.position);
    }
  }

  function closeOthers(except) {
    document.querySelectorAll('.lp-jalali-wrap').forEach(function (wrapper) {
      if (wrapper !== except) close(wrapper);
    });
  }

  function buildPicker(wrapper, input, trigger) {
    var panel = element('div', 'lp-jalali-panel');
    panel.hidden = true;
    panel.setAttribute('role', 'dialog');
    panel.setAttribute('aria-label', 'انتخاب تاریخ شمسی');
    var picker = { panel: panel, trigger: trigger, position: null };
    wrapper._lpJalaliPicker = picker;

    var header = element('div', 'lp-jalali-header');
    var previous = element('button', 'lp-jalali-nav', '‹');
    previous.type = 'button'; previous.dataset.lpNav = '-1'; previous.setAttribute('aria-label', 'ماه قبل');
    var title = element('strong', 'lp-jalali-month');
    var next = element('button', 'lp-jalali-nav', '›');
    next.type = 'button'; next.dataset.lpNav = '1'; next.setAttribute('aria-label', 'ماه بعد');
    header.append(previous, title, next);

    var weekdays = element('div', 'lp-jalali-weekdays');
    WEEKDAYS.forEach(function (day) { weekdays.appendChild(element('span', '', day)); });
    var days = element('div', 'lp-jalali-days');

    var footer = element('div', 'lp-jalali-footer');
    var today = element('button', '', 'امروز');
    today.type = 'button'; today.dataset.lpAction = 'today';
    var tomorrow = element('button', '', 'فردا');
    tomorrow.type = 'button'; tomorrow.dataset.lpAction = 'tomorrow';
    var cancel = element('button', 'lp-jalali-cancel', 'بستن');
    cancel.type = 'button'; cancel.dataset.lpAction = 'close';
    footer.append(today, tomorrow, cancel);
    panel.append(header, weekdays, days, footer);
    // A body-level fixed panel escapes overflow:hidden/auto ancestors in Django's stacked and tabular admin layouts.
    document.body.appendChild(panel);

    var current = todayJalali();

    function render() {
      title.textContent = MONTHS[current[1] - 1] + ' ' + faDigits(current[0]);
      days.replaceChildren();
      var offset = weekdaySaturdayFirst([current[0], current[1], 1]);
      for (var blank = 0; blank < offset; blank += 1) days.appendChild(element('span', 'lp-jalali-empty'));
      var count = monthLength(current[0], current[1]);
      var selected = parseJalali(input.value);
      var todayValue = todayJalali();
      for (var day = 1; day <= count; day += 1) {
        var button = element('button', 'lp-jalali-day', faDigits(day));
        button.type = 'button';
        button.dataset.lpDay = String(day);
        if (selected && selected[0] === current[0] && selected[1] === current[1] && selected[2] === day) button.classList.add('is-selected');
        if (todayValue[0] === current[0] && todayValue[1] === current[1] && todayValue[2] === day) button.classList.add('is-today');
        if ((offset + day - 1) % 7 === 6) button.classList.add('is-friday');
        days.appendChild(button);
      }
    }

    function positionPanel() {
      if (panel.hidden) return;
      var anchor = trigger.getBoundingClientRect();
      var viewportWidth = window.innerWidth || document.documentElement.clientWidth;
      var viewportHeight = window.innerHeight || document.documentElement.clientHeight;
      var margin = 12;
      panel.style.width = Math.max(120, Math.min(288, viewportWidth - margin * 2)) + 'px';
      panel.style.maxHeight = Math.max(120, viewportHeight - margin * 2) + 'px';
      var size = panel.getBoundingClientRect();
      var left = Math.max(margin, Math.min(anchor.right - size.width, viewportWidth - size.width - margin));
      var below = viewportHeight - anchor.bottom - margin - 6;
      var above = anchor.top - margin - 6;
      var top = anchor.bottom + 6;
      if (below < size.height && above > below) top = anchor.top - size.height - 6;
      top = Math.max(margin, Math.min(top, viewportHeight - size.height - margin));
      panel.style.left = Math.round(left) + 'px';
      panel.style.top = Math.round(top) + 'px';
    }
    picker.position = positionPanel;

    trigger.addEventListener('click', function () {
      if (!panel.hidden) { close(wrapper); return; }
      closeOthers(wrapper);
      current = parseJalali(input.value) || todayJalali();
      render();
      panel.hidden = false;
      trigger.setAttribute('aria-expanded', 'true');
      positionPanel();
      window.addEventListener('scroll', positionPanel, true);
      window.addEventListener('resize', positionPanel);
      if (window.visualViewport) {
        window.visualViewport.addEventListener('scroll', positionPanel);
        window.visualViewport.addEventListener('resize', positionPanel);
      }
    });
    input.addEventListener('click', function () {
      if (panel.hidden) trigger.click();
    });
    input.addEventListener('blur', function () {
      var parsed = parseJalali(input.value);
      if (parsed) input.value = formatJalali(parsed);
    });
    input.addEventListener('keydown', function (event) {
      if (event.key === 'Escape' && !panel.hidden) { close(wrapper); }
      if (event.key === 'ArrowDown' && event.altKey) { event.preventDefault(); trigger.click(); }
    });
    panel.addEventListener('click', function (event) {
      var button = event.target.closest('button');
      if (!button) return;
      if (button.dataset.lpNav) {
        current = shiftMonth(current[0], current[1], Number(button.dataset.lpNav));
        render();
      } else if (button.dataset.lpDay) {
        input.value = formatJalali([current[0], current[1], Number(button.dataset.lpDay)]);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        close(wrapper);
        input.focus();
      } else if (button.dataset.lpAction === 'today' || button.dataset.lpAction === 'tomorrow') {
        var selectedDay = addDays(todayJalali(), button.dataset.lpAction === 'tomorrow' ? 1 : 0);
        input.value = formatJalali(selectedDay);
        input.dispatchEvent(new Event('input', { bubbles: true }));
        input.dispatchEvent(new Event('change', { bubbles: true }));
        close(wrapper);
        input.focus();
      } else if (button.dataset.lpAction === 'close') {
        close(wrapper);
        input.focus();
      }
    });

    document.addEventListener('pointerdown', function (event) {
      if (!wrapper.contains(event.target) && !panel.contains(event.target)) close(wrapper);
    });
    document.addEventListener('keydown', function (event) {
      if (event.key === 'Escape') close(wrapper);
    });
  }

  function attach(input) {
    if (input.dataset.lpJalaliReady === '1' || input.disabled || input.type === 'hidden') return;
    input.dataset.lpJalaliReady = '1';
    var wrapper = element('span', 'lp-jalali-wrap');
    input.parentNode.insertBefore(wrapper, input);
    wrapper.appendChild(input);
    var trigger = element('button', 'lp-jalali-trigger', '▦');
    trigger.type = 'button';
    trigger.setAttribute('aria-label', 'باز کردن تقویم شمسی');
    trigger.setAttribute('aria-expanded', 'false');
    wrapper.appendChild(trigger);
    buildPicker(wrapper, input, trigger);
  }

  function attachNumber(input) {
    if (input.dataset.lpNumberReady === '1' || input.disabled || input.type === 'hidden') return;
    var kind = input.getAttribute('data-lp-number') || (input.step && input.step !== '1' ? 'decimal' : 'integer');
    if (input.type === 'number') input.type = 'text';
    input.setAttribute('data-lp-number-ready', '1');
    input.setAttribute('inputmode', kind === 'integer' ? 'numeric' : 'decimal');
    input.setAttribute('dir', 'ltr');

    input.addEventListener('input', function () {
      var value = input.value;
      var normalized = latinNumber(value);
      if (normalized === value) return;
      var start = input.selectionStart;
      var end = input.selectionEnd;
      input.value = normalized;
      if (start !== null && end !== null) input.setSelectionRange(start, end);
    }, true);

    var initial = latinNumber(input.value);
    if (initial !== input.value) input.value = initial;
  }

  function boot(root) {
    root = root || document;
    if (root.matches && root.matches('input.lp-jalali-date')) attach(root);
    if (root.matches && root.matches('input[data-lp-number], input[type="number"]')) attachNumber(root);
    root.querySelectorAll('input.lp-jalali-date').forEach(attach);
    root.querySelectorAll('input[data-lp-number], input[type="number"]').forEach(attachNumber);
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', function () { boot(); });
  else boot();

  // Django inlines and the chapter editor create controls after initial load; date and number inputs get the same
  // calendar/numeral handling before a user can interact with them.
  if (window.MutationObserver) {
    new MutationObserver(function (records) {
      records.forEach(function (record) {
        record.addedNodes.forEach(function (node) {
          if (node.nodeType === 1) boot(node);
        });
      });
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
})();
