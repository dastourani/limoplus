"""
A book's own line drawing for its cover (motif «طرح سفارشی»): an uploaded SVG is reduced to plain shapes, and its
colours are replaced by placeholders (@L@ for lines and fills) so the cover paints it lemon on dark or ink on light,
like the built-in motifs. Nothing else from the file survives: no scripts, styles, links, text or images.
"""

from __future__ import annotations

import json
import re
import xml.etree.ElementTree as ET

MAX_BYTES = 200 * 1024
MAX_SHAPES = 600
SHAPES = {"path", "circle", "ellipse", "rect", "line", "polyline", "polygon"}
GROUPS = {"svg", "g"}
GEOMETRY = {"d", "cx", "cy", "r", "rx", "ry", "x", "y", "width", "height", "x1", "y1", "x2", "y2", "points", "transform"}
_NUMBER = re.compile(r"^[\d\s.,eE+\-]+$")
_SAFE = re.compile(r"^[\w\s.,()+\-#%]*$")


class DrawingError(ValueError):
    pass


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _style(el) -> dict:
    out = {}
    for part in (el.get("style") or "").split(";"):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _paint(value: str | None) -> str | None:
    if value is None:
        return None
    v = value.strip().lower()
    return "none" if v in ("none", "transparent", "") else "on"


def clean_svg(data: bytes) -> dict:
    """{"viewBox": "...", "body": "<path …/>…"} or DrawingError."""
    if len(data) > MAX_BYTES:
        raise DrawingError("فایل طرح بیشتر از ۲۰۰ کیلوبایت است.")
    text = data.decode("utf-8", errors="replace")
    if re.search(r"<!(DOCTYPE|ENTITY)", text, re.IGNORECASE):
        raise DrawingError("این SVG بخش DOCTYPE یا ENTITY دارد و پذیرفته نمی‌شود.")
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        raise DrawingError("فایل SVG خراب است یا باز نمی‌شود.")
    if _local(root.tag) != "svg":
        raise DrawingError("فایل باید SVG باشد.")
    view_box = (root.get("viewBox") or "").strip()
    if not view_box and root.get("width") and root.get("height"):
        w, h = (re.sub(r"[^\d.]", "", root.get(k)) for k in ("width", "height"))
        view_box = f"0 0 {w} {h}"
    if not _NUMBER.match(view_box or "x") or len(view_box.replace(",", " ").split()) != 4:
        raise DrawingError("SVG باید viewBox داشته باشد (مثلاً 0 0 24 24).")

    shapes: list[str] = []

    def walk(el, stroke, fill, width):
        tag = _local(el.tag)
        st = _style(el)
        stroke = _paint(st.get("stroke", el.get("stroke"))) or stroke
        fill = _paint(st.get("fill", el.get("fill"))) or fill
        width = st.get("stroke-width", el.get("stroke-width")) or width
        if tag in GROUPS:
            transform = el.get("transform") if tag == "g" else None
            if transform and not _SAFE.match(transform):
                transform = None
            inner_start = len(shapes)
            for child in el:
                walk(child, stroke, fill, width)
            if transform and len(shapes) > inner_start:
                shapes[inner_start:] = [f'<g transform="{transform}">' + "".join(shapes[inner_start:]) + "</g>"]
            return
        if tag not in SHAPES:
            return  # text, images, scripts, styles, links … are dropped
        if len(shapes) >= MAX_SHAPES:
            raise DrawingError(f"طرح بیشتر از {MAX_SHAPES} شکل دارد؛ ساده‌ترش کنید.")
        attrs = []
        for key in GEOMETRY:
            value = el.get(key)
            if value is None:
                continue
            if key == "d":
                if not re.match(r"^[MmLlHhVvCcSsQqTtAaZz\d\s.,eE+\-]+$", value):
                    continue
            elif not _SAFE.match(value):
                continue
            attrs.append(f'{key}="{value}"')
        s = stroke or "none"
        f = fill or ("on" if stroke in (None, "none") else "none")  # SVG's default fill is black
        attrs.append(f'stroke="{"@L@" if s == "on" else "none"}"')
        attrs.append(f'fill="{"@L@" if f == "on" else "none"}"')
        if width and _NUMBER.match(str(width)):
            attrs.append(f'stroke-width="{width}"')
        shapes.append(f"<{tag} " + " ".join(sorted(attrs)) + "/>")

    walk(root, None, None, None)
    if not shapes:
        raise DrawingError("در این SVG هیچ شکلی (خط، مسیر، دایره …) پیدا نشد.")
    return {"viewBox": " ".join(view_box.replace(",", " ").split()), "body": "".join(shapes)}


def dumps(drawing: dict | None) -> str:
    return json.dumps(drawing, ensure_ascii=False) if drawing else ""


def loads(text: str) -> dict | None:
    try:
        value = json.loads(text) if text else None
    except ValueError:
        return None
    return value if isinstance(value, dict) and value.get("body") else None
