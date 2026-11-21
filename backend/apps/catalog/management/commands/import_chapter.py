from pathlib import Path

from django.core.management.base import BaseCommand, CommandError

from apps.catalog.importer import import_file
from apps.catalog.zipdir import zip_chapter_dir


class Command(BaseCommand):
    help = "Import a chapter from a .md file, a .zip, or a folder containing chapter.md and images/."

    def add_arguments(self, parser):
        parser.add_argument("path")
        parser.add_argument("--publish", action="store_true", help="Publish immediately")
        parser.add_argument("--dry-run", action="store_true", help="Only check the file")

    def handle(self, path, publish, dry_run, **options):
        p = Path(path)
        if p.is_dir():
            name, data = f"{p.name}.zip", zip_chapter_dir(p)
        elif p.is_file():
            name, data = p.name, p.read_bytes()
        else:
            raise CommandError(f"Not found: {path}")
        chapter, result = import_file(name, data, publish=publish, dry_run=dry_run)
        for issue in chapter.warnings:
            self.stdout.write(self.style.WARNING(f"هشدار · {issue}"))
        for issue in chapter.errors:
            self.stdout.write(self.style.ERROR(f"خطا · {issue}"))
        if chapter.errors:
            raise CommandError(f"{len(chapter.errors)} error(s); nothing was imported.")
        if result:
            self.stdout.write(self.style.SUCCESS(f"{result.chapter.title}: {result.summary()}"))
        else:
            self.stdout.write(self.style.SUCCESS("فایل بدون خطاست."))
