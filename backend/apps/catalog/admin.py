import os

from django import forms
from django.contrib import admin
from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import Count, Q
from django.shortcuts import redirect
from django.urls import path, reverse
from django.utils.html import format_html

from . import access, bookpanel, panel
from .drawing import DrawingError, clean_svg
from .drawing import dumps as dumps_drawing
from .drawing import loads as loads_drawing
from .filters import BookFilter, BookFKFilter, ChapterFilter, YesNoFilter
from .panel_display import badges
from .models import (Banner, Book, BookChange, BookEditor, BookWaitlist, ChapterRevision, CleanupRun, ContentNode, FormulaCommand, Label, Major, Section,
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
        # `is_published` is deliberately NOT a form field: writing a book and releasing it are separate gates, and a
        # checkbox in a form cannot tell the two apart. Publishing goes through the button below the title, which
        # asks can_publish_book (see publish_book view).
        ("فروش و نمایش", {"fields": ("price", "is_free", "is_coming_soon", "release_estimate", "position", "is_archived")}),
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
        if request.user.is_superuser:
            return self.list_display
        return ("cover_thumb", "title", "author", "chapter_count", "status")

    def has_add_permission(self, request):
        return bool(request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        # Teachers prepare chapter drafts in the chapter manager; book metadata and commercial settings are manager-only.
        return bool(request.user.is_superuser)

    def get_fieldsets(self, request, obj=None):
        if request.user.is_superuser:
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
        extra["orphans"] = [n for n in panel.orphans() if not n.is_archived] if request.user.is_superuser else []
        extra["can_manage_access"] = request.user.is_superuser
        extra["can_create_book"] = bool(request.user.is_superuser or access.is_book_teacher(request.user))
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
            extra["can_manage_access"] = request.user.is_superuser
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
            from .models import BookTeamTask
            extra["team_tasks"] = list(BookTeamTask.objects.filter(book=book).select_related("author"))
            can_view_study = bool(
                request.user.is_superuser
                or (access.is_book_teacher(request.user) and BookEditor.objects.filter(book=book, user=request.user, can_view_aggregate_study=True).exists())
            )
            extra["can_view_study"] = can_view_study
            if not request.user.is_superuser and access.is_book_teacher(request.user):
                editor = BookEditor.objects.filter(book=book, user=request.user).first()
                extra["can_request_publication"] = bool(editor and editor.can_request_publication)
                extra["can_request_group_access"] = bool(editor and editor.can_request_group_access)
                from apps.website.models import PublicationRequest
                extra["publication_request"] = PublicationRequest.objects.filter(book=book, requested_by=request.user).order_by("-submitted_at").first()
            else:
                extra["can_request_publication"] = False
                extra["can_request_group_access"] = False
            if request.user.is_superuser:
                extra.update(gift_context(book))
            # The publish box reads this and not `original.is_published` alone: only the manager gets the control.
            extra["publish"] = access.publish_state(request.user, book)
        return super().change_view(request, object_id, form_url, extra_context=extra)

    def get_urls(self):
        site = self.admin_site.admin_view
        custom = [
            path("new-draft/", site(self.teacher_create_book_view), name="catalog_book_teacher_new"),
            path("import/", site(lambda r: panel.import_view(self.admin_site, r)), name="catalog_import"),
            path("<int:book_id>/import/", site(lambda r, book_id: panel.import_view(self.admin_site, r, book_id)), name="catalog_book_import"),
            path("<int:book_id>/export/", site(panel.book_export), name="catalog_book_export"),
            path("<int:book_id>/email-export/", site(panel.book_email_export), name="catalog_book_email_export"),
            path("orphan/<int:node_id>/archive/", site(panel.archive_orphan), name="catalog_archive_orphan"),
            path("<int:book_id>/chapters/", site(panel.book_chapter_action), name="catalog_book_chapter_action"),
            path("<int:book_id>/assistants/", site(self.book_assistants_action), name="catalog_book_assistants_action"),
            path("<int:book_id>/team-tasks/", site(self.book_team_tasks_action), name="catalog_book_team_tasks_action"),
            path("<int:book_id>/study-analytics/", site(self.book_study_analytics_view), name="catalog_book_study_analytics"),
            path("<int:book_id>/request-publication/", site(self.book_request_publication_view), name="catalog_book_request_publication"),
            path("<int:book_id>/publish/", site(lambda r, book_id: panel.book_publish(self.admin_site, r, book_id)),
                 name="catalog_book_publish"),
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

        if request.method == "POST":
            title = request.POST.get("title", "").strip()
            title_en = request.POST.get("title_en", "").strip()
            author = request.POST.get("author", "").strip()
            about = request.POST.get("about", "").strip()

            if not title:
                messages.error(request, "عنوان کتاب الزامی است.")
            else:
                # Generate clean unique slug
                base_slug = re.sub(r"[^\w\s-]", "", title_en or title).strip()
                base_slug = re.sub(r"[-\s]+", "-", base_slug) or "book"
                slug_candidate = f"{base_slug}-{request.user.pk}".lower()
                suffix = 1
                while ContentNode.objects.filter(slug=slug_candidate).exists():
                    slug_candidate = f"{base_slug}-{request.user.pk}-{suffix}".lower()
                    suffix += 1

                with transaction.atomic():
                    book = ContentNode(
                        kind=ContentNode.Kind.BOOK,
                        title=title,
                        title_en=title_en,
                        slug=slug_candidate,
                        author=author or (f"استاد {request.user.phone}"),
                        about=about,
                        is_published=False,  # strictly draft
                    )
                    ContentNode.add_root(instance=book)

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

                    # Optional initial file import
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

                messages.success(request, f"کتاب پیش‌نویس «{book.title}» با موفقیت ایجاد شد.{imported_summary}")
                return redirect(reverse("admin:catalog_book_change", args=[book.pk]))

        context = {
            **self.admin_site.each_context(request),
            "title": "ایجاد کتاب پیش‌نویس تازه",
            "opts": self.model._meta,
        }
        return render(request, "admin/catalog/book/teacher_create_book.html", context)

    def book_assistants_action(self, request, book_id):
        from django.contrib import messages
        from django.contrib.auth import get_user_model
        from django.contrib.auth.models import Group
        from django.core.exceptions import PermissionDenied
        from django.shortcuts import get_object_or_404, redirect
        from .access import BOOK_EDITOR_GROUP, can_edit_book
        from .models import BookEditor

        book = get_object_or_404(ContentNode, pk=book_id, kind=ContentNode.Kind.BOOK)
        if not can_edit_book(request.user, book):
            raise PermissionDenied("دسترسی مدیریت دستیاران این کتاب را ندارید.")

        if request.method != "POST":
            return redirect(reverse("admin:catalog_book_change", args=[book.pk]))

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
                messages.success(request, f"دسترسی‌های دستیار با شماره {phone} به‌روزرسانی شد.")
            else:
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
                editor.delete()
                messages.success(request, f"دسترسی دستیار با شماره {phone} از این کتاب حذف شد.")

        return redirect(reverse("admin:catalog_book_change", args=[book.pk]) + "#assistants")

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
            .annotate(rate=Cast("correct_count", FloatField()) / F("answer_count"))
            .order_by("rate", "id")[:8]
        )
        hardest_questions = []
        for q in questions:
            hardest_questions.append({
                "id": q.id,
                "stem": q.stem[:140],
                "rate": fa_digits(round(100 * q.correct_count / q.answer_count)),
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
            digest = publication_content_digest(book)

            # Check if pending request exists
            pending = PublicationRequest.objects.filter(
                book=book,
                requested_by=request.user,
                status__in=(PublicationRequest.Status.PENDING, PublicationRequest.Status.NEEDS_INFO),
            ).first()

            if pending:
                pending.request_note = note
                pending.content_digest = digest
                pending.status = PublicationRequest.Status.PENDING
                pending.save(update_fields=["request_note", "content_digest", "status"])
                record_publication_request(pending, actor=request.user, action=PublicationRequestEvent.Action.SUBMITTED, reason=note)
                messages.success(request, "درخواست بازبینی شما با موفقیت به‌روزرسانی شد و برای مدیر کل ارسال گردید.")
            else:
                new_req = PublicationRequest.objects.create(
                    book=book,
                    requested_by=request.user,
                    request_note=note,
                    content_digest=digest,
                    status=PublicationRequest.Status.PENDING,
                )
                record_publication_request(new_req, actor=request.user, action=PublicationRequestEvent.Action.SUBMITTED, reason=note)
                messages.success(request, f"درخواست بازبینی انتشار کتاب «{book.title}» با موفقیت برای مدیر کل ارسال شد.")

            return redirect(reverse("admin:catalog_book_change", args=[book.pk]) + "#publish")

        context = {
            **self.admin_site.each_context(request),
            "title": f"درخواست بازبینی انتشار: {book.title}",
            "book": book,
            "latest_req": latest_req,
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


@admin.register(BookEditor)
class BookEditorAdmin(admin.ModelAdmin):
    """«استادان کتاب»: only the manager assigns a reviewed, approved editor to a book."""

    list_display = (
        "book", "user", "can_edit_content", "can_request_publication", "can_request_group_access",
        "can_view_reports", "can_view_aggregate_study", "can_view_aggregate_sales", "can_publish", "note", "created_at",
    )
    list_filter = (
        "can_edit_content", "can_request_publication", "can_request_group_access", "can_view_reports",
        "can_view_aggregate_study", "can_view_aggregate_sales", BookFilter,
    )
    search_fields = ("book__title", "user__phone", "user__first_name", "user__last_name", "note")
    list_select_related = ("book", "user")

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
        label = "خرید از کمپین" if obj.sale_campaign_id else "مقصد بنر"
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

    if request.user.is_active and request.user.is_superuser:
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
    context = _assets_each_context(request)
    context["assets_v"] = _assets_version()
    user = getattr(request, "user", None)
    # Allow superusers to preview the teacher portal via ?view=teacher or session
    teacher_view_mode = False
    if request:
        if "view" in request.GET:
            if request.GET.get("view") == "teacher":
                request.session["admin_view_mode"] = "teacher"
            elif request.GET.get("view") == "admin":
                request.session.pop("admin_view_mode", None)
        teacher_view_mode = (request.session.get("admin_view_mode") == "teacher")

    context["teacher_view_mode"] = teacher_view_mode
    is_teacher = bool(user and user.is_authenticated and (access.is_book_teacher(user) or (user.is_superuser and teacher_view_mode)))
    if is_teacher:
        context["is_teacher"] = True
        from django.conf import settings
        from apps.website.models import Classroom
        from .models import BookEditor

        if user.is_superuser:
            # For superuser previewing teacher portal: show recently edited draft books or all books
            teacher_books = []
            for b in ContentNode.objects.filter(kind=ContentNode.Kind.BOOK, is_published=False)[:6]:
                ch_count = ContentNode.objects.filter(path__startswith=b.path, depth=2, is_archived=False).count()
                teacher_books.append({
                    "pk": b.pk,
                    "title": b.title,
                    "author": b.author,
                    "chapters_count": ch_count,
                })
            context["teacher_books"] = teacher_books

            classrooms = []
            site_url = getattr(settings, "SITE_URL", "").rstrip("/")
            for c in Classroom.objects.filter(is_active=True).select_related("book").order_by("-created_at")[:6]:
                m_count = c.members.filter(status="active").count()
                classrooms.append({
                    "pk": c.pk,
                    "title": c.title,
                    "book": c.book,
                    "code": c.code,
                    "capacity": c.capacity,
                    "members_count": m_count,
                })
            context["teacher_classrooms"] = classrooms
            context["site_url"] = site_url
        else:
            book_ids = list(BookEditor.objects.filter(user=user).values_list("book_id", flat=True))
            teacher_books = []
            for b in ContentNode.objects.filter(pk__in=book_ids, kind=ContentNode.Kind.BOOK):
                ch_count = ContentNode.objects.filter(path__startswith=b.path, depth=2, is_archived=False).count()
                teacher_books.append({
                    "pk": b.pk,
                    "title": b.title,
                    "author": b.author,
                    "chapters_count": ch_count,
                })
            context["teacher_books"] = teacher_books

            classrooms = []
            site_url = getattr(settings, "SITE_URL", "").rstrip("/")
            for c in Classroom.objects.filter(teacher=user, is_active=True).select_related("book").order_by("-created_at")[:6]:
                m_count = c.members.filter(status="active").count()
                classrooms.append({
                    "pk": c.pk,
                    "title": c.title,
                    "book": c.book,
                    "code": c.code,
                    "capacity": c.capacity,
                    "members_count": m_count,
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
