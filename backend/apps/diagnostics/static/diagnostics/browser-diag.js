/* Lightweight browser error & 5xx reporter for LimoPlus panel (teacher/superadmin) and website.
   Sends allowlisted, PII-free structured diagnostics to /api/v1/diagnostics/events/ with zero loop risk. */
(function () {
  'use strict';

  if (typeof window === 'undefined' || window.__limoBrowserDiagInstalled) return;
  window.__limoBrowserDiagInstalled = true;

  var scriptEl =
    document.currentScript ||
    document.querySelector('script[src*="browser-diag.js"]') ||
    null;

  var PLATFORM = (scriptEl && scriptEl.getAttribute('data-platform')) || 'website';
  var CHANNEL = (scriptEl && scriptEl.getAttribute('data-channel')) || 'public';
  var APP_BUILD = (scriptEl && scriptEl.getAttribute('data-build')) || '';
  var SESSION_TAG = (scriptEl && scriptEl.getAttribute('data-session-tag')) || '';

  var ENDPOINT = '/api/v1/diagnostics/events/';
  var INSTALL_KEY = 'limo.browserInstallId';
  var OUTBOX_KEY = 'limo.browserDiagOutbox';
  var MAX_QUEUE = 15;
  var MAX_AGE_MS = 7 * 24 * 3600 * 1000;
  var MAX_BREADCRUMBS = 12;

  var ALLOWED_CONTEXT_KEYS = {
    book_slug: true,
    node_id: true,
    status_code: true,
    error_name: true,
    stack: true,
    method: true,
    location: true,
    source: true,
  };

  var breadcrumbs = [];
  var recentDedupe = Object.create(null);
  var installIdCache = '';
  var flushing = false;
  var origFetch = typeof window.fetch === 'function' ? window.fetch.bind(window) : null;

  function readStorage(key) {
    try {
      return window.localStorage ? window.localStorage.getItem(key) : null;
    } catch (e) {
      return null;
    }
  }

  function writeStorage(key, val) {
    try {
      if (window.localStorage) window.localStorage.setItem(key, val);
    } catch (e) {
      /* ignore private-mode / quota errors */
    }
  }

  function randomToken(len) {
    var chars = '0123456789abcdefghijklmnopqrstuvwxyz';
    var out = '';
    try {
      if (window.crypto && window.crypto.getRandomValues) {
        var bytes = new Uint8Array(len);
        window.crypto.getRandomValues(bytes);
        for (var i = 0; i < bytes.length; i++) out += chars[bytes[i] % chars.length];
        return out;
      }
    } catch (e) { /* fallback */ }
    while (out.length < len) out += Math.random().toString(36).slice(2);
    return out.slice(0, len);
  }

  function newEventId() {
    return 'evt_' + Date.now().toString(36) + '_' + randomToken(10);
  }

  function newRequestId() {
    return 'req_' + Date.now().toString(36) + '_' + randomToken(8);
  }

  function getInstallId() {
    if (installIdCache) return installIdCache;
    var stored = readStorage(INSTALL_KEY);
    if (stored && stored.trim()) {
      installIdCache = stored.trim().slice(0, 64);
      return installIdCache;
    }
    installIdCache = 'inst_b_' + Date.now().toString(36) + '_' + randomToken(10);
    writeStorage(INSTALL_KEY, installIdCache);
    return installIdCache;
  }

  function cleanString(value, maxLen) {
    if (value == null) return '';
    return String(value)
      .replace(/(?:\+?98|0)9\d{9}/g, '[PHONE]')
      .replace(/[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}/g, '[EMAIL]')
      .replace(/(bearer\s+)[A-Za-z0-9._\-]{8,}/gi, '$1[REDACTED]')
      .replace(/\beyJ[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{8,}\.[A-Za-z0-9_\-]{6,}\b/g, '[REDACTED]')
      .replace(/([?&](?:sig|signature|token|code|exp|expires|password|key|q|query|search)=)[^&\s]+/gi, '$1[REDACTED]')
      .replace(/\?[^\s"'<>#]+/g, '?[REDACTED]')
      .trim()
      .slice(0, maxLen || 300);
  }

  function normalizeRoute(raw) {
    if (!raw) return '';
    var path = String(raw).split('?')[0].split('#')[0].trim();
    path = path.replace(/\/[0-9a-f]{16,}(?=\/|$)/gi, '/<hex>');
    path = path.replace(/\/\d+(?=\/|$)/g, '/<id>');
    path = path.replace(/^((?:\/site)?(?:\/api\/v1\/books\/|\/books\/|\/book\/))([^/]+)/, '$1<slug>');
    path = path.replace(/^((?:\/site)?(?:\/join\/|\/verify-email\/|\/invite\/))([^/]+)/, '$1<token>');
    return cleanString(path, 200);
  }

  function normalizeOperation(raw) {
    var s = cleanString(raw, 120);
    if (!s) return '';
    var spaceIdx = s.indexOf(' ');
    if (spaceIdx > 0 && s.charAt(spaceIdx + 1) === '/') {
      return (s.slice(0, spaceIdx) + ' ' + normalizeRoute(s.slice(spaceIdx + 1))).slice(0, 80);
    }
    if (s.charAt(0) === '/') return normalizeRoute(s).slice(0, 80);
    return s.slice(0, 80);
  }

  function sanitizeErrorName(value) {
    var s = String(value == null ? '' : value).trim();
    return /^[A-Za-z_][A-Za-z0-9_.]{0,60}$/.test(s) ? s : 'Error';
  }

  function cleanFrameFile(raw) {
    var withoutQuery = String(raw || '').split('?')[0].split('#')[0];
    return cleanString(withoutQuery, 160).slice(-140);
  }

  function parseStackFrameLine(line) {
    var trimmed = String(line || '').trim();
    if (!trimmed) return null;

    var py = /^File\s+"([^"]+)",\s+line\s+(\d+)(?:,\s+in\s+([A-Za-z_][\w.<>]{0,60}))?/.exec(trimmed);
    if (py) {
      var pyFile = cleanFrameFile(py[1]);
      return py[3] ? 'File "' + pyFile + '", line ' + py[2] + ', in ' + py[3] : 'File "' + pyFile + '", line ' + py[2];
    }

    var v8Paren = /^(?:at|in)\s+(?:(?:async|new)\s+)?([A-Za-z_$][\w$.<>]{0,80})\s+\(([^()]+?):(\d+)(?::(\d+))?\)\s*$/.exec(trimmed);
    if (v8Paren) {
      var f1 = cleanFrameFile(v8Paren[2]);
      var loc1 = v8Paren[4] ? f1 + ':' + v8Paren[3] + ':' + v8Paren[4] : f1 + ':' + v8Paren[3];
      return 'at ' + v8Paren[1] + ' (' + loc1 + ')';
    }

    var v8Anon = /^at\s+(?:async\s+)?([^\s()]+?):(\d+)(?::(\d+))?\s*$/.exec(trimmed);
    if (v8Anon) {
      var f2 = cleanFrameFile(v8Anon[1]);
      return v8Anon[3] ? 'at ' + f2 + ':' + v8Anon[2] + ':' + v8Anon[3] : 'at ' + f2 + ':' + v8Anon[2];
    }

    var jsc = /^([A-Za-z_$][\w$.<>]{0,80})?@([^\s@()]+?):(\d+)(?::(\d+))?\s*$/.exec(trimmed);
    if (jsc) {
      var f3 = cleanFrameFile(jsc[2]);
      var loc3 = jsc[4] ? f3 + ':' + jsc[3] + ':' + jsc[4] : f3 + ':' + jsc[3];
      return jsc[1] ? jsc[1] + '@' + loc3 : '@' + loc3;
    }

    return null;
  }

  function sanitizeStack(value) {
    if (!value) return '';
    var lines = String(value).split(/\r?\n/);
    var out = [];
    for (var i = 0; i < lines.length; i++) {
      var parsed = parseStackFrameLine(lines[i]);
      if (parsed) out.push(parsed);
    }
    return out.slice(-14).join('\n').slice(0, 1400);
  }

  function cleanContext(raw) {
    if (!raw || typeof raw !== 'object') return undefined;
    var out = {};
    var hasKeys = false;
    var keys = Object.keys(raw);
    for (var i = 0; i < keys.length; i++) {
      var k = keys[i];
      if (!ALLOWED_CONTEXT_KEYS[k]) continue;
      var v = raw[k];
      if (v === undefined || v === null) continue;
      if (typeof v === 'boolean' || typeof v === 'number') {
        out[k] = v;
        hasKeys = true;
      } else {
        var cleaned =
          k === 'stack'
            ? sanitizeStack(v)
            : k === 'error_name'
              ? sanitizeErrorName(v)
              : k === 'location'
                ? normalizeRoute(v)
                : cleanString(v, 300);
        if (cleaned) {
          out[k] = cleaned;
          hasKeys = true;
        }
      }
    }
    return hasKeys ? out : undefined;
  }

  function addBreadcrumb(type, name, detail) {
    var normType = cleanString(type, 30);
    var normName = normType === 'route' || normType === 'api' ? normalizeOperation(name) : cleanString(name, 80);
    var cleanedDetail = detail ? cleanString(detail, 120) : '';
    var safeDetail = '';
    if (cleanedDetail) {
      safeDetail = /^(?:[A-Za-z0-9_.:=\-/]{1,64}|\[(?:PHONE|EMAIL|REDACTED)\])$/.test(cleanedDetail)
        ? cleanedDetail
        : '[REDACTED]';
    }
    var item = {
      at: new Date().toISOString(),
      type: normType,
      name: normName,
    };
    if (safeDetail) item.detail = safeDetail;
    breadcrumbs.push(item);
    if (breadcrumbs.length > MAX_BREADCRUMBS) {
      breadcrumbs.splice(0, breadcrumbs.length - MAX_BREADCRUMBS);
    }
  }

  function readQueue() {
    var raw = readStorage(OUTBOX_KEY);
    if (!raw) return [];
    try {
      var parsed = JSON.parse(raw);
      return Array.isArray(parsed) ? parsed : [];
    } catch (e) {
      return [];
    }
  }

  function writeQueue(items) {
    var now = Date.now();
    var kept = [];
    for (var i = 0; i < items.length; i++) {
      var it = items[i];
      if (it && typeof it === 'object' && now - (it.created_at_ms || now) <= MAX_AGE_MS) {
        kept.push(it);
      }
    }
    if (kept.length > MAX_QUEUE) kept = kept.slice(-MAX_QUEUE);
    writeStorage(OUTBOX_KEY, JSON.stringify(kept));
  }

  function shouldSkipDuplicate(key) {
    var now = Date.now();
    var prev = recentDedupe[key];
    if (prev && now - prev < 5000) return true;
    recentDedupe[key] = now;
    var keys = Object.keys(recentDedupe);
    if (keys.length > 40) {
      for (var i = 0; i < keys.length; i++) {
        if (now - recentDedupe[keys[i]] >= 5000) delete recentDedupe[keys[i]];
      }
    }
    return false;
  }

  function buildTitleAndObserved(kind, code, ctx) {
    var errName = (ctx && ctx.error_name) || 'Error';
    var statusCode = (ctx && ctx.status_code) || 500;
    if (kind === 'network') {
      if (code === 'fetch_network_error') {
        return {
          title: 'خطای شبکه در درخواست مرورگر',
          expected: 'درخواست مرورگر به سرور برسد و پاسخ بگیرد.',
          observed: 'درخواست شبکه با خطا متوقف شد (' + errName + ').',
        };
      }
      return {
        title: 'پاسخ خطای سرور (' + statusCode + ')',
        expected: 'درخواست صفحه یا پنل بدون خطای ۵۰۰ پاسخ داده شود.',
        observed: 'سرور وضعیت ' + statusCode + ' برگرداند.',
      };
    }
    if (code === 'asset_load_error') {
      return {
        title: 'خطا در بارگذاری فایل اسکریپت یا استایل صفحه',
        expected: 'فایل‌های ایستا در مرورگر بدون خطا بارگذاری شوند.',
        observed: 'بارگذاری یکی از فایل‌های ایستا با شکست مواجه شد.',
      };
    }
    if (code === 'unhandled_rejection') {
      return {
        title: 'وعدهٔ مدیریت‌نشده (' + errName + ')',
        expected: 'همهٔ عملیات ناهم‌زمان خطاها را مدیریت کنند.',
        observed: 'وعدهٔ ناهم‌زمان مدیریت‌نشده (' + errName + ') رخ داد.',
      };
    }
    return {
      title: 'خطای اجرای جاوااسکریپت: ' + errName,
      expected: 'اسکریپت صفحه بدون خطای مهارنشده اجرا شود.',
      observed: 'خطای مهارنشدهٔ جاوااسکریپت (' + errName + ') رخ داد.',
    };
  }

  function report(input) {
    try {
      var kind = input.kind || 'client_error';
      var code = cleanString(input.code || 'js_error', 80) || 'js_error';
      var ctx = cleanContext(input.context);
      var copy = buildTitleAndObserved(kind, code, ctx);
      var event = {
        event_id: newEventId(),
        kind: kind,
        severity: input.severity || 'error',
        code: code,
        title: copy.title,
        route: normalizeRoute(input.route || (window.location && window.location.pathname) || '/'),
        operation: normalizeOperation(input.operation || ''),
        expected: copy.expected,
        observed: copy.observed,
        request_id: cleanString(input.request_id || '', 64),
        install_id: getInstallId(),
        platform: PLATFORM,
        channel: CHANNEL,
        app_build: APP_BUILD || undefined,
        session_tag: SESSION_TAG,
        is_offline: typeof navigator !== 'undefined' && navigator.onLine === false,
        breadcrumbs: breadcrumbs.length ? breadcrumbs.slice() : undefined,
        context: ctx,
        created_at_ms: Date.now(),
      };
      var q = readQueue();
      q.push(event);
      writeQueue(q);
      if (typeof navigator === 'undefined' || navigator.onLine !== false) {
        window.setTimeout(flush, 0);
      }
      return event.event_id;
    } catch (e) {
      return null;
    }
  }

  function isMatchingSessionEvent(ev) {
    return Boolean(SESSION_TAG && ev && (ev.session_tag || '') === SESSION_TAG);
  }

  function flush() {
    if (flushing || !origFetch) return;
    if (typeof navigator !== 'undefined' && navigator.onLine === false) return;
    var items = readQueue();
    if (!items.length) return;

    flushing = true;
    var batchMatchesSession = isMatchingSessionEvent(items[0]);
    var batch = [];
    var sentIds = Object.create(null);
    for (var i = 0; i < items.length && batch.length < 20; i++) {
      if (isMatchingSessionEvent(items[i]) === batchMatchesSession) {
        batch.push(items[i]);
        sentIds[items[i].event_id] = true;
      }
    }

    var shouldRetryRemaining = false;
    origFetch(ENDPOINT, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'X-App-Platform': PLATFORM,
        'X-App-Channel': CHANNEL,
        'X-App-Install-Id': getInstallId(),
      },
      // Never attach session cookies to queued events whose capture-time session does not match the current page.
      credentials: batchMatchesSession ? 'same-origin' : 'omit',
      keepalive: true,
      body: JSON.stringify({ events: batch }),
    })
      .then(function (resp) {
        if (resp.ok || (resp.status >= 400 && resp.status < 500 && resp.status !== 429 && resp.status !== 401 && resp.status !== 408)) {
          var remaining = readQueue().filter(function (x) { return !sentIds[x.event_id]; });
          writeQueue(remaining);
          shouldRetryRemaining = remaining.length > 0;
        }
      })
      .catch(function () {
        /* keep queued with fixed event_id; never spawn secondary diagnostics */
      })
      .then(function () {
        flushing = false;
        if (shouldRetryRemaining) window.setTimeout(flush, 0);
      });
  }

  // Initial normalized route breadcrumb
  try {
    addBreadcrumb('route', (window.location && window.location.pathname) || '/');
  } catch (e) { /* ignore */ }

  // Capture runtime JS errors AND same-origin static <script>/<link> load failures (capture phase).
  window.addEventListener(
    'error',
    function (ev) {
      try {
        var target = ev && ev.target;
        if (target && target !== window && target.tagName) {
          var tag = String(target.tagName).toUpperCase();
          if (tag === 'SCRIPT' || tag === 'LINK') {
            var assetUrl = target.src || target.href || '';
            if (!assetUrl) return;
            var parsed = new URL(assetUrl, window.location.href);
            if (parsed.origin !== window.location.origin) return;
            var loc = normalizeRoute(parsed.pathname);
            if (shouldSkipDuplicate('asset:' + loc)) return;
            report({
              kind: 'client_error',
              severity: 'error',
              code: 'asset_load_error',
              operation: 'load_' + tag.toLowerCase(),
              context: { error_name: tag + 'LoadError', location: loc },
            });
            return;
          }
        }
        var err = ev && ev.error instanceof Error ? ev.error : null;
        var errName = sanitizeErrorName((err && err.name) || 'Error');
        var stack = sanitizeStack(err && err.stack);
        var topFrame = (stack.split('\n')[0] || (ev && ev.filename ? cleanFrameFile(ev.filename) + ':' + (ev.lineno || 0) : '')).slice(0, 80);
        if (!stack && ev && ev.filename) {
          stack = 'at ' + cleanFrameFile(ev.filename) + ':' + (ev.lineno || 0) + (ev.colno ? ':' + ev.colno : '');
        }
        if (shouldSkipDuplicate('js:' + errName + ':' + topFrame)) return;
        report({
          kind: 'client_error',
          severity: 'error',
          code: 'js_error',
          context: { error_name: errName, stack: stack },
        });
      } catch (e) { /* ignore */ }
    },
    true,
  );

  window.addEventListener('unhandledrejection', function (ev) {
    try {
      var reason = ev && ev.reason;
      var err = reason instanceof Error ? reason : null;
      var errName = sanitizeErrorName((err && err.name) || 'PromiseRejection');
      var stack = sanitizeStack(err && err.stack);
      var topFrame = (stack.split('\n')[0] || '').slice(0, 80);
      if (shouldSkipDuplicate('rej:' + errName + ':' + topFrame)) return;
      report({
        kind: 'client_error',
        severity: 'error',
        code: 'unhandled_rejection',
        context: { error_name: errName, stack: stack },
      });
    } catch (e) { /* ignore */ }
  });

  // Wrap same-origin fetch (string, URL, or Request) to attach correlation headers and capture 5xx / network drops.
  if (origFetch) {
    window.fetch = function (input, init) {
      var parsed = null;
      var isSameOrigin = false;
      var isDiag = false;
      var isRequest = typeof Request !== 'undefined' && input instanceof Request;
      var method = 'GET';
      var reqId = '';

      try {
        var rawUrl =
          typeof input === 'string'
            ? input
            : input && typeof input.url === 'string'
              ? input.url
              : input && typeof input.href === 'string'
                ? input.href
                : String(input || '');
        parsed = new URL(rawUrl, window.location.href);
        isSameOrigin = parsed.origin === window.location.origin;
        isDiag = parsed.pathname.indexOf('/api/v1/diagnostics/') === 0;
        method = String((init && init.method) || (isRequest && input.method) || 'GET').toUpperCase();
      } catch (e) {
        isSameOrigin = false;
      }

      if (!isSameOrigin || isDiag) {
        return origFetch(input, init);
      }

      reqId = newRequestId();
      var callInput = input;
      var callInit = init;
      try {
        var hasInitHeaders = Boolean(init && 'headers' in init && init.headers !== undefined);
        var hdrs = new Headers(hasInitHeaders ? init.headers : isRequest ? input.headers : undefined);
        if (hdrs.has('X-Request-Id')) reqId = hdrs.get('X-Request-Id') || reqId;
        else hdrs.set('X-Request-Id', reqId);
        if (!hdrs.has('X-App-Platform')) hdrs.set('X-App-Platform', PLATFORM);
        if (!hdrs.has('X-App-Channel')) hdrs.set('X-App-Channel', CHANNEL);
        if (!hdrs.has('X-App-Install-Id')) hdrs.set('X-App-Install-Id', getInstallId());

        if (isRequest) {
          callInput = new Request(input, { headers: hdrs });
          if (init) {
            callInit = Object.assign({}, init);
            delete callInit.headers;
          }
        } else {
          callInit = Object.assign({}, init || {}, { headers: hdrs });
        }
      } catch (e) { /* fall back to original args */ }

      var normPath = normalizeRoute(parsed.pathname);
      return origFetch(callInput, callInit).then(
        function (resp) {
          addBreadcrumb('api', method + ' ' + normPath, String(resp.status));
          if (resp.status >= 500) {
            var srvReqId = (resp.headers && resp.headers.get('X-Request-Id')) || reqId;
            if (!shouldSkipDuplicate('5xx:' + resp.status + ':' + normPath)) {
              report({
                kind: 'network',
                severity: 'error',
                code: 'api_5xx',
                route: normPath,
                operation: method + ' ' + normPath,
                request_id: srvReqId,
                context: { status_code: resp.status, method: method },
              });
            }
          }
          return resp;
        },
        function (err) {
          addBreadcrumb('api', method + ' ' + normPath, 'network_error');
          var errName = sanitizeErrorName(err && err.name);
          if (errName !== 'AbortError' && (typeof navigator === 'undefined' || navigator.onLine !== false)) {
            if (!shouldSkipDuplicate('net:' + method + ':' + normPath)) {
              report({
                kind: 'network',
                severity: 'warning',
                code: 'fetch_network_error',
                route: normPath,
                operation: method + ' ' + normPath,
                request_id: reqId,
                context: { method: method, error_name: errName },
              });
            }
          }
          throw err;
        },
      );
    };
  }

  window.addEventListener('online', flush);
  window.addEventListener('pageshow', flush);
  if (document.readyState === 'complete') {
    window.setTimeout(flush, 50);
  } else {
    window.addEventListener('load', function () {
      window.setTimeout(flush, 50);
    });
  }

  window.__limoBrowserDiag = {
    flush: flush,
    pendingCount: function () { return readQueue().length; },
  };
})();
