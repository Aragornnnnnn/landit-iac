-- 복원된 RDS에서 푸시 대상 조회용 역할에 원본과 같은 읽기 권한을 부여한다.
DO $$
DECLARE
  table_ref record;
BEGIN
  IF current_database() NOT IN ('landit', 'landit_rehearsal')
    OR to_regclass('public.flyway_schema_history') IS NULL THEN
    RAISE EXCEPTION 'Run this only against the restored Landit RDS database';
  END IF;

  IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'landit_push_reader') THEN
    CREATE ROLE landit_push_reader NOLOGIN;
  END IF;

  ALTER ROLE landit_push_reader NOBYPASSRLS;
  ALTER ROLE landit_push_reader SET default_transaction_read_only TO on;
  EXECUTE format('GRANT CONNECT ON DATABASE %I TO landit_push_reader', current_database());
  GRANT USAGE ON SCHEMA public TO landit_push_reader;

  FOR table_ref IN
    SELECT c.relname
    FROM pg_class c
    WHERE c.relnamespace = 'public'::regnamespace AND c.relkind IN ('r', 'p')
  LOOP
    EXECUTE format('GRANT SELECT ON TABLE public.%I TO landit_push_reader', table_ref.relname);
  END LOOP;
END;
$$;
