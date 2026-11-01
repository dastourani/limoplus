from django.contrib import admin, messages
from django.db.models import Count, F, Q
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.html import format_html

from apps.catalog.filters import NodeBookFilter, NodeChapterFilter, YesNoFilter

from .models import ExamSource, Flashcard, Question, Report


def manager_url(node, anchor: str) -> str:
    """The chapter manager page for an item in this node (a section or a chapter's introduction)."""
    from apps.catalog.models import ContentNode

    chapter = node if node.kind == ContentNode.Kind.CHAPTER else node.get_parent()
    if chapter is None or chapter.kind != ContentNode.Kind.CHAPTER or chapter.book() is None:
        return ""
    return reverse("admin:catalog_chapter_manager", args=[chapter.pk]) + anchor


class SourceFilter(admin.SimpleListFilter):
    title = "منبع"
    parameter_name = "source"

    def lookups(self, request, model_admin):
        return [("original", "تألیفی")] + [(str(s.pk), str(s)) for s in ExamSource.objects.all()]

    def queryset(self, request, queryset):
        if self.value() == "original":
            return queryset.filter(is_original=True)
        if self.value():
            return queryset.filter(sources__pk=self.value())
        return queryset


class HasQuickFilter(YesNoFilter):
    title = "راه‌حل سریع دارد"
    parameter_name = "quick"

    def yes(self, qs):
        return qs.exclude(quick_solution="")


class HasAlternativeFilter(YesNoFilter):
    title = "زاویه‌ی دیگر دارد"
    parameter_name = "alt"

    def yes(self, qs):
        return qs.exclude(alternative_view="")


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
    """Lists for finding things; adding and editing happen in «مدیریت فصل», so the file rules always apply."""

    def has_add_permission(self, request):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    @admin.display(description="جا (کتاب › فصل › بخش)")
    def place(self, obj):
        chapter = obj.node if obj.node.kind == "chapter" else obj.node.get_parent()
        book = obj.node.book()
        section = obj.node.title if obj.node.kind == "section" else "مقدمه‌ی فصل"
        return format_html(
            '<span style="font-size:11px;color:var(--body-quiet-color)">{} › فصل {}</span><br>{}',
            book.title if book else "بدون کتاب", (chapter.position or chapter.title) if chapter else "", section,
        )

    @admin.display(description="")
    def manage(self, obj):
        url = manager_url(obj.node, f"#{self.anchor}={obj.slug}")
        return format_html('<a class="button" href="{}">ویرایش</a>', url) if url else "—"

    def change_view(self, request, object_id, form_url="", extra_context=None):
        obj = self.model.objects.filter(pk=object_id).select_related("node").first()
        if obj:
            url = manager_url(obj.node, f"#{self.anchor}={obj.slug}")
            if url:
                return redirect(url)
        return super().change_view(request, object_id, form_url, extra_context)


SAMPLES_PER_BOOK = 10


@admin.register(Question)
class QuestionAdmin(_ManagedInChapter, admin.ModelAdmin):
    anchor = "q"
    list_display = ("short_stem", "place", "difficulty", "kind", "source_label", "answers", "open_reports", "is_sample", "is_archived", "manage")
    list_filter = (NodeBookFilter, NodeChapterFilter, SourceFilter, "difficulty", "kind", "domain", MeasuredFilter, HasQuickFilter,
                   HasAlternativeFilter, HasFlashcardsFilter, OpenReportsFilter, "is_sample", "is_free", "is_archived")
    actions = ("make_sample", "unmake_sample")

    @admin.action(description="نمونه‌ی قابل اشتراک شود (حداکثر ۱۰ در هر کتاب)")
    def make_sample(self, request, queryset):
        from apps.catalog.models import ContentNode

        steplen = ContentNode.steplen
        added = skipped = 0
        for q in queryset.select_related("node"):
            if q.is_sample:
                continue
            book_path = q.node.path[:steplen]
            if Question.objects.filter(is_sample=True, node__path__startswith=book_path).count() >= SAMPLES_PER_BOOK:
                skipped += 1
                continue
            Question.objects.filter(pk=q.pk).update(is_sample=True)
            added += 1
        if added:
            self.message_user(request, f"{added} تست نمونه‌ی قابل اشتراک شد.")
        if skipped:
            self.message_user(request, f"{skipped} تست نشد: هر کتاب حداکثر {SAMPLES_PER_BOOK} نمونه دارد.", level=messages.WARNING)

    @admin.action(description="از نمونه‌های قابل اشتراک برداشته شود")
    def unmake_sample(self, request, queryset):
        n = queryset.update(is_sample=False)
        self.message_user(request, f"{n} تست از نمونه‌ها برداشته شد.")
    search_fields = ("stem", "explanation", "quick_solution", "slug", "choices__text")
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("node").prefetch_related("sources").annotate(
            n_reports=Count("reports", filter=Q(reports__status=Report.Status.OPEN), distinct=True)
        ).order_by("node__path", "order", "id")

    @admin.display(description="صورت تست")
    def short_stem(self, obj):
        text = " ".join(obj.stem.split())
        return format_html('<div style="min-width:280px">{}</div>', text[:140] + ("…" if len(text) > 140 else ""))

    @admin.display(description="منبع")
    def source_label(self, obj):
        names = [str(s) for s in obj.sources.all()]
        return "، ".join(names) or ("تألیفی" if obj.is_original else "")

    @admin.display(description="پاسخ‌ها", ordering="answer_count")
    def answers(self, obj):
        if not obj.answer_count:
            return "—"
        return f"{obj.answer_count} ({round(100 * obj.correct_count / obj.answer_count)}٪ درست)"

    @admin.display(description="گزارش باز", ordering="n_reports")
    def open_reports(self, obj):
        return obj.n_reports or ""


@admin.register(Flashcard)
class FlashcardAdmin(_ManagedInChapter, admin.ModelAdmin):
    anchor = "f"
    list_display = ("title", "short_point", "place", "has_formula", "is_free", "is_archived", "manage")
    list_filter = (NodeBookFilter, NodeChapterFilter, HasFormulaFilter, LinkedToQuestionsFilter, "is_free", "is_archived")
    search_fields = ("title", "point", "slug", "formula")
    list_per_page = 50

    def get_queryset(self, request):
        return super().get_queryset(request).select_related("node").order_by("node__path", "order", "id")

    @admin.display(description="نکته")
    def short_point(self, obj):
        return obj.point[:80] + ("…" if len(obj.point) > 80 else "")

    @admin.display(description="فرمول", boolean=True)
    def has_formula(self, obj):
        return bool(obj.formula)


@admin.register(ExamSource)
class ExamSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "year", "group", "booklet")
    search_fields = ("name", "group")
    list_filter = ("year",)


@admin.register(Report)
class ReportAdmin(admin.ModelAdmin):
    list_display = ("created_at", "user", "reason", "status", "question", "flashcard", "node", "manage")
    list_filter = ("status", "reason")
    search_fields = ("note", "user__phone")
    raw_id_fields = ("user", "question", "flashcard", "node")
    actions = ["mark_fixed", "mark_rejected"]

    @admin.display(description="")
    def manage(self, obj):
        if obj.question_id:
            return format_html('<a class="button" href="{}">باز کردن</a>', manager_url(obj.question.node, f"#q={obj.question.slug}"))
        if obj.flashcard_id:
            return format_html('<a class="button" href="{}">باز کردن</a>', manager_url(obj.flashcard.node, f"#f={obj.flashcard.slug}"))
        if obj.node_id and obj.node.kind in ("section", "chapter"):
            return format_html('<a class="button" href="{}">باز کردن</a>', manager_url(obj.node, f"#s={obj.node.slug if obj.node.kind == 'section' else ''}"))
        return ""

    @admin.action(description="علامت «اصلاح شد»")
    def mark_fixed(self, request, queryset):
        queryset.update(status=Report.Status.FIXED, resolved_at=timezone.now())

    @admin.action(description="علامت «بررسی شد، درست بود»")
    def mark_rejected(self, request, queryset):
        queryset.update(status=Report.Status.REJECTED, resolved_at=timezone.now())
