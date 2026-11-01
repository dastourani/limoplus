from django import forms
from django.contrib import admin
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from . import bookpanel, panel
from .drawing import DrawingError, clean_svg
from .drawing import dumps as dumps_drawing
from .drawing import loads as loads_drawing
from .filters import BookFilter, ChapterFilter, YesNoFilter
from .models import Banner, Book, BookWaitlist, ChapterRevision, ContentNode, Major, Section


@admin.register(Major)
class MajorAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "is_coming_soon", "order")
    list_editable = ("is_coming_soon", "order")
    prepopulated_fields = {"slug": ("name",)}


class BookForm(forms.ModelForm):
    drawing_file = forms.FileField(
        label="فایل طرح سفارشی (SVG)",
        required=False,
        help_text="فقط وقتی هیچ «نقش جلد» آماده‌ای به درس نمی‌خورد: یک طرح خطی ساده (مثلاً از یک سایت آیکن) با پسوند svg. "
        "رنگ‌هایش خودکار لیمویی یا جوهری می‌شود. با بارگذاری، «نقش جلد» خودکار «طرح سفارشی» می‌شود.",
    )
    clear_drawing = forms.BooleanField(label="حذف طرح سفارشی", required=False)

    class Meta:
        model = Book
        fields = "__all__"

    def clean_drawing_file(self):
        upload = self.cleaned_data.get("drawing_file")
        self.drawing = None
        if upload:
            if not upload.name.lower().endswith(".svg"):
                raise forms.ValidationError("فقط فایل svg.")
            try:
                self.drawing = clean_svg(upload.read())
            except DrawingError as e:
                raise forms.ValidationError(str(e))
        return upload

    def clean(self):
        data = super().clean()
        new = getattr(self, "drawing", None)
        if data.get("clear_drawing") and not new and data.get("cover_motif") == "custom":
            data["cover_motif"] = "book"  # removing the drawing falls back to the plain book motif
        has_drawing = new or (self.instance.cover_drawing and not data.get("clear_drawing"))
        if data.get("cover_motif") == "custom" and not has_drawing:
            self.add_error("cover_motif", "برای «طرح سفارشی» اول فایل SVG طرح را بارگذاری کنید.")
        return data


@admin.register(Book)
class BookAdmin(admin.ModelAdmin):
    """«کتاب‌ها»: make a book first (cover, about, majors, price), then add its chapters on the book's page."""

    form = BookForm
    change_form_template = "admin/catalog/book/change_form.html"
    change_list_template = "admin/catalog/book/change_list.html"
    list_display = ("cover_thumb", "title", "author", "chapter_count", "price", "waiting", "is_coming_soon", "is_published", "is_archived")
    list_display_links = ("cover_thumb", "title")
    list_filter = ("is_published", "is_archived", "majors")
    search_fields = ("title", "slug", "author")
    fieldsets = (
        (None, {"fields": ("title", "title_en", "slug", "author", "edition", "majors")}),
        ("جلد و معرفی", {"fields": ("cover_motif", "drawing_file", "clear_drawing", "cover", "about")}),
        ("فروش و نمایش", {"fields": ("price", "is_free", "is_coming_soon", "position", "is_published", "is_archived")}),
    )

    def get_queryset(self, request):
        return super().get_queryset(request).filter(kind=ContentNode.Kind.BOOK, depth=1)

    def get_readonly_fields(self, request, obj=None):
        return ("slug",) if obj else ()

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "slug" in form.base_fields:
            form.base_fields["slug"].required = True
            form.base_fields["slug"].help_text = "شناسه‌ی لاتین ثابت کتاب، مثلاً bushberg؛ بعداً عوض نمی‌شود."
        if "position" in form.base_fields:
            form.base_fields["position"].label = "ترتیب در قفسه"
            form.base_fields["position"].help_text = "عدد کمتر جلوتر؛ خالی = بعد از بقیه (کتاب‌های «به‌زودی» همیشه آخرند)."
        if "majors" in form.base_fields:
            from django import forms

            form.base_fields["majors"].widget = forms.CheckboxSelectMultiple(choices=form.base_fields["majors"].choices)
            form.base_fields["majors"].help_text = "کتاب در صفحه‌ی این رشته‌ها در اپ دیده می‌شود."
        if "about" in form.base_fields:
            form.base_fields["about"].widget.attrs.update({"data-md-editor": "1", "rows": 12})
            form.base_fields["about"].help_text = "در صفحه‌ی کتاب در اپ، بالای فهرست فصل‌ها نشان داده می‌شود."
        if "is_free" in form.base_fields:
            form.base_fields["is_free"].help_text = "کل کتاب رایگان؛ برای رایگان کردن فقط چند فصل، گزینه‌ی هر فصل را در فهرست فصل‌ها بزنید."
        return form

    def save_model(self, request, obj, form, change):
        obj.kind = ContentNode.Kind.BOOK
        if getattr(form, "drawing", None):
            obj.cover_drawing = dumps_drawing(form.drawing)
            obj.cover_motif = ContentNode.Motif.CUSTOM
        elif form.cleaned_data.get("clear_drawing"):
            obj.cover_drawing = ""
            if obj.cover_motif == ContentNode.Motif.CUSTOM:
                obj.cover_motif = ContentNode.Motif.BOOK
        if change:
            obj.save()
        else:
            ContentNode.add_root(instance=obj)

    def has_delete_permission(self, request, obj=None):
        return False  # Archive instead; learners' purchases and progress point at books.

    @admin.display(description="جلد")
    def cover_thumb(self, obj):
        if obj.cover:
            return format_html('<img src="{}" style="height:66px;border-radius:6px">', obj.cover.url)
        major = obj.majors.order_by("order", "name").first()
        return format_html(
            '<span class="lp-cover" data-title="{}" data-en="{}" data-author="{}" data-edition="{}" data-motif="{}" data-major="{}" data-strip="{}" data-drawing="{}" data-width="44"></span>',
            obj.title, obj.title_en, obj.author, obj.edition, obj.cover_motif, major.name if major else "", major.color if major else "", obj.cover_drawing,
        )

    @admin.display(description="خبرم کن")
    def waiting(self, obj):
        n = obj.waitlist.filter(is_active=True).count()
        return n or ""

    @admin.display(description="فصل‌ها")
    def chapter_count(self, obj):
        return obj.get_children().filter(kind=ContentNode.Kind.CHAPTER, is_archived=False).count()

    def changelist_view(self, request, extra_context=None):
        extra = extra_context or {}
        extra["orphans"] = [n for n in panel.orphans() if not n.is_archived]
        return super().changelist_view(request, extra_context=extra)

    def _majors_json(self):
        import json

        return json.dumps({str(m.pk): {"name": m.name, "color": m.color} for m in Major.objects.all()}, ensure_ascii=False)

    def add_view(self, request, form_url="", extra_context=None):
        return super().add_view(request, form_url, extra_context={**(extra_context or {}), "majors_json": self._majors_json()})

    def change_view(self, request, object_id, form_url="", extra_context=None):
        extra = extra_context or {}
        extra["majors_json"] = self._majors_json()
        drawing_owner = ContentNode.objects.filter(pk=object_id).first()
        extra["drawing_json"] = drawing_owner.cover_drawing if drawing_owner else ""
        book = ContentNode.objects.filter(pk=object_id, kind=ContentNode.Kind.BOOK).first()
        if book:
            from apps.learning.models import Flashcard, Question

            chapters = []
            for c in book.get_children().filter(kind=ContentNode.Kind.CHAPTER):
                ids = [c.pk, *c.get_descendants().values_list("pk", flat=True)]
                chapters.append({
                    "node": c,
                    "sections": c.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False).count(),
                    "drafts": c.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False, is_published=False).count(),
                    "questions": Question.objects.filter(node_id__in=ids, is_archived=False).count(),
                    "flashcards": Flashcard.objects.filter(node_id__in=ids, is_archived=False).count(),
                })
            extra["chapters"] = chapters
            from .bookpanel import book_health, gift_context

            extra["health"] = book_health(book)
            extra.update(gift_context(book))
        return super().change_view(request, object_id, form_url, extra_context=extra)

    def get_urls(self):
        site = self.admin_site.admin_view
        custom = [
            path("import/", site(lambda r: panel.import_view(self.admin_site, r)), name="catalog_import"),
            path("<int:book_id>/import/", site(lambda r, book_id: panel.import_view(self.admin_site, r, book_id)), name="catalog_book_import"),
            path("<int:book_id>/export/", site(panel.book_export), name="catalog_book_export"),
            path("orphan/<int:node_id>/archive/", site(panel.archive_orphan), name="catalog_archive_orphan"),
            path("<int:book_id>/chapters/", site(panel.book_chapter_action), name="catalog_book_chapter_action"),
            path("<int:book_id>/gift/", site(bookpanel.book_gift), name="catalog_book_gift"),
            path("chapter/<int:chapter_id>/", site(lambda r, chapter_id: panel.chapter_manager(self.admin_site, r, chapter_id)), name="catalog_chapter_manager"),
            path("chapter/<int:chapter_id>/api/", site(panel.chapter_api), name="catalog_chapter_api"),
            path("chapter/<int:chapter_id>/file/", site(lambda r, chapter_id: panel.chapter_file(self.admin_site, r, chapter_id)), name="catalog_chapter_file"),
            path("chapter/<int:chapter_id>/export/", site(panel.chapter_export), name="catalog_chapter_export"),
            path("chapter/<int:chapter_id>/history/", site(lambda r, chapter_id: panel.chapter_history(self.admin_site, r, chapter_id)), name="catalog_chapter_history"),
            path("chapter/<int:chapter_id>/history/<int:revision_id>/", site(panel.revision_text), name="catalog_revision_text"),
        ]
        return custom + super().get_urls()


class GroupFilter(admin.SimpleListFilter):
    title = "گروه"
    parameter_name = "group"

    def lookups(self, request, model_admin):
        qs = ContentNode.objects.filter(kind=ContentNode.Kind.SECTION).exclude(group="")
        chapter = request.GET.get("chapter")
        if chapter and (c := ContentNode.objects.filter(pk=chapter).first()):
            qs = qs.filter(path__startswith=c.path)
        return [(g, g) for g in qs.order_by("group").values_list("group", flat=True).distinct()]

    def queryset(self, request, queryset):
        return queryset.filter(group=self.value()) if self.value() else queryset


class HasSummaryFilter(YesNoFilter):
    title = "خلاصه دارد"
    parameter_name = "has_summary"

    def yes(self, qs):
        return qs.exclude(summary_body="")


class HasReviewCardFilter(YesNoFilter):
    title = "خلاصه به شکل کارت مرور"
    parameter_name = "review_card"

    def yes(self, qs):
        return qs.filter(Q(summary_body__contains="در یک نگاه:") | Q(summary_body__contains="مهم:"))


class HasNotesFilter(YesNoFilter):
    title = "جزوه دارد"
    parameter_name = "has_notes"

    def yes(self, qs):
        return qs.exclude(full_body="")


class HasImageFilter(YesNoFilter):
    title = "عکس دارد"
    parameter_name = "has_image"

    def yes(self, qs):
        return qs.filter(Q(full_body__contains="![") | Q(summary_body__contains="!["))


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    """A searchable list of every section's notes and summary; editing happens in «مدیریت فصل»."""

    list_display = ("title", "chapter_title", "group", "summary_kind", "counts", "is_free", "is_published", "is_archived", "manage")
    list_filter = (BookFilter, ChapterFilter, GroupFilter, HasNotesFilter, HasSummaryFilter, HasReviewCardFilter, HasImageFilter,
                   "is_free", "is_published", "is_archived")
    search_fields = ("title", "slug", "full_body", "summary_body", "group")
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).filter(kind=ContentNode.Kind.SECTION).annotate(
            n_questions=Count("questions", filter=Q(questions__is_archived=False), distinct=True),
            n_flashcards=Count("flashcards", filter=Q(flashcards__is_archived=False), distinct=True),
        ).order_by("path")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def _chapter(self, obj):
        return obj.get_parent()

    @admin.display(description="فصل")
    def chapter_title(self, obj):
        c = self._chapter(obj)
        return f"{c.position or ''} {c.title}".strip() if c else ""

    @admin.display(description="کتاب")
    def book_title(self, obj):
        b = obj.book()
        return b.title if b else ""

    @admin.display(description="خلاصه")
    def summary_kind(self, obj):
        if not obj.summary_body:
            return "—"
        return "کارت مرور" if ("در یک نگاه:" in obj.summary_body or "مهم:" in obj.summary_body) else "متن ساده"

    @admin.display(description="تست / فلش‌کارت")
    def counts(self, obj):
        return f"{obj.n_questions} / {obj.n_flashcards}"

    @admin.display(description="")
    def manage(self, obj):
        c = self._chapter(obj)
        if not c or c.kind != ContentNode.Kind.CHAPTER or c.book() is None:
            return ""
        return format_html('<a class="button" href="{}#s={}">ویرایش</a>', reverse("admin:catalog_chapter_manager", args=[c.pk]), obj.slug)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        node = ContentNode.objects.filter(pk=object_id).first()
        if node and (c := node.get_parent()):
            return redirect(reverse("admin:catalog_chapter_manager", args=[c.pk]) + f"#s={node.slug}")
        return super().change_view(request, object_id, form_url, extra_context)


@admin.register(ChapterRevision)
class ChapterRevisionAdmin(admin.ModelAdmin):
    list_display = ("chapter", "source", "note", "user", "updated_at")
    list_filter = ("source", BookFilter)
    search_fields = ("note", "chapter__title")
    readonly_fields = ("chapter", "source", "note", "user", "created_at", "updated_at", "text")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def get_list_filter(self, request):
        return ("source",)


@admin.register(BookWaitlist)
class BookWaitlistAdmin(admin.ModelAdmin):
    """Who pressed «خبرم کن» on a coming-soon book."""

    list_display = ("book", "user", "is_active", "created_at")
    list_filter = ("is_active", "book")
    search_fields = ("user__phone", "book__title")

    def get_readonly_fields(self, request, obj=None):
        return ("user", "book", "is_active", "created_at")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("title", "target", "is_active", "priority", "starts_at", "ends_at", "impressions", "clicks")
    fields = ("template", "title", "subtitle", "button", "motif", "image", "target", "target_value", "link", "majors", "starts_at", "ends_at",
              "countdown", "priority", "is_active")
    change_form_template = "admin/catalog/banner/change_form.html"

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        """The books a «کتاب تازه» banner can show, for the live preview."""
        books = {}
        for b in ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1, is_archived=False).prefetch_related("majors"):
            major = b.majors.order_by("order", "name").first()
            books[b.slug] = {"title": b.title, "title_en": b.title_en, "author": b.author, "edition": b.edition, "motif": b.cover_motif,
                             "drawing": loads_drawing(b.cover_drawing), "major": major.name if major else "", "strip": major.color if major else ""}
        extra = {**(extra_context or {}), "banner_books": books}
        return super().changeform_view(request, object_id, form_url, extra)

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        if db_field.name == "motif":
            from django import forms

            choices = [("", "—")] + [c for c in ContentNode.Motif.choices if c[0] != ContentNode.Motif.CUSTOM]
            return forms.ChoiceField(choices=choices, required=False, label=db_field.verbose_name, help_text=db_field.help_text)
        return super().formfield_for_dbfield(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if obj.countdown and not obj.ends_at:
            from django.contrib import messages

            obj.countdown = False
            messages.warning(request, "برای شمارش معکوس، «پایان» را پر کنید؛ فعلاً بدون شمارش ذخیره شد.")
        super().save_model(request, obj, form, change)
    list_editable = ("is_active", "priority")
    list_filter = ("is_active", "majors")
    filter_horizontal = ("majors",)
