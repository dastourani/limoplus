"""Manager-only and book-scoped administration for phase-four workflows."""

from datetime import timedelta

from django import forms
from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponseNotAllowed
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html, format_html_join

from apps.catalog import access
from apps.catalog.jalali import jalali_datetime
from apps.catalog.models import BookEditor, ContentNode
from apps.commerce.models import Entitlement

from .forms import BookAccessRequestChangeForm, BookAccessRequestCreateForm, GroupAccessRenewForm, GroupAccessRevokeForm
from .models import (
    BookAccessEvent,
    BookAccessMember,
    BookAccessRequest,
    BookAccessRequestEvent,
    PublicationRequest,
    PublicationRequestEvent,
    TeacherApplication,
    TeacherInvitation,
)
from .publication import publication_content_digest, record_publication_request, review_publication_request


_TEACHER_CAPABILITIES = (
    "can_edit_content",
    "can_request_publication",
    "can_request_group_access",
    "can_view_reports",
    "can_view_aggregate_study",
    "can_view_aggregate_sales",
)


def _is_manager(user):
    return bool(user and user.is_active and user.is_staff and user.is_superuser)


def _has_book_capability(user, book, capability):
    if not access.is_book_teacher(user) or not book or book.is_archived or book.is_inbox:
        return False
    return BookEditor.objects.filter(user=user, book=book, **{capability: True}).exists()


def _event_action_for_access(previous_status, new_status):
    if new_status == BookAccessRequest.Status.APPROVED:
        return BookAccessRequestEvent.Action.APPROVED
    if new_status == BookAccessRequest.Status.REJECTED:
        return BookAccessRequestEvent.Action.REJECTED
    if new_status == BookAccessRequest.Status.NEEDS_INFO:
        return BookAccessRequestEvent.Action.NEEDS_INFO
    if previous_status == BookAccessRequest.Status.NEEDS_INFO and new_status == BookAccessRequest.Status.PENDING:
        return BookAccessRequestEvent.Action.REOPENED
    return BookAccessRequestEvent.Action.NOTE_UPDATED


class TeacherInvitationAdminForm(forms.ModelForm):
    class Meta:
        model = TeacherInvitation
        fields = "__all__"

    def clean(self):
        data = super().clean()
        application = data.get("application")
        book = data.get("book")
        status = data.get("status")
        reason = (data.get("revocation_reason") or "").strip()

        if not self.instance.pk:
            if application and application.status != TeacherApplication.Status.APPROVED:
                self.add_error("application", "ابتدا باید درخواست استاد جداگانه تأیید شود.")
            if application and book and TeacherInvitation.objects.filter(
                application=application,
                book=book,
                status=TeacherInvitation.Status.ISSUED,
                expires_at__gt=timezone.now(),
            ).exists():
                self.add_error("book", "برای همین درخواست و کتاب، یک پیوند فعال وجود دارد؛ آن را لغو یا منقضی کنید.")
        elif "status" in self.fields:
            previous = TeacherInvitation.objects.filter(pk=self.instance.pk).values_list("status", flat=True).first()
            if previous == TeacherInvitation.Status.ISSUED:
                if status not in (TeacherInvitation.Status.ISSUED, TeacherInvitation.Status.REVOKED):
                    self.add_error("status", "از این فرم فقط می‌توان پیوند صادرشده را لغو کرد.")
                if status == TeacherInvitation.Status.REVOKED and not reason:
                    self.add_error("revocation_reason", "برای لغو، دلیل را ثبت کنید.")
                if status == TeacherInvitation.Status.ISSUED and reason:
                    self.add_error("revocation_reason", "برای ثبت دلیل، وضعیت را روی «لغوشده» بگذارید.")
            elif status != previous:
                self.add_error("status", "دعوت پذیرفته‌شده یا منقضی‌شده قابل بازنویسی نیست.")
        return data


class TeacherInvitationStatusFilter(admin.SimpleListFilter):
    title = "وضعیت دعوت"
    parameter_name = "effective_status"

    def lookups(self, request, model_admin):
        return TeacherInvitation.Status.choices

    def queryset(self, request, queryset):
        status = self.value()
        if status == TeacherInvitation.Status.ISSUED:
            return queryset.filter(status=status, expires_at__gt=timezone.now())
        if status == TeacherInvitation.Status.EXPIRED:
            return queryset.filter(
                Q(status=TeacherInvitation.Status.EXPIRED)
                | Q(status=TeacherInvitation.Status.ISSUED, expires_at__lte=timezone.now())
            )
        if status:
            return queryset.filter(status=status)
        return queryset


@admin.register(TeacherInvitation)
class TeacherInvitationAdmin(admin.ModelAdmin):
    """Only the manager issues or revokes a hashed, one-use link; its raw token is shown only once."""

    form = TeacherInvitationAdminForm
    list_display = (
        "application", "book", "status_label", "expires_at", "capability_summary",
        "issued_audit", "accepted_audit", "revoked_audit", "revocation_reason_label",
    )
    list_filter = (TeacherInvitationStatusFilter, "book")
    search_fields = ("application__name", "application__phone", "book__title")
    list_select_related = ("application", "book", "created_by", "accepted_by", "revoked_by")
    ordering = ("-created_at", "-pk")
    actions = None

    @admin.display(description="وضعیت", ordering="status")
    def status_label(self, obj):
        if obj.status == TeacherInvitation.Status.ISSUED and obj.is_expired:
            return "منقضی‌شده"
        return obj.get_status_display()

    @admin.display(description="قابلیت‌های این دعوت")
    def capability_summary(self, obj):
        labels = (
            str(TeacherInvitation._meta.get_field(field).verbose_name)
            for field in _TEACHER_CAPABILITIES
            if getattr(obj, field)
        )
        rendered = tuple(labels)
        if not rendered:
            return "قابلیتی ثبت نشده"
        return format_html_join("<br>", "{}", ((label,) for label in rendered))

    @admin.display(description="دعوت‌کننده · زمان صدور")
    def issued_audit(self, obj):
        return format_html("{}<br>{}", obj.created_by, jalali_datetime(obj.created_at))

    @admin.display(description="پذیرنده · زمان پذیرش")
    def accepted_audit(self, obj):
        if not obj.accepted_by or not obj.accepted_at:
            return "—"
        return format_html("{}<br>{}", obj.accepted_by, jalali_datetime(obj.accepted_at))

    @admin.display(description="لغوکننده · زمان لغو")
    def revoked_audit(self, obj):
        if not obj.revoked_by or not obj.revoked_at:
            return "—"
        return format_html("{}<br>{}", obj.revoked_by, jalali_datetime(obj.revoked_at))

    @admin.display(description="دلیل لغو")
    def revocation_reason_label(self, obj):
        return obj.revocation_reason or "—"

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("application", "book", "expires_at", *_TEACHER_CAPABILITIES)
        status_field = (
            "status_label"
            if obj.status == TeacherInvitation.Status.ISSUED and obj.is_expired
            else "status"
        )
        return (
            "application", "book", status_field, "expires_at", *_TEACHER_CAPABILITIES,
            "created_by", "created_at", "accepted_by", "accepted_at", "revoked_by", "revoked_at", "revocation_reason",
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        fields = (
            "application", "book", "expires_at", *_TEACHER_CAPABILITIES,
            "created_by", "created_at", "accepted_by", "accepted_at", "revoked_by", "revoked_at",
        )
        if obj.status == TeacherInvitation.Status.ISSUED and obj.is_expired:
            return (*fields, "status_label", "revocation_reason")
        if obj.status != TeacherInvitation.Status.ISSUED:
            return (*fields, "status", "revocation_reason")
        return fields

    def has_module_permission(self, request):
        return _is_manager(request.user)

    def has_view_permission(self, request, obj=None):
        return _is_manager(request.user)

    def has_add_permission(self, request):
        return _is_manager(request.user)

    def has_change_permission(self, request, obj=None):
        return _is_manager(request.user)

    def has_delete_permission(self, request, obj=None):
        return False

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "application":
            kwargs["queryset"] = TeacherApplication.objects.filter(status=TeacherApplication.Status.APPROVED)
        elif db_field.name == "book":
            kwargs["queryset"] = ContentNode.objects.filter(
                kind=ContentNode.Kind.BOOK, depth=1, is_archived=False, is_inbox=False
            ).order_by("title")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not _is_manager(request.user):
            raise PermissionDenied
        if not change:
            raw_token = TeacherInvitation.new_token()
            now = timezone.now()
            with transaction.atomic():
                application = TeacherApplication.objects.select_for_update().get(pk=obj.application_id)
                if application.status != TeacherApplication.Status.APPROVED:
                    raise ValidationError("فقط برای درخواست تأییدشده می‌توان دعوت صادر کرد.")
                TeacherInvitation.objects.filter(
                    application=obj.application,
                    book=obj.book,
                    status=TeacherInvitation.Status.ISSUED,
                    expires_at__lte=now,
                ).update(status=TeacherInvitation.Status.EXPIRED)
                if TeacherInvitation.objects.filter(
                    application=obj.application,
                    book=obj.book,
                    status=TeacherInvitation.Status.ISSUED,
                    expires_at__gt=now,
                ).exists():
                    raise ValidationError("برای همین درخواست و کتاب، پیوند فعال دیگری وجود دارد.")
                obj.token_hash = TeacherInvitation.digest_token(raw_token)
                obj.created_by = request.user
                super().save_model(request, obj, form, change)
            url = f"{request.build_absolute_uri(reverse('website:teacher-invitation'))}#{raw_token}"
            messages.success(
                request,
                format_html("پیوند یک‌بارمصرف را همین حالا برای استاد بفرستید؛ پس از بستن این پیام دوباره نمایش داده نمی‌شود: <a dir='ltr' href='{0}'>{0}</a>", url),
            )
            return

        with transaction.atomic():
            previous = TeacherInvitation.objects.select_for_update().get(pk=obj.pk)
            if previous.status == TeacherInvitation.Status.ISSUED and obj.status == TeacherInvitation.Status.REVOKED:
                obj.revoked_by = request.user
                obj.revoked_at = timezone.now()
                obj.revocation_reason = obj.revocation_reason.strip()
            elif obj.status != previous.status:
                raise ValidationError("وضعیت این دعوت قابل تغییر نیست.")
            super().save_model(request, obj, form, change)

    def response_add(self, request, obj, post_url_continue=None):
        response = super().response_add(request, obj, post_url_continue)
        response["Cache-Control"] = "no-store, max-age=0"
        response["Referrer-Policy"] = "no-referrer"
        return response


@admin.register(BookAccessRequest)
class BookAccessRequestAdmin(admin.ModelAdmin):
    """Teachers may submit a private number list; only a superuser chooses the book and expiry approval."""

    form = BookAccessRequestCreateForm
    list_display = ("book", "requester", "status_label", "member_count", "submitted_at", "reviewed_at")
    list_filter = ("status", "book")
    search_fields = ("book__title", "requested_by__phone", "request_note")
    list_select_related = ("book", "requested_by", "reviewed_by")
    ordering = ("-submitted_at", "-pk")
    actions = None

    @admin.display(description="درخواست‌دهنده")
    def requester(self, obj):
        return obj.requested_by.phone

    @admin.display(description="وضعیت", ordering="status")
    def status_label(self, obj):
        return obj.get_status_display()

    @admin.display(description="شماره‌های یکتا")
    def member_count(self, obj):
        return obj.members.count()

    @admin.display(description="فهرست پیشنهادی")
    def members_display(self, obj):
        phones = obj.members.order_by("phone").values_list("phone", flat=True)
        return format_html_join("<br>", '<span dir="ltr">{}</span>', ((phone,) for phone in phones)) or "—"

    def get_form(self, request, obj=None, **kwargs):
        kwargs.setdefault("form", BookAccessRequestCreateForm if obj is None else BookAccessRequestChangeForm)
        return super().get_form(request, obj, **kwargs)

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("book", "request_note", "member_phones")
        return (
            "book", "requested_by", "request_note", "members_display", "status", "review_note",
            "expiry_policy", "ends_on", "duration_days", "submitted_at", "reviewed_by", "reviewed_at",
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        if not _is_manager(request.user):
            return self.get_fields(request, obj)
        fixed = ("book", "requested_by", "request_note", "members_display", "submitted_at", "reviewed_by", "reviewed_at")
        if obj.status in (BookAccessRequest.Status.APPROVED, BookAccessRequest.Status.REJECTED):
            return (*fixed, "status", "review_note", "expiry_policy", "ends_on", "duration_days")
        return fixed

    def get_queryset(self, request):
        qs = super().get_queryset(request).annotate(_lp_member_count=Count("members", distinct=True))
        if _is_manager(request.user):
            return qs
        return qs.filter(requested_by=request.user)

    def has_module_permission(self, request):
        if _is_manager(request.user):
            return True
        return bool(
            access.is_book_teacher(request.user)
            and BookEditor.objects.filter(user=request.user, can_request_group_access=True).exists()
        )

    def has_view_permission(self, request, obj=None):
        if _is_manager(request.user):
            return True
        if obj is not None:
            return bool(obj.requested_by_id == request.user.pk)
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        if _is_manager(request.user) or not access.is_book_teacher(request.user):
            return False
        return BookEditor.objects.filter(
            user=request.user, can_request_group_access=True, book__kind=ContentNode.Kind.BOOK,
            book__depth=1, book__is_archived=False, book__is_inbox=False,
        ).exists()

    def has_change_permission(self, request, obj=None):
        return _is_manager(request.user)

    def has_delete_permission(self, request, obj=None):
        return False

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "book":
            books = ContentNode.objects.filter(
                kind=ContentNode.Kind.BOOK, depth=1, is_archived=False, is_inbox=False
            )
            if not _is_manager(request.user):
                allowed_ids = BookEditor.objects.filter(
                    user=request.user, can_request_group_access=True
                ).values("book_id")
                books = books.filter(pk__in=allowed_ids)
            kwargs["queryset"] = books.order_by("title")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            if not _has_book_capability(request.user, obj.book, "can_request_group_access"):
                raise PermissionDenied
            phones = getattr(form, "normalized_phones", None)
            if not phones:
                raise ValidationError("فهرست شماره‌های معتبر خالی است.")
            with transaction.atomic():
                obj.requested_by = request.user
                obj.status = BookAccessRequest.Status.PENDING
                obj.expiry_policy = ""
                obj.ends_on = None
                obj.duration_days = None
                obj.full_clean()
                super().save_model(request, obj, form, change)
                BookAccessMember.objects.bulk_create([
                    BookAccessMember(request=obj, book=obj.book, phone=phone)
                    for phone in phones
                ])
                BookAccessRequestEvent.objects.create(
                    request=obj,
                    action=BookAccessRequestEvent.Action.SUBMITTED,
                    actor=request.user,
                    reason=obj.request_note[:500],
                )
            duplicates = getattr(form, "duplicate_count", 0)
            extra = f"؛ {duplicates} شماره‌ی تکراری حذف شد" if duplicates else ""
            self.message_user(
                request,
                f"پیشنهاد برای {len(phones)} شماره‌ی یکتا ثبت شد{extra}. هیچ حساب یا دسترسی‌ای ایجاد نشده؛ تأیید مدیر کل لازم است.",
                level=messages.SUCCESS,
            )
            return

        if not _is_manager(request.user):
            raise PermissionDenied
        with transaction.atomic():
            previous = BookAccessRequest.objects.select_for_update().get(pk=obj.pk)
            if previous.status not in (BookAccessRequest.Status.PENDING, BookAccessRequest.Status.NEEDS_INFO):
                raise ValidationError("درخواست نهایی‌شده قابل ویرایش نیست؛ برای تغییر، درخواست تازه بسازید.")
            status_changed = obj.status != previous.status
            note_changed = obj.review_note != previous.review_note
            expiry_changed = any(getattr(obj, field) != getattr(previous, field) for field in ("expiry_policy", "ends_on", "duration_days"))
            if obj.status in (BookAccessRequest.Status.NEEDS_INFO, BookAccessRequest.Status.APPROVED, BookAccessRequest.Status.REJECTED) and not (obj.review_note or "").strip():
                raise ValidationError("برای ثبت تصمیم مدیر، دلیل یا یادداشت را وارد کنید.")
            if not (status_changed or note_changed or expiry_changed):
                super().save_model(request, obj, form, change)
                return
            if obj.status == BookAccessRequest.Status.APPROVED:
                obj.full_clean()
            elif obj.expiry_policy or obj.ends_on or obj.duration_days is not None:
                raise ValidationError("سیاست انقضا را فقط هنگام تأیید مدیر تعیین کنید.")

            obj.reviewed_by = request.user
            obj.reviewed_at = timezone.now()
            super().save_model(request, obj, form, change)
            if status_changed and obj.status == BookAccessRequest.Status.APPROVED:
                obj.members.filter(status=BookAccessMember.Status.PENDING_REVIEW).update(status=BookAccessMember.Status.WAITING_OTP)
            elif status_changed and obj.status == BookAccessRequest.Status.REJECTED:
                obj.members.filter(status=BookAccessMember.Status.PENDING_REVIEW).update(status=BookAccessMember.Status.REJECTED)

            action = _event_action_for_access(previous.status, obj.status) if status_changed else BookAccessRequestEvent.Action.NOTE_UPDATED
            BookAccessRequestEvent.objects.create(
                request=obj,
                action=action,
                actor=request.user,
                reason=obj.review_note[:500],
                expiry_policy=obj.expiry_policy,
                ends_on=obj.ends_on,
                duration_days=obj.duration_days,
            )


class PublicationRequestAdminForm(forms.ModelForm):
    class Meta:
        model = PublicationRequest
        fields = "__all__"

    def clean(self):
        data = super().clean()
        status = data.get("status")
        note = (data.get("review_note") or "").strip()
        if self.instance.pk and "status" in self.fields:
            previous = PublicationRequest.objects.filter(pk=self.instance.pk).values_list("status", flat=True).first()
            if previous in (PublicationRequest.Status.APPROVED, PublicationRequest.Status.REJECTED) and status != previous:
                self.add_error("status", "درخواست نهایی‌شده قابل بازنویسی نیست.")
            if previous in (PublicationRequest.Status.PENDING, PublicationRequest.Status.NEEDS_INFO) and status == PublicationRequest.Status.APPROVED:
                book = self.instance.book
                try:
                    if book.is_archived or book.is_inbox:
                        self.add_error("status", "کتاب بایگانی‌شده یا صندوق تست قابل انتشار نیست.")
                    elif publication_content_digest(book) != self.instance.content_digest:
                        self.add_error("status", "محتوا پس از ثبت درخواست تغییر کرده؛ نسخه‌ی تازه باید دوباره ارسال شود.")
                except ValidationError as exc:
                    self.add_error("status", exc)
            if status in (PublicationRequest.Status.NEEDS_INFO, PublicationRequest.Status.APPROVED, PublicationRequest.Status.REJECTED) and not note:
                self.add_error("review_note", "برای ثبت تصمیم انتشار، دلیل یا یادداشت را وارد کنید.")
        return data


@admin.register(PublicationRequest)
class PublicationRequestAdmin(admin.ModelAdmin):
    """Teachers may submit a version for review; only the superuser can release it publicly."""

    form = PublicationRequestAdminForm
    list_display = ("book", "requester", "status_label", "submitted_at", "reviewed_at", "digest_short")
    list_filter = ("status", "book")
    search_fields = ("book__title", "requested_by__phone", "request_note")
    list_select_related = ("book", "requested_by", "reviewed_by")
    ordering = ("-submitted_at", "-pk")
    actions = None

    @admin.display(description="درخواست‌دهنده")
    def requester(self, obj):
        return obj.requested_by.phone

    @admin.display(description="وضعیت", ordering="status")
    def status_label(self, obj):
        return obj.get_status_display()

    @admin.display(description="نسخه")
    def digest_short(self, obj):
        return obj.content_digest[:12]

    def get_fields(self, request, obj=None):
        if obj is None:
            return ("book", "request_note")
        if _is_manager(request.user):
            return (
                "book", "requested_by", "request_note", "content_digest", "status", "review_note",
                "submitted_at", "reviewed_by", "reviewed_at",
            )
        return ("book", "request_note", "content_digest", "status", "submitted_at", "reviewed_at")

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        if not _is_manager(request.user):
            return self.get_fields(request, obj)
        fixed = ("book", "requested_by", "request_note", "content_digest", "submitted_at", "reviewed_by", "reviewed_at")
        if obj.status in (PublicationRequest.Status.APPROVED, PublicationRequest.Status.REJECTED):
            return (*fixed, "status", "review_note")
        return fixed

    def get_form(self, request, obj=None, **kwargs):
        base_form = super().get_form(request, obj, **kwargs)
        if obj is not None:
            return base_form
        submitter = request.user

        class SubmissionForm(base_form):
            def clean(self):
                data = super().clean()
                book = data.get("book")
                if book and _has_book_capability(submitter, book, "can_request_publication"):
                    digest = publication_content_digest(book)
                    if PublicationRequest.objects.filter(
                        book=book,
                        requested_by=submitter,
                        content_digest=digest,
                        status__in=(PublicationRequest.Status.PENDING, PublicationRequest.Status.NEEDS_INFO),
                    ).exists():
                        self.add_error("book", "همین نسخه پیش‌تر برای بازبینی فرستاده شده است.")
                return data

        return SubmissionForm

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if _is_manager(request.user):
            return qs
        return qs.filter(requested_by=request.user)

    def has_module_permission(self, request):
        if _is_manager(request.user):
            return True
        return bool(
            access.is_book_teacher(request.user)
            and BookEditor.objects.filter(user=request.user, can_request_publication=True).exists()
        )

    def has_view_permission(self, request, obj=None):
        if _is_manager(request.user):
            return True
        if obj is not None:
            return bool(obj.requested_by_id == request.user.pk)
        return self.has_module_permission(request)

    def has_add_permission(self, request):
        if _is_manager(request.user) or not access.is_book_teacher(request.user):
            return False
        return BookEditor.objects.filter(
            user=request.user, can_request_publication=True, book__kind=ContentNode.Kind.BOOK,
            book__depth=1, book__is_archived=False, book__is_inbox=False,
        ).exists()

    def has_change_permission(self, request, obj=None):
        return _is_manager(request.user)

    def has_delete_permission(self, request, obj=None):
        return False

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name == "book":
            books = ContentNode.objects.filter(
                kind=ContentNode.Kind.BOOK, depth=1, is_archived=False, is_inbox=False
            )
            if not _is_manager(request.user):
                allowed_ids = BookEditor.objects.filter(
                    user=request.user, can_request_publication=True
                ).values("book_id")
                books = books.filter(pk__in=allowed_ids)
            kwargs["queryset"] = books.order_by("title")
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        if not change:
            if not _has_book_capability(request.user, obj.book, "can_request_publication"):
                raise PermissionDenied
            with transaction.atomic():
                digest = publication_content_digest(obj.book)
                if PublicationRequest.objects.filter(
                    book=obj.book, requested_by=request.user, content_digest=digest,
                    status__in=(PublicationRequest.Status.PENDING, PublicationRequest.Status.NEEDS_INFO),
                ).exists():
                    raise ValidationError("همین نسخه پیش‌تر برای بازبینی فرستاده شده است.")
                obj.requested_by = request.user
                obj.content_digest = digest
                obj.status = PublicationRequest.Status.PENDING
                obj.review_note = ""
                super().save_model(request, obj, form, change)
                record_publication_request(obj, actor=request.user, action=PublicationRequestEvent.Action.SUBMITTED, reason=obj.request_note)
            return

        if not _is_manager(request.user):
            raise PermissionDenied
        previous = PublicationRequest.objects.get(pk=obj.pk)
        if previous.status not in (PublicationRequest.Status.PENDING, PublicationRequest.Status.NEEDS_INFO):
            raise ValidationError("درخواست نهایی‌شده قابل ویرایش نیست.")
        if obj.status == previous.status and obj.review_note == previous.review_note:
            super().save_model(request, obj, form, change)
            return
        reviewed = review_publication_request(
            obj.pk, actor=request.user, status=obj.status, review_note=obj.review_note
        )
        obj.status = reviewed.status
        obj.review_note = reviewed.review_note
        obj.reviewed_by = reviewed.reviewed_by
        obj.reviewed_at = reviewed.reviewed_at


class BookAccessActionAdminMixin:
    """Shared no-cache, manager-only action page context."""

    def _action_response(self, request, member, form, *, title, action):
        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "title": title,
            "original": member,
            "current_end_fa": (
                jalali_datetime(member.entitlement.ends_at)
                if member.entitlement_id and member.entitlement.ends_at
                else ""
            ),
            "form": form,
            "action_name": action,
            "change_url": reverse("admin:website_bookaccessmember_change", args=[member.pk]),
        }
        response = render(request, "admin/website/book_access_action.html", context)
        response["Cache-Control"] = "no-store, max-age=0"
        return response


@admin.register(BookAccessMember)
class BookAccessMemberAdmin(BookAccessActionAdminMixin, admin.ModelAdmin):
    """Manager-only phone/member view. Changes to the approved list require a new request."""

    list_display = ("book", "phone_ltr", "request_link", "state", "user_link", "activated_at", "ends_at", "manage_links")
    list_filter = ("status", "book")
    search_fields = ("phone", "user__phone", "book__title")
    list_select_related = ("book", "request", "user", "entitlement")
    ordering = ("book__title", "phone", "pk")
    actions = None
    fields = (
        "request", "book", "phone", "status", "user", "entitlement", "activated_at", "created_at",
        "revoked_by", "revoked_at", "revocation_reason",
    )
    readonly_fields = fields

    @admin.display(description="شماره", ordering="phone")
    def phone_ltr(self, obj):
        return format_html('<span dir="ltr">{}</span>', obj.phone)

    @admin.display(description="درخواست")
    def request_link(self, obj):
        url = reverse("admin:website_bookaccessrequest_change", args=[obj.request_id])
        return format_html('<a href="{}">#{}</a>', url, obj.request_id)

    @admin.display(description="کاربر")
    def user_link(self, obj):
        if not obj.user_id:
            return "—"
        url = reverse("admin:accounts_user_change", args=[obj.user_id])
        return format_html('<a href="{}"><span dir="ltr">{}</span></a>', url, obj.user.phone)

    @admin.display(description="وضعیت", ordering="status")
    def state(self, obj):
        if obj.status == BookAccessMember.Status.ACTIVE and obj.entitlement_id:
            if obj.entitlement.is_archived:
                return "دسترسی لغوشده"
            if obj.entitlement.ends_at and obj.entitlement.ends_at <= timezone.now():
                return "منقضی‌شده"
        return obj.get_status_display()

    @admin.display(description="پایان دسترسی")
    def ends_at(self, obj):
        return obj.entitlement.ends_at if obj.entitlement_id else "—"

    @admin.display(description="اقدام")
    def manage_links(self, obj):
        links = []
        if obj.status == BookAccessMember.Status.ACTIVE and obj.entitlement_id and not obj.entitlement.is_archived:
            renew = reverse("admin:website_bookaccessmember_renew", args=[obj.pk])
            links.append(format_html('<a class="button" href="{}">تمدید</a>', renew))
        if obj.status in (BookAccessMember.Status.WAITING_OTP, BookAccessMember.Status.ACTIVE, BookAccessMember.Status.EXPIRED):
            revoke = reverse("admin:website_bookaccessmember_revoke", args=[obj.pk])
            links.append(format_html('<a class="button" href="{}">لغو</a>', revoke))
        return format_html_join(" ", "{}", ((link,) for link in links)) or "—"

    def get_urls(self):
        custom = [
            path("<int:object_id>/renew/", self.admin_site.admin_view(self.renew_view), name="website_bookaccessmember_renew"),
            path("<int:object_id>/revoke/", self.admin_site.admin_view(self.revoke_view), name="website_bookaccessmember_revoke"),
        ]
        return custom + super().get_urls()

    def _get_member_for_manager(self, request, object_id):
        if not self.has_view_permission(request):
            raise PermissionDenied
        return get_object_or_404(self.get_queryset(request).select_related("book", "request", "user", "entitlement"), pk=object_id)

    def renew_view(self, request, object_id):
        member = self._get_member_for_manager(request, object_id)
        if request.method not in ("GET", "POST"):
            return HttpResponseNotAllowed(["GET", "POST"])
        form = GroupAccessRenewForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            now = timezone.now()
            with transaction.atomic():
                member = BookAccessMember.objects.select_for_update(of=("self",)).select_related("entitlement").get(pk=member.pk)
                if (
                    member.status != BookAccessMember.Status.ACTIVE
                    or not member.entitlement_id
                    or member.entitlement.is_archived
                ):
                    form.add_error(None, "فقط دسترسی فعال یا منقضی‌نشده‌ی لغونشده را می‌توان تمدید کرد.")
                else:
                    entitlement = Entitlement.objects.select_for_update().get(pk=member.entitlement_id)
                    previous_end = entitlement.ends_at
                    start = max(previous_end, now) if previous_end else now
                    new_end = start + timedelta(days=form.cleaned_data["additional_days"])
                    entitlement.ends_at = new_end
                    entitlement.save(update_fields=["ends_at"])
                    BookAccessEvent.objects.create(
                        member=member,
                        action=BookAccessEvent.Action.RENEWED,
                        actor=request.user,
                        reason=form.cleaned_data["reason"],
                        previous_ends_at=previous_end,
                        new_ends_at=new_end,
                    )
                    messages.success(request, "دسترسی با ثبت رویداد قابل ممیزی تمدید شد.")
                    return redirect("admin:website_bookaccessmember_change", member.pk)
        return self._action_response(request, member, form, title="تمدید دسترسی گروهی", action="renew")

    def revoke_view(self, request, object_id):
        member = self._get_member_for_manager(request, object_id)
        if request.method not in ("GET", "POST"):
            return HttpResponseNotAllowed(["GET", "POST"])
        form = GroupAccessRevokeForm(request.POST or None)
        if request.method == "POST" and form.is_valid():
            with transaction.atomic():
                member = BookAccessMember.objects.select_for_update(of=("self",)).select_related("entitlement").get(pk=member.pk)
                if member.status in (BookAccessMember.Status.REVOKED, BookAccessMember.Status.REJECTED):
                    form.add_error(None, "این ردیف قبلاً لغو یا رد شده است.")
                else:
                    previous_end = None
                    if member.entitlement_id:
                        entitlement = Entitlement.objects.select_for_update().get(pk=member.entitlement_id)
                        previous_end = entitlement.ends_at
                        if not entitlement.is_archived:
                            entitlement.is_archived = True
                            entitlement.save(update_fields=["is_archived"])
                    member.status = BookAccessMember.Status.REVOKED
                    member.revoked_by = request.user
                    member.revoked_at = timezone.now()
                    member.revocation_reason = form.cleaned_data["reason"]
                    member.save(update_fields=["status", "revoked_by", "revoked_at", "revocation_reason"])
                    BookAccessEvent.objects.create(
                        member=member,
                        action=BookAccessEvent.Action.REVOKED,
                        actor=request.user,
                        reason=form.cleaned_data["reason"],
                        previous_ends_at=previous_end,
                    )
                    messages.success(request, "دسترسی لغو و رویداد آن ثبت شد.")
                    return redirect("admin:website_bookaccessmember_change", member.pk)
        return self._action_response(request, member, form, title="لغو دسترسی گروهی", action="revoke")

    def has_module_permission(self, request):
        return _is_manager(request.user)

    def has_view_permission(self, request, obj=None):
        return _is_manager(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return _is_manager(request.user)

    def has_delete_permission(self, request, obj=None):
        return False


class AppendOnlyEventAdmin(admin.ModelAdmin):
    """Audit-event rows are never edited or deleted through the panel."""

    actions = None

    def has_module_permission(self, request):
        return _is_manager(request.user)

    def has_view_permission(self, request, obj=None):
        return _is_manager(request.user)

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(field.name for field in self.model._meta.fields)


@admin.register(BookAccessRequestEvent)
class BookAccessRequestEventAdmin(AppendOnlyEventAdmin):
    list_display = ("request", "action", "actor", "reason", "expiry_policy", "ends_on", "duration_days", "created_at")
    list_filter = ("action", "expiry_policy")
    search_fields = ("request__book__title", "request__requested_by__phone", "reason")
    list_select_related = ("request", "actor", "request__book", "request__requested_by")


@admin.register(BookAccessEvent)
class BookAccessEventAdmin(AppendOnlyEventAdmin):
    list_display = ("member", "action", "actor", "reason", "previous_ends_at", "new_ends_at", "created_at")
    list_filter = ("action",)
    search_fields = ("member__phone", "member__book__title", "reason")
    list_select_related = ("member", "actor", "member__book")


@admin.register(PublicationRequestEvent)
class PublicationRequestEventAdmin(AppendOnlyEventAdmin):
    list_display = ("request", "action", "actor", "reason", "content_digest", "created_at")
    list_filter = ("action",)
    search_fields = ("request__book__title", "request__requested_by__phone", "reason", "content_digest")
    list_select_related = ("request", "actor", "request__book", "request__requested_by")
