/* Panel lists (tests, flashcards): formulas in the short texts drawn with the app's own renderer
   (catalog/limo-preview.js), each kept left to right inside the Persian line. Without it the $…$ text stays. */
(function () {
  function esc(t) {
    return String(t).replace(/[&<>"]/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]; });
  }

  function draw(P, text) {
    var out = '';
    var re = /\$\$([\s\S]+?)\$\$|\$([^$]+)\$/g;
    var last = 0, m;
    while ((m = re.exec(text))) {
      out += esc(text.slice(last, m.index));
      var src = m[1] || m[2];
      var html;
      try { html = P.mathHtml(src, false); } catch (e) { html = esc(m[0]); }
      out += '<span class="lp-f" dir="ltr">' + html + '</span>';
      last = re.lastIndex;
    }
    return out + esc(text.slice(last));
  }

  function start() {
    var P = window.LimoPreview;
    if (!P || !P.mathHtml) return;
    var m = document.getElementById('limo-macros');
    if (m && P.setMacros) { try { P.setMacros(JSON.parse(m.textContent)); } catch (e) { /* ignore */ } }
    document.querySelectorAll('.lp-tex').forEach(function (el) {
      el.innerHTML = draw(P, el.textContent);
    });
  }

  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', start);
  else start();
})();
