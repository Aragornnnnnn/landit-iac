#!/usr/bin/env python3
# 운영 EC2에서 Supabase의 업무 스키마를 별도 RDS 데이터베이스에 복원한다.
import json
import os
import re
import secrets
import subprocess
import sys
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit


ROOT = Path("/run/landit-rehearsal")
DATABASE = "landit_rehearsal"
REGION = "ap-northeast-2"
RDS_CA = f"https://truststore.pki.rds.amazonaws.com/{REGION}/{REGION}-bundle.pem"
SUPABASE_CA = "https://supabase-downloads.s3-ap-southeast-1.amazonaws.com/prod/ssl/prod-ca-2021.crt"
SOURCE_PARAMETERS = tuple(f"/landit/prod/{name}" for name in ("DB_URL", "DB_USERNAME", "DB_PASSWORD"))
COUNTS = r"""
SELECT format('SELECT %L, count(*) FROM %I.%I;', tablename, schemaname, tablename)
FROM pg_tables WHERE schemaname = 'public' ORDER BY tablename
\gexec
"""
MANAGED_TRIGGERS = """
SELECT t.oid FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
JOIN pg_proc p ON p.oid = t.tgfoid JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE c.relnamespace = 'public'::regnamespace AND NOT t.tgisinternal
  AND n.nspname IN ('supabase_functions', 'landit_alerts', 'net');
"""


def aws(*args):
    return json.loads(subprocess.check_output(["aws", *args, "--region", REGION, "--output", "json"]))


def pg_env(host, port, database, user, password, ca):
    return dict(
        os.environ,
        PGHOST=host,
        PGPORT=str(port),
        PGDATABASE=database,
        PGUSER=user,
        PGPASSWORD=password,
        PGSSLMODE="verify-full",
        PGSSLROOTCERT=ca,
        PGCONNECT_TIMEOUT="10",
        PGAPPNAME="landit-lan-886-rehearsal",
    )


def psql(env, sql):
    return subprocess.check_output(
        ["psql", "-XAtq", "-v", "ON_ERROR_STOP=1"],
        input=sql, text=True, env=env,
    ).strip()


def dump_snapshot(source, archive):
    # 행 수와 pg_dump가 같은 운영 스냅샷을 사용하도록 읽기 트랜잭션을 열어 둔다.
    with subprocess.Popen(
        ["psql", "-XAtq", "-v", "ON_ERROR_STOP=1"],
        stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, env=source,
    ) as snapshot:
        try:
            snapshot.stdin.write(
                "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
                "SELECT pg_export_snapshot();\n"
            )
            snapshot.stdin.flush()
            identifier = snapshot.stdout.readline().strip()
            if not re.fullmatch(r"[0-9A-Fa-f-]+", identifier):
                raise RuntimeError("Source snapshot could not be exported")
            subprocess.run(
                ["pg_dump", "--format=custom", "--schema=public", "--lock-wait-timeout=5s",
                 f"--snapshot={identifier}", "--file", str(archive)],
                env=source, check=True,
            )
            begin = (
                "BEGIN ISOLATION LEVEL REPEATABLE READ READ ONLY;\n"
                f"SET TRANSACTION SNAPSHOT '{identifier}';\n"
            )
            counts = psql(source, f"{begin}{COUNTS}\nROLLBACK;\n")
            excluded_triggers = set(psql(source, f"{begin}{MANAGED_TRIGGERS}\nROLLBACK;\n").splitlines())
            return counts, excluded_triggers
        finally:
            snapshot.stdin.close()


def main():
    if len(sys.argv) not in (3, 4) or (len(sys.argv) == 4 and sys.argv[3] != "--resume-empty"):
        raise SystemExit("Usage: rehearse-database.py RDS_DNS RDS_MASTER_SECRET_ARN [--resume-empty]")
    host, secret_id = sys.argv[1:3]
    if not re.fullmatch(r"prod-landit-postgres\.[a-z0-9-]+\.ap-northeast-2\.rds\.amazonaws\.com", host):
        raise SystemExit("Unexpected rehearsal RDS endpoint")
    if not re.fullmatch(r"arn:aws:secretsmanager:ap-northeast-2:944011958218:secret:rds!db-.+", secret_id):
        raise SystemExit("Unexpected rehearsal RDS secret")

    ca_path = ROOT / "rds-ca.pem"
    subprocess.run(["curl", "-fsSL", "--retry", "3", RDS_CA, "-o", str(ca_path)], check=True)
    source_ca = ROOT / "supabase-ca.pem"
    subprocess.run(
        ["curl", "-fsSL", "--proto", "=https", "--proto-redir", "=https",
         "--retry", "3", SUPABASE_CA, "-o", str(source_ca)],
        check=True,
    )
    values = aws("ssm", "get-parameters", "--with-decryption", "--names", *SOURCE_PARAMETERS)
    source_credentials = {item["Name"]: item["Value"] for item in values["Parameters"]}
    url, user, password = (source_credentials[name] for name in SOURCE_PARAMETERS)
    parsed = urlsplit(url.removeprefix("jdbc:"))
    if not parsed.hostname or not parsed.hostname.endswith(".supabase.com"):
        raise SystemExit("Unexpected source database provider")
    source = pg_env(parsed.hostname, parsed.port or 5432, unquote(parsed.path[1:]), user, password, str(source_ca))
    source["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=60000 -c lock_timeout=5000"

    secret = json.loads(aws("secretsmanager", "get-secret-value", "--secret-id", secret_id)["SecretString"])
    target = pg_env(host, 5432, "landit", secret["username"], secret["password"], str(ca_path))
    target_exists = bool(psql(target, f"SELECT 1 FROM pg_database WHERE datname = '{DATABASE}';"))
    if target_exists:
        if len(sys.argv) != 4:
            raise SystemExit("Rehearsal DB already exists. Preserve it for inspection before retrying.")
        target["PGDATABASE"] = DATABASE
        if psql(target, """
            SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = 'public' LIMIT 1;
        """):
            raise SystemExit("Rehearsal DB already contains restored objects.")

    with TemporaryDirectory(prefix="landit-886-", dir="/var/tmp") as scratch:
        archive = Path(scratch) / "public.dump"
        expected, excluded_triggers = dump_snapshot(source, archive)
        if not target_exists:
            psql(target, f"CREATE DATABASE {DATABASE} TEMPLATE template0;")
        target["PGDATABASE"] = DATABASE
        archive_objects = subprocess.check_output(["pg_restore", "--list", str(archive)], text=True)
        if re.search(r"^\d+; \d+ \d+ SCHEMA - public ", archive_objects, re.MULTILINE):
            psql(target, "DROP SCHEMA IF EXISTS public;")
        psql(target, """
            CREATE SCHEMA IF NOT EXISTS extensions;
            CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;
            CREATE EXTENSION IF NOT EXISTS pgcrypto WITH SCHEMA extensions;
            CREATE EXTENSION IF NOT EXISTS "uuid-ossp" WITH SCHEMA extensions;
            DO $$
            BEGIN
              IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'landit_push_reader') THEN
                CREATE ROLE landit_push_reader NOLOGIN;
              END IF;
            END
            $$;
        """)
        restore_list = Path(scratch) / "restore.list"
        entries = archive_objects.splitlines()
        excluded_count = 0
        for index, entry in enumerate(entries):
            trigger = re.match(r"^\d+; 2620 (\d+) TRIGGER ", entry)
            if trigger and trigger.group(1) in excluded_triggers:
                entries[index] = ";" + entry
                excluded_count += 1
        if excluded_count != len(excluded_triggers):
            raise SystemExit("Could not match all managed triggers to archive entries.")
        restore_list.write_text("\n".join(entries) + "\n")
        subprocess.run(
            ["pg_restore", "--single-transaction", "--exit-on-error", "--no-owner",
             "--no-privileges", "--use-list", str(restore_list), "--dbname", DATABASE, str(archive)],
            env=target, check=True,
        )
        actual = psql(target, COUNTS)
        if expected != actual:
            source_counts = dict(line.split("|", 1) for line in expected.splitlines())
            target_counts = dict(line.split("|", 1) for line in actual.splitlines())
            mismatches = sorted(table for table in source_counts.keys() | target_counts.keys()
                                if source_counts.get(table) != target_counts.get(table))
            raise SystemExit("Table counts differ: " + ", ".join(mismatches))
        print(f"Snapshot row counts match for {len(actual.splitlines())} public tables.")
        print(f"Excluded {excluded_count} Supabase-managed trigger(s) from the rehearsal DB.")

    psql(target, r"""
        SELECT format('ALTER TABLE %I.%I DISABLE TRIGGER %I;', n.nspname, c.relname, t.tgname)
        FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace JOIN pg_proc p ON p.oid = t.tgfoid
        WHERE n.nspname = 'public' AND p.proname = 'notify_landit_referral' AND NOT t.tgisinternal
        \gexec
    """)

    # 각 도구에 필요한 자격 증명은 재부팅 시 사라지는 root 전용 디렉터리에만 둔다.
    jdbc = f"jdbc:postgresql://{host}:5432/{DATABASE}?sslmode=verify-full&sslrootcert={ca_path}"
    (ROOT / "flyway.env").write_text(
        f"DB_URL={jdbc}\nDB_USERNAME={secret['username']}\nDB_PASSWORD={secret['password']}\n"
    )
    smoke_password = secrets.token_urlsafe(36)
    psql(target, f"""
        CREATE ROLE landit_rehearsal_reader LOGIN PASSWORD '{smoke_password}';
        ALTER ROLE landit_rehearsal_reader SET default_transaction_read_only = on;
        REVOKE CONNECT ON DATABASE {DATABASE} FROM PUBLIC;
        GRANT CONNECT ON DATABASE {DATABASE} TO landit_rehearsal_reader;
        GRANT USAGE ON SCHEMA public, extensions TO landit_rehearsal_reader;
        GRANT SELECT ON ALL TABLES IN SCHEMA public TO landit_rehearsal_reader;
    """)
    (ROOT / "api.env").write_text(
        f"DB_URL={jdbc}\nDB_USERNAME=landit_rehearsal_reader\nDB_PASSWORD={smoke_password}\n"
        f"LANDIT_AUTH_TOKEN_SECRET={secrets.token_hex(48)}\n"
        "SPRING_PROFILES_ACTIVE=prod\n"
        "LANDIT_NOTIFICATION_CONSUMER_ENABLED=false\n"
        "MANAGEMENT_OTLP_METRICS_EXPORT_ENABLED=false\n"
    )
    print("Flyway version|successful|failed: " + psql(target, """
        SELECT (SELECT version FROM flyway_schema_history WHERE version IS NOT NULL
                ORDER BY installed_rank DESC LIMIT 1),
               count(*) FILTER (WHERE success), count(*) FILTER (WHERE NOT success)
        FROM flyway_schema_history;
    """))


if __name__ == "__main__":
    os.umask(0o077)
    ROOT.mkdir(mode=0o700, exist_ok=True)
    with (ROOT / "restore.log").open("w") as diagnostic_log:
        os.dup2(diagnostic_log.fileno(), 2)
        try:
            main()
        except Exception:
            traceback.print_exc()
            print("Restore failed; check the root-only restore.log.")
            sys.exit(1)
