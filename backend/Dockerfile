FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 MALLOC_ARENA_MAX=2
WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN SECRET_KEY=build-only HASH_KEY=build-only DEBUG=False \
    SMS_BACKEND=raygan PAYMENTS_ENABLED=False ALLOWED_HOSTS=localhost \
    python manage.py collectstatic --noinput

EXPOSE 8000
CMD ["gunicorn", "-c", "gunicorn.conf.py"]
