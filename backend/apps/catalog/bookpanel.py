"""
The book page's two helper boxes:

- «بررسی کتاب»: says, in plain Persian, why something in this book will not show in the app (unpublished book or
  chapter, draft sections, an empty chapter, no major, no price) and offers a one-click fix where there is one.
- «هدیه به کاربر»: give one user this book, for good or for a while, without an order. Gifts are entitlements with
  `granted_by` set; taking one back archives it (nothing is deleted).
"""

from __future__ import annotations

from datetime import timedelta

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from .models import ContentNode

GIFT_DAYS = {"forever": None, "30": 30, "90": 90, "365": 365}


def book_health(book: ContentNode) -> list[dict]:
    """Problems that hide content in the app, most serious first. Each: {"level", "text", "fix"?: {action, chapter}}."""
    out: list[dict] = []
    if book.is_archived:
        return [{"level": "warn", "text": "این کتاب بایگانی شده و در اپ دیده نمی‌شود."}]
    if not book.is_published:
        out.append({"level": "error", "text": "خود کتاب منتشر نشده؛ هیچ‌چیزش در اپ دیده نمی‌شود. «منتشر شده» را در فرم بالا تیک بزنید."})
    if not book.majors.exists():
        out.append({"level": "error", "text": "کتاب به هیچ رشته‌ای وصل نیست، پس در قفسه‌ی هیچ رشته‌ای نمی‌آید."})
    chapters = list(book.get_children().filter(kind=ContentNode.Kind.CHAPTER, is_archived=False))
    if not chapters:
        out.append({"level": "warn", "text": "هنوز فصلی ندارد."})
    if book.price is None and not book.is_free and not book.is_coming_soon:
        out.append({"level": "warn", "text": "قیمت ندارد؛ کاربر فقط بخش‌های رایگان را می‌بیند و دکمه‌ی خرید کار نمی‌کند (مگر با اشتراک)."})
    for c in chapters:
        name = f"فصل {c.position or ''} «{c.title}»".replace("  ", " ")
        sections = c.get_children().filter(kind=ContentNode.Kind.SECTION, is_archived=False)
        drafts = sections.filter(is_published=False).count()
        fix = {"action": "publish", "chapter": c.pk}
        if not c.is_published:
            more = f" (و {drafts} بخش پیش‌نویس)" if drafts else ""
            out.append({"level": "error", "text": f"{name} منتشر نشده و در اپ دیده نمی‌شود{more}.", "fix": fix})
        elif drafts:
            out.append({"level": "error", "text": f"{name}: {drafts} بخش پیش‌نویس است؛ در اپ فقط عنوان فصل دیده می‌شود.", "fix": fix})
        elif not sections.exists() and not (c.full_body or c.summary_body):
            out.append({"level": "warn", "text": f"{name} هیچ بخشی ندارد؛ در اپ خالی است."})
    return out


def _gifts(book: ContentNode):
    from apps.commerce.models import Entitlement

    return Entitlement.objects.filter(book=book, granted_by__isnull=False, order__isnull=True).select_related("user", "granted_by").order_by("is_archived", "-created_at")


def gift_context(book: ContentNode) -> dict:
    now = timezone.now()
    rows = []
    for g in _gifts(book)[:50]:
        expired = g.ends_at is not None and g.ends_at <= now
        rows.append({"g": g, "active": not g.is_archived and not expired, "expired": expired})
    return {"gifts": rows, "gift_days": [("forever", "همیشگی"), ("30", "یک ماه"), ("90", "سه ماه"), ("365", "یک سال")]}


def _can_gift(request):
    if not (request.user.is_active and request.user.is_staff and request.user.has_perm("commerce.add_entitlement")):
        raise PermissionDenied


@require_POST
def book_gift(request, book_id):
    """Give the book to one user (by phone), or take a gift back."""
    from apps.accounts.models import User
    from apps.accounts.phone import InvalidPhone, normalize_phone
    from apps.commerce.models import Entitlement

    _can_gift(request)
    book = get_object_or_404(ContentNode, pk=book_id, kind=ContentNode.Kind.BOOK, depth=1)
    back = reverse("admin:catalog_book_change", args=[book.pk]) + "#gifts"

    if request.POST.get("action") == "revoke":
        g = _gifts(book).filter(pk=request.POST.get("gift")).first()
        if g and not g.is_archived:
            g.is_archived = True
            g.save(update_fields=["is_archived"])
            messages.success(request, f"هدیه‌ی {g.user.phone} پس گرفته شد (در سابقه می‌ماند).")
        return redirect(back)

    try:
        phone = normalize_phone(request.POST.get("phone", ""))
    except InvalidPhone as e:
        messages.error(request, str(e))
        return redirect(back)
    days = GIFT_DAYS.get(request.POST.get("days", "forever"), None)
    note = " ".join(request.POST.get("note", "").split())[:200]
    with transaction.atomic():
        user = User.objects.filter(phone=phone).first()
        created = user is None
        if created:
            # Someone who hasn't signed up yet: the account waits for their first login by SMS code.
            user = User.objects.create_user(phone)
        now = timezone.now()
        Entitlement.objects.create(
            user=user, book=book, granted_by=request.user, note=note or "هدیه", starts_at=now, ends_at=now + timedelta(days=days) if days else None
        )
    how = "همیشگی" if days is None else f"تا {days} روز"
    extra = " (این شماره هنوز ثبت‌نام نکرده بود؛ با اولین ورود کتاب را دارد)" if created else ""
    messages.success(request, f"«{book.title}» به {phone} هدیه داده شد، {how}.{extra}")
    return redirect(back)
