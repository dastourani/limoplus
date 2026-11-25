import math
"""{% icon "name" size %}: the app's icons (Lucide, ISC licence) as inline SVG, in the colour of the text around them."""
from django import template
from django.utils.safestring import mark_safe

register = template.Library()

ICONS = {
            "sparkles": "<path d=\"m12 3-1.912 5.813a2 2 0 0 1-1.275 1.275L3 12l5.813 1.912a2 2 0 0 1 1.275 1.275L12 21l1.912-5.813a2 2 0 0 1 1.275-1.275L21 12l-5.813-1.912a2 2 0 0 1-1.275-1.275L12 3Z\"/><path d=\"M5 3v4\"/><path d=\"M19 17v4\"/><path d=\"M3 5h4\"/><path d=\"M17 19h4\"/>",
    "house": "<path d=\"M15 21v-8a1 1 0 0 0-1-1h-4a1 1 0 0 0-1 1v8\"/><path d=\"M3 10a2 2 0 0 1 .709-1.528l7-5.999a2 2 0 0 1 2.582 0l7 5.999A2 2 0 0 1 21 10v9a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z\"/>",
    "library-big": "<rect width=\"8\" height=\"18\" x=\"3\" y=\"3\" rx=\"1\"/><path d=\"m16 8 1.83 11.2a1 1 0 0 1-.83 1.15l-1.97.32a1 1 0 0 1-1.15-.83L12 8\"/><path d=\"M7 3v18\"/><path d=\"M20.4 3.7A2 2 0 0 0 18.5 2H18a2 2 0 0 0-1.8 1.1L12.5 12\"/>",
    "circle-user-round": "<path d=\"M18 20a6 6 0 0 0-12 0\"/><circle cx=\"12\" cy=\"10\" r=\"4\"/><circle cx=\"12\" cy=\"12\" r=\"10\"/>",
    "wifi": "<path d=\"M12 20h.01\"/><path d=\"M2 8.82a15 15 0 0 1 20 0\"/><path d=\"M5 12.859a10 10 0 0 1 14 0\"/><path d=\"M8.5 16.429a5 5 0 0 1 7 0\"/>",
    "battery-medium": "<rect width=\"16\" height=\"10\" x=\"2\" y=\"7\" rx=\"2\"/><line x1=\"22\" x2=\"22\" y1=\"11\" y2=\"13\"/><line x1=\"6\" x2=\"6\" y1=\"11\" y2=\"13\"/><line x1=\"10\" x2=\"10\" y1=\"11\" y2=\"13\"/>",
    "download": "<path d=\"M12 15V3\"/><path d=\"M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4\"/><path d=\"m7 10 5 5 5-5\"/>",
    "book-open": "<path d=\"M12 5v16\"/><path d=\"M20.001 19A2 2 0 0022 17V5a2 2 0 00-1.999-2L16 3.002A5 5 0 0012 5a5 5 0 00-4-2H4a2 2 0 00-2 2v12a2 2 0 001.999 2H8a5 5 0 014 2 5 5 0 014-2z\"/>",
    "calendar": "<path d=\"M8 2v4\"/><path d=\"M16 2v4\"/><rect width=\"18\" height=\"18\" x=\"3\" y=\"4\" rx=\"2\"/><path d=\"M3 10h18\"/>",
    "circle-check": "<circle cx=\"12\" cy=\"12\" r=\"10\"/><path d=\"m16 9-5.5 5.5L8 12\"/>",
    "list-checks": "<path d=\"M13 5h8\"/><path d=\"M13 12h8\"/><path d=\"M13 19h8\"/><path d=\"m3 17 2 2 4-4\"/><path d=\"m3 7 2 2 4-4\"/>",
    "layers": "<path d=\"M12.83 2.18a2 2 0 0 0-1.66 0L2.6 6.08a1 1 0 0 0 0 1.83l8.58 3.91a2 2 0 0 0 1.66 0l8.58-3.9a1 1 0 0 0 0-1.83z\"/><path d=\"M2 12a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 12\"/><path d=\"M2 17a1 1 0 0 0 .58.91l8.6 3.91a2 2 0 0 0 1.65 0l8.58-3.9A1 1 0 0 0 22 17\"/>",
    "chart-column": "<path d=\"M3 3v16a2 2 0 0 0 2 2h16\"/><path d=\"M18 17V9\"/><path d=\"M13 17V5\"/><path d=\"M8 17v-3\"/>",
    "tag": "<path d=\"M12.586 2.586A2 2 0 0 0 11.172 2H4a2 2 0 0 0-2 2v7.172a2 2 0 0 0 .586 1.414l8.704 8.704a2.426 2.426 0 0 0 3.42 0l6.58-6.58a2.426 2.426 0 0 0 0-3.42z\"/><circle cx=\"7.5\" cy=\"7.5\" r=\".5\" fill=\"currentColor\"/>",
    "gift": "<path d=\"M12 7v14\"/><path d=\"M20 11v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8\"/><path d=\"M7.5 7a1 1 0 0 1 0-5A4.8 8 0 0 1 12 7a4.8 8 0 0 1 4.5-5 1 1 0 0 1 0 5\"/><rect x=\"3\" y=\"7\" width=\"18\" height=\"4\" rx=\"1\"/>",
    "bell": "<path d=\"M10.268 21a2 2 0 0 0 3.464 0\"/><path d=\"M3.262 15.326A1 1 0 0 0 4 17h16a1 1 0 0 0 .74-1.673C19.41 13.956 18 12.499 18 8A6 6 0 0 0 6 8c0 4.499-1.411 5.956-2.738 7.326\"/>",
    "lock": "<rect width=\"18\" height=\"11\" x=\"3\" y=\"11\" rx=\"2\" ry=\"2\"/><path d=\"M7 11V7a5 5 0 0 1 10 0v4\"/>",
    "lock-open": "<rect width=\"18\" height=\"11\" x=\"3\" y=\"11\" rx=\"2\" ry=\"2\"/><path d=\"M7 11V7a5 5 0 0 1 9.9-1\"/>",
    "smartphone": "<rect width=\"14\" height=\"20\" x=\"5\" y=\"2\" rx=\"2\" ry=\"2\"/><path d=\"M12 18h.01\"/>",
    "monitor-smartphone": "<path d=\"M18 8V6a2 2 0 0 0-2-2H4a2 2 0 0 0-2 2v7a2 2 0 0 0 2 2h8\"/><path d=\"M10 19v-3.96 3.15\"/><path d=\"M7 19h5\"/><rect width=\"6\" height=\"10\" x=\"16\" y=\"12\" rx=\"2\"/>",
    "share-2": "<circle cx=\"18\" cy=\"5\" r=\"3\"/><circle cx=\"6\" cy=\"12\" r=\"3\"/><circle cx=\"18\" cy=\"19\" r=\"3\"/><line x1=\"8.59\" x2=\"15.42\" y1=\"13.51\" y2=\"17.49\"/><line x1=\"15.41\" x2=\"8.59\" y1=\"6.51\" y2=\"10.49\"/>",
    "check": "<path d=\"M20 6 9 17l-5-5\"/>",
    "play": "<path d=\"M5 5a2 2 0 0 1 3.008-1.728l11.997 6.998a2 2 0 0 1 .003 3.458l-12 7A2 2 0 0 1 5 19z\"/>",
    "chevron-left": "<path d=\"m15 18-6-6 6-6\"/>",
    "timer": "<line x1=\"10\" x2=\"14\" y1=\"2\" y2=\"2\"/><line x1=\"12\" x2=\"15\" y1=\"14\" y2=\"11\"/><circle cx=\"12\" cy=\"14\" r=\"8\"/>",
    "repeat": "<path d=\"m17 2 4 4-4 4\"/><path d=\"M3 11v-1a4 4 0 0 1 4-4h14\"/><path d=\"m7 22-4-4 4-4\"/><path d=\"M21 13v1a4 4 0 0 1-4 4H3\"/>",
    "notebook-pen": "<path d=\"M13.4 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-7.4\"/><path d=\"M2 6h4\"/><path d=\"M2 10h4\"/><path d=\"M2 14h4\"/><path d=\"M2 18h4\"/><path d=\"M21.378 5.626a1 1 0 1 0-3.004-3.004l-5.01 5.012a2 2 0 0 0-.506.854l-.837 2.87a.5.5 0 0 0 .62.62l2.87-.837a2 2 0 0 0 .854-.506z\"/>",
    "wifi-off": "<path d=\"M12 20h.01\"/><path d=\"M8.5 16.429a5 5 0 0 1 7 0\"/><path d=\"M5 12.859a10 10 0 0 1 5.17-2.69\"/><path d=\"M19 12.859a10 10 0 0 0-2.007-1.523\"/><path d=\"M2 8.82a15 15 0 0 1 4.177-2.643\"/><path d=\"M22 8.82a15 15 0 0 0-11.288-3.764\"/><path d=\"m2 2 20 20\"/>",
    "search": "<path d=\"m21 21-4.34-4.34\"/><circle cx=\"11\" cy=\"11\" r=\"8\"/>",
    "graduation-cap": "<path d=\"M21.42 10.922a1 1 0 0 0-.019-1.838L12.83 5.18a2 2 0 0 0-1.66 0L2.6 9.08a1 1 0 0 0 0 1.832l8.57 3.908a2 2 0 0 0 1.66 0z\"/><path d=\"M22 10v6\"/><path d=\"M6 12.5V16a6 3 0 0 0 12 0v-3.5\"/>",
    "message-circle": "<path d=\"M7.9 20A9 9 0 1 0 4 16.1L2 22Z\"/>",
    "mail": "<rect width=\"20\" height=\"16\" x=\"2\" y=\"4\" rx=\"2\"/><path d=\"m22 7-8.97 5.7a1.94 1.94 0 0 1-2.06 0L2 7\"/>",
    "corner-down-left": "<polyline points=\"9 10 4 15 9 20\"/><path d=\"M20 4v7a4 4 0 0 1-4 4H4\"/>",
}


@register.simple_tag
def icon(name, size=20, width=2):
    body = ICONS.get(name, "")
    return mark_safe(
        f'<svg class="i" width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="{width}" '
        f'stroke-linecap="round" stroke-linejoin="round" aria-hidden="true">{body}</svg>'
    )


def _point(r, deg):
    a = (deg - 90) * math.pi / 180
    return f"{r * math.cos(a):.2f} {r * math.sin(a):.2f}"

def _wedge_path(i, n, outer=76):
    step = 360 / n
    a0 = i * step
    a1 = (i + 1) * step
    large = 1 if (a1 - a0) > 180 else 0
    return f"M 0 0 L {_point(outer, a0)} A {outer} {outer} 0 {large} 1 {_point(outer, a1)} Z"

@register.simple_tag
def lemon_progress(segments=8, size=44, fill="#FFC414"):
    """Renders the signature Limokhan lemon with N juicy wedges matching LemonProgress in the app."""
    try:
        n = int(segments)
    except (ValueError, TypeError):
        n = 8
    n = max(1, min(24, n))
    stroke_w = 3.5 if n > 16 else (4.5 if n > 8 else 6)
    
    wedges_html = []
    # If 1 section, render 8 wedges so it always looks like a full natural lemon
    render_n = 8 if n == 1 else n
    for i in range(render_n):
        path = _wedge_path(i, render_n)
        wedges_html.append(f'<path d="{path}" fill="{fill}" stroke="#fff" stroke-width="{stroke_w}" stroke-linejoin="round"/>')
    
    body = "".join(wedges_html)
    return mark_safe(
        f'<svg class="lemon-progress-icon" width="{size}" height="{size}" viewBox="-100 -100 200 200" aria-hidden="true">'
        f'<circle r="98" fill="#F5C518"/>'
        f'<circle r="98" fill="none" stroke="#E0AE0B" stroke-width="3"/>'
        f'<circle r="87" fill="#fff"/>'
        f'<g>{body}</g>'
        f'<circle r="9" fill="#fff"/>'
        f'</svg>'
    )
