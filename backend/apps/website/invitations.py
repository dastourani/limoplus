"""OTP-bound, one-use teacher invitations. These grants never promote a teacher to superuser."""

from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from apps.catalog.access import BOOK_EDITOR_GROUP
from apps.catalog.models import BookEditor, ContentNode

from .models import TeacherApplication, TeacherInvitation


_REQUIRED_BOOK_TEACHER_PERMISSIONS = {
    ("catalog", "view_book"),
    ("catalog", "view_contentnode"),
    ("catalog", "change_contentnode"),
    ("catalog", "view_section"),
    ("catalog", "view_chapterrevision"),
    ("catalog", "view_label"),
    ("catalog", "add_label"),
    ("catalog", "change_label"),
    ("catalog", "delete_label"),
    ("catalog", "view_aiprovider"),
    ("catalog", "add_aiprovider"),
    ("catalog", "change_aiprovider"),
    ("catalog", "delete_aiprovider"),
    ("catalog", "view_bookassistantauditlog"),
    ("learning", "view_question"),
    ("learning", "view_flashcard"),
    ("learning", "view_examsource"),
    ("learning", "view_report"),
    ("learning", "change_report"),
}
_CAPABILITIES = (
    "can_edit_content",
    "can_request_publication",
    "can_request_group_access",
    "can_view_reports",
    "can_view_aggregate_study",
    "can_view_aggregate_sales",
)


def _safe_teacher_group():
    group = Group.objects.filter(name=BOOK_EDITOR_GROUP).first()
    if group is None:
        raise ValidationError("نقش محدود «استاد کتاب» در سامانه پیدا نشد؛ دعوت انجام نشد.")
    actual = set(group.permissions.values_list("content_type__app_label", "codename"))
    if actual != _REQUIRED_BOOK_TEACHER_PERMISSIONS:
        raise ValidationError("مجوزهای نقش «استاد کتاب» با فهرست حداقلی سامانه یکی نیست؛ دعوت انجام نشد.")
    return group


def accept_teacher_invitation(invitation: TeacherInvitation, user, *, now=None):
    """Atomically attach the invitation's exact book capabilities after OTP proved the invited phone."""
    now = now or timezone.now()
    with transaction.atomic():
        invite = TeacherInvitation.objects.select_for_update().select_related("application", "book").get(pk=invitation.pk)
        if invite.status != TeacherInvitation.Status.ISSUED:
            raise ValidationError("این دعوت دیگر قابل استفاده نیست.")
        if invite.expires_at <= now:
            invite.status = TeacherInvitation.Status.EXPIRED
            invite.save(update_fields=["status"])
            raise ValidationError("مهلت این دعوت به پایان رسیده است.")
        if invite.application.status != TeacherApplication.Status.APPROVED:
            raise ValidationError("درخواست استاد دیگر تأییدشده نیست؛ دعوت قابل استفاده نیست.")
        if invite.application.phone != user.phone:
            raise ValidationError("این شماره با دعوت‌نامه مطابقت ندارد.")
        if not user.is_active or user.is_superuser:
            raise ValidationError("این حساب برای پذیرش دعوت استاد واجد شرایط نیست.")
        if (
            invite.book.kind != ContentNode.Kind.BOOK
            or invite.book.depth != 1
            or invite.book.is_archived
            or invite.book.is_inbox
        ):
            raise ValidationError("کتاب دعوت دیگر فعال نیست.")
        if not any(getattr(invite, capability) for capability in _CAPABILITIES):
            raise ValidationError("دعوت بدون قابلیت مصوب قابل استفاده نیست.")

        group = _safe_teacher_group()
        allowed_permissions = {f"{app_label}.{codename}" for app_label, codename in _REQUIRED_BOOK_TEACHER_PERMISSIONS}
        if not user.get_all_permissions().issubset(allowed_permissions):
            raise ValidationError("این حساب مجوزهای پنلی دیگری دارد؛ ابتدا مدیر باید آن‌ها را بازبینی کند.")
        if not user.is_staff:
            user.is_staff = True
            user.save(update_fields=["is_staff"])
        user.groups.add(group)

        defaults = {capability: bool(getattr(invite, capability)) for capability in _CAPABILITIES}
        editor = BookEditor.objects.select_for_update().filter(book=invite.book, user=user).first()
        if editor is None:
            BookEditor.objects.create(
                book=invite.book,
                user=user,
                note=f"دعوت #{invite.pk}",
                **defaults,
            )
        else:
            # Preserve rights separately approved on an earlier row; this invitation only adds its own approved flags.
            changed = []
            for capability, approved in defaults.items():
                if approved and not getattr(editor, capability):
                    setattr(editor, capability, True)
                    changed.append(capability)
            if changed:
                editor.save(update_fields=changed)

        invite.status = TeacherInvitation.Status.ACCEPTED
        invite.accepted_by = user
        invite.accepted_at = now
        invite.save(update_fields=["status", "accepted_by", "accepted_at"])
        return invite
