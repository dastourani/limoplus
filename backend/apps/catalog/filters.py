"""List filters shared by the panel's section, question and flashcard lists: book, then chapter, by tree path."""

from django.contrib import admin

from .models import ContentNode


def _book_choices():
    return [(str(b.pk), b.title) for b in ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1).order_by("title")]


class BookFilter(admin.SimpleListFilter):
    title = "کتاب"
    parameter_name = "book"
    path_field = "path"

    def lookups(self, request, model_admin):
        return _book_choices()

    def queryset(self, request, queryset):
        if self.value():
            book = ContentNode.objects.filter(pk=self.value()).first()
            if book:
                return queryset.filter(**{f"{self.path_field}__startswith": book.path})
        return queryset


class ChapterFilter(admin.SimpleListFilter):
    title = "فصل"
    parameter_name = "chapter"
    path_field = "path"

    def lookups(self, request, model_admin):
        book_id = request.GET.get("book")
        chapters = ContentNode.objects.filter(kind=ContentNode.Kind.CHAPTER)
        if book_id:
            book = ContentNode.objects.filter(pk=book_id).first()
            chapters = chapters.filter(path__startswith=book.path) if book else chapters.none()
        return [(str(c.pk), f"{c.position or '-'}. {c.title}" if book_id else f"{c.book().title} › {c.title}") for c in chapters.order_by("path")]

    def queryset(self, request, queryset):
        if self.value():
            chapter = ContentNode.objects.filter(pk=self.value()).first()
            if chapter:
                return queryset.filter(**{f"{self.path_field}__startswith": chapter.path})
        return queryset


class NodeBookFilter(BookFilter):
    path_field = "node__path"


class NodeChapterFilter(ChapterFilter):
    path_field = "node__path"


class YesNoFilter(admin.SimpleListFilter):
    """Subclasses set title, parameter_name and yes(queryset)."""

    def lookups(self, request, model_admin):
        return [("1", "بله"), ("0", "خیر")]

    def queryset(self, request, queryset):
        if self.value() == "1":
            return self.yes(queryset)
        if self.value() == "0":
            return queryset.exclude(pk__in=self.yes(queryset).values("pk"))
        return queryset
