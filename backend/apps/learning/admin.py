from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db.models import BooleanField, Count, Exists, F, Func, IntegerField, OuterRef, Q, Subquery, Value
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.catalog import access
from apps.catalog.panel_display import badges, tex
from apps.catalog.filters import NodeBookFilter, NodeChapterFilter, YesNoFilter

from .models import ExamSource, Flashcard, Question, QuestionSource, Report


def manager_url(node, anchor: str) -> str:
    """The chapter manager page for an item in this node (a section or a chapter's introduction)."""
    from apps.catalog.models import ContentNode

    chapter = node if node.kind == ContentNode.Kind.CHAPTER else node.get_parent()
    if chapter is None or chapter.kind != ContentNode.Kind.CHAPTER or chapter.book() is None:
        return ""
    return reverse("admin:catalog_chapter_manager", args=[chapter.pk]) + anchor


class SourceNameFilter(admin.SimpleListFilter):
    """The konkur by name (all its years); «تألیفی» for tests written by us."""

    title = "نام کنکور"
    parameter_name = "konkur"
    lp_list = True

    def lookups(self, request, model_admin):
        names = sorted(set(model_admin.get_queryset(request).values_list("sources__name", flat=True)) - {None})
        return [("original", "تألیفی")] + [(n, n) for n in names]

    def queryset(self, request, queryset):
        if self.value() == "original":
            return queryset.filter(is_original=True)
        if self.value():
            return queryset.filter(sources__name=self.value()).distinct()
        return queryset


class OneSourceFilter(admin.SimpleListFilter):
    """«منبع» from the exam sources list (?source=<id>): the tests of exactly that exam, shown only while chosen."""

    title = "منبع کنکور"
    parameter_name = "source"

    def lookups(self, request, model_admin):
        value = request.GET.get(self.parameter_name, "")
        visible = value.isdigit() and model_admin.get_queryset(request).filter(sources__pk=value).exists()
        source = ExamSource.objects.filter(pk=value).first() if visible else None
        return [(str(source.pk), str(source))] if source else []

    def queryset(self, request, queryset):
        return queryset.filter(sources__pk=self.value()).distinct() if self.value() else queryset


class SourceYearFilter(admin.SimpleListFilter):
    title = "سال کنکور"
    parameter_name = "year"

    def lookups(self, request, model_admin):
        from apps.catalog.jalali import fa_digits

        questions = model_admin.get_queryset(request)
        years = sorted((y for y in set(questions.values_list("sources__year", flat=True)) if y), reverse=True)
        out = [(str(y), fa_digits(y)) for y in years]
        if questions.filter(sources__year=0).exists():
            out.append(("0", "بدون سال (کتاب مرجع)"))
        return out

    def queryset(self, request, queryset):
        if self.value():
            return queryset.filter(sources__year=self.value()).distinct()
        return queryset


class RoleFilter(admin.SimpleListFilter):
    title = "نقش"
    parameter_name = "role"

    def lookups(self, request, model_admin):
        return [("core", "پایه"), ("extra", "تکمیلی")]

    def queryset(self, request, queryset):
        if self.value() == "core":
            return queryset.filter(is_extra=False)
        if self.value() == "extra":
            return queryset.filter(is_extra=True)
        return queryset


class HasSimilarFilter(YesNoFilter):
    title = "تست مشابه دارد"
    parameter_name = "similar"

    def yes(self, qs):
        return qs.filter(Q(similar_to__isnull=False) | Q(similar_from__isnull=False)).distinct()


class KeyChangedFilter(YesNoFilter):
    title = "پاسخ‌نامه‌اش اصلاح شده"
    parameter_name = "key"

    def yes(self, qs):
        return qs.filter(key_changed_at__isnull=False)


class JsonArrayLength(Func):
    """Length of a JSON list column (SQLite json_array_length, PostgreSQL jsonb_array_length)."""

    function = "JSON_ARRAY_LENGTH"
    output_field = IntegerField()

    def as_postgresql(self, compiler, connection, **extra):
        return super().as_sql(compiler, connection, function="JSONB_ARRAY_LENGTH", **extra)


class HasQuickFilter(YesNoFilter):
    title = "راه‌حل دیگر دارد"
    parameter_name = "quick"

    def yes(self, qs):
        return qs.exclude(solutions=[])


class HasAlternativeFilter(YesNoFilter):
    title = "بیش از یک راه‌حل دیگر دارد"
    parameter_name = "alt"

    def yes(self, qs):
        # Counted by the database: reading every test's solutions was slow on a big bank.
        return qs.alias(n_solutions=JsonArrayLength("solutions")).filter(n_solutions__gt=1)


class HasFlashcardsFilter(YesNoFilter):
    title = "به فلش‌کارت وصل است"
    parameter_name = "linked"

    def yes(self, qs):
        return qs.filter(flashcards__isnull=False).distinct()


class OpenReportsFilter(YesNoFilter):
    title = "گزارش خطای باز دارد"
    parameter_name = "reported"

    def yes(self, qs):
        return qs.filter(reports__status=Report.Status.OPEN).distinct()


class MeasuredFilter(admin.SimpleListFilter):
    title = "دشواری سنجیده‌شده (۳۰ پاسخ به بالا)"
    parameter_name = "measured"

    def lookups(self, request, model_admin):
        return [("easy", "آسان (بیش از ۷۰٪ درست)"), ("medium", "متوسط"), ("hard", "سخت (کمتر از ۴۰٪ درست)"), ("none", "هنوز کمتر از ۳۰ پاسخ")]

    def queryset(self, request, queryset):
        v = self.value()
        if v == "none":
            return queryset.filter(answer_count__lt=30)
        if v:
            qs = queryset.filter(answer_count__gte=30)
            if v == "easy":
                return qs.filter(correct_count__gt=F("answer_count") * 0.7)
            if v == "hard":
                return qs.filter(correct_count__lt=F("answer_count") * 0.4)
            return qs.filter(correct_count__gte=F("answer_count") * 0.4, correct_count__lte=F("answer_count") * 0.7)
        return queryset


class LinkedToQuestionsFilter(YesNoFilter):
    title = "به تستی وصل است"
    parameter_name = "linked"

    def yes(self, qs):
        return qs.filter(questions__isnull=False).distinct()


class HasFormulaFilter(YesNoFilter):
    title = "فرمول دارد"
    parameter_name = "formula"

    def yes(self, qs):
        return qs.exclude(formula="")


class _ManagedInChapter:
    """Lists for finding things; adding and editing happen in «مدیریت فصل», so the file rules always apply.
    The book and chapter of each row come with the list's own query (by tree path), not one query per row."""

    change_list_template = "admin/lp_tex_change_list.html"

    class Media:
        js = ("catalog/limo-preview.js", "catalog/lists.js")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        # Direct model editing bypasses the chapter file's validation and review trail.
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return False

    def changelist_view(self, request, extra_context=None):
        from apps.catalog.fresh import formula_macros

        return super().changelist_view(request, {**(extra_context or {}), "lp_macros": formula_macros()})

    def with_place(self, qs):
        from django.db.models import OuterRef, Subquery
        from django.db.models.functions import Substr

        from apps.catalog.models import ContentNode

        step = ContentNode.steplen
        book = ContentNode.objects.filter(path=Substr(OuterRef("node__path"), 1, step))
        chapter = ContentNode.objects.filter(path=Substr(OuterRef("node__path"), 1, 2 * step), kind=ContentNode.Kind.CHAPTER)
        return qs.select_related("node").annotate(
            p_book=Subquery(book.values("title")[:1]),
            p_chapter_id=Subquery(chapter.values("pk")[:1]),
            p_chapter_pos=Subquery(chapter.values("position")[:1]),
            p_chapter_title=Subquery(chapter.values("title")[:1]),
        )

    @admin.display(description="جا (کتاب › فصل › بخش)")
    def place(self, obj):
        from apps.catalog.jalali import fa_digits

        chapter = f"فصل {fa_digits(obj.p_chapter_pos)}" if obj.p_chapter_pos else (obj.p_chapter_title or "")
        section = obj.node.title if obj.node.kind == "section" else "مقدمه‌ی فصل"
        full = " › ".join(x for x in (obj.p_book or "بدون کتاب", obj.p_chapter_title or chapter, section) if x)
        book = obj.p_book or "بدون کتاب"
        if len(book) > 32:  # the whole name is in the tooltip; the section must stay in sight
            book = book[:30].rstrip() + "…"
        return format_html('<div class="lp-place lp-quiet" title="{}">{} › {} › {}</div>', full, book, chapter, section)

    @admin.display(description="")
    def manage(self, obj):
        if not getattr(obj, "p_chapter_id", None):
            return "—"
        url = reverse("admin:catalog_chapter_manager", args=[obj.p_chapter_id]) + f"#{self.anchor}={obj.slug}"
        return format_html('<a class="button" href="{}">ویرایش</a>', url)

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.get_queryset(request).filter(pk=object_id).select_related("node").first()
        if obj:
            url = manager_url(obj.node, f"#{self.anchor}={obj.slug}")
            if url:
                return redirect(url)
        return super().change_view(request, object_id, form_url, extra_context)


@admin.register(Question)
class QuestionAdmin(_ManagedInChapter, admin.ModelAdmin):
    anchor = "q"
    list_display = ("short_stem", "source_label", "level", "status", "manage")
    list_filter = (NodeBookFilter, NodeChapterFilter, SourceNameFilter, SourceYearFilter, OneSourceFilter, RoleFilter, "difficulty", "kind", "domain", MeasuredFilter,
                   HasQuickFilter, HasAlternativeFilter, HasSimilarFilter, KeyChangedFilter, HasFlashcardsFilter, OpenReportsFilter, "is_sample",
                   "is_free", "is_archived")
    actions = ("make_sample", "unmake_sample")

    @admin.action(description="قابل اشتراک شود (کاربر می‌تواند تصویرش را بفرستد، بدون جواب)", permissions=["change"])
    def make_sample(self, request, queryset):
        n = queryset.update(is_sample=True)
        self.message_user(request, f"{n} تست قابل اشتراک شد.")

    @admin.action(description="از نمونه‌های قابل اشتراک برداشته شود", permissions=["change"])
    def unmake_sample(self, request, queryset):
        n = queryset.update(is_sample=False)
        self.message_user(request, f"{n} تست از نمونه‌ها برداشته شد.")
    search_fields = ("stem", "explanation", "slug", "choices__text")
    list_per_page = 50

    def get_queryset(self, request):
        qs = access.scope_to_editor_books(super().get_queryset(request), request.user, "node__path")
        return self.with_place(qs).prefetch_related("sources").annotate(
            n_reports=Count("reports", filter=Q(reports__status=Report.Status.OPEN), distinct=True)
        ).order_by("node__path", "order", "id")

    @admin.display(description="وضعیت و پاسخ‌ها", ordering="answer_count")
    def status(self, obj):
        from apps.catalog.panel_display import fa_number

        tags = badges(obj.n_reports and (f"{fa_number(obj.n_reports)} گزارش باز", "red"), obj.is_archived and ("بایگانی", "grey"),
                      obj.is_sample and ("نمونه", "blue"), obj.is_extra and ("تکمیلی", "yellow"))
        return format_html('{}<div class="lp-quiet" style="margin-top:3px;white-space:nowrap">{}</div>', tags, self.answers(obj))

    @admin.display(description="صورت تست (و جای آن)")
    def short_stem(self, obj):
        return format_html('{}<div class="lp-clamp">{}</div>', self.place(obj), tex(obj.stem, 160))

    @admin.display(description="سطح و نوع", ordering="difficulty")
    def level(self, obj):
        kind = obj.get_kind_display() if obj.kind else ""
        return format_html('{}<br><span class="lp-quiet">{}</span>', obj.get_difficulty_display(), kind)

    @admin.display(description="منبع")
    def source_label(self, obj):
        from apps.catalog.jalali import fa_digits

        items = [(f"{s.name} {fa_digits(s.year)}" if s.year else s.name, "blue") for s in obj.sources.all()]
        return badges(*items, obj.is_original and not items and ("تألیفی", "grey"))

    @admin.display(description="پاسخ‌ها", ordering="answer_count")
    def answers(self, obj):
        from apps.catalog.panel_display import fa_number

        if not obj.answer_count:
            return "بی‌پاسخ"
        return f"{fa_number(obj.answer_count)} پاسخ، {fa_number(round(100 * obj.correct_count / obj.answer_count))}٪ درست"

    @admin.display(description="گزارش باز", ordering="n_reports")
    def open_reports(self, obj):
        return obj.n_reports or ""


@admin.register(Flashcard)
class FlashcardAdmin(_ManagedInChapter, admin.ModelAdmin):
    anchor = "f"
    list_display = ("short_title", "short_point", "status", "manage")
    list_filter = (NodeBookFilter, NodeChapterFilter, HasFormulaFilter, LinkedToQuestionsFilter, "is_free", "is_archived")
    search_fields = ("title", "point", "slug", "formula")
    list_per_page = 50

    def get_queryset(self, request):
        qs = access.scope_to_editor_books(super().get_queryset(request), request.user, "node__path")
        return self.with_place(qs).order_by("node__path", "order", "id")

    @admin.display(description="عنوان (رو) و جای آن", ordering="title")
    def short_title(self, obj):
        return format_html('{}<div>{}</div>', self.place(obj), tex(obj.title, 80))

    @admin.display(description="نکته (پشت)")
    def short_point(self, obj):
        formula = format_html('<div class="lp-tex lp-quiet">${}$</div>', obj.formula) if obj.formula else ""
        return format_html('<div class="lp-clamp">{}</div>{}', tex(obj.point, 120), formula)

    @admin.display(description="وضعیت")
    def status(self, obj):
        return badges(obj.is_archived and ("بایگانی", "grey"), obj.is_free and ("رایگان", "green"))


class ExamSourceNameFilter(admin.SimpleListFilter):
    title = "نام کنکور"
    parameter_name = "name"

    def lookups(self, request, model_admin):
        return [(n, n) for n in sorted(set(model_admin.get_queryset(request).values_list("name", flat=True)))]

    def queryset(self, request, queryset):
        return queryset.filter(name=self.value()) if self.value() else queryset


class ExamYearFilter(admin.SimpleListFilter):
    title = "سال"
    parameter_name = "year"

    def lookups(self, request, model_admin):
        from apps.catalog.jalali import fa_digits

        sources = model_admin.get_queryset(request)
        years = sorted((y for y in set(sources.values_list("year", flat=True)) if y), reverse=True)
        out = [(str(y), fa_digits(y)) for y in years]
        if sources.filter(year=0).exists():
            out.append(("0", "بدون سال (کتاب مرجع)"))
        return out

    def queryset(self, request, queryset):
        return queryset.filter(year=self.value()) if self.value() else queryset


@admin.register(ExamSource)
class ExamSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "shown_year", "shown_group", "shown_booklet", "n_questions")
    search_fields = ("name", "group")
    list_filter = (ExamSourceNameFilter, ExamYearFilter)
    ordering = ("-year", "name", "group", "booklet")

    def get_queryset(self, request):
        from django.db.models.functions import Coalesce, Substr

        from apps.catalog.models import ContentNode

        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs.annotate(n=Count("question", filter=Q(question__is_archived=False), distinct=True))
        roots = access.books_for_editor(request.user).values("path")
        linked_questions = (QuestionSource.objects.filter(source_id=OuterRef("pk"))
                            .annotate(_lp_root=Substr("question__node__path", 1, ContentNode.steplen))
                            .filter(_lp_root__in=roots))
        count = (linked_questions.order_by().values("source_id")
                 .annotate(n=Count("question_id", filter=Q(question__is_archived=False), distinct=True))
                 .values("n")[:1])
        return qs.annotate(_lp_used_by_editor=Exists(linked_questions), n=Coalesce(Subquery(count), 0)).filter(_lp_used_by_editor=True)

    def has_add_permission(self, request):
        return bool(request.user.is_superuser)

    def has_change_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    def has_delete_permission(self, request, obj=None):
        return bool(request.user.is_superuser)

    @admin.display(description="سال", ordering="year")
    def shown_year(self, obj):
        from apps.catalog.jalali import fa_digits

        return fa_digits(obj.year) if obj.year else "—"

    @admin.display(description="گروه/رشته", ordering="group")
    def shown_group(self, obj):
        return obj.group or "—"

    @admin.display(description="دفترچه", ordering="booklet")
    def shown_booklet(self, obj):
        return obj.booklet or "—"

    @admin.display(description="تست‌ها", ordering="n")
    def n_questions(self, obj):
        from apps.catalog.panel_display import fa_number

        if not obj.n:
            return "—"
        url = reverse("admin:learning_question_changelist") + f"?source={obj.pk}"
        return format_html('<a href="{}">{}</a>', url, fa_number(obj.n))


class ReportBookFilter(admin.SimpleListFilter):
    lp_list = True
    title = "کتاب"
    parameter_name = "book"

    def lookups(self, request, model_admin):
        from apps.catalog.filters import _book_choices

        return _book_choices(user=request.user, capability="can_view_reports")

    def queryset(self, request, queryset):
        from apps.catalog.models import ContentNode

        book = ContentNode.objects.filter(pk=self.value()).first() if self.value() else None
        if not book:
            return queryset
        return queryset.filter(Q(question__node__path__startswith=book.path) | Q(flashcard__node__path__startswith=book.path)
                               | Q(node__path__startswith=book.path))


class ReportKindFilter(admin.SimpleListFilter):
    title = "درباره‌ی"
    parameter_name = "about"

    def lookups(self, request, model_admin):
        return [("question", "تست"), ("flashcard", "فلش‌کارت"), ("text", "متن درس")]

    def queryset(self, request, queryset):
        v = self.value()
        if v == "question":
            return queryset.filter(question__isnull=False)
        if v == "flashcard":
            return queryset.filter(flashcard__isnull=False)
        if v == "text":
            return queryset.filter(question__isnull=True, flashcard__isnull=True, node__isnull=False)
        return queryset


class ReportArchivedFilter(admin.SimpleListFilter):
    """Reports whose section was archived since: picked all at once, they can be closed together."""

    title = "بخش"
    parameter_name = "gone"

    def lookups(self, request, model_admin):
        return [("yes", "بخش بایگانی‌شده"), ("no", "بخش فعال")]

    def queryset(self, request, queryset):
        if self.value() == "yes":
            return queryset.filter(p_archived=True)
        if self.value() == "no":
            return queryset.filter(p_archived=False)
        return queryset


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    """Reports come from learners in the app; here they are read, opened in the chapter manager and closed."""

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_fields(self, request, obj=None):
        if request.user.is_superuser:
            return super().get_fields(request, obj)
        # Teacher reports are reviewable, but never a route to the reporter's account or editable report metadata.
        return ("status", "reason", "note", "quote", "question", "flashcard", "node", "mode", "box", "created_at", "resolved_at")

    def get_readonly_fields(self, request, obj=None):
        return self.get_fields(request, obj) if not request.user.is_superuser else ()

    def get_search_fields(self, request):
        if request.user.is_superuser:
            return self.search_fields
        return ("note", "quote", "question__stem", "flashcard__title", "node__title")

    def get_actions(self, request):
        actions = super().get_actions(request)
        if not request.user.is_superuser:
            actions.pop("block_reporter", None)
            actions.pop("unblock_reporter", None)
        return actions

    list_display = ("about", "when", "state", "manage")
    list_filter = ("status", "reason", ReportBookFilter, ReportKindFilter, ReportArchivedFilter)
    search_fields = ("note", "quote", "user__phone", "question__stem", "flashcard__title", "node__title")
    raw_id_fields = ("user", "question", "flashcard", "node")
    actions = ["mark_fixed", "mark_rejected", "block_reporter", "unblock_reporter"]
    change_list_template = "admin/lp_tex_change_list.html"

    class Media:
        js = ("catalog/limo-preview.js", "catalog/lists.js")

    def changelist_view(self, request, extra_context=None):
        from apps.catalog.fresh import formula_macros

        return super().changelist_view(request, {**(extra_context or {}), "lp_macros": formula_macros()})

    def get_queryset(self, request):
        from django.db.models.functions import Coalesce, Substr

        from apps.catalog.models import ContentNode

        # The chapter of whatever was reported, from its tree path: no query per row for the «باز کردن» link.
        item_path = Coalesce("question__node__path", "flashcard__node__path", "node__path")
        # Was the reported item's section archived since (its tests and cards go with it)?
        archived = Coalesce("question__node__is_archived", "flashcard__node__is_archived", "node__is_archived", Value(False))
        chapter = ContentNode.objects.filter(path=Substr(OuterRef("item_path"), 1, 2 * ContentNode.steplen), kind=ContentNode.Kind.CHAPTER)
        qs = (super().get_queryset(request).select_related("user", "question", "flashcard", "node")
              .annotate(item_path=item_path, p_archived=archived,
                        p_reporter_visible=Value(bool(request.user.is_superuser), output_field=BooleanField()))
              .annotate(p_chapter_id=Subquery(chapter.values("pk")[:1])))
        return access.scope_to_editor_books(qs, request.user, "item_path", capability="can_view_reports")

    @admin.display(description="گزارش")
    def about(self, obj):
        from apps.catalog.panel_display import tex

        if obj.question_id:
            kind, text = "تست", tex(obj.question.stem, 110)
        elif obj.flashcard_id:
            kind, text = "فلش‌کارت", tex(obj.flashcard.title, 110)
        elif obj.node_id:
            where = "، ".join(x for x in (obj.get_mode_display() if obj.mode else "", obj.box) if x)
            kind, text = f"متن درس ({where})" if where else "متن درس", obj.node.title
        else:
            kind, text = "", ""
        # What the learner selected, then what they wrote.
        quote = format_html('<div class="lp-quote" style="margin-top:4px;padding:4px 8px;border-right:3px solid #F2C200;background:#FFFBEA;color:#17201A;border-radius:4px">{}</div>',
                            tex(obj.quote, 300)) if obj.quote else ""
        note = format_html('<div style="margin-top:3px">توضیح: «{}»</div>', obj.note[:200]) if obj.note else ""
        gone = ("بخش بایگانی‌شده", "grey") if getattr(obj, "p_archived", False) else None
        return format_html('<div style="min-width:240px">{} <span class="lp-quiet">{}:</span> {}{}{}</div>',
                           badges((obj.get_reason_display(), "blue"), gone), kind, text, quote, note)

    @admin.display(description="گزارش‌دهنده و زمان", ordering="created_at")
    def when(self, obj):
        from apps.catalog.jalali import jalali_datetime

        if getattr(obj, "p_reporter_visible", True):
            user_url = reverse("admin:accounts_user_change", args=[obj.user_id])
            reporter = format_html('<a href="{}">{}</a>', user_url, obj.user.phone)
            tag = badges(("گزارش بسته", "red")) if not getattr(obj.user, "can_report", True) else ""
        else:
            reporter, tag = "دانشجو", ""
        return format_html('{} {}<div class="lp-quiet" style="white-space:nowrap">{}</div>',
                           reporter, tag, jalali_datetime(obj.created_at))

    @admin.display(description="وضعیت", ordering="status")
    def state(self, obj):
        color = {Report.Status.OPEN: "red", Report.Status.FIXED: "green"}.get(obj.status, "grey")
        return badges((obj.get_status_display(), color))

    @admin.display(description="")
    def manage(self, obj):
        if not getattr(obj, "p_chapter_id", None):
            return ""
        if obj.question_id:
            anchor = f"#q={obj.question.slug}"
        elif obj.flashcard_id:
            anchor = f"#f={obj.flashcard.slug}"
        else:
            from urllib.parse import quote as q

            anchor = f"#s={obj.node.slug if obj.node.kind == 'section' else ''}"
            if obj.mode:
                anchor += f"&m={obj.mode}"
            if obj.quote and not getattr(obj, "p_archived", False):
                # The chapter manager opens the text and selects these words.
                anchor += f"&find={q(obj.quote[:300], safe='')}"
        if getattr(obj, "p_archived", False):
            from urllib.parse import quote as q

            # The section is gone from the chapter: the manager says so and shows what the learner reported.
            anchor += "&gone=1&r=" + q((obj.quote or obj.note or "")[:300], safe="")
        url = reverse("admin:catalog_chapter_manager", args=[obj.p_chapter_id]) + anchor
        return format_html('<a class="button" style="white-space:nowrap" href="{}">باز کردن</a>', url)

    @admin.action(description="علامت «اصلاح شد»")
    def mark_fixed(self, request, queryset):
        queryset.update(status=Report.Status.FIXED, resolved_at=timezone.now())

    @admin.action(description="علامت «بررسی شد، درست بود»")
    def mark_rejected(self, request, queryset):
        queryset.update(status=Report.Status.REJECTED, resolved_at=timezone.now())

    @admin.action(description="رد گزارش و بستن امکان ارسال گزارش برای این کاربر")
    def block_reporter(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        from apps.accounts.models import User

        user_ids = set(queryset.values_list("user_id", flat=True))
        queryset.update(status=Report.Status.REJECTED, resolved_at=timezone.now())
        User.objects.filter(pk__in=user_ids).update(can_report=False)
        self.message_user(request, f"امکان ارسال گزارش برای {len(user_ids)} کاربر بسته شد.")

    @admin.action(description="باز کردن دوباره امکان ارسال گزارش برای این کاربر")
    def unblock_reporter(self, request, queryset):
        if not request.user.is_superuser:
            raise PermissionDenied
        from apps.accounts.models import User

        user_ids = set(queryset.values_list("user_id", flat=True))
        User.objects.filter(pk__in=user_ids).update(can_report=True)
        self.message_user(request, f"امکان ارسال گزارش برای {len(user_ids)} کاربر دوباره باز شد.")


_each_context = admin.site.each_context


def _each_context_with_reports(request):
    """Every panel page knows how many error reports are open: the side menu shows it next to «گزارش‌های ایراد»."""
    context = _each_context(request)
    if getattr(request, "user", None) is not None and request.user.is_active and request.user.is_staff:
        model_admin = admin.site._registry.get(Report)
        reports = model_admin.get_queryset(request) if model_admin else Report.objects.none()
        context["lp_open_reports"] = reports.filter(status=Report.Status.OPEN).count()
    return context


admin.site.each_context = _each_context_with_reports
