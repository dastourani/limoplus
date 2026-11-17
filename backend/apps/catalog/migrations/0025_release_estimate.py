from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("catalog", "0024_waitlist_sms"),
    ]

    operations = [
        migrations.AddField(
            model_name="contentnode",
            name="release_estimate",
            field=models.CharField(
                blank=True,
                help_text="اختیاری؛ مثلاً «آذر ۱۴۰۵» یا «نیمسال دوم ۱۴۰۵». کنار دکمه‌ی «خبرم کن» در سایت و اپ نشان داده می‌شود.",
                max_length=80,
                verbose_name="زمان حدودی انتشار",
            ),
        ),
    ]
