-- Local and CI only: lets pytest create and drop its test database as grs_owner, so tests run
-- with the same role, ownership and privileges as production. Never applied in production.
ALTER ROLE grs_owner CREATEDB;
