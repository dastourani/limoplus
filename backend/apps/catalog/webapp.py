"""
The web version of the app, served by this same server at its root (http://<server>:8000/), for trying changes on the
laptop (or a phone on the same Wi-Fi) without building an APK. `update.bat` puts the latest build (made by GitHub from
every change, branch «web-build») in the folder WEBAPP_DIR. Without that folder this page explains what to do.
"""

import mimetypes
from pathlib import Path

from django.conf import settings
from django.http import FileResponse, Http404, HttpResponse
from django.utils._os import safe_join


def webapp(request, path=""):
    root = Path(settings.WEBAPP_DIR)
    index = root / "index.html"
    if not index.is_file():
        return HttpResponse(
            "<html dir=rtl lang=fa><meta charset=utf-8><body style='font-family:Tahoma;padding:24px'>"
            "<h2>نسخه‌ی وب اپ هنوز اینجا نیست</h2><p>یک بار <b>update.bat</b> را اجرا کنید تا آخرین نسخه‌ی وب گرفته شود.</p>"
            "</body></html>",
            status=404,
        )
    try:
        file = Path(safe_join(str(root), path)) if path else index
    except Exception:
        raise Http404
    if not file.is_file():
        file = index  # a page of the app (e.g. /book/math-1): the app finds its own way from index.html
    kind, _ = mimetypes.guess_type(str(file))
    response = FileResponse(open(file, "rb"), content_type=kind or "application/octet-stream")
    # The page itself always fresh, so a new build shows at once; its files have content-hashed names.
    response["Cache-Control"] = "no-cache" if file == index else "public, max-age=31536000, immutable"
    return response
