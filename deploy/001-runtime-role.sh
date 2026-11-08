#!/bin/sh
set -eu
# Trusted PostgreSQL bootstrap only. Runtime never receives the admin password.
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" \
  --set=runtime_password="$CALIBURN_RUNTIME_DB_PASSWORD" <<'SQL'
CREATE ROLE caliburn LOGIN PASSWORD :'runtime_password';
GRANT CONNECT ON DATABASE caliburn TO caliburn;
GRANT USAGE ON SCHEMA public TO caliburn;
ALTER DEFAULT PRIVILEGES FOR ROLE postgres IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO caliburn;
SQL
