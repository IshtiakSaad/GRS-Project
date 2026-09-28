# syntax=docker/dockerfile:1

# ---- build: install pinned, hash-checked dependencies into a virtualenv ----
FROM python:3.12-slim-bookworm AS build
ENV PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1
RUN python -m venv /venv
COPY requirements/base.txt /tmp/base.txt
RUN /venv/bin/pip install --require-hashes -r /tmp/base.txt

# ---- dev extras for the test image (CI runs the suite inside the same base) ----
FROM build AS build-dev
COPY requirements/dev.txt /tmp/dev.txt
RUN /venv/bin/pip install --require-hashes -r /tmp/dev.txt

# ---- translations: compile .po to .mo (gettext stays out of the runtime image) ----
FROM python:3.12-slim-bookworm AS i18n
RUN apt-get update && apt-get install -y --no-install-recommends gettext     && rm -rf /var/lib/apt/lists/*
COPY src/locale /locale
RUN find /locale -name '*.po' -execdir msgfmt --check -o django.mo django.po \;

# ---- runtime: no compilers, no pip cache, non-root ----
FROM python:3.12-slim-bookworm AS runtime
ARG BUILD_SHA=dev
ENV PATH="/venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/src \
    DJANGO_SETTINGS_MODULE=config.settings.prod \
    BUILD_SHA=${BUILD_SHA}
RUN groupadd --system --gid 10001 app \
    && useradd --system --uid 10001 --gid app --no-create-home --shell /usr/sbin/nologin app
COPY --from=build /venv /venv
WORKDIR /app
COPY --chown=app:app manage.py ./
COPY --chown=app:app src ./src
COPY --from=i18n --chown=app:app /locale ./src/locale
COPY --chown=app:app deploy/gunicorn ./deploy/gunicorn
USER app
EXPOSE 8000
CMD ["gunicorn", "--config", "deploy/gunicorn/api.py", "config.wsgi:application"]

# ---- test: runtime plus pytest, used by CI ----
FROM runtime AS test
USER root
COPY --from=build-dev /venv /venv
COPY --chown=app:app pyproject.toml ./
COPY --chown=app:app tests ./tests
COPY --chown=app:app deploy/nginx ./deploy/nginx
USER app
ENV DJANGO_SETTINGS_MODULE=config.settings.test \
    PYTEST_ADDOPTS="-p no:cacheprovider" \
    COVERAGE_FILE=/tmp/.coverage
CMD ["pytest"]
