from whitenoise.storage import CompressedManifestStaticFilesStorage


class StaticStorage(CompressedManifestStaticFilesStorage):
    """Hashed, compressed static files (WhiteNoise). A file missing from the manifest gets its plain name instead of
    an error page, so a page never fails only because `collectstatic` has not caught up."""

    manifest_strict = False
