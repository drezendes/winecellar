FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY . .

ENV PATH="/opt/venv/bin:$PATH"

EXPOSE 8000

# At start: run migrations and collect static (env_file supplies DEBUG=False, so
# WhiteNoise's hashed manifest storage is used), then serve. gthread workers —
# a couple of processes with several threads each — carry the slow synchronous
# Claude calls (label scan / pairing / menu) without a large RAM footprint on
# the 4 GB box. --timeout 120 so a long API call isn't killed mid-flight.
CMD ["sh", "-c", "python manage.py migrate --noinput && python manage.py collectstatic --noinput && exec gunicorn config.wsgi:application --bind 0.0.0.0:8000 --worker-class gthread --workers 2 --threads 4 --timeout 120 --access-logfile - --error-logfile -"]
