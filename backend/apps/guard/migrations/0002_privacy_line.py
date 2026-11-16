from django.db import migrations

LINE = ("- وقتی بخشی از متن درس‌ها را کپی می‌کنید، برای جلوگیری از انتشار بی‌اجازه‌ی کتاب‌ها، زمان کپی، بخش و جای آن متن در کتاب "
        "ثبت می‌شود و یک نشانه‌ی نامرئی به متن کپی‌شده افزوده می‌شود.")


def add(apps, schema_editor):
    SitePage = apps.get_model("website", "SitePage")
    page = SitePage.objects.filter(slug="privacy").first()
    if page and LINE not in page.body:
        page.body = page.body.rstrip() + "\n" + LINE
        page.save(update_fields=["body"])


def remove(apps, schema_editor):
    SitePage = apps.get_model("website", "SitePage")
    page = SitePage.objects.filter(slug="privacy").first()
    if page and LINE in page.body:
        page.body = page.body.replace("\n" + LINE, "").replace(LINE, "")
        page.save(update_fields=["body"])


class Migration(migrations.Migration):
    dependencies = [("guard", "0001_initial"), ("website", "0003_app_pages")]
    operations = [migrations.RunPython(add, remove)]
