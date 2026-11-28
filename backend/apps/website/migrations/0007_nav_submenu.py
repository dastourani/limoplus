import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("website", "0006_nav_and_page_controls"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitenavitem",
            name="parent",
            field=models.ForeignKey(
                blank=True,
                help_text="خالی = آیتم اصلی در نوار بالا؛ اگر یک آیتم اصلی را انتخاب کنید، به‌عنوان زیرمنوی آبشاری آن نمایش داده می‌شود.",
                limit_choices_to={"parent__isnull": True},
                null=True,
                on_delete=django.db.models.deletion.CASCADE,
                related_name="children",
                to="website.sitenavitem",
                verbose_name="زیرمجموعه‌ی منوی",
            ),
        ),
        migrations.AlterField(
            model_name="sitenavitem",
            name="url",
            field=models.CharField(
                blank=True,
                default="#",
                help_text="نام بخش داخلی («books»، «pricing»، «download»، «faq»)، آدرس یک صفحه («page:protection») یا لینک کامل («https://...»).",
                max_length=300,
                verbose_name="آدرس یا مسیر",
            ),
        ),
    ]
