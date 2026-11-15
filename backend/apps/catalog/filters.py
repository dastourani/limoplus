"""List filters shared by the panel's section, question and flashcard lists: book, then chapter, by tree path."""

from django.contrib import admin

from .models import ContentNode


def _book_choices(with_inbox=False):
    """The books, by title. The hidden «صندوق تست» only where tests and cards are listed (it holds pasted ones)."""
    books = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1)
    if not with_inbox:
        books = books.filter(is_inbox=False)
    return [(str(b.pk), b.title) for b in books.order_by("title")]


class BookFKFilter(admin.SimpleListFilter):
    """«کتاب» for a model that points at its book directly (field «book»): only books, never every chapter and section."""

    title = "کتاب"
    parameter_name = "book_id"
    field = "book"
    lp_list = True  # book names are long: a list, not a row of chips (templates/admin/filter.html)

    def lookups(self, request, model_admin):
        return _book_choices()

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(**{f"{self.field}_id": self.value()})
        return queryset


class BookFilter(admin.SimpleListFilter):
    lp_list = True
    title = "کتاب"
    parameter_name = "book"
    path_field = "path"
    with_inbox = False

    def lookups(self, request, model_admin):
        return _book_choices(self.with_inbox)

    def queryset(self, request, queryset):
        if self.value():
            book = ContentNode.objects.filter(pk=self.value()).first()
            if book:
                return queryset.filter(**{f"{self.path_field}__startswith": book.path})
        return queryset


class ChapterFilter(admin.SimpleListFilter):
    lp_list = True
    title = "فصل"
    parameter_name = "chapter"
    path_field = "path"

    def lookups(self, request, model_admin):
        # Chapters only once a book is chosen: a list of every chapter of every book helps nobody.
        book_id = request.GET.get("book")
        if not book_id:
            return []
        book = ContentNode.objects.filter(pk=book_id).first()
        chapters = ContentNode.objects.filter(kind=ContentNode.Kind.CHAPTER)
        chapters = chapters.filter(path__startswith=book.path) if book else chapters.none()
        out = []
        for c in chapters.order_by("path"):
            book = c.book()
            if book is None:
                continue  # a chapter outside any book (made by hand in the old panel); listed on the books page
            out.append((str(c.pk), f"{c.position or '-'}. {c.title}" if book_id else f"{book.title} › {c.title}"))
        return out

    def queryset(self, request, queryset):
        if self.value():
            chapter = ContentNode.objects.filter(pk=self.value()).first()
            if chapter:
                return queryset.filter(**{f"{self.path_field}__startswith": chapter.path})
        return queryset


class NodeBookFilter(BookFilter):
    path_field = "node__path"
    with_inbox = True


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
