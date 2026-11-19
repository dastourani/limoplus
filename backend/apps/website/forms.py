import re

from django import forms

from apps.accounts.phone import InvalidPhone, normalize_phone

from .models import BookAccessRequest, TeacherApplication


class TeacherApplicationForm(forms.ModelForm):
    """Public teacher-interest form; the honeypot is intentionally not stored with the application."""

    phone = forms.CharField(
        label="شماره‌ی موبایل",
        max_length=20,
        widget=forms.TelInput(attrs={"autocomplete": "tel", "inputmode": "tel", "dir": "ltr"}),
    )
    website = forms.CharField(
        label="وب‌سایت",
        required=False,
        widget=forms.TextInput(attrs={"autocomplete": "off", "tabindex": "-1", "aria-hidden": "true"}),
    )

    class Meta:
        model = TeacherApplication
        fields = ("name", "phone", "book_or_link", "explanation", "sample_work")
        widgets = {
            "name": forms.TextInput(attrs={"autocomplete": "name", "maxlength": 120}),
            "book_or_link": forms.TextInput(attrs={"maxlength": 300}),
            "explanation": forms.Textarea(attrs={"rows": 4, "maxlength": 2000}),
            "sample_work": forms.Textarea(attrs={"rows": 5, "maxlength": 3000}),
        }
        help_texts = {
            "book_or_link": "کتاب مرتبط، یا لینک صفحه‌ی کتاب/زمینه‌ی پیشنهادی را بنویسید.",
            "sample_work": "شرح کوتاه یا پیوند نمونه‌کار/شواهد؛ فایل پیوست دریافت نمی‌شود.",
        }

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def clean_phone(self):
        try:
            return normalize_phone(self.cleaned_data["phone"])
        except InvalidPhone as exc:
            raise forms.ValidationError(str(exc)) from exc

    def clean_book_or_link(self):
        return self.cleaned_data["book_or_link"].strip()

    def clean_explanation(self):
        return self.cleaned_data["explanation"].strip()

    def clean_sample_work(self):
        return self.cleaned_data["sample_work"].strip()


MAX_GROUP_ACCESS_MEMBERS = 500


def normalized_phone_list(raw):
    """One phone per line, or comma/semicolon-separated; normalize and de-duplicate in first-seen order."""
    normalized = []
    seen = set()
    duplicates = 0
    parts = []
    for line_number, line in enumerate((raw or "").splitlines(), start=1):
        for part in re.split(r"[,،;؛]+", line):
            value = part.strip()
            if value:
                parts.append((line_number, value))
    if not parts:
        raise forms.ValidationError("دست‌کم یک شماره‌ی موبایل وارد کنید.")
    for line_number, value in parts:
        try:
            phone = normalize_phone(value)
        except InvalidPhone as exc:
            raise forms.ValidationError(f"شماره‌ی ردیف {line_number} معتبر نیست.") from exc
        if phone in seen:
            duplicates += 1
            continue
        seen.add(phone)
        normalized.append(phone)
        if len(normalized) > MAX_GROUP_ACCESS_MEMBERS:
            raise forms.ValidationError(f"در هر درخواست حداکثر {MAX_GROUP_ACCESS_MEMBERS} شماره‌ی یکتا مجاز است.")
    return normalized, duplicates


class BookAccessRequestCreateForm(forms.ModelForm):
    member_phones = forms.CharField(
        label="فهرست پیشنهادی شماره‌ها",
        max_length=20000,
        widget=forms.Textarea(attrs={"rows": 12, "dir": "ltr", "autocomplete": "off"}),
        help_text="هر شماره را در یک خط بنویسید؛ می‌توانید با ویرگول هم جدا کنید. شماره‌ها نرمال و تکراری‌ها حذف می‌شوند. ثبت فهرست هیچ حساب یا دسترسی‌ای ایجاد نمی‌کند؛ مدیر کل باید کتاب و انقضا را جداگانه تأیید کند.",
    )

    class Meta:
        model = BookAccessRequest
        fields = ("book", "request_note")
        widgets = {"request_note": forms.Textarea(attrs={"rows": 3, "maxlength": 1000})}

    def clean_member_phones(self):
        phones, duplicates = normalized_phone_list(self.cleaned_data["member_phones"])
        self.normalized_phones = phones
        self.duplicate_count = duplicates
        return self.cleaned_data["member_phones"]


class BookAccessRequestChangeForm(forms.ModelForm):
    class Meta:
        model = BookAccessRequest
        fields = "__all__"


class GroupAccessRenewForm(forms.Form):
    additional_days = forms.IntegerField(
        label="تمدید به تعداد روز",
        min_value=1,
        max_value=3650,
        widget=forms.NumberInput(attrs={"min": 1, "max": 3650, "dir": "ltr"}),
    )
    reason = forms.CharField(
        label="دلیل تمدید",
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": 500}),
    )

    def clean_reason(self):
        value = self.cleaned_data["reason"].strip()
        if not value:
            raise forms.ValidationError("دلیل تمدید را ثبت کنید.")
        return value


class GroupAccessRevokeForm(forms.Form):
    reason = forms.CharField(
        label="دلیل لغو",
        max_length=500,
        widget=forms.Textarea(attrs={"rows": 3, "maxlength": 500}),
    )

    def clean_reason(self):
        value = self.cleaned_data["reason"].strip()
        if not value:
            raise forms.ValidationError("دلیل لغو را ثبت کنید.")
        return value
