# لیمو پلاس

پلتفرم درس تعاملی: کتاب‌های هر رشته به‌صورت خلاصه و جزوه، با تست، فلش‌کارت و آمار مطالعه.

| بخش | پوشه | فناوری |
| --- | --- | --- |
| سرور و پنل مدیر | `backend/` | Python · Django 5.2 · Django REST Framework · PostgreSQL |
| اپ (اندروید، وب‌اپ آیفون و کامپیوتر) | `app/` | TypeScript · React Native · Expo |

## اجرا روی سیستم خودتان

### ۱. سرور (با Docker)

پیش‌نیاز: [Docker Desktop](https://www.docker.com/products/docker-desktop/)

```bash
cp backend/.env.example backend/.env      # بعد SECRET_KEY را در آن عوض کنید
docker compose up --build
```

- سرور: http://localhost:8000/api/v1/health/
- پنل مدیر: http://localhost:8000/admin/

ساخت حساب مدیر (در یک ترمینال دیگر):

```bash
docker compose exec backend python manage.py createsuperuser
```

بارگذاری کتاب نمونه (ریاضی عمومی ۱، با رشته‌ها و بنرهای نمونه):

```bash
docker compose exec backend python manage.py load_samples
```

تا وقتی `SMS_BACKEND=console` است، کد ورود به‌جای پیامک در خروجی همین ترمینال Docker چاپ می‌شود.

### ۱ (راه دیگر). سرور بدون Docker، فقط با Python

اگر Docker نصب یا دانلود نمی‌شود، کافی است [Python](https://www.python.org/downloads/) نسخه‌ی ۳.۱۲ یا بالاتر نصب باشد.
در این حالت داده‌ها در فایل `backend/db.sqlite3` ذخیره می‌شوند و نیازی به PostgreSQL نیست.
پوشه‌ی پروژه را **بیرون از Dropbox/OneDrive/Google Drive** بگذارید (مثلاً `C:\limoplus`)؛ همگام‌سازی این برنامه‌ها می‌تواند فایل دیتابیس را خراب کند.

1. در پوشه‌ی `backend` فایل `.env.example` را کپی کنید و نامش را `.env` بگذارید.
2. `.env` را با Notepad باز کنید و خط `DATABASE_URL=...` را خالی کنید: `DATABASE_URL=`
3. در همان پوشه یک ترمینال باز کنید (ویندوز: در نوار آدرس پوشه بنویسید `cmd` و Enter) و این دستورها را یکی‌یکی اجرا کنید:

```bash
python -m venv venv
venv\Scripts\activate            # مک و لینوکس: source venv/bin/activate
pip install -r requirements.txt
python manage.py migrate
python manage.py load_samples
python manage.py createsuperuser
python manage.py runserver 0.0.0.0:8000
```

دفعه‌های بعد فقط دو دستور لازم است: `venv\Scripts\activate` و `python manage.py runserver 0.0.0.0:8000`.

### ۲. اپ

پیش‌نیاز: [Node.js](https://nodejs.org/) نسخه‌ی ۲۰ یا بالاتر

```bash
cd app
cp .env.example .env
npm install
npm run web        # نسخه‌ی وب در مرورگر: http://localhost:8081
```

برای گوشی از APK بخش ۳ استفاده کنید.

### ۳. نسخه‌ی آزمایشی اندروید (APK)

با هر تغییر در اپ، گیت‌هاب خودکار یک APK می‌سازد (حدود ۱۵ دقیقه). دانلود: صفحه‌ی مخزن در گیت‌هاب › **Releases**
› آخرین «نسخه‌ی آزمایشی» › فایل `.apk`. روی گوشی نصبش کنید (اجازه‌ی «نصب از منابع ناشناس» لازم است).

برای وصل شدن به سروری که روی لپ‌تاپ اجرا می‌کنید:

1. گوشی و لپ‌تاپ در یک Wi‑Fi باشند.
2. آدرس IP لپ‌تاپ را پیدا کنید (ویندوز: دستور `ipconfig`؛ مک: تنظیمات Wi‑Fi). مثلاً `192.168.1.20`.
3. در `backend/.env` خط `ALLOWED_HOSTS=*` را اضافه کنید و سرور را دوباره اجرا کنید (فقط برای تست روی سیستم خودتان).
4. در اپ: صفحه‌ی اول › «تنظیمات سرور» › `http://192.168.1.20:8000` › «آزمایش اتصال» › «ذخیره».

## نوشتن و بارگذاری محتوا

راهنمای کامل قالب فایل فصل‌ها، همراه با دستور آماده برای هوش مصنوعی: [`docs/content-format.md`](docs/content-format.md)

بارگذاری: پنل مدیر › محتوا › «بارگذاری فصل از فایل».

## انتقال به سرور اصلی و دامنه

فقط دو فایل عوض می‌شود:

1. **`backend/.env`**: `SITE_DOMAIN` (مثلاً `api.limoplus.ir`)، `SITE_SCHEME=https`، `DEBUG=False`، `SECRET_KEY` جدید، `DATABASE_URL`، `CORS_ALLOWED_ORIGINS` (آدرس نسخه‌ی وب)، اطلاعات پیامک و `ZIBAL_MERCHANT`.
2. **`app/.env`**: `EXPO_PUBLIC_API_URL=https://api.limoplus.ir`

هیچ آدرس یا رمزی داخل کد نوشته نشده است. فایل‌های `.env` هرگز وارد GitHub نمی‌شوند.

## تست‌ها

```bash
cd backend && pip install -r requirements.txt && SECRET_KEY=test DEBUG=True python manage.py test apps
cd app && npm run typecheck
```

## سند امکانات

همه‌ی تصمیم‌ها و امکانات توافق‌شده در سند «لیمو پلاس · فهرست امکانات و تصمیم‌ها» نگه داشته می‌شود.
