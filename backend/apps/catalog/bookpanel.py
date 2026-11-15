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
from django.db import IntegrityError, transaction
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
    out.extend(_numbered_explanations(book))
    out.extend(_broken_refs(book))
    return out


def _broken_refs(book: ContentNode) -> list[dict]:
    """«[[#name]]» links whose box is nowhere in the book (learners see a red «#name»)."""
    from apps.learning.models import Question

    from .numbering import REF, panel_refs

    known = set(panel_refs(book))
    where: dict[str, set[str]] = {}
    nodes = ContentNode.objects.filter(path__startswith=book.path, depth__gt=1, is_archived=False).only("title", "full_body", "summary_body", "path")
    titles = {n.pk: n.title for n in nodes}
    for n in nodes:
        for name in REF.findall((n.full_body or "") + "\n" + (n.summary_body or "")):
            if name not in known:
                where.setdefault(name, set()).add(n.title)
    for q in Question.objects.filter(node__path__startswith=book.path, is_archived=False).only("node_id", "slug", "explanation", "solutions", "stem"):
        for name in REF.findall(" ".join([q.stem, q.explanation, *[x.get("body", "") for x in q.solutions or []]])):
            if name not in known:
                where.setdefault(name, set()).add(f"تست {q.slug} ({titles.get(q.node_id, '')})")
    return [{"level": "warn", "text": f"ارجاع «[[#{name}]]» کادری در این کتاب پیدا نمی‌کند (در {'، '.join(sorted(places))}); در اپ به رنگ قرمز دیده می‌شود."}
            for name, places in sorted(where.items())]


def _numbered_explanations(book: ContentNode) -> list[dict]:
    """Explanations that say «گزینه‌ی ۲» while the app shuffles the choices."""
    from apps.learning.models import Question
    from apps.learning.order import names_choice_number

    found = []
    questions = Question.objects.filter(node__path__startswith=book.path, is_archived=False).prefetch_related("choices")
    for q in questions.only("id", "slug", "fixed_order", "explanation", "solutions"):
        if q.keeps_order:
            continue
        if any(names_choice_number(t) for t in (q.explanation, *[x.get("body", "") for x in q.solutions or []])):
            found.append(q.slug)
    if not found:
        return []
    shown = "، ".join(found[:8]) + ("، …" if len(found) > 8 else "")
    return [{
        "level": "warn",
        "text": f"توضیح {len(found)} تست شماره‌ی گزینه را نوشته («گزینه‌ی ۲»)، ولی اپ جای گزینه‌ها را عوض می‌کند: {shown}. "
                "متن جواب درست را بنویسید، یا در فرم تست «ترتیب گزینه‌ها ثابت بماند» را بزنید.",
    }]


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
        if not request.user.has_perm("commerce.change_entitlement"):
            raise PermissionDenied
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
    choice = request.POST.get("days", "forever")
    if choice not in GIFT_DAYS:
        messages.error(request, "مدت هدیه درست انتخاب نشده است.")
        return redirect(back)
    days = GIFT_DAYS[choice]
    note = " ".join(request.POST.get("note", "").split())[:200]
    user = User.objects.filter(phone=phone).first()
    if user and Entitlement.active_for(user).filter(book=book, ends_at__isnull=True).exists():
        messages.warning(request, f"{phone} همین حالا این کتاب را برای همیشه دارد.")
        return redirect(back)
    created = user is None
    with transaction.atomic():
        if created:
            # Someone who hasn't signed up yet: the account waits for their first login by SMS code.
            try:
                with transaction.atomic():
                    user = User.objects.create_user(phone)
            except IntegrityError:  # created at the same moment by another request
                user = User.objects.get(phone=phone)
                created = False
        now = timezone.now()
        Entitlement.objects.create(
            user=user, book=book, granted_by=request.user, note=note or "هدیه", starts_at=now, ends_at=now + timedelta(days=days) if days else None
        )
    how = "همیشگی" if days is None else f"تا {days} روز"
    extra = " (این شماره هنوز ثبت‌نام نکرده بود؛ با اولین ورود کتاب را دارد)" if created else ""
    messages.success(request, f"«{book.title}» به {phone} هدیه داده شد، {how}.{extra}")
    return redirect(back)


def waitlist_notify(admin_site, request, book_id):
    """«خبر دادن به منتظران»: a confirmation page (how many, the text, SMS parts); on confirm, one SMS to each."""
    from django.template.response import TemplateResponse

    from . import waitlist_sms
    from .jalali import fa_digits
    from .models import BookWaitlist

    if not (request.user.is_active and request.user.is_staff and request.user.has_perm("catalog.change_book")):
        raise PermissionDenied
    book = get_object_or_404(ContentNode, pk=book_id, kind=ContentNode.Kind.BOOK, depth=1)
    waiting = waitlist_sms.waiting(book)
    count = waiting.count()
    text = request.POST.get("text", waitlist_sms.default_text(book)).strip()
    problems = waitlist_sms.problems(book)
    errors = []
    if request.method == "POST":
        if not text:
            errors.append("متن پیامک خالی است.")
        elif len(text) > 300:
            errors.append("متن پیامک بلند است (بیش از ۳۰۰ نویسه).")
        if not count:
            errors.append("کسی منتظر خبر نیست.")
        if not problems and not errors:
            n = waitlist_sms.queue(book, text)
            messages.success(request, f"پیامک برای {fa_digits(n)} نفر در صف ارسال است؛ چند دقیقه‌ی دیگر همه فرستاده می‌شوند.")
            return redirect(reverse("admin:catalog_bookwaitlist_changelist") + f"?book_id={book.pk}")
    all_rows = BookWaitlist.objects.filter(book=book)
    context = {
        **admin_site.each_context(request),
        "title": "خبر دادن به منتظران",
        "book": book,
        "count": count,
        "told": all_rows.filter(notified_at__isnull=False).count(),
        "queued": all_rows.filter(notify_queued_at__isnull=False, notified_at__isnull=True).count(),
        "failed": all_rows.filter(notified_at__isnull=True).exclude(notify_error="").count(),
        "text": text,
        "parts": waitlist_sms.sms_parts(text),
        "total": waitlist_sms.sms_parts(text) * count,
        "problems": problems,
        "errors": errors,
        "opts": ContentNode._meta,
    }
    context["fa"] = {k: fa_digits(context[k]) for k in ("count", "told", "queued", "failed", "total")}
    return TemplateResponse(request, "admin/catalog/book/waitlist_notify.html", context)
