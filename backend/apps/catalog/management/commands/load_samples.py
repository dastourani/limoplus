from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError

from apps.catalog.importer import import_file
from apps.catalog.models import Banner, ContentNode, Major
from apps.catalog.zipdir import zip_chapter_dir

SAMPLES = Path(settings.BASE_DIR).parent / "content" / "samples"

MAJORS = [
    ("economics", "اقتصاد", "#4A54C9", False, 1),
    ("biomedical-engineering", "مهندسی پزشکی", "#1A8A80", False, 2),
    ("dentistry", "دندانپزشکی", "#D0652A", True, 3),
    ("psychology", "روانشناسی", "#8A4FA8", True, 4),
]


class Command(BaseCommand):
    help = "Create sample majors, banners and the sample books from content/samples (safe to run again)."

    def handle(self, **options):
        if not SAMPLES.is_dir():
            raise CommandError(f"Sample folder not found: {SAMPLES}")
        for slug, name, color, soon, order in MAJORS:
            Major.objects.update_or_create(slug=slug, defaults={"name": name, "color": color, "is_coming_soon": soon, "order": order})

        for chapter_dir in sorted(p for p in SAMPLES.glob("*/*") if (p / "chapter.md").is_file()):
            chapter, result = import_file(f"{chapter_dir.name}.zip", zip_chapter_dir(chapter_dir), publish=True)
            if chapter.errors:
                for issue in chapter.errors:
                    self.stdout.write(self.style.ERROR(f"{chapter_dir}: {issue}"))
                raise CommandError("Sample content has errors.")
            self.stdout.write(self.style.SUCCESS(f"{result.book.title} › {result.chapter.title}: {result.summary()}"))

        from apps.commerce.models import Plan

        # Starting prices (toman); change them any time in the admin.
        for order, (title, scope, months, price) in enumerate(
            [("اشتراک ماهانه‌ی رشته", "major", 1, 149_000), ("اشتراک سه‌ماهه‌ی رشته", "major", 3, 369_000), ("اشتراک ماهانه‌ی همه‌ی رشته‌ها", "all", 1, 249_000)]
        ):
            Plan.objects.get_or_create(title=title, defaults={"scope": scope, "months": months, "price": price, "order": order})
        book = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, slug="math-1").first()
        if book and not book.price:
            book.price = 249_000
            book.save(update_fields=["price"])

        Banner.objects.get_or_create(
            title="۳۰٪ تخفیف ریاضی عمومی ۱",
            defaults={"subtitle": "فقط تا آخر هفته", "link": "book/math-1", "priority": 2},
        )
        Banner.objects.get_or_create(
            title="فصل اول رایگان است",
            defaults={"subtitle": "حد و پیوستگی را همین حالا بخوانید", "link": "book/math-1", "priority": 1},
        )
        self.stdout.write(self.style.SUCCESS("Sample data is ready."))
