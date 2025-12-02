# app/db.py
import os
import asyncpg
from functools import lru_cache
from typing import Optional, Tuple
from typing import Optional, Mapping, Any
from neo4j import GraphDatabase, Driver
from app import config

# ---------- Postgres ----------
_pg_pool: Optional[asyncpg.Pool] = None

async def ensure_user_from_claims(claims: dict) -> dict:
    email = claims.get("email")
    if not email:
        # Token didn’t include email: ensure your client has the "email" scope.
        raise ValueError("OIDC token missing 'email' claim")

    # Prefer a human-friendly name; fallbacks are safe.
    name = (
        claims.get("name")
        or " ".join(x for x in [claims.get("given_name"), claims.get("family_name")] if x)
        or claims.get("preferred_username")
        or email.split("@")[0]
    )
    picture = claims.get("picture")  # optional → profile_pic_url

    sql = """
    INSERT INTO users (name, email, profile_pic_url)
    VALUES ($1, $2, $3)
    ON CONFLICT (email) DO UPDATE
      SET name = COALESCE(EXCLUDED.name, users.name),
          profile_pic_url = COALESCE(EXCLUDED.profile_pic_url, users.profile_pic_url)
    RETURNING id, name, email, profile_pic_url;
    """

    pool = await get_pg_pool()
    async with pool.acquire() as conn:
        row = await conn.fetchrow(sql, name, email, picture)
    return dict(row)


_pg_pool: Optional[asyncpg.Pool] = None

async def get_pg_pool() -> asyncpg.Pool:
    global _pg_pool
    if _pg_pool is None:
        _pg_pool = await asyncpg.create_pool(
            user=config.DB_USER,
            password=config.DB_PASSWORD,
            database=config.DB_NAME,
            host=config.DB_HOST,
            port=int(config.DB_PORT or 5432),
            min_size=1,
            max_size=10,
            command_timeout=30,
        )
    return _pg_pool


async def get_pg_conn() -> asyncpg.Connection:
    """Kept for compatibility — grabs a connection from the pool."""
    pool = await get_pg_pool()
    return await pool.acquire()

async def release_pg_conn(conn: asyncpg.Connection) -> None:
    pool = await get_pg_pool()
    await pool.release(conn)


