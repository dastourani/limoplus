"""Public, spam-limited contact & support intake on /p/contact/."""

from __future__ import annotations

from django.conf import settings
from django.db import IntegrityError, transaction
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.cache import never_cache

from apps.accounts import ratelimit
from apps.accounts.views import _client_ip
from apps.catalog.jalali import jalali_date as fa_date

from .forms import ContactMessageForm
from .models import ContactMessage, generate_contact_tracking_code

_SUBMITTED_SESSION_KEY = "contact_message_submitted"

TOPIC_META = {
    ContactMessage.Topic.ORDER_PAYMENT: {
        "icon": "receipt",
        "short": "پرداخت ناموفق یا بازنشدن کتاب",
        "hint": "اگر مبلغ از حسابتان کسر شده اما خرید یا اشتراک فعال نشده است، شماره موبایل ثبت‌نام و در صورت امکان کد رهگیری زیبال یا شماره سفارش را بنویسید. وضعیت پرداخت بلافاصله بررسی و نتیجه اعلام می‌شود.",
        "link_label": "بند ۳ شرایط استفاده و خرید (پرداخت و فعال‌سازی)",
        "link_url_name": "website:page",
        "link_arg": "terms",
        "link_hash": "#sec-3",
        "phone_required": True,
        "show_order": True,
        "placeholder": "تاریخ و ساعت تقریبی پرداخت، مبلغ و نام کتاب یا طرح اشتراک را بنویسید...",
    },
    ContactMessage.Topic.REFUND: {
        "icon": "clock",
        "short": "انصراف، مغایرت یا ایراد فنی (تا ۷ روز)",
        "hint": "مطابق بند ۶ شرایط استفاده و خرید، درخواست‌های انصراف یا مغایرت حداکثر ظرف ۷ روز کاری بررسی و نتیجه به‌صورت مکتوب اعلام می‌شود. شماره موبایل حساب و شماره سفارش را بنویسید.",
        "link_label": "بند ۶ شرایط استفاده و خرید (انصراف و بازپرداخت)",
        "link_url_name": "website:page",
        "link_arg": "terms",
        "link_hash": "#sec-6",
        "phone_required": True,
        "show_order": True,
        "placeholder": "علت درخواست استرداد یا شرح مشکل و زمان خرید را بنویسید...",
    },
    ContactMessage.Topic.ACCOUNT_ACCESS: {
        "icon": "circle-user-round",
        "short": "ورود، تغییر شماره یا سقف ۲ دستگاه",
        "hint": "برای انتقال حساب به شمارهٔ جدید، مشکل دریافت کد پیامکی یا آزادسازی نشست دستگاه قبلی، شماره موبایل فعلی و در صورت تغییر شماره، شمارهٔ قبلی و توضیح کوتاه را ثبت کنید.",
        "link_label": "راهنمای ورود و دستگاه‌ها در پرسش‌های پرتکرار",
        "link_url_name": "website:faq",
        "link_arg": "",
        "link_hash": "#account-payment",
        "phone_required": True,
        "show_order": False,
        "placeholder": "شماره قبلی/جدید، نوع دستگاه (وب یا اندروید) و خطای دیده‌شده را بنویسید...",
    },
    ContactMessage.Topic.PRIVACY: {
        "icon": "shield-check",
        "short": "اصلاح، حذف اطلاعات یا گزارش محرمانگی",
        "hint": "درخواست مشاهده، اصلاح یا حذف اطلاعات حساب یا گزارش مشاهدهٔ ناخواستهٔ اطلاعات دیگری، مطابق سیاست حریم خصوصی حداکثر ظرف ۷ روز کاری بررسی می‌شود.",
        "link_label": "سیاست حریم خصوصی لیموخوان",
        "link_url_name": "website:page",
        "link_arg": "privacy",
        "link_hash": "#sec-10",
        "phone_required": True,
        "show_order": False,
        "placeholder": "نوع درخواست حریم خصوصی (اصلاح، حذف یا گزارش مورد) و جزئیات لازم را بنویسید...",
    },
    ContactMessage.Topic.CONTENT_COPYRIGHT: {
        "icon": "alert-circle",
        "short": "گزارش اشکال علمی یا بازنشر غیرمجاز",
        "hint": "اگر در متن درسنامه، فرمول یا پاسخ تشریحی خطایی دیده‌اید یا موردی از بازنشر غیرمجاز و نقض کپی‌رایت مشاهده کرده‌اید، نام کتاب و بخش یا لینک مورد را بنویسید.",
        "link_label": "صفحهٔ حقوق مؤلفان و حفاظت از محتوا",
        "link_url_name": "website:page",
        "link_arg": "protection",
        "link_hash": "",
        "phone_required": False,
        "show_order": False,
        "placeholder": "نام کتاب، فصل/بخش یا نشانی محل بازنشر غیرمجاز و شرح مورد را بنویسید...",
    },
    ContactMessage.Topic.TEACHER_ORG: {
        "icon": "graduation-cap",
        "short": "همکاری مؤلفان، کلاس یا خرید دانشگاهی",
        "hint": "اگر قصد تألیف کتاب یا برگزاری کلاس اختصاصی دارید، فرم تخصصی «درخواست همکاری آموزشی» سریع‌ترین مسیر است؛ برای خریدهای گروهی و دانشگاهی هم می‌توانید همین‌جا با ثبت شماره موبایل پیام بگذارید.",
        "link_label": "رفتن به فرم تخصصی درخواست همکاری آموزشی",
        "link_url_name": "website:teacher-application",
        "link_arg": "",
        "link_hash": "",
        "phone_required": True,
        "show_order": False,
        "placeholder": "نام دانشگاه/مؤسسه، عنوان درس یا تعداد دانشجویان مورد نظر را بنویسید...",
    },
    ContactMessage.Topic.OTHER: {
        "icon": "message-circle",
        "short": "پیشنهاد، انتقاد یا پرسش عمومی",
        "hint": "هر پیشنهاد برای بهبود لیموخوان، پرسش دربارهٔ کتاب‌های آینده یا موضوع دیگری دارید، برای ما بنویسید. اگر مایل به دریافت تماس یا پیگیری هستید، شماره موبایلتان را هم ثبت کنید.",
        "link_label": "مشاهدهٔ پرسش‌های پرتکرار",
        "link_url_name": "website:faq",
        "link_arg": "",
        "link_hash": "",
        "phone_required": False,
        "show_order": False,
        "placeholder": "پرسش، پیشنهاد یا دیدگاه خود را بنویسید...",
    },
}


def _ip_is_limited(request) -> bool:
    ip = _client_ip(request)
    key = f"contact-message-ip:{ip}"
    with transaction.atomic():
        ratelimit.lock(key)
        if ratelimit.count(key) >= settings.CONTACT_MESSAGES_PER_IP_PER_HOUR:
            return True
        ratelimit.hit(key)
    return False


def _sender_is_limited(phone: str) -> bool:
    if not phone:
        return False
    key = f"contact-message-sender:{phone}"
    with transaction.atomic():
        ratelimit.lock(key)
        if ratelimit.count(key) >= settings.CONTACT_MESSAGES_PER_SENDER_PER_HOUR:
            return True
        ratelimit.hit(key)
    return False


def _create_message(form: ContactMessageForm, user) -> ContactMessage:
    topic = form.cleaned_data["topic"]
    priority = (
        ContactMessage.Priority.HIGH
        if topic in (ContactMessage.Topic.ORDER_PAYMENT, ContactMessage.Topic.PRIVACY)
        else ContactMessage.Priority.NORMAL
    )
    for _ in range(5):
        code = generate_contact_tracking_code()
        try:
            with transaction.atomic():
                obj = form.save(commit=False)
                obj.tracking_code = code
                obj.priority = priority
                if user is not None and getattr(user, "is_authenticated", False):
                    obj.user = user
                obj.save()
                from apps.catalog.backups import notify_bale_after_commit

                contact_line = obj.phone or "ثبت نشده (بازخورد عمومی)"
                order_line = f"\nشماره سفارش/رهگیری: {obj.order_reference}" if obj.order_reference else ""
                item_line = f"\nمرتبط با: {obj.related_item}" if obj.related_item else ""
                snippet = obj.message.strip().replace("\n", " ")
                if len(snippet) > 350:
                    snippet = snippet[:347] + "..."
                notify_bale_after_commit(
                    f"📩 پیام جدید تماس با ما ({obj.tracking_code})\n"
                    f"موضوع: {obj.get_topic_display()}\n"
                    f"اولویت: {obj.get_priority_display()}\n"
                    f"نام: {obj.name}\n"
                    f"شماره تماس: {contact_line}"
                    f"{order_line}{item_line}\n"
                    f"متن: {snippet}",
                    log_label=f"Bale contact message alert for {obj.tracking_code}",
                )
                return obj
        except IntegrityError:
            continue
    raise IntegrityError("Could not allocate unique contact tracking code.")


def _topic_cards():
    cards = []
    for value, label in ContactMessage.Topic.choices:
        meta = dict(TOPIC_META[value])
        if meta["link_arg"]:
            href = reverse(meta["link_url_name"], args=[meta["link_arg"]]) + meta["link_hash"]
        else:
            href = reverse(meta["link_url_name"]) + meta["link_hash"]
        cards.append(
            {
                "value": value,
                "label": label,
                "icon": meta["icon"],
                "short": meta["short"],
                "hint": meta["hint"],
                "link_label": meta["link_label"],
                "link_href": href,
                "phone_required": meta["phone_required"],
                "phone_help": (
                    ContactMessageForm.PHONE_REQUIRED_HELP
                    if meta["phone_required"]
                    else ContactMessageForm.PHONE_OPTIONAL_HELP
                ),
                "show_order": meta["show_order"],
                "placeholder": meta["placeholder"],
            }
        )
    return cards


def _initial_for_request(request) -> dict:
    initial = {}
    req_topic = (request.GET.get("topic") or "").strip()
    valid_topics = {choice[0] for choice in ContactMessage.Topic.choices}
    initial["topic"] = req_topic if req_topic in valid_topics else ContactMessage.Topic.ORDER_PAYMENT
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        full_name = " ".join(p for p in (getattr(user, "first_name", ""), getattr(user, "last_name", "")) if p).strip()
        if full_name:
            initial["name"] = full_name
        phone = getattr(user, "phone", "")
        if phone and phone.startswith("09") and len(phone) == 11:
            initial["phone"] = phone
    return initial


def _render_contact_page(request, page_obj, form, *, submitted=None, rate_limited=False, status=200):
    from .views import _base, simple_text

    topic_cards = _topic_cards()
    selected_topic = form["topic"].value() or ContactMessage.Topic.ORDER_PAYMENT
    if selected_topic not in TOPIC_META:
        selected_topic = ContactMessage.Topic.ORDER_PAYMENT
    active_meta = next((c for c in topic_cards if c["value"] == selected_topic), topic_cards[0])

    return render(
        request,
        "website/page.html",
        _base(
            request,
            page=page_obj,
            body=simple_text(page_obj.body, with_ids=True),
            updated_on=fa_date(page_obj.updated_at),
            important_on=fa_date(page_obj.important_at) if page_obj.important_at else "",
            contact_form=form,
            contact_topics=topic_cards,
            contact_active_topic=active_meta,
            contact_submitted=submitted,
            contact_rate_limited=rate_limited,
        ),
        status=status,
    )


@never_cache
def contact_page(request, page_obj):
    if request.method == "GET":
        submitted = request.session.pop(_SUBMITTED_SESSION_KEY, None)
        form = ContactMessageForm(initial=_initial_for_request(request))
        return _render_contact_page(request, page_obj, form, submitted=submitted)

    if request.method != "POST":
        form = ContactMessageForm(initial=_initial_for_request(request))
        return _render_contact_page(request, page_obj, form, status=405)

    form = ContactMessageForm(request.POST)
    if _ip_is_limited(request):
        return _render_contact_page(request, page_obj, form, rate_limited=True, status=429)

    if form.is_valid():
        if form.cleaned_data["website"]:
            # Silent decoy confirmation for bots filling the honeypot field.
            request.session[_SUBMITTED_SESSION_KEY] = {
                "tracking_code": generate_contact_tracking_code(),
                "topic_label": dict(ContactMessage.Topic.choices).get(form.cleaned_data["topic"], ""),
                "is_high_priority": False,
                "has_phone": bool(form.cleaned_data["phone"]),
            }
            return redirect("website:page", slug="contact")

        if _sender_is_limited(form.cleaned_data["phone"]):
            return _render_contact_page(request, page_obj, form, rate_limited=True, status=429)

        created = _create_message(form, getattr(request, "user", None))
        request.session[_SUBMITTED_SESSION_KEY] = {
            "tracking_code": created.tracking_code,
            "topic_label": created.get_topic_display(),
            "is_high_priority": created.priority == ContactMessage.Priority.HIGH,
            "has_phone": bool(created.phone),
        }
        return redirect(reverse("website:page", args=["contact"]) + "#contact-result")

    return _render_contact_page(request, page_obj, form)
