import sys, pathlib, types, os
import pytest
import pytest_asyncio
import asyncpg

# --- ensure repo root on sys.path ---
ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

# --- optional stubs for deps you don't need in these tests ---
neo4j_stub = types.ModuleType("neo4j")
neo4j_stub.GraphDatabase = type("GraphDatabase", (), {"driver": staticmethod(lambda *a, **k: object())})
sys.modules.setdefault("neo4j", neo4j_stub)

dotenv_stub = types.ModuleType("dotenv")
dotenv_stub.load_dotenv = lambda *a, **k: None
sys.modules.setdefault("dotenv", dotenv_stub)

# --- import app modules AFTER stubs & path fixes ---
import app.db as app_db
import app.services.postgresql_adapter as adapter_mod

# --- DB config: use host networking (published port) ---
DB_HOST = os.getenv("DB_HOST", "127.0.0.1")
DB_PORT = int(os.getenv("DB_PORT", "5432"))
DB_NAME = os.getenv("DB_NAME", "db_test1")
DB_USER = os.getenv("DB_USER", "test")
DB_PASSWORD = os.getenv("DB_PASSWORD", "test")

DDL = """
CREATE EXTENSION IF NOT EXISTS postgis;

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL
);

CREATE TABLE IF NOT EXISTS historical_sites (
    id SERIAL PRIMARY KEY,
    user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT NOT NULL,
    location GEOGRAPHY(Point, 4326) NOT NULL,
    image TEXT,
    likes INT NOT NULL DEFAULT 0,
    dislikes INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS posts (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    site_id INTEGER REFERENCES historical_sites(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    image TEXT,
    likes INT NOT NULL DEFAULT 0,
    dislikes INT NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS comments (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
    title TEXT NOT NULL,
    content TEXT NOT NULL,
    image TEXT,
    likes INT NOT NULL DEFAULT 0,
    dislikes INT NOT NULL DEFAULT 0
);
"""

TRUNCATE_ALL = """
TRUNCATE comments RESTART IDENTITY CASCADE;
TRUNCATE posts RESTART IDENTITY CASCADE;
TRUNCATE historical_sites RESTART IDENTITY CASCADE;
TRUNCATE users RESTART IDENTITY CASCADE;
"""

# Function-scoped pool binds to the same event loop as each test.
@pytest_asyncio.fixture
async def pg_pool():
    pool = await asyncpg.create_pool(
        host=DB_HOST,
        port=DB_PORT,
        user=DB_USER,
        password=DB_PASSWORD,
        database=DB_NAME,
        statement_cache_size=0,
        ssl=False,   # local docker PG isn't using SSL
        min_size=1,
        max_size=5,
    )
    # Ensure schema exists
    async with pool.acquire() as conn:
        await conn.execute(DDL)
    # Clean DB before each test
    async with pool.acquire() as conn:
        await conn.execute(TRUNCATE_ALL)
    try:
        yield pool
    finally:
        await pool.close()

# Patch the *symbol the adapter imported* so adapter methods use the pool.
@pytest.fixture(autouse=True)
def patch_get_pg_conn(pg_pool, monkeypatch):
    async def _get_pg_conn():
        # PoolConnectionProxy: adapter's conn.close() will release to pool.
        return await pg_pool.acquire()

    # Patch both the definition module and the consumer module.
    monkeypatch.setattr(app_db, "get_pg_conn", _get_pg_conn, raising=True)
    monkeypatch.setattr(adapter_mod, "get_pg_conn", _get_pg_conn, raising=True)
