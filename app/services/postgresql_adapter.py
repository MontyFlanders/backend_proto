from app.db import get_pg_conn
from typing import Optional

class PostgresAdapter:
    
    # Handles PostgreSQL queries related to sites and users.
    
    async def fetch_one_site(self, site_id: int) -> dict:
        conn = await get_pg_conn()
        result = await conn.fetchrow("SELECT * FROM historical_sites WHERE id = $1", site_id)
        await conn.close()
        return dict(result) if result else None

    async def fetch_site_location(self, site_id: int) -> dict:
        conn = await get_pg_conn()
        result = await conn.fetchrow("""
            SELECT ST_X(location::geometry) AS longitude,
                   ST_Y(location::geometry) AS latitude
            FROM historical_sites WHERE id = $1
        """, site_id)
        await conn.close()
        return dict(result) if result else None

    async def fetch_posts_by_site(self, site_id: int) -> list[dict]:
        conn = await get_pg_conn()
        results = await conn.fetch("SELECT * FROM posts WHERE site_id = $1", site_id)
        await conn.close()
        return [dict(row) for row in results]

    async def fetch_post(self, post_id: int) -> dict:
        conn = await get_pg_conn()
        result = await conn.fetchrow("SELECT * FROM posts WHERE id = $1", post_id)
        await conn.close()
        return dict(result) if result else None

    async def fetch_user_by_post(self, post_id: int) -> dict:
        conn = await get_pg_conn()
        result = await conn.fetchrow("""
            SELECT u.* FROM users u
            JOIN posts p ON p.user_id = u.id
            WHERE p.id = $1
        """, post_id)
        await conn.close()
        return dict(result) if result else None

    async def fetch_comments_by_post(self, post_id: int) -> list[dict]:
        conn = await get_pg_conn()
        results = await conn.fetch("SELECT * FROM comments WHERE post_id = $1", post_id)
        await conn.close()
        return [dict(row) for row in results]

    async def fetch_user(self, user_id: int) -> dict:
        conn = await get_pg_conn()
        result = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
        await conn.close()
        return dict(result) if result else None
    
    async def insert_post(self, user_id, title, content, site_id, image_url):
        conn = await get_pg_conn()
        await conn.execute("""
            INSERT INTO posts (user_id, title, content, site_id, image, likes, dislikes)
            VALUES ($1, $2, $3, $4, $5, 0, 0)
        """, user_id, title, content, site_id, image_url)
        await conn.close()

    async def insert_comment(self, user_id, post_id, title, content, image_url):
        conn = await get_pg_conn()
        await conn.execute("""
            INSERT INTO comments (user_id, post_id, title, content, image, likes, dislikes)
            VALUES ($1, $2, $3, $4, $5, 0, 0)
        """, user_id, post_id, title, content, image_url)
        await conn.close()

    async def update_post_image(self, post_id, image_url):
        conn = await get_pg_conn()
        await conn.execute("""
            UPDATE posts SET image = $1 WHERE id = $2
        """, image_url, post_id)
        await conn.close()
        
    async def insert_historical_site(
        self,
        user_id: int,
        title: str,
        description: str,
        latitude: float,
        longitude: float,
        image_url: Optional[str] = None
    ) -> dict:
        conn = await get_pg_conn()
        row = await conn.fetchrow("""
            INSERT INTO historical_sites (user_id, title, description, location, image, likes, dislikes)
            VALUES ($1, $2, $3, ST_SetSRID(ST_MakePoint($4, $5), 4326), $6, 0, 0)
            RETURNING *
        """, user_id, title, description, longitude, latitude, image_url)
        await conn.close()
        return dict(row)

        
    async def create_user(self, name, email):
        conn = await get_pg_conn()
        result = await conn.fetchrow("""
            INSERT INTO users (name, email)
            VALUES ($1, $2)
            RETURNING *
        """, name, email)
        await conn.close()
        return dict(result)

    async def fetch_sites_within_bounds(
        self,
        ne_lat: float,
        ne_lng: float,
        sw_lat: float,
        sw_lng: float
    ) -> list[dict]:
        conn = await get_pg_conn()
        rows = await conn.fetch(
            """
            SELECT
              id,
              title,
              description,
              ST_Y(location::geometry) AS latitude,
              ST_X(location::geometry) AS longitude
            FROM historical_sites
            WHERE ST_Within(
              location::geometry,
              ST_MakeEnvelope(
                $4,  -- minX = sw_lng
                $3,  -- minY = sw_lat
                $2,  -- maxX = ne_lng
                $1,  -- maxY = ne_lat
                4326 -- SRID
              )
            )
            LIMIT $5
            """,
            ne_lat,
            ne_lng,
            sw_lat,
            sw_lng,
        )
        await conn.close()
        return [dict(r) for r in rows]
