#!/usr/bin/env bash
set -euo pipefail
export STAFFER_OWNER_PASSWORD="$(cat /run/secrets/owner_password)"
export STAFFER_APP_PASSWORD="$(cat /run/secrets/app_password)"
psql --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" --set ON_ERROR_STOP=1 <<'SQL'
\getenv owner_pw STAFFER_OWNER_PASSWORD
\getenv app_pw STAFFER_APP_PASSWORD
CREATE ROLE staffer_owner LOGIN PASSWORD :'owner_pw';
CREATE ROLE staffer_app LOGIN PASSWORD :'app_pw';
ALTER DATABASE staffer OWNER TO staffer_owner;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT ALL ON SCHEMA public TO staffer_owner;
GRANT USAGE ON SCHEMA public TO staffer_app;
ALTER DEFAULT PRIVILEGES FOR ROLE staffer_owner IN SCHEMA public GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO staffer_app;
ALTER DEFAULT PRIVILEGES FOR ROLE staffer_owner IN SCHEMA public GRANT USAGE, SELECT ON SEQUENCES TO staffer_app;
SQL
unset STAFFER_OWNER_PASSWORD STAFFER_APP_PASSWORD
