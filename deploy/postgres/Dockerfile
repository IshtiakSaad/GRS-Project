# PostgreSQL with pgaudit. pgaudit records what people do directly in the database (psql,
# admin tools), which the application's own access log cannot see.
FROM postgres:17.11-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-pgaudit=17.1-2.pgdg12+1 \
    && rm -rf /var/lib/apt/lists/*

# Every server built from this image reads its tuning from one directory, mounted read-only.
# The standby gets the same line through its base backup, so both run the same settings.
RUN echo "include_dir = '/etc/postgresql/conf.d'" >> /usr/share/postgresql/postgresql.conf.sample
