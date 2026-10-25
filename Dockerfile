FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN useradd --create-home --uid 1000 app \
    && mkdir -p /data \
    && DJANGO_SECRET_KEY=solo-para-compilar ALLOWED_HOSTS=localhost python manage.py collectstatic --noinput \
    && chown -R app:app /app /data

USER app

EXPOSE 8000

CMD ["sh", "-c", "python manage.py migrate --noinput && gunicorn backendClinica.wsgi:application --bind 0.0.0.0:8000 --workers 3"]
