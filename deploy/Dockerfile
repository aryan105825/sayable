# @exports: image sayable-pantry (build: docker build -f deploy/Dockerfile -t sayable-pantry . from the repo root)
# @imports: requirements.txt, pantry/, sayable/
# @env: PANTRY_PORT
# @env: PANTRY_DB
# @env: CONFIRM_SECRET
# @env: CONFIRM_THRESHOLD
# @env: PANTRY_ALLOWED_HOSTS
# @schema: runs `python -m pantry.server --host 0.0.0.0` as non-root user "app" (uid 10001); data dir /app/data
FROM python:3.12.7-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home --shell /usr/sbin/nologin app

WORKDIR /app
COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY pantry/ ./pantry/
COPY sayable/ ./sayable/

RUN mkdir -p /app/data && chown -R app:app /app
USER app

ENV PANTRY_PORT=8801 \
    PANTRY_DB=/app/data/pantry.db
EXPOSE 8801

CMD ["python", "-m", "pantry.server", "--host", "0.0.0.0"]
