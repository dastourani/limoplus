from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("accounts", "0003_persian_labels"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="can_copy",
            field=models.BooleanField(
                default=True,
                help_text="اگر برداشته شود، حساب و کتاب‌هایش باز می‌ماند ولی دیگر نمی‌تواند متن درس را کپی کند.",
                verbose_name="امکان کپی متن",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="can_report",
            field=models.BooleanField(
                default=True,
                help_text="اگر برداشته شود، حساب باز می‌ماند ولی دیگر نمی‌تواند گزارش اشکال بفرستد.",
                verbose_name="امکان ارسال گزارش",
            ),
        ),
        migrations.AddField(
            model_name="user",
            name="admin_note",
            field=models.CharField(blank=True, max_length=300, verbose_name="یادداشت مدیر / علت محدودیت"),
        ),
    ]
