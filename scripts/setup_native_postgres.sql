-- Одноразовая настройка PostgreSQL для flipper (без Docker).
-- Запустить ОДИН РАЗ от пользователя postgres:
--   psql -U postgres -f scripts/setup_native_postgres.sql
--   или через PowerShell (psql запросит пароль пользователя postgres):
--   & "C:\Program Files\PostgreSQL\18\bin\psql.EXE" -U postgres -f scripts/setup_native_postgres.sql

DO $$
BEGIN
  IF NOT EXISTS (SELECT FROM pg_catalog.pg_roles WHERE rolname = 'flipper') THEN
    CREATE ROLE flipper LOGIN PASSWORD 'flipper_secret' SUPERUSER;
  END IF;
END
$$;

SELECT 'CREATE DATABASE flipper OWNER flipper'
WHERE NOT EXISTS (SELECT FROM pg_database WHERE datname = 'flipper')
\gexec
