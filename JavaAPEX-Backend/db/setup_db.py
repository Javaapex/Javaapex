"""Apply the APEX schema to PostgreSQL."""
import sys
import os
import re

# Parse .env manually to avoid dotenv import issues
env_vars = {}
env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
if os.path.exists(env_path):
    with open(env_path, "r") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env_vars[key.strip()] = value.strip()

DB_HOST = env_vars.get("DB_HOST", "localhost")
DB_PORT = int(env_vars.get("DB_PORT", "5432"))
DB_NAME = env_vars.get("DB_NAME", "javaapex")
DB_USER = env_vars.get("DB_USER", "postgres")
DB_PASSWORD = env_vars.get("DB_PASSWORD", "afzal")
DB_SCHEMA = env_vars.get("DB_SCHEMA", "apex")

import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT

# Step 1: Connect to 'postgres' default DB and create javaapex if not exists
try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname="postgres",
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    
    with conn.cursor() as cur:
        cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (DB_NAME,))
        if cur.fetchone():
            print(f"Database '{DB_NAME}' already exists.")
        else:
            cur.execute(f'CREATE DATABASE "{DB_NAME}"')
            print(f"Database '{DB_NAME}' created.")
    conn.close()
except psycopg2.Error as e:
    print(f"Error creating database: {e}", file=sys.stderr)
    sys.exit(1)

# Step 2: Apply schema
schema_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "schema.sql")
if not os.path.exists(schema_path):
    print(f"schema.sql not found at {schema_path}", file=sys.stderr)
    sys.exit(1)

with open(schema_path, "r", encoding="utf-8") as f:
    schema_sql = f.read()

try:
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        dbname=DB_NAME,
    )
    conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
    
    with conn.cursor() as cur:
        cur.execute(schema_sql)
        print(f"Schema applied successfully to database '{DB_NAME}'.")
    
    # Verify tables
    with conn.cursor() as cur:
        cur.execute("""
            SELECT table_schema, table_name 
            FROM information_schema.tables 
            WHERE table_schema = %s 
            ORDER BY table_name
        """, (DB_SCHEMA,))
        tables = cur.fetchall()
        if tables:
            print(f"\nTables in schema '{DB_SCHEMA}':")
            for schema, table in tables:
                print(f"  {schema}.{table}")
        else:
            print(f"\nNo tables found in schema '{DB_SCHEMA}'.")
            
        # Also show table count
        cur.execute("""
            SELECT COUNT(*) 
            FROM information_schema.tables 
            WHERE table_schema = %s
        """, (DB_SCHEMA,))
        count = cur.fetchone()[0]
        print(f"\nTotal tables: {count}")
    
    conn.close()
    print("\nDone!")
except psycopg2.Error as e:
    print(f"Error applying schema: {e}", file=sys.stderr)
    sys.exit(1)