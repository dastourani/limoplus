"""One shelf per major, holding that major's books, so the home page looks as before until the shelves are edited.
Reverse removes the shelves named after a major (shelves are layout, not user data)."""

from django.db import migrations


def forwards(apps, schema_editor):
    Major = apps.get_model("catalog", "Major")
    Shelf = apps.get_model("catalog", "Shelf")
    ShelfBook = apps.get_model("catalog", "ShelfBook")
    ContentNode = apps.get_model("catalog", "ContentNode")
    for i, major in enumerate(Major.objects.order_by("order", "name")):
        books = ContentNode.objects.filter(kind="book", depth=1, majors=major).order_by("path")
        if not books.exists():
            continue
        shelf = Shelf.objects.create(title=major.name, order=i)
        for j, book in enumerate(books):
            ShelfBook.objects.create(shelf=shelf, book=book, order=j)


def backwards(apps, schema_editor):
    Shelf = apps.get_model("catalog", "Shelf")
    Major = apps.get_model("catalog", "Major")
    Shelf.objects.filter(title__in=list(Major.objects.values_list("name", flat=True))).delete()


class Migration(migrations.Migration):
    dependencies = [("catalog", "0010_shelves_and_banner_audience")]
    operations = [migrations.RunPython(forwards, backwards)]
