# PostgreSQL with pgaudit. pgaudit records what people do directly in the database (psql,
# admin tools), which the application's own access log cannot see.
FROM postgres:17.11-bookworm

RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-17-pgaudit=17.1-2.pgdg12+1 \
    && rm -rf /var/lib/apt/lists/*

# WAL-G: continuous WAL archiving and base backups to the off-host bucket (point-in-time
# recovery). Pinned by checksum: a changed release file fails the build.
ADD --checksum=sha256:d6795c663894d836ba20840bffe8970aed81bbe25d3151bd4951f6f9c362def9 \
    --chmod=755 \
    https://github.com/wal-g/wal-g/releases/download/v3.0.9/wal-g-pg-22.04-amd64 /usr/local/bin/wal-g

# Every server built from this image reads its tuning from one directory, mounted read-only.
# The standby gets the same line through its base backup, so both run the same settings.
RUN echo "include_dir = '/etc/postgresql/conf.d'" >> /usr/share/postgresql/postgresql.conf.sample
