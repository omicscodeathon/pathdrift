"""Setup PostgreSQL for PathDrift — run as a standalone script."""
import subprocess
import sys
import os

PSQL = r"C:\Program Files\PostgreSQL\18\bin\psql.exe"
PG_PASS = "PD_5dWzcphWhE0tEwkS1oQ3uO8HBVo"

def run(cmd, env=None):
    result = subprocess.run(cmd, capture_output=True, text=True, env=env)
    print(result.stdout.strip())
    if result.stderr.strip():
        print("STDERR:", result.stderr.strip())
    return result.returncode

env_super = {**os.environ, "PGPASSWORD": "postgres"}
env_pd   = {**os.environ, "PGPASSWORD": PG_PASS}

print("=== Creating pathdrift role ===")
run([PSQL, "-U", "postgres", "-c",
     f"DO $$ BEGIN IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname='pathdrift') "
     f"THEN CREATE ROLE pathdrift WITH LOGIN PASSWORD '{PG_PASS}'; "
     f"ELSE ALTER ROLE pathdrift WITH PASSWORD '{PG_PASS}'; END IF; END $$;"],
    env=env_super)

print("=== Dropping old database (if exists) ===")
run([PSQL, "-U", "postgres", "-c", "DROP DATABASE IF EXISTS pathdrift;"], env=env_super)

print("=== Creating pathdrift database ===")
run([PSQL, "-U", "postgres", "-c", "CREATE DATABASE pathdrift OWNER pathdrift;"], env=env_super)

print("=== Granting privileges ===")
run([PSQL, "-U", "postgres", "-d", "pathdrift", "-c",
     "GRANT ALL PRIVILEGES ON DATABASE pathdrift TO pathdrift;"], env=env_super)
run([PSQL, "-U", "postgres", "-d", "pathdrift", "-c",
     "GRANT ALL ON SCHEMA public TO pathdrift;"], env=env_super)

print("=== Enabling extensions ===")
run([PSQL, "-U", "postgres", "-d", "pathdrift", "-c",
     'CREATE EXTENSION IF NOT EXISTS "uuid-ossp";'], env=env_super)

print("=== Verifying connection as pathdrift user ===")
rc = run([PSQL, "-U", "pathdrift", "-d", "pathdrift", "-c", "SELECT current_user, version();"],
         env=env_pd)

if rc == 0:
    print("\n✓ PostgreSQL setup complete")
    print(f"  Host: localhost:5432")
    print(f"  Database: pathdrift")
    print(f"  User: pathdrift")
    print(f"  Password: {PG_PASS}")
else:
    print("\n✗ Setup had errors — check output above")
    sys.exit(1)
