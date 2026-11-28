import os

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from . import access, bookpanel, panel
from .drawing import DrawingError, clean_svg
from .drawing import dumps as dumps_drawing
from .drawing import loads as loads_drawing
from .filters import BookFilter, BookFKFilter, ChapterFilter, YesNoFilter
from .jalali import fa_digits
from .panel_display import badges
from .models import (
    AIProvider,
    Banner,
    Book,
    BookAssistantAuditLog,
    BookBoxMapping,
    BookChange,
    BookEditor,
    BookOpinion,
    BookTeamTask,
    BookWaitlist,
    ChapterRevision,
    CleanupRun,
    ContentNode,
    FormulaCommand,
    Label,
    Major,
    Section,
    ShareSettings,
    Shelf,
    ShelfBook,
    TeacherProfile,
)


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
        # `is_published` is deliberately NOT a form field: writing a book and releasing it are separate gates, and a
        # checkbox in a form cannot tell the two apart. Publishing goes through the button below the title, which
        # asks can_publish_book (see publish_book view).
        ("فروش و نمایش", {"fields": ("price", "is_free", "is_coming_soon", "release_estimate", "release_note", "position", "is_archived")}),
        ("شرایط عرضه و خروجی فنی (توافق انتشار)", {"fields": ("single_sale_only", "campaign_discount_cap_percent", "technical_export_disabled")}),
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
        qs = (super().get_queryset(request).filter(kind=ContentNode.Kind.BOOK, depth=1, is_inbox=False)
              .prefetch_related("majors")
              .annotate(n_chapters=Coalesce(Subquery(chapters, output_field=IntegerField()), 0),
                        n_waiting=Coalesce(Subquery(waiting, output_field=IntegerField()), 0)))
        if not request.user.is_superuser:
            qs = qs.filter(pk__in=access.book_editor_ids(request.user, capability=None))
        return qs

    def get_list_display(self, request):
        if access.acts_as_panel_superuser(request):
            return self.list_display
        return ("cover_thumb", "title", "author", "chapter_count", "status")

    def has_add_permission(self, request):
        return access.acts_as_panel_superuser(request)

    def has_change_permission(self, request, obj=None):
        # Teachers prepare chapter drafts in the chapter manager; book metadata and commercial settings are manager-only.
        return access.acts_as_panel_superuser(request)

    def get_fieldsets(self, request, obj=None):
        if access.acts_as_panel_superuser(request):
            return self.fieldsets
        # The view-only book page is a navigation hub for the assigned chapters, not a way to change title, price,
        # free access, majors, sale state, or sharing settings.
        return (
            (None, {"fields": ("title", "title_en", "slug", "author", "edition", "majors")}),
            ("جلد و معرفی", {"fields": ("cover_motif", "cover", "about")}),
        )

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
        if "release_note" in form.base_fields:
            form.base_fields["release_note"].widget.attrs.update({"rows": 3})
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
        view_param = (request.GET.get("view") or "").strip().lower()
        if "view" in request.GET:
            qd = request.GET.copy()
            qd.pop("view", None)
            request.GET = qd
        # Always clear any legacy session preference left over from before the layout switcher was removed.
        request.session.pop("book_list_view", None)
        book_view_mode = "table" if view_param == "table" else "shelf"

        is_panel_su = access.acts_as_panel_superuser(request)
        can_create_book = bool(is_panel_su or access.acts_as_panel_teacher(request))
        extra["orphans"] = [n for n in panel.orphans() if not n.is_archived] if is_panel_su else []
        extra["can_manage_access"] = is_panel_su
        extra["can_create_book"] = can_create_book
        extra["book_view_mode"] = book_view_mode

        response = super().changelist_view(request, extra_context=extra)
        if hasattr(response, "context_data") and "cl" in response.context_data:
            from .panel_display import fa_number

            cl = response.context_data["cl"]
            classroom_book_ids = (
                set(access.classroom_books_for_request(request).values_list("pk", flat=True))
                if not is_panel_su
                else set()
            )
            can_teacher = access.acts_as_panel_teacher(request)
            shelf_books = []
            for obj in cl.result_list:
                majors_sorted = sorted(obj.majors.all(), key=lambda m: (m.order, m.name))
                major = majors_sorted[0] if majors_sorted else None
                n_chapters = getattr(obj, "n_chapters", None)
                if n_chapters is None:
                    n_chapters = obj.get_children().filter(kind=ContentNode.Kind.CHAPTER, is_archived=False).count()
                n_waiting = getattr(obj, "n_waiting", None)
                if n_waiting is None:
                    n_waiting = obj.waitlist.filter(is_active=True).count()
                if obj.is_archived:
                    status_label, status_kind = "بایگانی", "grey"
                elif obj.is_published:
                    status_label, status_kind = "منتشر", "green"
                else:
                    status_label, status_kind = "پیش‌نویس", "draft"
                can_classrooms = bool(is_panel_su or can_teacher or obj.pk in classroom_book_ids)
                shelf_books.append({
                    "pk": obj.pk,
                    "title": obj.title,
                    "title_en": obj.title_en,
                    "author": obj.author,
                    "edition": obj.edition,
                    "cover_url": obj.cover.url if obj.cover else "",
                    "cover_motif": obj.cover_motif,
                    "cover_drawing": obj.cover_drawing,
                    "major_name": major.name if major else "",
                    "major_color": major.color if major else "",
                    "chapters_count": n_chapters,
                    "chapters_fa": fa_number(n_chapters),
                    "price_fa": fa_number(obj.price) if obj.price is not None else "",
                    "waiting_count": n_waiting,
                    "waiting_fa": fa_number(n_waiting),
                    "waitlist_url": reverse("admin:catalog_bookwaitlist_changelist") + f"?book_id={obj.pk}",
                    "is_published": obj.is_published,
                    "is_coming_soon": obj.is_coming_soon,
                    "is_archived": obj.is_archived,
                    "is_free": obj.is_free,
                    "status_label": status_label,
                    "status_kind": status_kind,
                    "status_html": self.status(obj),
                    "change_url": reverse("admin:catalog_book_change", args=[obj.pk]),
                    "classrooms_url": reverse("admin:catalog_book_classrooms_canvas", args=[obj.pk]) if can_classrooms else "",
                    "study_url": reverse("admin:catalog_book_study_analytics", args=[obj.pk]),
                    "inbox_url": reverse("admin:catalog_book_inbox", args=[obj.pk]),
                    "import_url": reverse("admin:catalog_book_import", args=[obj.pk]),
                })

            base_qs_params = request.GET.copy()
            base_qs_params.pop("p", None)
            def _qs_with(**updates):
                q = base_qs_params.copy()
                for k, v in updates.items():
                    if v is None:
                        q.pop(k, None)
                    else:
                        q[k] = str(v)
                encoded = q.urlencode()
                return f"?{encoded}" if encoded else "?"

            active_published = request.GET.get("is_published__exact", "")
            active_archived = request.GET.get("is_archived__exact", "")
            active_major = request.GET.get("majors__id__exact", "")

            majors_qs = Major.objects.order_by("order", "name")
            if not is_panel_su:
                user_book_ids = access.book_editor_ids(request.user, capability=None)
                majors_qs = majors_qs.filter(books__id__in=user_book_ids).distinct()

            response.context_data.update({
                "shelf_books": shelf_books,
                "shelf_majors": [
                    {
                        "id": str(m.pk),
                        "name": m.name,
                        "color": m.color,
                        "active": active_major == str(m.pk),
                        "href": _qs_with(majors__id__exact=None if active_major == str(m.pk) else m.pk),
                    }
                    for m in majors_qs
                ],
                "shelf_status_chips": [
                    {
                        "label": "همه کتاب‌ها",
                        "active": not active_published and not active_archived and not active_major,
                        "href": "?",
                    },
                    {
                        "label": "منتشرشده",
                        "active": active_published == "1",
                        "href": _qs_with(is_published__exact="1" if active_published != "1" else None, is_archived__exact=None),
                    },
                    {
                        "label": "پیش‌نویس",
                        "active": active_published == "0",
                        "href": _qs_with(is_published__exact="0" if active_published != "0" else None, is_archived__exact=None),
                    },
                    {
                        "label": "بایگانی",
                        "active": active_archived == "1",
                        "href": _qs_with(is_archived__exact="1" if active_archived != "1" else None, is_published__exact=None),
                    },
                ],
                "toggle_table_url": _qs_with(view="table"),
                "toggle_shelf_url": _qs_with(view="shelf"),
            })
        return response

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
            from .panel_display import fa_number

            chapters = []
            total_sections = 0
            total_questions = 0
            total_flashcards = 0
            for c in book.get_children().filter(kind=ContentNode.Kind.CHAPTER):
                ids = [c.pk, *c.get_descendants().values_list("pk", flat=True)]
                sec_count = c.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False).count()
                draft_count = c.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False, is_published=False).count()
                q_count = Question.objects.filter(node_id__in=ids, is_archived=False).count()
                fc_count = Flashcard.objects.filter(node_id__in=ids, is_archived=False).count()
                if not c.is_archived:
                    total_sections += sec_count
                    total_questions += q_count
                    total_flashcards += fc_count
                chapters.append({
                    "node": c,
                    "sections": sec_count,
                    "drafts": draft_count,
                    "questions": q_count,
                    "flashcards": fc_count,
                })
            extra["chapters"] = chapters
            extra["book_studio_stats"] = {
                "chapters": fa_number(sum(1 for c in chapters if not c["node"].is_archived)),
                "sections": fa_number(total_sections),
                "questions": fa_number(total_questions),
                "flashcards": fa_number(total_flashcards),
                "status_html": self.status(book),
                "major": book.majors.order_by("order", "name").first(),
            }
            from .bookpanel import book_health, gift_context

            is_panel_su = access.acts_as_panel_superuser(request)
            extra["health"] = book_health(book)
            extra["can_manage_access"] = is_panel_su
            from .models import BookEditor
            # Load assistants/editors for this book (both for teacher and superuser)
            assistants = []
            for ed in BookEditor.objects.filter(book=book).select_related("user"):
                is_self = (ed.user_id == request.user.id)
                assistants.append({
                    "pk": ed.pk,
                    "user": ed.user,
                    "phone": ed.user.phone,
                    "name": ed.user.full_name or ed.user.phone,
                    "can_edit_content": ed.can_edit_content,
                    "can_view_reports": ed.can_view_reports,
                    "can_view_aggregate_study": ed.can_view_aggregate_study,
                    "can_publish": ed.can_publish,
                    "note": ed.note,
                    "is_self": is_self,
                })
            extra["assistants"] = assistants
            has_real_assistants = any(not a["is_self"] for a in assistants)
            extra["has_real_assistants"] = has_real_assistants
            from .models import BookTeamTask, BookAssistantAuditLog
            extra["team_tasks"] = list(BookTeamTask.objects.filter(book=book).select_related("author"))
            extra["assistant_audit_logs"] = list(
                BookAssistantAuditLog.objects.filter(book=book).select_related("actor", "assistant_user")[:25]
            )
            can_view_study = bool(
                is_panel_su
                or access.is_teacher_preview(request)
                or (access.is_book_teacher(request.user) and BookEditor.objects.filter(book=book, user=request.user, can_view_aggregate_study=True).exists())
            )
            extra["can_view_study"] = can_view_study
            extra["can_view_classrooms_canvas"] = bool(
                is_panel_su or access.classroom_books_for_request(request).filter(pk=book.pk).exists()
            )
            extra["can_edit_book_content"] = access.can_edit_book(request.user, book)
            extra["can_export_technical_files"] = access.can_export_book_technical_files(request.user, book, request=request)
            if not is_panel_su and access.acts_as_panel_teacher(request):
                editor = BookEditor.objects.filter(book=book, user=request.user).first()
                is_preview = access.is_teacher_preview(request)
                extra["can_request_publication"] = bool(is_preview or (editor and editor.can_request_publication))
                extra["can_request_group_access"] = bool(is_preview or (editor and editor.can_request_group_access))
                from apps.website.models import PublicationRequest
                pub_req = PublicationRequest.objects.filter(book=book, requested_by=request.user).order_by("-submitted_at").first()
                extra["publication_request"] = pub_req
                extra["publication_offer"] = self._publication_offer_context(book, pub_req, request.user)
            else:
                extra["can_request_publication"] = False
                extra["can_request_group_access"] = False
            if is_panel_su:
                extra.update(gift_context(book))
            # The publish box reads this and not `original.is_published` alone: only the manager gets the control.
            extra["publish"] = (
                access.publish_state(request.user, book)
                if is_panel_su
                else {"can_publish": False, "why": "انتشار و بازکردن دسترسی دانشجویان فقط با مدیر کل است؛ استاد محتوا را پیش‌نویس و آماده می‌کند."}
            )
        return super().change_view(request, object_id, form_url, extra_context=extra)

    def get_urls(self):
        site = self.admin_site.admin_view
        custom = [
            path("ai-clean-chunk/", site(panel.ai_clean_chunk_action), name="catalog_ai_clean_chunk"),
            path("label-quick-create/", site(self.label_quick_create_api), name="catalog_label_quick_create"),
            path("new-major/", site(self.major_quick_create_api), name="catalog_major_quick_create"),
            path("new-draft/", site(self.teacher_create_book_view), name="catalog_book_teacher_new"),
            path("import/", site(lambda r: panel.import_view(self.admin_site, r)), name="catalog_import"),
            path("<int:book_id>/import/", site(lambda r, book_id: panel.import_view(self.admin_site, r, book_id)), name="catalog_book_import"),
            path("<int:book_id>/export/", site(panel.book_export), name="catalog_book_export"),
            path("<int:book_id>/export/tex/", site(panel.book_tex_export), name="catalog_book_tex_export"),
            path("<int:book_id>/email-export/", site(panel.book_email_export), name="catalog_book_email_export"),
            path("orphan/<int:node_id>/archive/", site(panel.archive_orphan), name="catalog_archive_orphan"),
            path("<int:book_id>/chapters/", site(panel.book_chapter_action), name="catalog_book_chapter_action"),
            path("<int:book_id>/assistants/", site(self.book_assistants_action), name="catalog_book_assistants_action"),
            path("<int:book_id>/team-tasks/", site(self.book_team_tasks_action), name="catalog_book_team_tasks_action"),
            path("study-analytics/", site(self.study_analytics_index_view), name="catalog_book_study_analytics_index"),
            path("<int:book_id>/study-analytics/", site(self.book_study_analytics_view), name="catalog_book_study_analytics"),
            path("<int:book_id>/classrooms/", site(lambda r, book_id: bookpanel.book_classrooms_canvas(self.admin_site, r, book_id)), name="catalog_book_classrooms_canvas"),
            path("<int:book_id>/trace/", site(self.book_trace_view), name="catalog_book_trace"),
            path("<int:book_id>/request-publication/", site(self.book_request_publication_view), name="catalog_book_request_publication"),
            path("<int:book_id>/respond-offer/", site(self.book_respond_offer_view), name="catalog_book_respond_offer"),
            path("<int:book_id>/publish/", site(lambda r, book_id: panel.book_publish(self.admin_site, r, book_id)),
                 name="catalog_book_publish"),
            path("<int:book_id>/inbox/", site(panel.open_book_inbox), name="catalog_book_inbox"),
            path("inbox/", site(panel.open_inbox), name="catalog_inbox"),
            path("<int:book_id>/gift/", site(bookpanel.book_gift), name="catalog_book_gift"),
            path("<int:book_id>/notify-waitlist/", site(lambda r, book_id: bookpanel.waitlist_notify(self.admin_site, r, book_id)),
                 name="catalog_book_waitlist_notify"),
            path("chapter/<int:chapter_id>/", site(lambda r, chapter_id: panel.chapter_manager(self.admin_site, r, chapter_id)), name="catalog_chapter_manager"),
            path("chapter/<int:chapter_id>/api/", site(panel.chapter_api), name="catalog_chapter_api"),
            path("chapter/<int:chapter_id>/file/", site(lambda r, chapter_id: panel.chapter_file(self.admin_site, r, chapter_id)), name="catalog_chapter_file"),
            path("chapter/<int:chapter_id>/export/", site(panel.chapter_export), name="catalog_chapter_export"),
            path("chapter/<int:chapter_id>/export/tex/", site(panel.chapter_tex), name="catalog_chapter_tex"),
            path("chapter/<int:chapter_id>/email-tex/", site(panel.chapter_email_tex), name="catalog_chapter_email_tex"),
            path("chapter/<int:chapter_id>/history/", site(lambda r, chapter_id: panel.chapter_history(self.admin_site, r, chapter_id)), name="catalog_chapter_history"),
            path("chapter/<int:chapter_id>/history/<int:revision_id>/", site(panel.revision_text), name="catalog_revision_text"),
        ]
        return custom + super().get_urls()

    def teacher_create_book_view(self, request):
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import render, redirect
        import re

        if not request.user.is_superuser and not access.is_book_teacher(request.user):
            raise PermissionDenied("فقط اساتید تأییدشده و مدیران امکان ایجاد کتاب دارند.")

        majors_all = list(Major.objects.order_by("order", "name"))
        valid_motifs = {v for v, _ in ContentNode.Motif.choices if v != ContentNode.Motif.CUSTOM}
        form_data = {
            "title": "",
            "title_en": "",
            "author": getattr(request.user, "full_name", "") or "",
            "edition": "",
            "about": "",
            "cover_motif": ContentNode.Motif.BOOK,
            "selected_majors": [],
        }

        if request.method == "POST":
            title = request.POST.get("title", "").strip()
            title_en = request.POST.get("title_en", "").strip()
            author = request.POST.get("author", "").strip()
            edition = request.POST.get("edition", "").strip()
            about = request.POST.get("about", "").strip()
            motif = (request.POST.get("cover_motif") or ContentNode.Motif.BOOK).strip()
            if motif not in valid_motifs:
                motif = ContentNode.Motif.BOOK
            selected_major_ids = [m for m in request.POST.getlist("majors") if str(m).isdigit()]

            form_data.update({
                "title": title,
                "title_en": title_en,
                "author": author,
                "edition": edition,
                "about": about,
                "cover_motif": motif,
                "selected_majors": [int(x) for x in selected_major_ids],
            })

            has_error = False
            if not title:
                messages.error(request, "عنوان کتاب الزامی است.")
                has_error = True

            cleaned_drawing = ""
            drawing_upload = request.FILES.get("drawing_file")
            if drawing_upload:
                if not drawing_upload.name.lower().endswith(".svg"):
                    messages.error(request, "برای طرح سفارشی فقط فایل SVG مجاز است.")
                    has_error = True
                else:
                    try:
                        cleaned_drawing = dumps_drawing(clean_svg(drawing_upload.read()))
                        motif = ContentNode.Motif.CUSTOM
                    except DrawingError as exc:
                        messages.error(request, str(exc))
                        has_error = True

            cleaned_cover = None
            cover_upload = request.FILES.get("cover")
            if cover_upload:
                try:
                    cleaned_cover = forms.ImageField().clean(cover_upload)
                except forms.ValidationError as exc:
                    messages.error(request, f"تصویر جلد معتبر نیست: {'، '.join(exc.messages)}")
                    has_error = True

            if not has_error:
                # Generate clean unique slug
                base_slug = re.sub(r"[^\w\s-]", "", title_en or title).strip()
                base_slug = re.sub(r"[-\s]+", "-", base_slug) or "book"
                slug_candidate = f"{base_slug}-{request.user.pk}".lower()
                suffix = 1
                while ContentNode.objects.filter(slug=slug_candidate).exists():
                    slug_candidate = f"{base_slug}-{request.user.pk}-{suffix}".lower()
                    suffix += 1

                default_author = (getattr(request.user, "full_name", "") or "").strip() or f"استاد {request.user.phone}"
                with transaction.atomic():
                    book = ContentNode(
                        kind=ContentNode.Kind.BOOK,
                        title=title,
                        title_en=title_en,
                        slug=slug_candidate,
                        author=author or default_author,
                        edition=edition,
                        about=about,
                        cover_motif=motif,
                        cover_drawing=cleaned_drawing,
                        is_published=False,  # strictly draft
                    )
                    if cleaned_cover:
                        book.cover = cleaned_cover
                    ContentNode.add_root(instance=book)
                    if selected_major_ids:
                        book.majors.set(Major.objects.filter(pk__in=selected_major_ids))

                    # Assign teacher as editor with full draft rights
                    from .models import BookEditor
                    BookEditor.objects.create(
                        book=book,
                        user=request.user,
                        can_edit_content=True,
                        can_request_publication=True,
                        can_request_group_access=True,
                        can_view_reports=True,
                        note="ایجادشده توسط مؤلف",
                    )

                    # Optional initial file import (kept for compatibility if submitted)
                    initial_file = request.FILES.get("initial_file")
                    imported_summary = ""
                    if initial_file:
                        from .importer import read_upload, check_against_db, apply_chapter
                        data = initial_file.read()
                        parsed = read_upload(initial_file.name, data, book=book)
                        check_against_db(parsed)
                        if not parsed.errors:
                            res = apply_chapter(parsed, publish=False)
                            imported_summary = f" همچنین فصل «{res.chapter.title}» با موفقیت از فایل وارد شد."
                        else:
                            messages.warning(request, f"کتاب ایجاد شد، اما فایل اولیه به دلیل خطا وارد نشد: {'، '.join(str(e) for e in parsed.errors[:3])}")

                messages.success(
                    request,
                    f"جلد کتاب پیش‌نویس «{book.title}» ساخته شد.{imported_summary} اکنون می‌توانید فصل‌ها را بنویسید یا کتاب آماده را با هوش مصنوعی وارد کنید.",
                )
                return redirect(reverse("admin:catalog_book_change", args=[book.pk]))

        context = {
            **self.admin_site.each_context(request),
            "title": "ساخت جلد و کتاب پیش‌نویس تازه",
            "opts": self.model._meta,
            "majors": majors_all,
            "majors_json": self._majors_json(),
            "motifs": [(v, l) for v, l in ContentNode.Motif.choices if v != ContentNode.Motif.CUSTOM],
            "form_data": form_data,
        }
        return render(request, "admin/catalog/book/teacher_create_book.html", context)

    def label_quick_create_api(self, request):
        from django.http import JsonResponse
        from django.views.decorators.http import require_POST
        from .labels import forget, normalize
        from .models import Label

        if not request.user.is_authenticated or not request.user.is_staff:
            return JsonResponse({"ok": False, "error": "دسترسی غیرمجاز."}, status=403)

        name = normalize((request.POST.get("name") or "").strip())
        if not name:
            return JsonResponse({"ok": False, "error": "نام برچسب نمی‌تواند خالی باشد."}, status=400)
        if len(name) > 40:
            return JsonResponse({"ok": False, "error": "نام برچسب حداکثر ۴۰ نویسه است."}, status=400)

        style = (request.POST.get("style") or "note").strip().lower()
        if style not in dict(Label.Style.choices):
            style = Label.Style.NOTE

        icon = (request.POST.get("icon") or "").strip()
        group = (request.POST.get("group") or "برچسب‌های اختصاصی").strip()[:40]

        existing = Label.objects.filter(name=name).first()
        if existing:
            return JsonResponse({
                "ok": True,
                "label": {
                    "id": existing.id,
                    "name": existing.name,
                    "style": existing.style,
                    "icon": existing.icon,
                    "group": existing.group,
                },
                "is_existing": True,
            })

        label = Label.objects.create(
            name=name,
            style=style,
            icon=icon,
            group=group,
            created_by=request.user if not request.user.is_superuser else None,
        )
        forget()
        return JsonResponse({
            "ok": True,
            "label": {
                "id": label.id,
                "name": label.name,
                "style": label.style,
                "icon": label.icon,
                "group": label.group,
            },
            "is_existing": False,
        })

    def major_quick_create_api(self, request):
        import re
        from django.http import JsonResponse

        if request.method != "POST":
            return JsonResponse({"ok": False, "error": "فقط درخواست POST مجاز است."}, status=405)
        if not request.user.is_authenticated or not request.user.is_staff or (
            not request.user.is_superuser and not access.is_book_teacher(request.user)
        ):
            return JsonResponse({"ok": False, "error": "دسترسی غیرمجاز."}, status=403)

        name = " ".join((request.POST.get("name") or "").split()).strip()
        if not name:
            return JsonResponse({"ok": False, "error": "نام رشته نمی‌تواند خالی باشد."}, status=400)
        if len(name) > 80:
            return JsonResponse({"ok": False, "error": "نام رشته حداکثر ۸۰ نویسه است."}, status=400)

        color = (request.POST.get("color") or "#3FB8A9").strip()
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
            color = "#3FB8A9"

        existing = Major.objects.filter(name__iexact=name).first()
        if existing:
            return JsonResponse({
                "ok": True,
                "major": {
                    "id": existing.id,
                    "name": existing.name,
                    "color": existing.color,
                    "slug": existing.slug,
                },
                "is_existing": True,
            })

        base_slug = re.sub(r"[^a-zA-Z0-9-]+", "-", name).strip("-").lower() or "major"
        slug_candidate = base_slug[:42]
        suffix = 1
        while Major.objects.filter(slug=slug_candidate).exists():
            suffix += 1
            slug_candidate = f"{base_slug[:36]}-{suffix}"
        if slug_candidate == "major":
            n = Major.objects.count() + 1
            while Major.objects.filter(slug=f"major-{n}").exists():
                n += 1
            slug_candidate = f"major-{n}"

        major = Major.objects.create(
            name=name,
            slug=slug_candidate,
            color=color.upper(),
            order=(Major.objects.order_by("-order").values_list("order", flat=True).first() or 0) + 1,
        )
        return JsonResponse({
            "ok": True,
            "major": {
                "id": major.id,
                "name": major.name,
                "color": major.color,
                "slug": major.slug,
            },
            "is_existing": False,
        })

    def book_assistants_action(self, request, book_id):
        from django.contrib import messages
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import get_object_or_404, redirect
        from apps.accounts.views import _client_ip
        from .access import BOOK_EDITOR_GROUP, can_edit_book
        from .models import BookEditor, BookAssistantAuditLog

        book = get_object_or_404(ContentNode, pk=book_id, kind=ContentNode.Kind.BOOK)
        if not can_edit_book(request.user, book):
            raise PermissionDenied("دسترسی مدیریت دستیاران این کتاب را ندارید.")

        if request.method != "POST":
            return redirect(reverse("admin:catalog_book_change", args=[book.pk]))

        client_ip = _client_ip(request)
        action = request.POST.get("action")
        if action == "add":
            phone = (request.POST.get("phone") or "").strip().translate(str.maketrans("۰۱۲۳۴۵۶۷۸۹", "0123456789"))
            if not phone.startswith("09") or len(phone) != 11 or not phone.isdigit():
                messages.error(request, "شماره موبایل نامعتبر است (باید ۱۱ رقم و با 09 شروع شود).")
                return redirect(reverse("admin:catalog_book_change", args=[book.pk]) + "#assistants")

            can_edit_content = bool(request.POST.get("can_edit_content"))
            can_view_reports = bool(request.POST.get("can_view_reports"))
            can_view_aggregate_study = bool(request.POST.get("can_view_aggregate_study"))
            note = (request.POST.get("note") or "").strip()[:200]

            perms_list = []
            if can_edit_content:
                perms_list.append("ویرایش محتوا")
            if can_view_reports:
                perms_list.append("گزارش ایرادها")
            if can_view_aggregate_study:
                perms_list.append("آمار مطالعه")
            perms_str = "، ".join(perms_list) if perms_list else "بدون مجوز تخصصی"
            if note:
                perms_str += f" (یادداشت: {note})"

            User = get_user_model()
            user, _ = User.objects.get_or_create(phone=phone)
            if not user.is_staff:
                user.is_staff = True
                user.save(update_fields=["is_staff"])
            group = Group.objects.filter(name=BOOK_EDITOR_GROUP).first()
            if group:
                user.groups.add(group)

            editor, created = BookEditor.objects.get_or_create(
                book=book,
                user=user,
                defaults={
                    "can_edit_content": can_edit_content,
                    "can_view_reports": can_view_reports,
                    "can_view_aggregate_study": can_view_aggregate_study,
                    "note": note,
                }
            )
            if not created:
                editor.can_edit_content = can_edit_content
                editor.can_view_reports = can_view_reports
                editor.can_view_aggregate_study = can_view_aggregate_study
                if note:
                    editor.note = note
                editor.save(update_fields=["can_edit_content", "can_view_reports", "can_view_aggregate_study", "note"])
                BookAssistantAuditLog.objects.create(
                    book=book,
                    actor=request.user,
                    assistant_user=user,
                    assistant_phone=phone,
                    action=BookAssistantAuditLog.Action.UPDATED,
                    details=f"به‌روزرسانی دسترسی‌ها: {perms_str}",
                    ip=client_ip,
                )
                messages.success(request, f"دسترسی‌های دستیار با شماره {phone} به‌روزرسانی شد.")
            else:
                BookAssistantAuditLog.objects.create(
                    book=book,
                    actor=request.user,
                    assistant_user=user,
                    assistant_phone=phone,
                    action=BookAssistantAuditLog.Action.ADDED,
                    details=f"افزودن دستیار جدید: {perms_str}",
                    ip=client_ip,
                )
                messages.success(request, f"دستیار آموزشی با شماره {phone} با موفقیت به کتاب اضافه شد.")
                # Send SMS notification to assistant
                try:
                    from apps.accounts.sms import send_sms
                    sms_text = f"سلام، شما به عنوان دستیار آموزشی به کتاب «{book.title}» در سامانه لیمو افزوده شدید."
                    send_sms(phone, sms_text)
                except Exception:
                    pass

        elif action == "remove":
            editor_id = request.POST.get("editor_id")
            editor = BookEditor.objects.filter(pk=editor_id, book=book).first()
            if not editor:
                messages.error(request, "دستیار پیدا نشد.")
            elif editor.user_id == request.user.id and not request.user.is_superuser:
                messages.error(request, "امکان حذف دسترسی خودتان وجود ندارد.")
            else:
                phone = editor.user.phone
                assistant_user = editor.user
                editor.delete()
                BookAssistantAuditLog.objects.create(
                    book=book,
                    actor=request.user,
                    assistant_user=assistant_user,
                    assistant_phone=phone,
                    action=BookAssistantAuditLog.Action.REMOVED,
                    details="حذف کامل دسترسی دستیار از کتاب",
                    ip=client_ip,
                )
                messages.success(request, f"دسترسی دستیار با شماره {phone} از این کتاب حذف شد.")

        return redirect(reverse("admin:catalog_book_change", args=[book.pk]) + "#assistants")

    def study_analytics_index_view(self, request):
        from django.core.exceptions import PermissionDenied
        from django.db.models import Count
        from django.db.models.functions import Substr
        from django.shortcuts import get_object_or_404, render
        from apps.catalog.panel_display import fa_number
        from apps.study.models import SectionProgress
        from .models import BookEditor

        if not request.user.is_superuser and not access.is_book_teacher(request.user):
            raise PermissionDenied("شما مجوز مشاهده گزارش مطالعهٔ کتاب‌ها را ندارید.")

        if request.user.is_superuser:
            books_qs = ContentNode.objects.filter(
                kind=ContentNode.Kind.BOOK, depth=1, is_inbox=False, is_archived=False
            ).order_by("title")
        else:
            allowed_ids = BookEditor.objects.filter(
                user=request.user, can_view_aggregate_study=True
            ).values_list("book_id", flat=True)
            books_qs = ContentNode.objects.filter(
                pk__in=allowed_ids, kind=ContentNode.Kind.BOOK, depth=1, is_inbox=False, is_archived=False
            ).order_by("title")

        selected_id = (request.GET.get("book_id") or "").strip()
        if selected_id.isdigit():
            chosen = get_object_or_404(books_qs, pk=int(selected_id))
            return redirect(reverse("admin:catalog_book_study_analytics", args=[chosen.pk]))

        books = list(books_qs)
        book_ids = [b.pk for b in books]
        readers_by_book = dict(
            SectionProgress.objects.filter(book_id__in=book_ids)
            .values("book_id")
            .annotate(c=Count("user_id", distinct=True))
            .values_list("book_id", "c")
        ) if book_ids else {}
        step = ContentNode.steplen
        book_paths = [b.path for b in books]
        chapters_by_path = dict(
            ContentNode.objects.filter(depth=2, kind=ContentNode.Kind.CHAPTER, is_archived=False)
            .annotate(root_path=Substr("path", 1, step))
            .filter(root_path__in=book_paths)
            .values("root_path")
            .annotate(c=Count("pk"))
            .values_list("root_path", "c")
        ) if book_paths else {}

        rows = [
            {
                "pk": b.pk,
                "title": b.title,
                "author": b.author,
                "is_published": b.is_published,
                "chapters_count": fa_number(chapters_by_path.get(b.path, 0)),
                "readers_count": fa_number(readers_by_book.get(b.pk, 0)),
            }
            for b in books
        ]
        context = {
            **self.admin_site.each_context(request),
            "title": "گزارش مطالعهٔ کتاب‌ها",
            "books": rows,
            "opts": self.model._meta,
        }
        return render(request, "admin/catalog/book/study_analytics_index.html", context)

    def book_study_analytics_view(self, request, book_id):
        from django.core.exceptions import PermissionDenied
        from django.db.models import Count, F, FloatField, Sum
        from django.db.models.functions import Cast
        from django.shortcuts import get_object_or_404, render
        from apps.catalog.jalali import fa_digits
        from apps.catalog.panel_display import fa_number
        from apps.learning.models import Question
        from apps.study.admin import _hms
        from apps.study.models import SectionProgress, StudyTime
        from .models import BookEditor

        book = get_object_or_404(ContentNode, pk=book_id, kind=ContentNode.Kind.BOOK)
        can_view_study = bool(
            request.user.is_superuser
            or (access.is_book_teacher(request.user) and BookEditor.objects.filter(book=book, user=request.user, can_view_aggregate_study=True).exists())
        )
        if not can_view_study:
            raise PermissionDenied("شما مجوز مشاهده آمار مطالعه این کتاب را ندارید.")

        total_readers = SectionProgress.objects.filter(book=book).values("user").distinct().count()
        completed_readers = SectionProgress.objects.filter(book=book, is_done=True).values("user").distinct().count()
        total_seconds = StudyTime.objects.filter(book=book).aggregate(s=Sum("seconds"))["s"] or 0

        chapters = ContentNode.objects.filter(path__startswith=book.path, depth=2, is_archived=False).order_by("path")
        chapter_stats = []
        for ch in chapters:
            ch_sec_ids = ContentNode.objects.filter(path__startswith=ch.path, depth=3, is_archived=False).values_list("pk", flat=True)
            ch_progress = SectionProgress.objects.filter(node_id__in=ch_sec_ids)
            ch_readers = ch_progress.values("user").distinct().count()
            ch_done = ch_progress.filter(is_done=True).values("user").distinct().count()
            ch_time = StudyTime.objects.filter(node_id__in=ch_sec_ids).aggregate(s=Sum("seconds"))["s"] or 0
            rate = round(100 * ch_done / max(1, ch_readers)) if ch_readers else 0
            chapter_stats.append({
                "title": ch.title,
                "sections_count": len(ch_sec_ids),
                "readers": fa_number(ch_readers),
                "done": fa_number(ch_done),
                "rate": fa_digits(rate),
                "total_time": _hms(ch_time) if ch_time else "—",
                "avg_time": _hms(ch_time // max(1, ch_readers)) if ch_readers and ch_time else "—",
            })

        questions = (
            Question.objects.filter(node__path__startswith=book.path, answer_count__gte=3, is_archived=False)
            .select_related("node")
            .annotate(rate=Cast("correct_count", FloatField()) / F("answer_count"))
            .order_by("rate", "id")[:10]
        )
        hardest_questions = []
        for q in questions:
            correct_pct = round(100 * q.correct_count / q.answer_count)
            error_pct = max(0, 100 - correct_pct)
            hardest_questions.append({
                "id": q.id,
                "stem": q.stem[:140],
                "chapter_or_section": q.node.title if q.node else "—",
                "rate": fa_digits(correct_pct),
                "error_rate": fa_digits(error_pct),
                "error_rate_num": error_pct,
                "answer_count": fa_number(q.answer_count),
            })

        if request.GET.get("format") == "csv":
            import csv
            from django.http import HttpResponse
            response = HttpResponse(content_type="text/csv; charset=utf-8-sig")
            response["Content-Disposition"] = f'attachment; filename="study-{book.slug}.csv"'
            writer = csv.writer(response)
            writer.writerow(["عنوان کتاب", book.title])
            writer.writerow(["تعداد کل خوانندگان", total_readers])
            writer.writerow(["تکمیل‌کنندگان", completed_readers])
            writer.writerow([])
            writer.writerow(["عنوان فصل", "تعداد بخش", "تعداد خوانندگان", "تکمیل‌کنندگان", "درصد پیشرفت", "کل زمان مطالعه", "میانگین زمان مطالعه هر دانشجو"])
            for ch in chapter_stats:
                writer.writerow([ch["title"], ch["sections_count"], ch["readers"], ch["done"], f"{ch['rate']}٪", ch["total_time"], ch["avg_time"]])
            return response

        context = {
            **self.admin_site.each_context(request),
            "title": f"آمار و پیشرفت مطالعه کلاس: {book.title}",
            "book": book,
            "total_readers": fa_number(total_readers),
            "completed_readers": fa_number(completed_readers),
            "total_time": _hms(total_seconds) if total_seconds else "—",
            "chapter_stats": chapter_stats,
            "hardest_questions": hardest_questions,
            "opts": self.model._meta,
        }
        return render(request, "admin/catalog/book/book_study_analytics.html", context)

    def book_trace_view(self, request, book_id):
        from django.core.cache import cache
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import get_object_or_404, render
        from apps.catalog.jalali import jalali_datetime
        from apps.guard import core
        from apps.guard.models import CopyEvent, TraceHit

        book = get_object_or_404(ContentNode, pk=book_id, kind=ContentNode.Kind.BOOK)
        if not access.can_edit_book(request.user, book):
            raise PermissionDenied("شما مجوز ردیابی و مدیریت محتوای این کتاب را ندارید.")

        found = None
        pasted = ""
        searched = False
        rate_limit_exceeded = False

        # سقف استعلام ساعتی برای کاربران غیر مدیر کل (حداکثر ۱۰ استعلام در ساعت)
        RATE_LIMIT = 10
        TIMEOUT = 3600
        cache_key = f"trace_rate:{request.user.id}:{book.id}"

        if request.method == "POST":
            if not request.user.is_superuser:
                current_hits = cache.get(cache_key, 0)
                if current_hits >= RATE_LIMIT:
                    rate_limit_exceeded = True
                else:
                    cache.set(cache_key, current_hits + 1, timeout=TIMEOUT)

            searched = True
            pasted = request.POST.get("text", "")[:20000]
            if not rate_limit_exceeded:
                result = core.trace(pasted, events=CopyEvent.objects.filter(node__path__startswith=book.path))

                marked_events = result["marked"]
                similar_events = result["similar"]

                # ثبت لاگ استعلام موفق در TraceHit
                for e in marked_events:
                    TraceHit.objects.get_or_create(event=e, found_by=request.user)

                def _fmt_row(event):
                    # ماسک کردن هویت دانشجو با منطق مشترک حفظ حریم خصوصی
                    display_user = core.masked_user_label(event.user, fallback="دانشجو")

                    exact = core.is_exact(event) if not event.packed else None
                    state = "متن ذخیره‌شده" if event.packed else ("نشانی دقیق" if exact else "نسخه تغییریافته")

                    return {
                        "display_user": display_user,
                        "when": jalali_datetime(event.created_at),
                        "node_title": event.node.title if event.node else "—",
                        "text": core.text_of(event),
                        "state": state,
                    }

                found = {
                    "marked": [_fmt_row(e) for e in marked_events],
                    "similar": [_fmt_row(e) for e in similar_events],
                }

        context = {
            **self.admin_site.each_context(request),
            "title": f"ردیاب کپی و اصالت اثر: {book.title}",
            "book": book,
            "found": found,
            "pasted": pasted,
            "searched": searched,
            "rate_limit_exceeded": rate_limit_exceeded,
            "opts": self.model._meta,
        }
        return render(request, "admin/catalog/book/book_trace.html", context)

    @staticmethod
    def _publication_offer_context(book, pub_req, user):
        if not pub_req:
            return None
        from apps.commerce.models import BookAuthorShare
        from apps.website.models import PublicationRequest
        from .jalali import jalali_datetime
        from .models import BookEditor

        summary = pub_req.workflow_summary()
        active_shares = list(BookAuthorShare.objects.filter(royalty_rule__book=book, is_active=True))
        editors_count = BookEditor.objects.filter(book=book).count()
        is_multi_author = len(active_shares) > 1 or editors_count > 1
        user_share_percent = next(
            (s.share_percent for s in active_shares if s.author_id == getattr(user, "pk", None)),
            None,
        )

        sent_offer = None
        if pub_req.has_sent_offer:
            snap = pub_req.sent_offer_snapshot or {}
            fee = int(snap.get("platform_fee_percent"))
            authors_total = 100 - fee
            example_base = 400_000
            example_platform = round(example_base * fee / 100)
            example_authors_total = example_base - example_platform
            fa_trans = str.maketrans("0123456789,", "۰۱۲۳۴۵۶۷۸۹٬")
            sent_offer = {
                "version": pub_req.sent_offer_version,
                "digest": pub_req.sent_offer_digest,
                "sent_at_fa": jalali_datetime(pub_req.offer_sent_at) if pub_req.offer_sent_at else "",
                "platform_fee_percent": fee,
                "authors_total_percent": authors_total,
                "example_base": example_base,
                "example_platform": example_platform,
                "example_authors_total": example_authors_total,
                "example_base_fa": f"{example_base:,}".translate(fa_trans),
                "example_platform_fa": f"{example_platform:,}".translate(fa_trans),
                "example_authors_total_fa": f"{example_authors_total:,}".translate(fa_trans),
                "prep_mode_label": snap.get("prep_mode_label") or "—",
                "distribution_scope": snap.get("distribution_scope") or "",
                "distribution_scope_label": snap.get("distribution_scope_label") or "—",
                "campaign_discount_cap": snap.get("campaign_discount_cap"),
                "rate_validity_note": snap.get("rate_validity_note") or "",
                "technical_deliverable": snap.get("technical_deliverable") or "",
                "technical_export_disabled": bool(snap.get("technical_export_disabled")),
                "offer_note": snap.get("offer_note") or "",
            }

        accepted_offer = None
        if pub_req.accepted_offer_version:
            acc = pub_req.accepted_offer_snapshot or {}
            accepted_offer = {
                "version": pub_req.accepted_offer_version,
                "fee_percent": acc.get("platform_fee_percent"),
                "authors_total_percent": acc.get("authors_total_percent"),
                "distribution_scope_label": acc.get("distribution_scope_label") or "",
                "prep_mode_label": acc.get("prep_mode_label") or "",
                "accepted_at_fa": jalali_datetime(pub_req.teacher_responded_at) if pub_req.teacher_responded_at else "",
                "is_current": pub_req.is_current_offer_accepted,
                "is_superseded": pub_req.has_superseded_acceptance,
            }

        can_respond = bool(
            not getattr(user, "is_superuser", False)
            and pub_req.has_sent_offer
            and pub_req.status in (PublicationRequest.Status.PENDING, PublicationRequest.Status.NEEDS_INFO)
            and not pub_req.is_current_offer_accepted
        )
        return {
            "summary": summary,
            "sent_offer": sent_offer,
            "accepted_offer": accepted_offer,
            "is_multi_author": is_multi_author,
            "user_share_percent": user_share_percent,
            "can_respond": can_respond,
            "is_superuser_preview": bool(getattr(user, "is_superuser", False)),
            "teacher_response": pub_req.teacher_response,
            "teacher_response_note": pub_req.teacher_response_note,
        }

    def book_respond_offer_view(self, request, book_id):
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied, ValidationError
        from django.shortcuts import get_object_or_404, redirect
        from apps.website.models import PublicationRequest
        from apps.website.publication import respond_to_publication_offer

        book = get_object_or_404(ContentNode, pk=book_id, kind=ContentNode.Kind.BOOK)
        if request.method != "POST":
            return redirect(reverse("admin:catalog_book_change", args=[book.pk]) + "#publish")

        req_id = request.POST.get("request_id")
        decision = (request.POST.get("decision") or "").strip()
        note = (request.POST.get("response_note") or "").strip()
        expected_digest = (request.POST.get("expected_offer_digest") or "").strip()
        raw_version = (request.POST.get("expected_offer_version") or "").strip()
        try:
            expected_version = int(raw_version) if raw_version else None
        except (TypeError, ValueError):
            expected_version = None
        return_to = (request.POST.get("return_to") or "").strip()
        req_obj = get_object_or_404(PublicationRequest, pk=req_id, book=book)

        try:
            updated = respond_to_publication_offer(
                req_obj.pk,
                actor=request.user,
                decision=decision,
                note=note,
                expected_offer_digest=expected_digest,
                expected_offer_version=expected_version,
            )
            if updated.teacher_response == PublicationRequest.TeacherResponse.ACCEPTED:
                messages.success(
                    request,
                    f"نسخه #{updated.accepted_offer_version} پیشنهاد با موفقیت پذیرفته شد. اکنون نوبت مدیر کل است تا انتشار نهایی را انجام دهد.",
                )
            else:
                messages.info(
                    request,
                    f"درخواست بازنگری شما روی نسخه #{updated.sent_offer_version} ثبت شد و به مدیر کل ارجاع گردید.",
                )
        except PermissionError as exc:
            raise PermissionDenied(str(exc)) from exc
        except ValidationError as exc:
            messages.error(request, " ".join(exc.messages) if hasattr(exc, "messages") else str(exc))

        if return_to == "request_page":
            return redirect(reverse("admin:catalog_book_request_publication", args=[book.pk]))
        return redirect(reverse("admin:catalog_book_change", args=[book.pk]) + "#publish")

    def book_request_publication_view(self, request, book_id):
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import get_object_or_404, redirect, render
        from apps.website.models import PublicationRequest, PublicationRequestEvent
        from apps.website.publication import publication_content_digest, record_publication_request
        from .models import BookEditor

        book = get_object_or_404(ContentNode, pk=book_id, kind=ContentNode.Kind.BOOK)
        if request.user.is_superuser:
            messages.info(request, "شما به عنوان مدیر کل می‌توانید مستقیماً کتاب را منتشر کنید.")
            return redirect(reverse("admin:catalog_book_change", args=[book.pk]) + "#publish")

        editor = BookEditor.objects.filter(book=book, user=request.user, can_request_publication=True).first()
        if not editor or not access.is_book_teacher(request.user):
            raise PermissionDenied("شما دسترسی ارسال درخواست بازبینی انتشار این کتاب را ندارید.")

        latest_req = PublicationRequest.objects.filter(book=book, requested_by=request.user).order_by("-submitted_at").first()

        if request.method == "POST":
            note = request.POST.get("note", "").strip()
            prep_pref = (request.POST.get("author_prep_preference") or "").strip()
            if prep_pref not in dict(PublicationRequest.PrepPreference.choices):
                prep_pref = ""
            dist_scope = (request.POST.get("requested_distribution_scope") or PublicationRequest.DistributionScope.STANDARD).strip()
            if dist_scope not in dict(PublicationRequest.DistributionScope.choices):
                dist_scope = PublicationRequest.DistributionScope.STANDARD
            exception_reason = (request.POST.get("single_sale_exception_reason") or "").strip()[:1000]
            digest = publication_content_digest(book)

            # Check if pending request exists
            pending = PublicationRequest.objects.filter(
                book=book,
                requested_by=request.user,
                status__in=(PublicationRequest.Status.PENDING, PublicationRequest.Status.NEEDS_INFO),
            ).first()

            if pending:
                pending.request_note = note
                pending.author_prep_preference = prep_pref
                pending.requested_distribution_scope = dist_scope
                pending.single_sale_exception_reason = exception_reason
                pending.content_digest = digest
                pending.status = PublicationRequest.Status.PENDING
                pending.save(update_fields=[
                    "request_note",
                    "author_prep_preference",
                    "requested_distribution_scope",
                    "single_sale_exception_reason",
                    "content_digest",
                    "status",
                ])
                record_publication_request(pending, actor=request.user, action=PublicationRequestEvent.Action.SUBMITTED, reason=note)
                messages.success(request, "درخواست بازبینی شما با موفقیت به‌روزرسانی شد و برای مدیر کل ارسال گردید.")
                try:
                    from apps.catalog.backups import notify_bale
                    user_desc = f"{request.user.phone}" + (f" ({request.user.full_name})" if getattr(request.user, 'full_name', None) else "")
                    notify_bale(
                        f"📢 به‌روزرسانی درخواست انتشار کتاب\n"
                        f"کتاب: {book.title}\n"
                        f"استاد/مؤلف: {user_desc}\n"
                        f"توضیحات: {note or 'بدون توضیح'}"
                    )
                except Exception:
                    pass
            else:
                new_req = PublicationRequest.objects.create(
                    book=book,
                    requested_by=request.user,
                    request_note=note,
                    author_prep_preference=prep_pref,
                    requested_distribution_scope=dist_scope,
                    single_sale_exception_reason=exception_reason,
                    content_digest=digest,
                    status=PublicationRequest.Status.PENDING,
                )
                record_publication_request(new_req, actor=request.user, action=PublicationRequestEvent.Action.SUBMITTED, reason=note)
                messages.success(request, f"درخواست بازبینی انتشار کتاب «{book.title}» با موفقیت برای مدیر کل ارسال شد.")
                try:
                    from apps.catalog.backups import notify_bale
                    user_desc = f"{request.user.phone}" + (f" ({request.user.full_name})" if getattr(request.user, 'full_name', None) else "")
                    notify_bale(
                        f"📚 درخواست جدید انتشار کتاب\n"
                        f"کتاب: {book.title}\n"
                        f"استاد/مؤلف: {user_desc}\n"
                        f"توضیحات: {note or 'بدون توضیح'}"
                    )
                except Exception:
                    pass

            return redirect(reverse("admin:catalog_book_change", args=[book.pk]) + "#publish")

        context = {
            **self.admin_site.each_context(request),
            "title": f"درخواست بازبینی انتشار: {book.title}",
            "book": book,
            "latest_req": latest_req,
            "publication_offer": self._publication_offer_context(book, latest_req, request.user),
            "prep_choices": PublicationRequest.PrepPreference.choices,
            "scope_choices": PublicationRequest.DistributionScope.choices,
            "opts": self.model._meta,
        }
        return render(request, "admin/catalog/book/book_request_publication.html", context)

    def book_team_tasks_action(self, request, book_id):
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import get_object_or_404, redirect
        from .models import BookTeamTask, BookEditor

        book = get_object_or_404(ContentNode, pk=book_id, kind=ContentNode.Kind.BOOK)
        is_editor = (
            request.user.is_superuser
            or (access.is_book_teacher(request.user) and BookEditor.objects.filter(book=book, user=request.user).exists())
        )
        if not is_editor:
            raise PermissionDenied("دسترسی به یادداشت‌های هماهنگی این کتاب را ندارید.")

        if request.method != "POST":
            return redirect(reverse("admin:catalog_book_change", args=[book.pk]) + "#team-notes")

        action = request.POST.get("action")
        if action == "add":
            text = request.POST.get("text", "").strip()
            if text:
                BookTeamTask.objects.create(book=book, author=request.user, text=text[:300])
                messages.success(request, "یادداشت هماهنگی با موفقیت اضافه شد.")
            else:
                messages.error(request, "متن یادداشت نمی‌تواند خالی باشد.")
        elif action == "toggle":
            task_id = request.POST.get("task_id")
            task = BookTeamTask.objects.filter(pk=task_id, book=book).first()
            if task:
                task.is_done = not task.is_done
                task.save(update_fields=["is_done"])
                messages.success(request, "وضعیت یادداشت به‌روزرسانی شد.")
        elif action == "delete":
            task_id = request.POST.get("task_id")
            task = BookTeamTask.objects.filter(pk=task_id, book=book).first()
            if task and (request.user.is_superuser or task.author_id == request.user.id or access.can_edit_book(request.user, book)):
                task.delete()
                messages.success(request, "یادداشت حذف شد.")

        return redirect(reverse("admin:catalog_book_change", args=[book.pk]) + "#team-notes")



class GroupFilter(admin.SimpleListFilter):
    title = "گروه"
    parameter_name = "group"

    def lookups(self, request, model_admin):
        qs = model_admin.get_queryset(request).exclude(group="")
        chapter_id = request.GET.get("chapter")
        chapter = ContentNode.objects.filter(pk=chapter_id, kind=ContentNode.Kind.CHAPTER).first() if chapter_id else None
        if chapter:
            qs = qs.filter(path__startswith=chapter.path) if access.can_edit_book(request.user, chapter.book()) else qs.none()
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
        qs = super().get_queryset(request).filter(kind=ContentNode.Kind.SECTION).annotate(
            n_questions=Count("questions", filter=Q(questions__is_archived=False), distinct=True),
            n_flashcards=Count("flashcards", filter=Q(flashcards__is_archived=False), distinct=True),
            p_chapter_id=Subquery(chapter.values("pk")[:1]),
            p_chapter_pos=Subquery(chapter.values("position")[:1]),
            p_chapter_title=Subquery(chapter.values("title")[:1]),
            p_book=Subquery(book.values("title")[:1]),
        ).order_by("path")
        return access.scope_to_editor_books(qs, request.user, "path")

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
        node = self.get_queryset(request).filter(pk=object_id).first()
        if node and (c := node.get_parent()):
            return redirect(reverse("admin:catalog_chapter_manager", args=[c.pk]) + f"#s={node.slug}")
        return super().change_view(request, object_id, form_url, extra_context)


class TeacherInactivityFilter(admin.SimpleListFilter):
    title = "وضعیت فعالیت تألیف محتوا"
    parameter_name = "inactivity_period"

    def lookups(self, request, model_admin):
        return (
            ("active_7", "فعال در ۷ روز اخیر"),
            ("inactive_15", "بدون تغییر محتوا در ۱۵ روز گذشته"),
            ("inactive_30", "بدون تغییر محتوا در ۳۰ روز گذشته"),
            ("inactive_60", "بدون تغییر محتوا در ۶۰ روز گذشته"),
            ("never", "بدون سابقه ویرایش فصول"),
        )

    def queryset(self, request, queryset):
        from datetime import timedelta
        from django.utils import timezone
        from apps.catalog.models import ContentNode

        val = self.value()
        if not val:
            return queryset

        now = timezone.now()
        # Find books with recent or older updates in their tree (chapters, sections, revisions)
        if val == "active_7":
            recent_books = ContentNode.objects.filter(
                kind=ContentNode.Kind.BOOK,
                updated_at__gte=now - timedelta(days=7),
            ).values_list("pk", flat=True)
            return queryset.filter(book_id__in=recent_books)

        if val == "inactive_15":
            cutoff = now - timedelta(days=15)
            inactive_books = ContentNode.objects.filter(
                kind=ContentNode.Kind.BOOK,
                updated_at__lt=cutoff,
            ).values_list("pk", flat=True)
            return queryset.filter(book_id__in=inactive_books)

        if val == "inactive_30":
            cutoff = now - timedelta(days=30)
            inactive_books = ContentNode.objects.filter(
                kind=ContentNode.Kind.BOOK,
                updated_at__lt=cutoff,
            ).values_list("pk", flat=True)
            return queryset.filter(book_id__in=inactive_books)

        if val == "inactive_60":
            cutoff = now - timedelta(days=60)
            inactive_books = ContentNode.objects.filter(
                kind=ContentNode.Kind.BOOK,
                updated_at__lt=cutoff,
            ).values_list("pk", flat=True)
            return queryset.filter(book_id__in=inactive_books)

        return queryset


@admin.register(BookEditor)
class BookEditorAdmin(admin.ModelAdmin):
    """«استادان کتاب»: only the manager assigns a reviewed, approved editor to a book."""

    list_display = (
        "book", "user", "last_book_update", "can_edit_content", "can_request_publication", "can_request_group_access",
        "can_view_reports", "can_view_aggregate_study", "can_view_aggregate_sales", "can_publish", "note", "created_at",
    )
    list_filter = (
        TeacherInactivityFilter,
        "can_edit_content", "can_request_publication", "can_request_group_access", "can_view_reports",
        "can_view_aggregate_study", "can_view_aggregate_sales", BookFilter,
    )
    search_fields = ("book__title", "user__phone", "user__first_name", "user__last_name", "note")
    list_select_related = ("book", "user")


    @admin.display(description="آخرین ویرایش کتاب")
    def last_book_update(self, obj):
        from apps.catalog.panel_display import fa_number
        from apps.catalog.jalali import jalali_date
        from django.utils import timezone
        diff = timezone.now() - obj.book.updated_at
        days = diff.days
        date_str = jalali_date(obj.book.updated_at)
        if days == 0:
            return format_html('<span style="color:#15803d; font-weight:700;">امروز ({})</span>', date_str)
        if days <= 7:
            return format_html('<span style="color:#0284c7; font-weight:700;">{} روز پیش</span>', fa_number(days))
        if days >= 30:
            return format_html('<span style="color:#b91c1c; font-weight:700;" title="عدم فعالیت بیش از ۳۰ روز">⚠️ {} روز پیش ({})</span>', fa_number(days), date_str)
        return f"{fa_number(days)} روز پیش ({date_str})"

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_add_permission(self, request):
        return bool(request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "book" in form.base_fields:
            form.base_fields["book"].help_text = "فقط کتاب؛ فصل یا بخش را اینجا نگذارید."
        return form


@admin.register(BookAssistantAuditLog)
class BookAssistantAuditLogAdmin(admin.ModelAdmin):
    list_display = ("book", "action_badge", "assistant_phone", "assistant_user", "actor", "ip", "created_at", "details")
    list_filter = ("action", BookFilter, "created_at")
    search_fields = ("book__title", "assistant_phone", "assistant_user__phone", "actor__phone", "details")
    readonly_fields = ("book", "actor", "assistant_user", "assistant_phone", "action", "details", "ip", "created_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        # Teachers only see logs for books they are authorized to edit, or actions they performed
        editor_books = access.scope_to_editor_books(ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, depth=1), request.user)
        return qs.filter(Q(book__in=editor_books) | Q(actor=request.user)).distinct()

    @admin.display(description="عملیات")
    def action_badge(self, obj):
        colors = {
            BookAssistantAuditLog.Action.ADDED: "#15803d",
            BookAssistantAuditLog.Action.UPDATED: "#0284c7",
            BookAssistantAuditLog.Action.REMOVED: "#b91c1c",
        }
        color = colors.get(obj.action, "#64748b")
        return format_html(
            '<span style="display:inline-block; padding:2px 8px; border-radius:4px; font-weight:700; font-size:12px; color:#fff; background:{};">{}</span>',
            color,
            obj.get_action_display(),
        )

    def has_view_permission(self, request, obj=None):
        if request.user.is_superuser:
            return True
        if obj is not None:
            return access.can_edit_book(request.user, obj.book) or obj.actor_id == request.user.id
        return access.is_book_teacher(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return bool(request.user.is_superuser)


@admin.register(ChapterRevision)
class ChapterRevisionAdmin(admin.ModelAdmin):
    list_display = ("chapter", "source", "note", "user", "updated_at")
    list_filter = ("source", BookFilter)
    search_fields = ("note", "chapter__title")
    readonly_fields = ("chapter", "source", "note", "user", "created_at", "updated_at", "text")

    def get_queryset(self, request):
        return access.scope_to_editor_books(super().get_queryset(request), request.user, "chapter__path")

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

        return [("all", "همه (بدون کتاب)")] + _book_choices(user=request.user)

    def queryset(self, request, queryset):
        if self.value() == "all":
            return queryset.filter(audience_book__isnull=True)
        if self.value():
            return queryset.filter(audience_book_id=self.value())
        return queryset


@admin.register(Banner)
class BannerAdmin(admin.ModelAdmin):
    list_display = ("title", "campaign", "destination", "is_active", "priority", "period", "shown", "ctr")
    fields = ("template", "title", "subtitle", "button", "motif", "image", "target", "target_value", "link", "audience_book", "starts_at", "ends_at",
              "countdown", "priority", "is_active")
    change_form_template = "admin/catalog/banner/change_form.html"

    def get_fields(self, request, obj=None):
        fields = list(super().get_fields(request, obj))
        if obj and obj.sale_campaign_id:
            position = fields.index("target")
            fields = [name for name in fields if name not in {"target", "target_value", "link"}]
            fields.insert(position, "effective_destination")
        return fields

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("sale_campaign", "sale_campaign__book", "sale_campaign__plan")
        # Campaign banners are part of a superuser-only sale setup; other staff cannot activate, deactivate, or retarget them.
        return qs if request.user.is_superuser else qs.filter(sale_campaign__isnull=True)

    @admin.display(description="کمپین")
    def campaign(self, obj):
        return obj.sale_campaign.title if obj.sale_campaign_id else "—"

    @admin.display(description="مقصد نهایی")
    def effective_destination(self, obj):
        from apps.commerce.pricing import campaign_banner_link

        target = campaign_banner_link(obj.sale_campaign) if obj.sale_campaign_id else obj.resolved_link()
        if not target:
            return "هنوز مسیر خرید فعالی برای این کمپین در دسترس نیست."
        if obj.sale_campaign_id and obj.sale_campaign.plan_id:
            label = "خرید اشتراک (همه‌ی کتاب‌ها)"
        elif obj.sale_campaign_id:
            label = "خرید از کمپین"
        else:
            label = "مقصد بنر"
        return format_html('<span><b>{}</b><br><code dir="ltr">{}</code></span>', label, target)

    @admin.display(description="مقصد")
    def destination(self, obj):
        if obj.sale_campaign_id:
            return self.effective_destination(obj)
        target = obj.resolved_link()
        if not target:
            return "بدون لینک"
        return format_html('<code dir="ltr">{}</code>', target)

    @admin.display(description="بازه")
    def period(self, obj):
        from .jalali import jalali_date

        start = obj.sale_campaign.starts_at if obj.sale_campaign_id else obj.starts_at
        end = obj.sale_campaign.ends_at if obj.sale_campaign_id else obj.ends_at
        if not start and not end:
            return "همیشه"
        return format_html('<span style="white-space:nowrap">{} تا {}</span>', jalali_date(start) if start else "…",
                           jalali_date(end) if end else "…")

    def get_readonly_fields(self, request, obj=None):
        if obj and obj.sale_campaign_id:
            # The linked campaign is the single source for its template, destination and timer.
            return ("template", "effective_destination", "starts_at", "ends_at", "countdown")
        return ()

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
        from .backups import (
            bale_ready,
            disk,
            local_backups,
            next_db_backup,
            object_storage_ready,
            storage_mode,
            storage_ready,
        )
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
        from django.conf import settings

        from apps.accounts.sms import pattern_ready

        context = {
            **self.admin_site.each_context(request),
            "title": "فضای سرور",
            "report": report,
            "space": [x for x in space if x["bytes"]],
            "media_bytes": sum(f["bytes"] for f in report["folders"]),
            "media_files": sum(f["files"] for f in report["folders"]),
            "runs": [{"at": jalali_datetime(r.at), "summary": r.summary} for r in CleanupRun.objects.all()[:10]],
            "can_run": access.acts_as_panel_superuser(request),
            "backups": [
                {"at": jalali_datetime(b.at), "kind": b.get_kind_display(), "ok": b.ok, "sent": b.sent, "size": b.size, "note": b.note}
                for b in BackupRun.objects.all()[:12]
            ],
            "bale_ready": bale_ready(),
            "object_storage_ready": object_storage_ready(),
            "storage_ready": storage_ready(),
            "backup_storage_mode": storage_mode(),
            "sms_backend": settings.SMS_BACKEND,
            "sms_pattern_ready": pattern_ready(),
            "default_test_phone": getattr(request.user, "phone", "") or "",
            "payments_enabled": bool(settings.PAYMENTS_ENABLED),
            "zibal_is_sandbox": settings.ZIBAL_MERCHANT == "zibal",
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
            path("backup-now/", transaction.non_atomic_requests(site(self.backup_now)), name="catalog_backup_now"),
            path("export-json/", transaction.non_atomic_requests(site(self.export_json)), name="catalog_export_json"),
            path("export-media/", site(self.export_media), name="catalog_export_media"),
            # Not inside the request's transaction: the database file itself is replaced.
            path("restore/", transaction.non_atomic_requests(site(self.restore)), name="catalog_restore"),
            path("restore-local/", transaction.non_atomic_requests(site(self.restore_local)), name="catalog_restore_local"),
            path("backup-file/", site(self.backup_file), name="catalog_backup_file"),
            path("test-bale/", site(self.test_bale), name="catalog_test_bale"),
            path("test-sms/", site(self.test_sms), name="catalog_test_sms"),
            path("test-zibal/", site(self.test_zibal), name="catalog_test_zibal"),
        ]
        return custom + super().get_urls()

    def backup_now(self, request):
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import redirect

        from .backups import backup_database, backup_media, storage_ready

        if request.method != "POST" or not request.user.is_superuser:
            raise PermissionDenied
        db = backup_database()
        msg = "پشتیبان دیتابیس " + ("ساخته شد" if db.ok else f"ساخته نشد: {db.note}") + ("، و به مقصد ارسال شد" if db.sent else "")
        if request.POST.get("media") and storage_ready():
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

    def export_json(self, request):
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied
        from django.http import FileResponse
        from django.shortcuts import redirect

        from .backups import _safe, export_database_json

        if request.method != "POST" or not access.acts_as_panel_superuser(request):
            raise PermissionDenied
        try:
            path = export_database_json()
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"ساخت خروجی JSON ناموفق بود: {_safe(exc)}")
            return redirect("..")
        return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name)

    def export_media(self, request):
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied
        from django.http import FileResponse
        from django.shortcuts import redirect

        from .backups import _safe, export_full_media

        if request.method != "POST" or not access.acts_as_panel_superuser(request):
            raise PermissionDenied
        try:
            path, _count = export_full_media()
        except Exception as exc:  # noqa: BLE001
            messages.error(request, f"ساخت آرشیو کامل عکس‌ها ناموفق بود: {_safe(exc)}")
            return redirect("..")
        if path is None:
            messages.info(request, "هیچ عکس یا فایل آپلودی در پوشه‌ی media وجود ندارد.")
            return redirect("..")
        return FileResponse(open(path, "rb"), as_attachment=True, filename=path.name)

    def test_sms(self, request):
        from django.conf import settings
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import redirect

        from apps.accounts.phone import InvalidPhone, normalize_phone
        from apps.accounts.sms import SMSError, pattern_ready, send_login_code

        if request.method != "POST" or not access.acts_as_panel_superuser(request):
            raise PermissionDenied
        raw_phone = (request.POST.get("phone") or getattr(request.user, "phone", "") or "").strip()
        try:
            phone = normalize_phone(raw_phone)
        except InvalidPhone as exc:
            messages.error(request, str(exc))
            return redirect("..")
        try:
            send_login_code(phone, "123456", "آزمایش اتصال پیامک لیموخوان: 123456")
        except SMSError as exc:
            messages.error(request, f"خطا در ارسال پیامک آزمایشی به {phone}: {exc}")
            return redirect("..")
        if settings.SMS_BACKEND == "console":
            messages.warning(request, f"SMS_BACKEND روی console است؛ پیامک آزمایشی برای {phone} فقط در لاگ سرور چاپ شد.")
        else:
            mode = "الگو (Pattern)" if pattern_ready() else "خط ارسال مستقیم"
            messages.success(request, f"پیامک آزمایشی به {phone} ارسال شد (روش: {mode}).")
        return redirect("..")

    def test_zibal(self, request):
        from django.conf import settings
        from django.contrib import messages
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import redirect

        from apps.commerce.zibal import GatewayError, request_payment

        if request.method != "POST" or not access.acts_as_panel_superuser(request):
            raise PermissionDenied
        try:
            track_id = request_payment(
                amount_rial=10000,
                order_id=0,
                callback_url=request.build_absolute_uri("/"),
                description="آزمایش اتصال درگاه لیموخوان",
            )
        except GatewayError as exc:
            messages.error(request, f"خطا در اتصال به درگاه زیبال: {exc}")
            return redirect("..")
        if not settings.PAYMENTS_ENABLED:
            messages.warning(request, f"اتصال به زیبال برقرار است (کد پیگیری آزمایشی: {track_id})، ولی PAYMENTS_ENABLED=False است و خرید خاموش است.")
        elif settings.ZIBAL_MERCHANT == "zibal":
            messages.warning(request, f"اتصال به زیبال برقرار است (کد پیگیری آزمایشی: {track_id})، ولی مرچنت روی مقدار آزمایشی zibal است.")
        else:
            messages.success(request, f"اتصال به درگاه واقعی زیبال برقرار است (کد پیگیری آزمایشی: {track_id}).")
        return redirect("..")


_admin_index = admin.site.index


def _admin_kpis_payload():
    from datetime import timedelta
    from django.db.models import Sum
    from django.utils import timezone
    from apps.catalog.panel_display import fa_number
    from apps.accounts.models import User, DeviceSession
    from apps.commerce.models import Order
    from apps.study.models import StudyDay

    now = timezone.now()
    today = timezone.localdate()
    week_start = today - timedelta(days=6)
    month_start = today - timedelta(days=29)

    # کاربران: امروز، هفته اخیر (۷ روز)، کل اعضا
    new_users_today = User.objects.filter(date_joined__date=today).count()
    new_users_week = User.objects.filter(date_joined__date__gte=week_start).count()
    total_users = User.objects.count()

    # کاربران فعال: آنلاین/فعال اخیر (۱۵ دقیقه گذشته) و کاربران فعال ماهانه (MAU در ۳۰ روز اخیر)
    active_now = DeviceSession.objects.filter(
        revoked_at__isnull=True, expires_at__gt=now, last_seen_at__gte=now - timedelta(minutes=15)
    ).values("user_id").distinct().count()
    active_month = StudyDay.objects.filter(date__gte=month_start).values("user").distinct().count()

    # درآمدهای تجمیعی: فروش امروز، فروش ۳۰ روز گذشته، و درآمد کل سامانه
    paid = Order.objects.filter(status=Order.Status.PAID)
    rev_today = paid.filter(paid_at__date=today).aggregate(s=Sum("amount"))["s"] or 0
    rev_month = paid.filter(paid_at__date__gte=month_start).aggregate(s=Sum("amount"))["s"] or 0
    rev_total = paid.aggregate(s=Sum("amount"))["s"] or 0

    from django.contrib.admin.models import LogEntry
    from apps.catalog.access import BOOK_EDITOR_GROUP
    from apps.catalog.models import (
        BookEditor,
        BookOpinion,
        BookTeamTask,
        ChapterRevision,
        ContentNode,
    )
    from apps.commerce.models import PayoutRequest
    from apps.diagnostics.models import ErrorGroup
    from apps.learning.models import Report
    from apps.website.models import (
        BookAccessRequest,
        Classroom,
        PublicationRequest,
        TeacherApplication,
    )

    since_30d = now - timedelta(days=30)

    # آمار جامعه اساتید و تألیف: فقط ویرایش‌های واقعی روی کتاب، فصل، بخش، تست و فلش‌کارت با هویت ویرایشگر محاسبه می‌شود
    teacher_ids = set(
        User.objects.filter(groups__name=BOOK_EDITOR_GROUP, is_active=True, is_superuser=False)
        .values_list("id", flat=True)
        .distinct()
    )
    active_teacher_ids = set()
    if teacher_ids:
        active_teacher_ids.update(
            ChapterRevision.objects.filter(updated_at__gte=since_30d, user_id__in=teacher_ids)
            .values_list("user_id", flat=True)
        )
        active_teacher_ids.update(
            LogEntry.objects.filter(
                action_time__gte=since_30d,
                user_id__in=teacher_ids,
                content_type__model__in=(
                    "contentnode",
                    "book",
                    "section",
                    "question",
                    "flashcard",
                ),
            ).values_list("user_id", flat=True)
        )
        active_teacher_ids &= teacher_ids

    all_teachers_count = len(teacher_ids)
    inactive_teachers_count = len(teacher_ids - active_teacher_ids)
    unattributed_edits_count = (
        ChapterRevision.objects.filter(updated_at__gte=since_30d, user__isnull=True)
        .exclude(note="نسخه‌ی پیش از اولین ویرایش در پنل")
        .count()
    )

    # وضعیت کتب تألیفی
    draft_books_count = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, is_published=False, is_inbox=False, is_archived=False).count()
    published_books_count = ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, is_published=True, is_archived=False).count()

    # کلاس‌ها و دانشجویان
    active_classrooms_count = Classroom.objects.filter(is_active=True).count()
    classroom_students_count = User.objects.filter(classroom_memberships__classroom__is_active=True, classroom_memberships__status="active").distinct().count()

    # گلوگاه‌ها و هشدارهای نیازمند اقدام مدیر
    pending_pubs = PublicationRequest.objects.filter(PublicationRequest.pending_queue_q()).count()
    pending_teacher_apps = TeacherApplication.objects.filter(status=TeacherApplication.Status.PENDING).count()
    open_team_tasks = BookTeamTask.objects.filter(BookTeamTask.pending_queue_q()).count()

    # سلامت، پشتیبانی و صف اقدام مدیر
    pending_payouts = PayoutRequest.objects.filter(PayoutRequest.pending_queue_q()).count()
    open_reports = Report.objects.filter(status=Report.Status.OPEN).count()
    open_errors = ErrorGroup.objects.filter(status=ErrorGroup.Status.OPEN).count()
    pending_opinions = BookOpinion.objects.filter(BookOpinion.pending_queue_q()).count()
    pending_access_requests = BookAccessRequest.objects.filter(status=BookAccessRequest.Status.PENDING).count()
    action_queue_total = (
        pending_payouts
        + open_reports
        + open_errors
        + pending_opinions
        + pending_access_requests
    )

    return {
        "kpi_users_today": fa_number(new_users_today),
        "kpi_users_week": fa_number(new_users_week),
        "kpi_users_total": fa_number(total_users),
        "kpi_active_now": fa_number(active_now),
        "kpi_active_month": fa_number(active_month),
        "kpi_rev_today": fa_number(rev_today),
        "kpi_rev_month": fa_number(rev_month),
        "kpi_rev_total": fa_number(rev_total),
        # شاخص‌های اساتید و خط تولید محتوا
        "kpi_teachers_total": fa_number(all_teachers_count),
        "kpi_teachers_inactive": fa_number(inactive_teachers_count),
        "kpi_teachers_inactive_count": inactive_teachers_count,
        "kpi_unattributed_edits": fa_number(unattributed_edits_count),
        "kpi_unattributed_edits_count": unattributed_edits_count,
        "kpi_draft_books": fa_number(draft_books_count),
        "kpi_published_books": fa_number(published_books_count),
        "kpi_active_classes": fa_number(active_classrooms_count),
        "kpi_class_students": fa_number(classroom_students_count),
        "kpi_pending_pubs": fa_number(pending_pubs),
        "kpi_pending_pubs_count": pending_pubs,
        "kpi_pending_teacher_apps": fa_number(pending_teacher_apps),
        "kpi_pending_teacher_apps_count": pending_teacher_apps,
        "kpi_open_team_tasks": fa_number(open_team_tasks),
        "kpi_open_team_tasks_count": open_team_tasks,
        # سلامت، پشتیبانی و صف اقدام مدیر
        "kpi_action_queue_total": fa_number(action_queue_total),
        "kpi_action_queue_total_count": action_queue_total,
        "kpi_pending_payouts": fa_number(pending_payouts),
        "kpi_pending_payouts_count": pending_payouts,
        "kpi_open_reports": fa_number(open_reports),
        "kpi_open_reports_count": open_reports,
        "kpi_open_errors": fa_number(open_errors),
        "kpi_open_errors_count": open_errors,
        "kpi_pending_opinions": fa_number(pending_opinions),
        "kpi_pending_opinions_count": pending_opinions,
        "kpi_pending_access_requests": fa_number(pending_access_requests),
        "kpi_pending_access_requests_count": pending_access_requests,
    }


def _index_with_daily_cleanup(request, extra_context=None):
    from .maintenance import run_if_due

    if request.user.is_active and request.user.is_superuser:
        run_if_due()
    ctx = dict(extra_context or {})

    # Sync view mode from query parameters before deciding on KPI rendering
    if request and hasattr(request, "session"):
        if request.GET.get("view") == "teacher":
            request.session["admin_view_mode"] = "teacher"
        elif request.GET.get("view") == "admin":
            request.session.pop("admin_view_mode", None)

    if access.acts_as_panel_superuser(request):
        try:
            ctx.update(_admin_kpis_payload())
            ctx["show_admin_kpis"] = True
        except Exception:
            pass
    return _admin_index(request, ctx)


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

    list_display = ("preview", "name", "owner_display", "group", "style", "icon", "numbered", "role", "order", "is_hidden")
    list_display_links = ("name",)
    list_editable = ("group", "style", "icon", "numbered", "order", "is_hidden")
    ordering = ("group", "order", "name")

    @admin.display(description="سازنده")
    def owner_display(self, obj):
        if not obj.created_by:
            return format_html('<span style="color:#6b7280;font-size:12px;">سیستمی (عمومی)</span>')
        return format_html('<span style="color:#15803d;font-weight:700;font-size:12px;">استاد: {}</span>', obj.created_by.full_name or obj.created_by.phone)

    @admin.display(description="نمونه")
    def preview(self, obj):
        """How the box looks, in the four looks' colours (as in the app)."""
        colors = {"formal": ("#3B5FC4", "rgba(70,110,220,.10)"), "note": ("#23864B", "rgba(46,158,91,.10)"),
                  "warn": ("#B4690E", "rgba(230,140,30,.12)"), "table": ("#6B6B6B", "rgba(120,120,120,.10)")}
        line, bg = colors.get(obj.style, colors["note"])
        return format_html('<span style="display:inline-block;min-width:76px;padding:3px 10px;border-inline-start:3px solid {};'
                           'background:{};border-radius:6px;font-weight:700;color:{};opacity:{}">{}</span>',
                           line, bg, line, ".45" if obj.is_hidden else "1", obj.name)
    list_filter = ("created_by", "group", "style", "is_hidden")
    search_fields = ("name", "aliases")
    fieldsets = (
        (None, {"fields": ("name", "group", "style", "icon", "numbered", "order", "is_hidden"),
                "description": "هر برچسب در «درسنامه» یک کادر است (:::تعریف … :::) و در «چکیده» یک بخش (تعریف: و بعد موردها با «- »). "
                               "برچسبی را که در متن‌ها به کار رفته پاک نکنید؛ «پنهان» کنید تا در دکمه‌های پنل نیاید."}),
        ("بیشتر", {"fields": ("aliases", "columns", "role", "created_by"), "classes": ("collapse",)}),
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        from django.db.models import Q
        return qs.filter(Q(created_by__isnull=True) | Q(created_by=request.user))

    def has_change_permission(self, request, obj=None):
        if not super().has_change_permission(request, obj):
            return False
        if obj and not request.user.is_superuser and obj.created_by != request.user:
            return False
        return True

    def has_delete_permission(self, request, obj=None):
        if obj and not request.user.is_superuser and obj.created_by == request.user:
            return True
        return False

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and not change:
            obj.created_by = request.user
            if not obj.group:
                obj.group = "برچسب‌های اختصاصی"
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



# --- A version stamp for the panel's own assets -------------------------------------------------------------------
# panel.css and panel.js are served by name; a browser that cached yesterday's copy keeps showing yesterday's panel
# («the width buttons do nothing» was exactly that for one round). The stamp is the newest modification time of the
# files, so it changes when they change and not on every request.
_assets_each_context = admin.site.each_context


def _assets_each_context_with_version(request):
    from django.utils import timezone
    context = _assets_each_context(request)
    context["assets_v"] = _assets_version()
    user = getattr(request, "user", None)
    # Allow superusers to preview the teacher portal via ?view=teacher or session
    if request:
        if "view" in request.GET:
            if request.GET.get("view") == "teacher":
                request.session["admin_view_mode"] = "teacher"
            elif request.GET.get("view") == "admin":
                request.session.pop("admin_view_mode", None)

    context["teacher_view_mode"] = access.is_teacher_preview(request)
    is_teacher = access.acts_as_panel_teacher(request)
    context["is_teacher"] = is_teacher
    if is_teacher:
        from django.conf import settings
        from django.db.models import Q
        from apps.website.models import Classroom
        from apps.learning.models import Report
        from .models import BookEditor, BookTeamTask

        def _teacher_book_entry(b):
            ch_count = ContentNode.objects.filter(path__startswith=b.path, depth=2, is_archived=False).count()
            pending_tasks = BookTeamTask.objects.filter(book=b, is_done=False).count()
            report_q = (
                Q(node__path__startswith=b.path)
                | Q(question__node__path__startswith=b.path)
                | Q(flashcard__node__path__startswith=b.path)
            )
            pending_reports = Report.objects.filter(report_q, status=Report.Status.OPEN).count()
            major = next(iter(b.majors.all()), None)
            return {
                "pk": b.pk,
                "title": b.title,
                "title_en": b.title_en,
                "author": b.author,
                "edition": b.edition,
                "cover_url": b.cover.url if b.cover else "",
                "cover_motif": b.cover_motif,
                "cover_drawing": b.cover_drawing,
                "major_name": major.name if major else "",
                "major_color": major.color if major else "",
                "chapters_count": ch_count,
                "pending_tasks_count": pending_tasks,
                "pending_reports_count": pending_reports,
            }

        if user.is_superuser:
            # For superuser previewing teacher portal: show recently edited draft books or all books (excluding inbox)
            teacher_books = [
                _teacher_book_entry(b)
                for b in ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, is_published=False, is_inbox=False)
                .prefetch_related("majors")[:6]
            ]
            context["teacher_books"] = teacher_books

            classrooms = []
            site_url = getattr(settings, "SITE_URL", "").rstrip("/")
            today_date = timezone.localdate()
            for c in Classroom.objects.filter(is_active=True).select_related("book").order_by("-created_at")[:6]:
                m_count = c.members.filter(status="active").count()
                days_left = (c.ends_on - today_date).days if (c.expiry_policy == Classroom.ExpiryPolicy.FIXED_DATE and c.ends_on) else None
                classrooms.append({
                    "pk": c.pk,
                    "title": c.title,
                    "book": c.book,
                    "code": c.code,
                    "capacity": c.capacity,
                    "members_count": m_count,
                    "days_left": days_left,
                    "is_expiring": (days_left is not None and 0 <= days_left <= 7),
                    "is_expired": (days_left is not None and days_left < 0),
                })
            context["teacher_classrooms"] = classrooms
            context["site_url"] = site_url
        else:
            book_ids = list(BookEditor.objects.filter(user=user).values_list("book_id", flat=True))
            teacher_books = [
                _teacher_book_entry(b)
                for b in ContentNode.objects.filter(pk__in=book_ids, kind=ContentNode.Kind.BOOK, is_inbox=False)
                .prefetch_related("majors")
            ]
            context["teacher_books"] = teacher_books

            classrooms = []
            site_url = getattr(settings, "SITE_URL", "").rstrip("/")
            today_date = timezone.localdate()
            for c in Classroom.objects.filter(teacher=user, is_active=True).select_related("book").order_by("-created_at")[:6]:
                m_count = c.members.filter(status="active").count()
                days_left = (c.ends_on - today_date).days if (c.expiry_policy == Classroom.ExpiryPolicy.FIXED_DATE and c.ends_on) else None
                classrooms.append({
                    "pk": c.pk,
                    "title": c.title,
                    "book": c.book,
                    "code": c.code,
                    "capacity": c.capacity,
                    "members_count": m_count,
                    "days_left": days_left,
                    "is_expiring": (days_left is not None and 0 <= days_left <= 7),
                    "is_expired": (days_left is not None and days_left < 0),
                })
            context["teacher_classrooms"] = classrooms
            context["site_url"] = site_url

        # Filter recent admin actions strictly to teacher workspace items when in teacher mode
        from django.contrib.admin.models import LogEntry
        _teacher_log_models = (
            "contentnode", "question", "flashcard", "label", "classroom",
            "classroommember", "report", "examsource", "sharesettings", "publicationrequest"
        )
        context["teacher_admin_log"] = (
            LogEntry.objects.filter(user=user, content_type__model__in=_teacher_log_models)
            .select_related("content_type")
            .order_by("-action_time")[:10]
        )

        # محاسبه کارت‌های شاخص تحلیلی اختصاصی استاد
        try:
            from datetime import timedelta
            from django.utils import timezone
            from django.db.models import Sum
            from apps.catalog.panel_display import fa_number
            from apps.website.models import ClassroomMember
            from apps.study.models import StudyTime, StudyDay

            now = timezone.now()
            today = timezone.localdate()
            week_start = today - timedelta(days=6)
            month_start = today - timedelta(days=29)

            if user.is_superuser:
                teacher_b_ids = [b["pk"] for b in teacher_books]
                c_qs = Classroom.objects.filter(is_active=True)
            else:
                teacher_b_ids = list(BookEditor.objects.filter(user=user).values_list("book_id", flat=True))
                c_qs = Classroom.objects.filter(teacher=user, is_active=True)

            tot_students = ClassroomMember.objects.filter(classroom__in=c_qs, status="active").values("user_id").distinct().count()
            week_students = ClassroomMember.objects.filter(classroom__in=c_qs, status="active", joined_at__date__gte=week_start).values("user_id").distinct().count()
            tot_classes = c_qs.count()

            act_students = StudyDay.objects.filter(date__gte=month_start, user__classroom_memberships__classroom__in=c_qs, user__classroom_memberships__status="active").values("user_id").distinct().count()
            sec_month = StudyTime.objects.filter(day__gte=month_start, book_id__in=teacher_b_ids).aggregate(s=Sum("seconds"))["s"] or 0
            hrs_month = round(sec_month / 3600, 1)

            tot_chapters = sum(b.get("chapters_count", 0) for b in teacher_books)
            tot_tasks = sum(b.get("pending_tasks_count", 0) for b in teacher_books)
            tot_reports = sum(b.get("pending_reports_count", 0) for b in teacher_books)

            context["teacher_kpis"] = {
                "students_total": fa_number(tot_students),
                "students_week": fa_number(week_students),
                "classes_count": fa_number(tot_classes),
                "active_students": fa_number(act_students),
                "study_hours": fa_number(hrs_month),
                "chapters_count": fa_number(tot_chapters),
                "pending_tasks": fa_number(tot_tasks),
                "pending_reports": fa_number(tot_reports),
            }
        except Exception:
            pass
    return context


def _assets_version() -> str:
    from django.contrib.staticfiles import finders

    newest = 0.0
    for name in (
        "catalog/jalali-admin.css",
        "catalog/jalali-admin.js",
        "catalog/panel.css",
        "catalog/panel.js",
        "catalog/preview-pane.js",
        "catalog/limo-preview.js",
        "catalog/limo-editor.js",
        "diagnostics/browser-diag.js",
        "catalog/fonts/Vazirmatn_400Regular.ttf",
        "catalog/fonts/Vazirmatn_700Bold.ttf",
        "catalog/fonts/Vazirmatn_800ExtraBold.ttf",
        "catalog/fonts/Vazirmatn_900Black.ttf",
    ):
        path = finders.find(name)
        if path:
            try:
                newest = max(newest, os.path.getmtime(path))
            except OSError:
                pass
    return str(int(newest)) or "1"


admin.site.each_context = _assets_each_context_with_version


@admin.register(AIProvider)
class AIProviderAdmin(admin.ModelAdmin):
    list_display = ("title", "provider_type", "model_name", "owner_display", "masked_key_display", "is_active", "is_default", "order")
    list_filter = ("provider_type", "is_active", "is_default")
    search_fields = ("title", "model_name", "base_url")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if access.acts_as_panel_superuser(request):
            return qs
        # Teachers only see their own providers (never global or other teachers' keys)
        return qs.filter(owner=request.user)

    def get_fieldsets(self, request, obj=None):
        base_fields = ["title", "provider_type", "api_key", "base_url", "model_name"]
        if access.acts_as_panel_superuser(request):
            base_fields.insert(1, "owner")
        return (
            (None, {
                "fields": tuple(base_fields)
            }),
            ("تنظیمات دسترسی و اولویت", {
                "fields": ("is_active", "is_default", "order"),
                "description": "ارائه‌دهنده‌های فعال در فرم بررسی و تمیزکاری فایل‌ها نمایش داده می‌شوند.",
            }),
        )

    def get_form(self, request, obj=None, **kwargs):
        form = super().get_form(request, obj, **kwargs)
        if "api_key" in form.base_fields:
            form.base_fields["api_key"].widget = forms.PasswordInput(render_value=True)
            form.base_fields["api_key"].help_text = "کلید API شما به صورت امن نگهداری می‌شود و فقط به خودتان نمایش داده خواهد شد."
        return form

    @admin.display(description="مالک / حساب")
    def owner_display(self, obj):
        if obj.owner:
            return format_html('<span style="color:#0369a1; font-weight:700;">👤 {}</span>', obj.owner.phone)
        return format_html('<span style="color:#15803d; font-weight:700;">🏢 سراسری مدیر کل</span>')

    @admin.display(description="کلید API (محافظت‌شده)")
    def masked_key_display(self, obj):
        return format_html('<code style="direction:ltr; unicode-bidi:isolate; font-size:12px;">{}</code>', obj.masked_api_key())

    def save_model(self, request, obj, form, change):
        if not access.acts_as_panel_superuser(request):
            # Force current teacher as owner
            obj.owner = request.user
        super().save_model(request, obj, form, change)

    def has_view_permission(self, request, obj=None):
        if access.acts_as_panel_superuser(request):
            return True
        if obj is not None:
            return obj.owner_id == request.user.id
        return access.acts_as_panel_teacher(request)

    def has_change_permission(self, request, obj=None):
        if access.acts_as_panel_superuser(request):
            return True
        if obj is not None:
            return obj.owner_id == request.user.id
        return access.acts_as_panel_teacher(request)

    def has_delete_permission(self, request, obj=None):
        if access.acts_as_panel_superuser(request):
            return True
        if obj is not None:
            return obj.owner_id == request.user.id
        return access.acts_as_panel_teacher(request)

    def has_add_permission(self, request):
        return bool(access.acts_as_panel_superuser(request) or access.acts_as_panel_teacher(request))




@admin.register(TeacherProfile)
class TeacherProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "academic_title", "contact_email", "updated_at")
    search_fields = ("user__phone", "user__first_name", "user__last_name", "academic_title", "bio")
    readonly_fields = ("created_at", "updated_at")

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if access.acts_as_panel_superuser(request):
            return qs
        return qs.filter(user=request.user)

    def get_fields(self, request, obj=None):
        fields = ["user", "academic_title", "avatar", "bio", "contact_email", "social_links", "created_at", "updated_at"]
        if not access.acts_as_panel_superuser(request) and obj is None:
            fields.remove("user")
        return fields

    def get_readonly_fields(self, request, obj=None):
        ro = ["created_at", "updated_at"]
        if obj is not None:
            ro.append("user")
        return tuple(ro)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "user":
            from django.db.models import Q
            UserModel = get_user_model()
            kwargs["queryset"] = (
                UserModel.objects.filter(teacher_profile__isnull=True)
                .filter(Q(edited_books__isnull=False) | Q(groups__name=access.BOOK_EDITOR_GROUP))
                .distinct()
                .order_by("phone")
            )
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            if not access.is_book_teacher(request.user):
                raise PermissionDenied
            if change:
                orig = TeacherProfile.objects.get(pk=obj.pk)
                if orig.user_id != request.user.id:
                    raise PermissionDenied
                obj.user_id = orig.user_id
            else:
                if TeacherProfile.objects.filter(user=request.user).exists():
                    raise PermissionDenied
                obj.user = request.user
        super().save_model(request, obj, form, change)

    def has_module_permission(self, request):
        return bool(access.acts_as_panel_superuser(request) or access.acts_as_panel_teacher(request))

    def has_add_permission(self, request):
        if access.acts_as_panel_superuser(request):
            return True
        return access.acts_as_panel_teacher(request) and not TeacherProfile.objects.filter(user=request.user).exists()

    def has_change_permission(self, request, obj=None):
        if access.acts_as_panel_superuser(request):
            return True
        if obj is not None and obj.user_id != request.user.id:
            return False
        return access.acts_as_panel_teacher(request)

    def has_view_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return access.acts_as_panel_superuser(request)


class BookOpinionQueueFilter(admin.SimpleListFilter):
    title = "صف بازبینی"
    parameter_name = "queue"

    def lookups(self, request, model_admin):
        return [("pending", "در انتظار بازبینی یا گزارش‌شده")]

    def queryset(self, request, queryset):
        if self.value() == "pending":
            return queryset.filter(BookOpinion.pending_queue_q())
        return queryset


@admin.register(BookOpinion)
class BookOpinionAdmin(admin.ModelAdmin):
    list_display = ("book", "display_user", "rating_badge", "satisfaction_display", "study_percent_display", "status", "has_reply", "is_pinned", "created_at")
    list_filter = (BookOpinionQueueFilter, "status", "rating", "is_pinned", "created_at")
    search_fields = ("book__title", "user__phone", "user__first_name", "user__last_name", "body", "teacher_reply")
    _ADMIN_READONLY = ("created_at", "updated_at", "study_percent", "test_percent", "reported_by", "reported_at", "teacher_replied_at", "teacher_replied_by")
    _TEACHER_PROTECTED = (
        "book",
        "user",
        "display_user",
        "rating",
        "satisfaction_percent",
        "body",
        "study_percent",
        "test_percent",
        "status",
        "is_pinned",
        "reported_by",
        "reported_at",
        "teacher_replied_at",
        "teacher_replied_by",
        "created_at",
        "updated_at",
    )

    def get_queryset(self, request):
        qs = super().get_queryset(request).select_related("book", "user", "teacher_replied_by")
        if request.user.is_superuser:
            return qs
        my_book_ids = access.book_editor_ids(request.user).values_list("book_id", flat=True)
        return qs.filter(book_id__in=my_book_ids)

    def get_fields(self, request, obj=None):
        if access.acts_as_panel_superuser(request):
            return super().get_fields(request, obj)
        return (
            "book",
            "display_user",
            "rating",
            "satisfaction_percent",
            "body",
            "study_percent",
            "test_percent",
            "status",
            "is_pinned",
            "teacher_reply",
            "teacher_replied_at",
            "report_reason",
            "reported_at",
            "created_at",
            "updated_at",
        )

    def get_readonly_fields(self, request, obj=None):
        if access.acts_as_panel_superuser(request):
            return self._ADMIN_READONLY
        return self._TEACHER_PROTECTED

    def display_user(self, obj):
        from apps.guard import core

        return core.masked_user_label(obj.user)
    display_user.short_description = "کاربر / دانشجو"

    def rating_badge(self, obj):
        stars = "★" * obj.rating + "☆" * (5 - obj.rating)
        color = "#eab308" if obj.rating >= 4 else ("#f97316" if obj.rating == 3 else "#ef4444")
        return format_html('<span style="color: {}; font-weight: bold; font-size: 14px;">{} ({} از ۵)</span>', color, stars, fa_digits(obj.rating))
    rating_badge.short_description = "امتیاز"

    def satisfaction_display(self, obj):
        return f"{fa_digits(obj.satisfaction_percent)}٪"
    satisfaction_display.short_description = "رضایت"

    def study_percent_display(self, obj):
        return f"مطالعه: {fa_digits(obj.study_percent)}٪ | تست: {fa_digits(obj.test_percent)}٪"
    study_percent_display.short_description = "میزان پیشرفت"

    def has_reply(self, obj):
        return bool(obj.teacher_reply)
    has_reply.boolean = True
    has_reply.short_description = "پاسخ استاد"

    def has_module_permission(self, request):
        return bool(access.acts_as_panel_superuser(request) or access.acts_as_panel_teacher(request))

    def has_view_permission(self, request, obj=None):
        if access.acts_as_panel_superuser(request) or access.is_teacher_preview(request):
            return True
        if obj is not None:
            return access.can_edit_book(request.user, obj.book)
        return access.is_book_teacher(request.user)

    def has_add_permission(self, request):
        return access.acts_as_panel_superuser(request)

    def has_change_permission(self, request, obj=None):
        if access.acts_as_panel_superuser(request):
            return True
        if obj is not None:
            return access.is_teacher_preview(request) or access.can_edit_book(request.user, obj.book)
        return access.acts_as_panel_teacher(request)

    def has_delete_permission(self, request, obj=None):
        return access.acts_as_panel_superuser(request)

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            if not access.is_book_teacher(request.user) or not change or not obj.pk:
                raise PermissionDenied
            orig = BookOpinion.objects.select_related("book").get(pk=obj.pk)
            if not access.can_edit_book(request.user, orig.book):
                raise PermissionDenied
            # Update only reply/report fields in SQL so concurrent manager/student edits (e.g. status) are never overwritten.
            update_fields = []
            if (obj.teacher_reply or "") != (orig.teacher_reply or ""):
                update_fields.extend(["teacher_reply", "teacher_replied_at", "teacher_replied_by"])
                if (obj.teacher_reply or "").strip():
                    obj.teacher_replied_at = timezone.now()
                    obj.teacher_replied_by = request.user
                else:
                    obj.teacher_replied_at = None
                    obj.teacher_replied_by = None

            if (obj.report_reason or "") != (orig.report_reason or ""):
                update_fields.extend(["report_reason", "reported_at", "reported_by"])
                if (obj.report_reason or "").strip():
                    obj.reported_at = timezone.now()
                    obj.reported_by = request.user
                else:
                    obj.reported_at = None
                    obj.reported_by = None

            if update_fields:
                obj.save(update_fields=update_fields + ["updated_at"])
            obj.refresh_from_db()
            return
        if "teacher_reply" in form.changed_data and obj.teacher_reply:
            obj.teacher_replied_at = timezone.now()
            obj.teacher_replied_by = request.user
        if "report_reason" in form.changed_data and not (obj.report_reason or "").strip():
            obj.reported_at = None
            obj.reported_by = None
        super().save_model(request, obj, form, change)


@admin.register(BookTeamTask)
class BookTeamTaskAdmin(admin.ModelAdmin):
    """نمای متمرکز همهٔ یادداشت‌ها و وظایف هماهنگی تیم‌های تألیف کتاب‌ها برای مدیر کل."""

    list_display = ("book", "text_preview", "author_col", "status_badge", "is_done", "created_at_fa")
    list_display_links = ("text_preview",)
    list_editable = ("is_done",)
    list_filter = ("is_done", BookFKFilter, "created_at")
    search_fields = ("book__title", "author__phone", "author__first_name", "author__last_name", "text")
    list_select_related = ("book", "author")
    readonly_fields = ("author", "created_at")

    @admin.display(description="متن یادداشت / وظیفه")
    def text_preview(self, obj):
        return obj.text

    @admin.display(description="نویسنده", ordering="author__phone")
    def author_col(self, obj):
        name = f"{obj.author.first_name} {obj.author.last_name}".strip()
        return f"{name} ({obj.author.phone})" if name else obj.author.phone

    @admin.display(description="وضعیت", ordering="is_done")
    def status_badge(self, obj):
        return badges(("انجام‌شده", "green")) if obj.is_done else badges(("باز", "yellow"))

    @admin.display(description="زمان ثبت", ordering="created_at")
    def created_at_fa(self, obj):
        from .jalali import jalali_datetime

        return jalali_datetime(obj.created_at)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("book", "text", "is_done")
        return ("book", "author", "text", "is_done", "created_at")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "book":
            kwargs["queryset"] = ContentNode.objects.filter(
                kind=ContentNode.Kind.BOOK, depth=1, is_inbox=False
            ).order_by("title")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.author = request.user
        else:
            obj.author_id = BookTeamTask.objects.values_list("author_id", flat=True).get(pk=obj.pk)
        super().save_model(request, obj, form, change)

    def has_module_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_add_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)


class BookBoxMappingForm(forms.ModelForm):
    class Meta:
        model = BookBoxMapping
        fields = ("book", "environment_name", "label_name")

    def clean(self):
        cleaned = super().clean()
        env, lbl = BookBoxMapping.normalize(cleaned.get("environment_name"), cleaned.get("label_name"))
        cleaned["environment_name"] = env
        cleaned["label_name"] = lbl
        book = cleaned.get("book")
        if book and env:
            dup = BookBoxMapping.objects.filter(book=book, environment_name=env)
            if self.instance.pk:
                dup = dup.exclude(pk=self.instance.pk)
            if dup.exists():
                self.add_error("environment_name", "برای این کتاب قبلاً نگاشتی با همین نام محیط ثبت شده است.")
        return cleaned


@admin.register(BookBoxMapping)
class BookBoxMappingAdmin(admin.ModelAdmin):
    """مدیریت حافظهٔ نگاشت محیط‌های LaTeX به کادرهای لیموخوان برای هر کتاب."""

    form = BookBoxMappingForm
    list_display = ("book", "env_code", "label_name", "creator_col", "updated_at_fa")
    list_filter = (BookFKFilter, "updated_at")
    search_fields = ("book__title", "environment_name", "label_name", "created_by__phone")
    list_select_related = ("book", "created_by")
    readonly_fields = ("created_by", "created_at", "updated_at")

    @admin.display(description="محیط LaTeX", ordering="environment_name")
    def env_code(self, obj):
        return format_html('<code style="direction:ltr;unicode-bidi:isolate">\\begin{{{}}}</code>', obj.environment_name)

    @admin.display(description="ثبت‌کننده", ordering="created_by__phone")
    def creator_col(self, obj):
        if not obj.created_by:
            return "—"
        name = f"{obj.created_by.first_name} {obj.created_by.last_name}".strip()
        return f"{name} ({obj.created_by.phone})" if name else obj.created_by.phone

    @admin.display(description="آخرین ویرایش", ordering="updated_at")
    def updated_at_fa(self, obj):
        from .jalali import jalali_datetime

        return jalali_datetime(obj.updated_at)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("book", "environment_name", "label_name")
        return ("book", "environment_name", "label_name", "created_by", "created_at", "updated_at")

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "book":
            kwargs["queryset"] = ContentNode.objects.filter(
                kind=ContentNode.Kind.BOOK, depth=1, is_inbox=False
            ).order_by("title")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        else:
            obj.created_by_id = BookBoxMapping.objects.values_list("created_by_id", flat=True).get(pk=obj.pk)
        super().save_model(request, obj, form, change)

    def has_module_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_view_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_add_permission(self, request):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return bool(request.user.is_active and request.user.is_superuser)
