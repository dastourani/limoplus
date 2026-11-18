from django import forms

from apps.accounts.phone import InvalidPhone, normalize_phone

from .models import TeacherApplication


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
