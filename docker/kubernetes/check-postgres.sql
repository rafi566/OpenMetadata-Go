\set ON_ERROR_STOP on
BEGIN READ ONLY;
SELECT current_setting('server_version') AS version, current_database() AS database, current_user AS role;
SELECT current_setting('server_version_num')::integer >= 120000 AS version_ok,
       NOT pg_is_in_recovery() AND current_setting('default_transaction_read_only') = 'off' AS primary_ok,
       has_schema_privilege(current_user, 'public', 'USAGE')
         AND has_schema_privilege(current_user, 'public', 'CREATE') AS schema_ok,
       NOT EXISTS (SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                   WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S')
                     AND NOT pg_has_role(current_user, c.relowner, 'USAGE')) AS ownership_ok,
       EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pgcrypto')
         AND EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') AS extensions_ok
\gset
\if :version_ok
\else
  DO $$ BEGIN RAISE EXCEPTION 'FAIL: PostgreSQL 12 or newer is required'; END $$;
\endif
\if :primary_ok
\else
  DO $$ BEGIN RAISE EXCEPTION 'FAIL: connect to a writable primary database'; END $$;
\endif
\if :schema_ok
\else
  DO $$ BEGIN RAISE EXCEPTION 'FAIL: the application role needs USAGE and CREATE on schema public'; END $$;
\endif
\if :extensions_ok
\else
  DO $$ BEGIN RAISE EXCEPTION 'FAIL: ask the DBA to install pgcrypto and pg_trgm in this database'; END $$;
\endif
\if :ownership_ok
\else
  DO $$ BEGIN RAISE EXCEPTION 'FAIL: the migration role must own existing tables and sequences in schema public'; END $$;
\endif
ROLLBACK;
\echo PASS: PostgreSQL version floor, primary, schema permissions and extensions
