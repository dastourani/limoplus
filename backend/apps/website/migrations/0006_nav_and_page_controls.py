from django.db import migrations, models

DEFAULT_NAV = [
    ("کتاب‌ها", "books", 1),
    ("قیمت‌ها", "pricing", 2),
    ("دانلود", "download", 3),
    ("پرسش‌های پرتکرار", "faq", 4),
    ("حفاظت از محتوا", "page:protection", 5),
]
PAGE_ORDERS = {"terms": 1, "privacy": 2, "protection": 3, "about": 4, "contact": 5}


def seed_nav(apps, schema_editor):
    SiteNavItem = apps.get_model("website", "SiteNavItem")
    SitePage = apps.get_model("website", "SitePage")
    for title, url, order in DEFAULT_NAV:
        SiteNavItem.objects.get_or_create(url=url, defaults={"title": title, "order": order, "is_hidden": False})
    for p in SitePage.objects.all():
        p.order = PAGE_ORDERS.get(p.slug, 10)
        p.show_in_footer = True
        p.save(update_fields=["order", "show_in_footer"])


class Migration(migrations.Migration):

    dependencies = [
        ("website", "0005_protection_page"),
    ]

    operations = [
        migrations.AddField(
            model_name="sitesettings",
            name="band_title",
            field=models.CharField(default="هر روز فقط چند دقیقه، با برنامه‌ی مرور هوشمند", max_length=140, verbose_name="عنوان بخش میانی (کنار لیمو)"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="band_sub",
            field=models.CharField(default="لیموخوان بر اساس عملکردت می‌داند امروز چه بخشی، تستی یا کارتی را باید مرور کنی", max_length=220, verbose_name="زیرعنوان بخش میانی"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="show_updates",
            field=models.BooleanField(default=True, verbose_name="نمایش بخش تازه‌ها در صفحه‌ی اول"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="show_sample_test",
            field=models.BooleanField(default=True, verbose_name="نمایش تست نمونه‌ی تعاملی در صفحه‌ی اول"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="show_home_faq",
            field=models.BooleanField(default=True, verbose_name="نمایش پرسش‌های پرتکرار در صفحه‌ی اول"),
        ),
        migrations.AddField(
            model_name="sitesettings",
            name="footer_about",
            field=models.TextField(default="کتاب درسی تعاملی برای دانشجوهای ایران: خلاصه، درسنامه، تست با پاسخ تشریحی و فلش‌کارت.", verbose_name="متن معرفی در فوتر سایت"),
        ),
        migrations.AddField(
            model_name="sitepage",
            name="order",
            field=models.PositiveIntegerField(default=10, verbose_name="ترتیب"),
        ),
        migrations.AddField(
            model_name="sitepage",
            name="show_in_nav",
            field=models.BooleanField(default=False, help_text="در نوار منوی بالای سایت نشان داده شود.", verbose_name="نمایش در منوی بالا"),
        ),
        migrations.AddField(
            model_name="sitepage",
            name="show_in_footer",
            field=models.BooleanField(default=True, help_text="در ستون پشتیبانی پایین سایت نشان داده شود.", verbose_name="نمایش در فوتر"),
        ),
        migrations.AlterField(
            model_name="sitepage",
            name="slug",
            field=models.SlugField(
                help_text="در آدرس /p/<slug>/ قرار می‌گیرد؛ مثلاً terms، privacy، protection یا هر نام لاتین دلخواه.",
                max_length=40,
                unique=True,
                verbose_name="شناسه‌ی آدرس (لاتین)",
            ),
        ),
        migrations.AlterModelOptions(
            name="sitepage",
            options={"ordering": ["order", "slug"], "verbose_name": "صفحه‌ی سایت", "verbose_name_plural": "صفحه‌های سایت"},
        ),
        migrations.CreateModel(
            name="SiteNavItem",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("title", models.CharField(max_length=60, verbose_name="عنوان در منو")),
                ("url", models.CharField(help_text="نام بخش داخلی («books»، «pricing»، «download»، «faq»)، آدرس یک صفحه («page:protection») یا لینک کامل («https://...»).", max_length=300, verbose_name="آدرس یا مسیر")),
                ("order", models.PositiveIntegerField(default=10, verbose_name="ترتیب")),
                ("is_hidden", models.BooleanField(default=False, verbose_name="پنهان")),
            ],
            options={
                "verbose_name": "آیتم منوی سایت",
                "verbose_name_plural": "منوی بالای سایت",
                "ordering": ["order", "id"],
            },
        ),
        migrations.RunPython(seed_nav, migrations.RunPython.noop),
    ]
