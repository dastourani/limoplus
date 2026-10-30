import io
import zipfile
from pathlib import Path


def zip_chapter_dir(directory: Path) -> bytes:
    """Pack a chapter folder (chapter.md + images/) into ZIP bytes, as an admin would upload it."""
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(directory.rglob("*")):
            if path.is_file():
                archive.write(path, path.relative_to(directory).as_posix())
    return buffer.getvalue()
