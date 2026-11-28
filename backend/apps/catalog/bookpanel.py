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
    # Granting or revoking learner access is reserved to the site manager, regardless of incidental model perms.
    if not (request.user.is_active and request.user.is_superuser):
        raise PermissionDenied("دادن یا گرفتن دسترسی دانشجو فقط با مدیر کل است.")


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


def book_classrooms_canvas(admin_site, request, book_id):
    """Visual canvas («کلاس‌ها و لینک‌های این کتاب») for managing a book's classrooms & student /join/ links."""
    from django.conf import settings
    from django.template.response import TemplateResponse
    from apps.catalog.jalali import jalali_date
    from apps.catalog.panel_display import fa_number
    from apps.website.forms import ClassroomCreateForm
    from apps.website.models import Classroom, ClassroomMember
    from . import access

    book = get_object_or_404(ContentNode, pk=book_id, kind=ContentNode.Kind.BOOK, depth=1)
    is_panel_su = access.acts_as_panel_superuser(request)
    is_panel_teacher = access.acts_as_panel_teacher(request)
    if not (is_panel_su or is_panel_teacher):
        raise PermissionDenied("شما مجوز مشاهده کلاس‌های این کتاب را ندارید.")
    if not is_panel_su and not access.classroom_books_for_request(request).filter(pk=book.pk).exists():
        raise PermissionDenied("شما مجوز مدیریت کلاس‌های این کتاب را ندارید.")

    canvas_url = reverse("admin:catalog_book_classrooms_canvas", args=[book.pk])
    classrooms_qs = Classroom.objects.filter(book=book).select_related("teacher").order_by("-created_at", "-id")
    if not is_panel_su:
        classrooms_qs = classrooms_qs.filter(teacher=request.user)

    create_form = ClassroomCreateForm(user=request.user, allowed_books=ContentNode.objects.filter(pk=book.pk))
    open_create_modal = False

    if request.method == "POST":
        from .jalali_admin import _parse_admin_date

        action = (request.POST.get("action") or "").strip()
        if action == "create":
            if book.is_inbox or book.is_archived:
                messages.error(request, "برای کتاب بایگانی‌شده یا صندوق تست امکان ایجاد کلاس وجود ندارد.")
                return redirect(canvas_url)
            post_data = request.POST.copy()
            post_data["book"] = str(book.pk)
            raw_ends_on = (post_data.get("ends_on") or "").strip()
            if raw_ends_on:
                parsed_end = _parse_admin_date(raw_ends_on)
                if parsed_end:
                    post_data["ends_on"] = parsed_end.isoformat()
            create_form = ClassroomCreateForm(
                post_data,
                user=request.user,
                allowed_books=ContentNode.objects.filter(pk=book.pk),
            )
            if create_form.is_valid():
                with transaction.atomic():
                    obj = create_form.save(commit=False)
                    obj.book = book
                    obj.teacher = request.user
                    obj.save()
                    for phone in getattr(create_form, "normalized_phones", []):
                        ClassroomMember.objects.get_or_create(
                            classroom=obj,
                            phone=phone,
                            defaults={"join_method": ClassroomMember.JoinMethod.BULK_IMPORT},
                        )
                messages.success(
                    request,
                    f"کلاس «{obj.title}» با لینک ثابت /join/{obj.code}/ ساخته شد.",
                )
                return redirect(canvas_url)
            open_create_modal = True

        elif action == "toggle_active":
            classroom = get_object_or_404(classrooms_qs, pk=request.POST.get("classroom_id"))
            new_active = not classroom.is_active
            if (
                new_active
                and classroom.expiry_policy == Classroom.ExpiryPolicy.FIXED_DATE
                and classroom.ends_on
                and classroom.ends_on < timezone.localdate()
            ):
                messages.error(
                    request,
                    f"مهلت کلاس «{classroom.title}» گذشته است؛ برای بازگشایی مجدد، از «تمدید لینک» تاریخ تازه ثبت کنید.",
                )
                return redirect(canvas_url)
            classroom.is_active = new_active
            classroom.save(update_fields=["is_active", "updated_at"])
            state_txt = "فعال" if new_active else "غیرفعال"
            messages.success(request, f"لینک دعوت کلاس «{classroom.title}» ({classroom.code}) {state_txt} شد.")
            return redirect(canvas_url)

        elif action == "renew":
            classroom = get_object_or_404(classrooms_qs, pk=request.POST.get("classroom_id"))
            mode = (request.POST.get("renew_mode") or "plus_30").strip()
            today = timezone.localdate()
            base_date = max(today, classroom.ends_on) if classroom.ends_on else today

            if mode == "plus_30":
                classroom.expiry_policy = Classroom.ExpiryPolicy.FIXED_DATE
                classroom.ends_on = base_date + timedelta(days=30)
                classroom.duration_days = None
                classroom.is_active = True
            elif mode == "plus_90":
                classroom.expiry_policy = Classroom.ExpiryPolicy.FIXED_DATE
                classroom.ends_on = base_date + timedelta(days=90)
                classroom.duration_days = None
                classroom.is_active = True
            elif mode == "plus_180":
                classroom.expiry_policy = Classroom.ExpiryPolicy.FIXED_DATE
                classroom.ends_on = base_date + timedelta(days=180)
                classroom.duration_days = None
                classroom.is_active = True
            elif mode == "unlimited":
                classroom.expiry_policy = Classroom.ExpiryPolicy.UNLIMITED
                classroom.ends_on = None
                classroom.duration_days = None
                classroom.is_active = True
            elif mode == "custom_date":
                parsed = _parse_admin_date((request.POST.get("custom_ends_on") or "").strip())
                if not parsed:
                    messages.error(request, "تاریخ جدید معتبر نیست. لطفاً تاریخ شمسی مانند ۱۴۰۵/۱۰/۳۰ وارد یا از تقویم انتخاب کنید.")
                    return redirect(canvas_url)
                if parsed < today:
                    messages.error(request, "تاریخ پایان نمی‌تواند در گذشته باشد.")
                    return redirect(canvas_url)
                classroom.expiry_policy = Classroom.ExpiryPolicy.FIXED_DATE
                classroom.ends_on = parsed
                classroom.duration_days = None
                classroom.is_active = True
            else:
                messages.error(request, "گزینهٔ تمدید نامعتبر است.")
                return redirect(canvas_url)

            try:
                classroom.full_clean()
            except Exception as exc:
                messages.error(request, str(exc))
                return redirect(canvas_url)
            classroom.save(update_fields=["expiry_policy", "ends_on", "duration_days", "is_active", "updated_at"])
            messages.success(
                request,
                f"کلاس «{classroom.title}» با همان لینک قبلی (/join/{classroom.code}/) تمدید و فعال شد.",
            )
            return redirect(canvas_url)

    now = timezone.now()
    today = timezone.localdate()
    site_url = (getattr(settings, "SITE_URL", "") or "").rstrip("/")

    cards = []
    active_total = 0
    expired_total = 0
    students_total = 0

    for c in classrooms_qs:
        active_members = c.active_members_count
        waiting_members = c.members.filter(status=ClassroomMember.Status.WAITING_OTP).count()
        is_expired = c.is_expired(now)
        is_full = bool(c.is_active and not is_expired and active_members >= c.capacity)

        if is_expired:
            state = "expired"
            state_label = "منقضی‌شده"
            expired_total += 1
        elif not c.is_active:
            state = "inactive"
            state_label = "غیرفعال"
        elif is_full:
            state = "full"
            state_label = "ظرفیت تکمیل"
            active_total += 1
        else:
            state = "active"
            state_label = "فعال"
            active_total += 1

        students_total += active_members
        pct = min(100, round(100 * active_members / max(1, c.capacity)))

        days_left = None
        if c.expiry_policy == Classroom.ExpiryPolicy.UNLIMITED:
            expiry_text = "همیشگی (بدون تاریخ پایان)"
        elif c.expiry_policy == Classroom.ExpiryPolicy.FIXED_DATE and c.ends_on:
            days_left = (c.ends_on - today).days
            expiry_text = f"پایان: {jalali_date(c.ends_on)}"
        elif c.expiry_policy == Classroom.ExpiryPolicy.FROM_JOIN and c.duration_days:
            expiry_text = f"{fa_number(c.duration_days)} روز پس از پیوستن دانشجو"
        else:
            expiry_text = c.get_expiry_policy_display()

        join_path = f"/join/{c.code}/"
        join_url = f"{site_url}{join_path}" if site_url else request.build_absolute_uri(join_path)

        cards.append({
            "obj": c,
            "pk": c.pk,
            "title": c.title,
            "description": c.description,
            "code": c.code,
            "join_path": join_path,
            "join_url": join_url,
            "state": state,
            "state_label": state_label,
            "is_active": c.is_active,
            "is_expired": is_expired,
            "is_full": is_full,
            "active_members": active_members,
            "active_members_fa": fa_number(active_members),
            "waiting_members": waiting_members,
            "waiting_members_fa": fa_number(waiting_members),
            "capacity": c.capacity,
            "capacity_fa": fa_number(c.capacity),
            "pct": pct,
            "expiry_text": expiry_text,
            "days_left": days_left,
            "days_left_fa": fa_number(abs(days_left)) if days_left is not None else "",
            "is_expiring_soon": bool(days_left is not None and 0 <= days_left <= 7 and c.is_active),
            "teacher_label": getattr(c.teacher, "full_name", "") or c.teacher.phone,
            "add_members_url": reverse("admin:website_classroom_add_members", args=[c.pk]),
            "members_url": reverse("admin:website_classroommember_changelist") + f"?classroom_id={c.pk}",
            "change_url": reverse("admin:website_classroom_change", args=[c.pk]),
        })

    chapters_count = ContentNode.objects.filter(path__startswith=book.path, depth=2, is_archived=False).count()
    sections_count = ContentNode.objects.filter(path__startswith=book.path, depth=3, is_archived=False).count()
    major = book.majors.first()

    context = {
        **admin_site.each_context(request),
        "title": f"کلاس‌ها و لینک‌های «{book.title}»",
        "book": book,
        "book_cover": {
            "title": book.title,
            "title_en": book.title_en,
            "author": book.author,
            "edition": book.edition,
            "cover_url": book.cover.url if book.cover else "",
            "cover_motif": book.cover_motif,
            "cover_drawing": book.cover_drawing,
            "major_name": major.name if major else "",
            "major_color": major.color if major else "",
            "chapters_fa": fa_number(chapters_count),
            "sections_fa": fa_number(sections_count),
        },
        "cards": cards,
        "summary": {
            "total_fa": fa_number(len(cards)),
            "active_fa": fa_number(active_total),
            "expired_fa": fa_number(expired_total),
            "students_fa": fa_number(students_total),
        },
        "is_panel_su": is_panel_su,
        "can_create_classroom": bool(not book.is_inbox and not book.is_archived),
        "create_form": create_form,
        "open_create_modal": open_create_modal,
        "today_iso": today.isoformat(),
        "today_jalali": jalali_date(today),
        "opts": ContentNode._meta,
    }
    return TemplateResponse(request, "admin/catalog/book/classrooms_canvas.html", context)

