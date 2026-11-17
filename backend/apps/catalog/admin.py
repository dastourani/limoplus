from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from . import bookpanel, panel
from .drawing import DrawingError, clean_svg
from .drawing import dumps as dumps_drawing
from .drawing import loads as loads_drawing
from .filters import BookFilter, BookFKFilter, ChapterFilter, YesNoFilter
from .panel_display import badges
from .models import (Banner, Book, BookChange, BookWaitlist, ChapterRevision, CleanupRun, ContentNode, FormulaCommand, Label, Major, Section,
                     ShareSettings, Shelf, ShelfBook)


class ShelfBookInline(admin.TabularInline):
    model = ShelfBook
    extra = 1
    fields = ("book", "order")
    verbose_name = "کتاب"
    verbose_name_plural = "کتاب‌های این قفسه (ترتیب: عدد کمتر، جلوتر)"


@admin.register(Shelf)
class ShelfAdmin(admin.ModelAdmin):
    """«قفسه‌ها»: the rows of the home page. Books on no shelf still show, in a last row «کتاب‌های دیگر»."""

    list_display = ("title", "order", "is_active", "book_count")
    list_editable = ("order", "is_active")
    inlines = [ShelfBookInline]

    @admin.display(description="کتاب‌ها")
    def book_count(self, obj):
        return obj.items.count()


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
    list_display = ("cover_thumb", "title", "author", "chapter_count", "price", "waiting", "status")
    list_display_links = ("cover_thumb", "title")
    list_filter = ("is_published", "is_archived", "majors")
    search_fields = ("title", "slug", "author")
    fieldsets = (
        (None, {"fields": ("title", "title_en", "slug", "author", "edition", "majors")}),
        ("جلد و معرفی", {"fields": ("cover_motif", "drawing_file", "clear_drawing", "cover", "about")}),
        ("فروش و نمایش", {"fields": ("price", "is_free", "is_coming_soon", "release_estimate", "position", "is_published", "is_archived")}),
        ("اشتراک‌گذاری", {"fields": ("share_link",)}),
    )


    @admin.display(description="وضعیت")
    def status(self, obj):
        return badges(
            ("بایگانی", "grey") if obj.is_archived else (("منتشر", "green") if obj.is_published else ("پیش‌نویس", "grey")),
            obj.is_coming_soon and ("به‌زودی", "yellow"),
            obj.is_free and ("رایگان", "blue"),
        )

    def get_queryset(self, request):
        # The «صندوق تست» has its own button above the list. Counts come with the list (no query per row).
        from django.db.models import IntegerField, OuterRef, Subquery
        from django.db.models.functions import Coalesce, Substr

        chapters = (ContentNode.objects.filter(kind=ContentNode.Kind.CHAPTER, depth=2, is_archived=False)
                    .annotate(root=Substr("path", 1, ContentNode.steplen)).filter(root=OuterRef("path"))
                    .order_by().values("root").annotate(n=Count("pk")).values("n")[:1])
        waiting = (BookWaitlist.objects.filter(book=OuterRef("pk"), is_active=True).order_by().values("book")
                   .annotate(n=Count("pk")).values("n")[:1])
        return (super().get_queryset(request).filter(kind=ContentNode.Kind.BOOK, depth=1, is_inbox=False)
                .prefetch_related("majors")
                .annotate(n_chapters=Coalesce(Subquery(chapters, output_field=IntegerField()), 0),
                          n_waiting=Coalesce(Subquery(waiting, output_field=IntegerField()), 0)))

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
        majors = sorted(obj.majors.all(), key=lambda m: (m.order, m.name))  # prefetched with the list
        major = majors[0] if majors else None
        return format_html(
            '<span class="lp-cover" data-title="{}" data-en="{}" data-author="{}" data-edition="{}" data-motif="{}" data-major="{}" data-strip="{}" data-drawing="{}" data-width="44"></span>',
            obj.title, obj.title_en, obj.author, obj.edition, obj.cover_motif, major.name if major else "", major.color if major else "", obj.cover_drawing,
        )

    @admin.display(description="منتظران «خبرم کن»", ordering="n_waiting")
    def waiting(self, obj):
        from .panel_display import fa_number

        n = getattr(obj, "n_waiting", None)
        if n is None:
            n = obj.waitlist.filter(is_active=True).count()
        if not n:
            return "—"
        url = reverse("admin:catalog_bookwaitlist_changelist") + f"?book_id={obj.pk}"
        return format_html('<a href="{}">{} نفر</a>', url, fa_number(n))

    @admin.display(description="فصل‌ها", ordering="n_chapters")
    def chapter_count(self, obj):
        n = getattr(obj, "n_chapters", None)
        return n if n is not None else obj.get_children().filter(kind=ContentNode.Kind.CHAPTER, is_archived=False).count()

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
            path("inbox/", site(panel.open_inbox), name="catalog_inbox"),
            path("<int:book_id>/gift/", site(bookpanel.book_gift), name="catalog_book_gift"),
            path("<int:book_id>/notify-waitlist/", site(lambda r, book_id: bookpanel.waitlist_notify(self.admin_site, r, book_id)),
                 name="catalog_book_waitlist_notify"),
            path("chapter/<int:chapter_id>/", site(lambda r, chapter_id: panel.chapter_manager(self.admin_site, r, chapter_id)), name="catalog_chapter_manager"),
            path("chapter/<int:chapter_id>/api/", site(panel.chapter_api), name="catalog_chapter_api"),
            path("chapter/<int:chapter_id>/file/", site(lambda r, chapter_id: panel.chapter_file(self.admin_site, r, chapter_id)), name="catalog_chapter_file"),
            path("chapter/<int:chapter_id>/export/", site(panel.chapter_export), name="catalog_chapter_export"),
            path("chapter/<int:chapter_id>/export/tex/", site(panel.chapter_tex), name="catalog_chapter_tex"),
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

    list_display = ("section_title", "chapter_title", "summary_kind", "counts", "status", "manage")
    list_filter = (BookFilter, ChapterFilter, GroupFilter, HasNotesFilter, HasSummaryFilter, HasReviewCardFilter, HasImageFilter,
                   "is_free", "is_published", "is_archived")
    search_fields = ("title", "slug", "full_body", "summary_body", "group")
    list_per_page = 50


    @admin.display(description="وضعیت")
    def status(self, obj):
        return badges(
            ("بایگانی", "grey") if obj.is_archived else (("منتشر", "green") if obj.is_published else ("پیش‌نویس", "grey")),
            obj.is_free and ("رایگان", "blue"),
        )

    def get_queryset(self, request):
        from django.db.models import OuterRef, Subquery
        from django.db.models.functions import Substr

        step = ContentNode.steplen
        chapter = ContentNode.objects.filter(path=Substr(OuterRef("path"), 1, 2 * step), kind=ContentNode.Kind.CHAPTER)
        book = ContentNode.objects.filter(path=Substr(OuterRef("path"), 1, step), kind=ContentNode.Kind.BOOK)
        return super().get_queryset(request).filter(kind=ContentNode.Kind.SECTION).annotate(
            n_questions=Count("questions", filter=Q(questions__is_archived=False), distinct=True),
            n_flashcards=Count("flashcards", filter=Q(flashcards__is_archived=False), distinct=True),
            p_chapter_id=Subquery(chapter.values("pk")[:1]),
            p_chapter_pos=Subquery(chapter.values("position")[:1]),
            p_chapter_title=Subquery(chapter.values("title")[:1]),
            p_book=Subquery(book.values("title")[:1]),
        ).order_by("path")

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="بخش", ordering="title")
    def section_title(self, obj):
        group = format_html('<div class="lp-quiet">{}</div>', obj.group) if obj.group else ""
        return format_html("{}{}", obj.title, group)

    @admin.display(description="کتاب و فصل", ordering="path")
    def chapter_title(self, obj):
        from .jalali import fa_digits

        if not getattr(obj, "p_chapter_title", None):
            return "—"
        head = f"فصل {fa_digits(obj.p_chapter_pos)}" if obj.p_chapter_pos else "فصل"
        book = obj.p_book or "بدون کتاب"
        return format_html('<div class="lp-quiet">{}</div><span style="white-space:nowrap"><b>{}</b>، {}</span>',
                           book, head, obj.p_chapter_title)

    @admin.display(description="خلاصه")
    def summary_kind(self, obj):
        if not obj.summary_body:
            return "—"
        return "کارت مرور" if ("در یک نگاه:" in obj.summary_body or "مهم:" in obj.summary_body) else "متن ساده"

    @admin.display(description="تست و فلش‌کارت")
    def counts(self, obj):
        from .panel_display import fa_number

        return format_html('<span style="white-space:nowrap">{} تست</span><div class="lp-quiet" style="white-space:nowrap">{} فلش‌کارت</div>',
                           fa_number(obj.n_questions), fa_number(obj.n_flashcards))

    @admin.display(description="")
    def manage(self, obj):
        if not getattr(obj, "p_chapter_id", None) or not obj.p_book:
            return ""
        return format_html('<a class="button" href="{}#s={}">ویرایش</a>', reverse("admin:catalog_chapter_manager", args=[obj.p_chapter_id]), obj.slug)

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


class WaitNotifiedFilter(admin.SimpleListFilter):
    title = "پیامک خبر"
    parameter_name = "told"

    def lookups(self, request, model_admin):
        return [("yes", "فرستاده شد"), ("no", "هنوز نه")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(notified_at__isnull=False)
        if self.value() == "no":
            return queryset.filter(notified_at__isnull=True)
        return queryset


@admin.register(BookWaitlist)
class BookWaitlistAdmin(admin.ModelAdmin):
    """Who pressed «خبرم کن» on a coming-soon book, and whether the SMS «منتشر شد» has gone to them."""

    change_list_template = "admin/catalog/bookwaitlist/change_list.html"

    list_display = ("book", "user", "state", "told", "created_at")
    list_filter = ("is_active", BookFKFilter, WaitNotifiedFilter)
    search_fields = ("user__phone", "book__title")
    list_select_related = ("book", "user")

    def get_readonly_fields(self, request, obj=None):
        return ("user", "book", "is_active", "created_at", "notified_at", "notify_error")

    def changelist_view(self, request, extra_context=None):
        """With one book chosen, the page offers «خبر دادن به منتظران» for it."""
        book = ContentNode.objects.filter(pk=request.GET.get("book_id"), kind=ContentNode.Kind.BOOK).first() if request.GET.get("book_id", "").isdigit() else None
        return super().changelist_view(request, {**(extra_context or {}), "lp_notify_book": book})

    @admin.display(description="درخواست", ordering="is_active")
    def state(self, obj):
        return badges(("فعال", "green") if obj.is_active else ("لغو کرده", "grey"))

    @admin.display(description="پیامک خبر", ordering="notified_at")
    def told(self, obj):
        from .jalali import jalali_datetime

        if obj.notified_at and obj.notify_error:  # the provider did not answer clearly: maybe sent, never resent
            return format_html('{}<div class="lp-quiet">{}</div>', badges(("نامعلوم (دوباره فرستاده نمی‌شود)", "yellow")), obj.notify_error[:80])
        if obj.notified_at:
            return format_html('{}<div class="lp-quiet">{}</div>', badges(("فرستاده شد", "green")), jalali_datetime(obj.notified_at))
        if obj.notify_queued_at:
            return badges(("در صف", "yellow"))
        if obj.notify_error:
            return format_html('{}<div class="lp-quiet">{}</div>', badges(("ناموفق", "red")), obj.notify_error[:80])
        return "—"

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class BannerBookFilter(admin.SimpleListFilter):
    """«کتاب مخاطب»: banners for the readers of one book, or for everyone (targeting by major is gone)."""

    title = "کتاب مخاطب"
    parameter_name = "audience"
    lp_list = True

    def lookups(self, request, model_admin):
        from .filters import _book_choices

        return [("all", "همه (بدون کتاب)")] + _book_choices()

    def queryset(self, request, queryset):
        if self.value() == "all":
            return queryset.filter(audience_book__isnull=True)
        if self.value():
            return queryset.filter(audience_book_id=self.value())
        return queryset


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("title", "target", "is_active", "priority", "period", "shown", "ctr")
    fields = ("template", "title", "subtitle", "button", "motif", "image", "target", "target_value", "link", "audience_book", "starts_at", "ends_at",
              "countdown", "priority", "is_active")
    change_form_template = "admin/catalog/banner/change_form.html"

    @admin.display(description="بازه")
    def period(self, obj):
        from .jalali import jalali_date

        if not obj.starts_at and not obj.ends_at:
            return "همیشه"
        return format_html('<span style="white-space:nowrap">{} تا {}</span>', jalali_date(obj.starts_at) if obj.starts_at else "…",
                           jalali_date(obj.ends_at) if obj.ends_at else "…")

    @admin.display(description="نمایش / کلیک", ordering="impressions")
    def shown(self, obj):
        from .panel_display import fa_number

        return format_html('<span style="white-space:nowrap">{} / {}</span>', fa_number(obj.impressions), fa_number(obj.clicks))

    @admin.display(description="نرخ کلیک")
    def ctr(self, obj):
        """Clicks per hundred views; under 100 views it says nothing yet."""
        from .panel_display import fa_number

        if obj.impressions < 100:
            return format_html('<span class="lp-quiet">{}</span>', "کمتر از ۱۰۰ نمایش")
        rate = 100 * obj.clicks / obj.impressions
        color = "green" if rate >= 2 else "yellow" if rate >= 0.5 else "grey"
        return badges((f"{fa_number(round(rate, 1))}٪", color))

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
    list_filter = ("is_active", BannerBookFilter)


@admin.register(CleanupRun)
class StorageAdmin(admin.ModelAdmin):
    """«فضای سرور»: what takes room on the server, the last clean-ups, and a button to run one now."""

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from django.contrib import messages
        from django.shortcuts import redirect
        from django.template.response import TemplateResponse

        from .jalali import jalali_datetime
        from .maintenance import run_all, storage_report

        if request.method == "POST" and request.user.is_superuser:
            s = run_all()
            messages.success(
                request,
                f"پاک‌سازی انجام شد: {s['codes']} کد منقضی، {s['rate_counters']} شمارنده، {s['sessions']} نشست قدیمی، "
                f"{s['revisions']} نسخه‌ی قدیمی فصل، {s['images']} عکس بی‌استفاده.",
            )
            return redirect(request.path)
        from .backups import bale_ready, disk, local_backups, next_db_backup
        from .models import BackupRun

        report = storage_report()
        from .backups import backup_dir
        from .maintenance import _folder_size

        labels = {"content": "عکس‌های محتوا", "covers": "جلدها", "banners": "بنرها", "apk": "فایل‌های APK", "imports": "ورودهای نیمه‌کاره"}
        colors = {"content": "#F5C518", "covers": "#7C9CF5", "banners": "#E58BC0", "apk": "#55B88A", "imports": "#C9C9C9"}
        backup_bytes, backup_files = _folder_size(str(backup_dir()))
        space = [{"label": "دیتابیس", "bytes": report["db_bytes"] or 0, "files": 0, "color": "#1D2B23"}]
        space += [{"label": labels.get(f["name"], f["name"]), "bytes": f["bytes"], "files": f["files"], "color": colors.get(f["name"], "#999")} for f in report["folders"]]
        space.append({"label": "پشتیبان‌ها", "bytes": backup_bytes, "files": backup_files, "color": "#A27B5C"})
        whole = sum(x["bytes"] for x in space) or 1
        for x in space:
            x["share"] = round(x["bytes"] / whole * 100, 2)
        context = {
            **self.admin_site.each_context(request),
            "title": "فضای سرور",
            "report": report,
            "space": [x for x in space if x["bytes"]],
            "media_bytes": sum(f["bytes"] for f in report["folders"]),
            "media_files": sum(f["files"] for f in report["folders"]),
            "runs": [{"at": jalali_datetime(r.at), "summary": r.summary} for r in CleanupRun.objects.all()[:10]],
            "can_run": request.user.is_superuser,
            "backups": [
                {"at": jalali_datetime(b.at), "kind": b.get_kind_display(), "ok": b.ok, "sent": b.sent, "size": b.size, "note": b.note}
                for b in BackupRun.objects.all()[:12]
            ],
            "bale_ready": bale_ready(),
            "disk": disk(),
            "local": [{**b, "at": jalali_datetime(b["at"])} for b in local_backups()[:12]],
            "next_backup": jalali_datetime(next_db_backup()),
            "last_backup": next(
                ({"at": jalali_datetime(b.at), "ok": b.ok, "sent": b.sent, "note": b.note} for b in BackupRun.objects.filter(kind="db")[:1]), None
            ),
            "users": get_user_model().objects.count(),
            "opts": self.model._meta,
        }
        return TemplateResponse(request, "admin/catalog/storage.html", context)


    def get_urls(self):
        from django.db import transaction

        site = self.admin_site.admin_view
        custom = [
            path("backup-now/", site(self.backup_now), name="catalog_backup_now"),
            # Not inside the request's transaction: the database file itself is replaced.
            path("restore/", transaction.non_atomic_requests(site(self.restore)), name="catalog_restore"),
            path("restore-local/", transaction.non_atomic_requests(site(self.restore_local)), name="catalog_restore_local"),
            path("backup-file/", site(self.backup_file), name="catalog_backup_file"),
            path("test-bale/", site(self.test_bale), name="catalog_test_bale"),
        ]
        return custom + super().get_urls()

    def backup_now(self, request):
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import redirect

        from .backups import backup_database, backup_media, bale_ready

        if request.method != "POST" or not request.user.is_superuser:
            raise PermissionDenied
        db = backup_database()
        msg = "پشتیبان دیتابیس " + ("ساخته شد" if db.ok else f"ساخته نشد: {db.note}") + ("، و در بله فرستاده شد" if db.sent else "")
        if request.POST.get("media") and bale_ready():
            media = backup_media()
            msg += "؛ پشتیبان عکس‌ها " + (f"فرستاده شد ({media.note})" if media.sent else f"انجام نشد {media.note}")
        (messages.success if db.ok else messages.error)(request, msg + ".")
        return redirect("..")

    def restore(self, request):
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import redirect

        from .backups import RestoreError, restore_upload

        if request.method != "POST" or not request.user.is_superuser:
            raise PermissionDenied
        upload = request.FILES.get("file")
        if not upload or request.POST.get("confirm", "").strip() != "بازگردانی":
            messages.error(request, "فایل را انتخاب کنید و برای تأیید کلمه‌ی «بازگردانی» را بنویسید.")
            return redirect("..")
        try:
            done = restore_upload(upload)
        except RestoreError as exc:
            messages.error(request, str(exc))
            return redirect("..")
        if done.get("waiting"):
            from .jalali import fa_digits

            left = "، ".join(fa_digits(i) for i in done["waiting"])
            messages.info(request, f"این تکه نگه داشته شد. تکه‌های مانده از {fa_digits(done['pieces'])}: {left}. "
                                   "هر وقت همه رسید، بازگردانی خودکار انجام می‌شود.")
            return redirect("..")
        parts = []
        if done["db"]:
            parts.append(f"دیتابیس جایگزین شد (نسخه‌ی قبلی با نام {done['aside']} در پوشه‌ی backups نگه داشته شد)")
        if done["media"]:
            parts.append(f"{done['media']} عکس و فایل اضافه شد")
        messages.success(request, "؛ ".join(parts) + ". اگر از پنل بیرون رفتید، با حساب مدیرِ همان دیتابیس وارد شوید.")
        return redirect("..")


    def restore_local(self, request):
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import redirect

        from .backups import RestoreError, restore_local

        if request.method != "POST" or not request.user.is_superuser:
            raise PermissionDenied
        if request.POST.get("confirm", "").strip() != "بازگردانی":
            messages.error(request, "برای تأیید کلمه‌ی «بازگردانی» را بنویسید.")
            return redirect("..")
        try:
            aside = restore_local(request.POST.get("name", ""))
        except RestoreError as exc:
            messages.error(request, str(exc))
            return redirect("..")
        messages.success(request, f"دیتابیس به این نسخه برگشت. نسخه‌ی پیش از آن با نام {aside} نگه داشته شد.")
        return redirect("..")

    def backup_file(self, request):
        from django.core.exceptions import PermissionDenied
        from django.http import FileResponse, Http404

        from .backups import RestoreError, local_backup_path

        if not request.user.is_superuser:
            raise PermissionDenied
        try:
            path = local_backup_path(request.GET.get("name", ""))
        except RestoreError as exc:
            raise Http404 from exc
        return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name)

    def test_bale(self, request):
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import redirect

        from .backups import _safe, bale_ready, send_text

        if request.method != "POST" or not request.user.is_superuser:
            raise PermissionDenied
        if not bale_ready():
            messages.error(request, "ربات بله تنظیم نشده است (BALE_BOT_TOKEN و BALE_CHAT_ID).")
            return redirect("..")
        try:
            send_text("✅ پیام آزمایشی از پنل لیموخوان: ربات بله درست کار می‌کند.")
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"پیام نرسید: {_safe(exc)}")
            return redirect("..")
        messages.success(request, "پیام آزمایشی در بله فرستاده شد.")
        return redirect("..")


_admin_index = admin.site.index


def _index_with_daily_cleanup(request, extra_context=None):
    from .maintenance import run_if_due

    if request.user.is_active and request.user.is_staff:
        run_if_due()
    return _admin_index(request, extra_context)


admin.site.index = _index_with_daily_cleanup


@admin.register(ShareSettings)
class ShareSettingsAdmin(admin.ModelAdmin):
    """A single row: the link the book page sends when a book has no link of its own."""

    list_display = ("__str__", "default_link")

    def changelist_view(self, request, extra_context=None):
        """One row only: the menu item opens its form straight away (made empty the first time)."""
        row = ShareSettings.objects.first() or ShareSettings.objects.create()
        return redirect(reverse("admin:catalog_sharesettings_change", args=[row.pk]))

    def response_change(self, request, obj):
        from django.contrib import messages

        if "_continue" in request.POST:
            return super().response_change(request, obj)
        messages.success(request, "تنظیمات اشتراک ذخیره شد.")
        return redirect(reverse("admin:catalog_sharesettings_change", args=[obj.pk]))

    def has_add_permission(self, request):
        return not ShareSettings.objects.exists()

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Label)
class LabelAdmin(admin.ModelAdmin):
    """«برچسب‌های متن»: boxes in the notes (:::تعریف) and parts of the summary (تعریف:). Never deleted: hide instead."""

    list_display = ("preview", "name", "group", "style", "icon", "numbered", "role", "order", "is_hidden")
    list_display_links = ("name",)
    list_editable = ("group", "style", "icon", "numbered", "order", "is_hidden")
    ordering = ("group", "order", "name")

    @admin.display(description="نمونه")
    def preview(self, obj):
        """How the box looks, in the four looks' colours (as in the app)."""
        colors = {"formal": ("#3B5FC4", "rgba(70,110,220,.10)"), "note": ("#23864B", "rgba(46,158,91,.10)"),
                  "warn": ("#B4690E", "rgba(230,140,30,.12)"), "table": ("#6B6B6B", "rgba(120,120,120,.10)")}
        line, bg = colors.get(obj.style, colors["note"])
        return format_html('<span style="display:inline-block;min-width:76px;padding:3px 10px;border-inline-start:3px solid {};'
                           'background:{};border-radius:6px;font-weight:700;color:{};opacity:{}">{}</span>',
                           line, bg, line, ".45" if obj.is_hidden else "1", obj.name)
    list_filter = ("group", "style", "is_hidden")
    search_fields = ("name", "aliases")
    fieldsets = (
        (None, {"fields": ("name", "group", "style", "icon", "numbered", "order", "is_hidden"),
                "description": "هر برچسب در «درسنامه» یک کادر است (:::تعریف … :::) و در «چکیده» یک بخش (تعریف: و بعد موردها با «- »). "
                               "برچسبی را که در متن‌ها به کار رفته پاک نکنید؛ «پنهان» کنید تا در دکمه‌های پنل نیاید."}),
        ("بیشتر", {"fields": ("aliases", "columns", "role"), "classes": ("collapse",)}),
    )

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        from .labels import forget

        forget()


@admin.register(FormulaCommand)
class FormulaCommandAdmin(admin.ModelAdmin):
    """«دستورهای فرمول»: \\R for \\mathbb{R} in every formula of every book (the app uses KaTeX macros)."""

    list_display = ("name", "definition", "note", "is_hidden")
    list_editable = ("definition", "note", "is_hidden")
    search_fields = ("name", "definition", "note")
    fieldsets = (
        (None, {"fields": ("name", "definition", "note", "is_hidden"),
                "description": "دستوری که این‌جا تعریف کنید در فرمول‌های همه‌ی کتاب‌ها کار می‌کند. مثال‌ها: «\\R» با معنی «\\mathbb{R}»؛ "
                               "«\\norm» با معنی «\\lVert #1 \\rVert» که در متن «\\norm{v}» نوشته می‌شود (#1 جای اولین ورودی است). "
                               "اگر معنی را عوض کنید، همه‌ی فرمول‌هایی که از آن استفاده کرده‌اند عوض می‌شوند. دستوری را که در متن‌ها به کار رفته پاک نکنید."}),
    )

    def has_delete_permission(self, request, obj=None):
        return False

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        from .fresh import forget_macros

        forget_macros()


class ChangeBookFilter(BookFilter):
    path_field = "book__path"


@admin.register(BookChange)
class BookChangeAdmin(admin.ModelAdmin):
    """«تغییرات کتاب»: written by the panel's «مطلب تازه» tick; the text can be edited or the line hidden here."""

    list_display = ("text", "book", "node", "created_at", "is_hidden")
    list_editable = ("is_hidden",)
    list_filter = (ChangeBookFilter, "is_hidden")
    search_fields = ("text",)
    fields = ("book", "node", "text", "is_hidden")
    raw_id_fields = ("node",)

    def has_delete_permission(self, request, obj=None):
        return False

