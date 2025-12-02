from typing import Optional, Dict, Any, List, Union
from contextlib import asynccontextmanager
import asyncpg

from app.db import get_pg_pool 

PoolOrConn = Union[asyncpg.Pool, asyncpg.Connection]


class PostgresAdapter:
    """Handles PostgreSQL queries related to sites, posts, comments, and users."""

    def __init__(self, pool: Optional[PoolOrConn] = None):
        self._pool = pool

    @asynccontextmanager
    async def _conn(self):
        pobj: PoolOrConn = self._pool or await get_pg_pool()
        if hasattr(pobj, "acquire"):
            async with pobj.acquire() as conn:
                yield conn
        else:
            yield pobj

    async def _fetchrow(self, sql: str, *args) -> Optional[Dict[str, Any]]:
        async with self._conn() as conn:
            row = await conn.fetchrow(sql, *args)
            return dict(row) if row else None

    async def _fetch(self, sql: str, *args) -> List[Dict[str, Any]]:
        async with self._conn() as conn:
            rows = await conn.fetch(sql, *args)
            return [dict(r) for r in rows]

    async def _execute(self, sql: str, *args) -> str:
        async with self._conn() as conn:
            return await conn.execute(sql, *args)

    async def fetch_one_site(self, site_id: int) -> Optional[Dict[str, Any]]:
        async with self._conn() as conn:
            sql = """
            SELECT
                s.id,
                s.user_id,
                s.title,
                COALESCE(s.description, '') AS description,
                s.image,  -- or s.image AS image_url if your column is named image
                COALESCE(s.likes, 0)    AS likes,
                COALESCE(s.dislikes, 0) AS dislikes,
                s.created_at,
                ST_Y(s.location::geometry)::float AS latitude,
                ST_X(s.location::geometry)::float AS longitude,
                COALESCE(
                ARRAY_AGG(t.name ORDER BY t.name)
                FILTER (WHERE t.name IS NOT NULL),
                '{}'
                ) AS tags
            FROM historical_sites s
            LEFT JOIN historical_site_tags st ON st.site_id = s.id
            LEFT JOIN tags t ON t.id = st.tag_id
            WHERE s.id = $1
            GROUP BY s.id
            """
            row = await conn.fetchrow(sql, site_id)
            return dict(row) if row else None
        
    async def fetch_sites_by_ids_with_tags(self, site_ids: List[int]) -> List[Dict[str, Any]]:
        if not site_ids:
            return []
        sql = """
        SELECT
            s.id,
            s.user_id,
            s.title,
            COALESCE(s.description, '') AS description,
            s.image,
            COALESCE(s.likes, 0)   AS likes,
            COALESCE(s.dislikes, 0) AS dislikes,
            s.created_at,
            ST_Y(s.location::geometry)::float AS latitude,
            ST_X(s.location::geometry)::float AS longitude,
            COALESCE(
              ARRAY_AGG(t.name ORDER BY t.name)
              FILTER (WHERE t.name IS NOT NULL),
              '{}'
            ) AS tags
        FROM historical_sites s
        LEFT JOIN historical_site_tags st ON st.site_id = s.id
        LEFT JOIN tags t ON t.id = st.tag_id
        WHERE s.id = ANY($1::int[])
        GROUP BY s.id
        ORDER BY s.created_at DESC
        """
        rows = await self._fetch(sql, site_ids)
        # _fetch should return List[Record] (dict-like); if you don’t have it yet:
        #   async def _fetch(self, sql, *args): with self._conn() as c: return await c.fetch(sql, *args)
        return [dict(r) for r in rows]
    
    async def fetch_posts_by_ids(self, post_ids: List[int]) -> List[Dict[str, Any]]:
        if not post_ids:
            return []
        sql = """
        SELECT
            p.id,
            p.user_id,
            p.site_id,
            COALESCE(p.title, '')   AS title,
            COALESCE(p.content, '') AS content,
            p.image,
            COALESCE(p.likes, 0)    AS likes,
            COALESCE(p.dislikes, 0) AS dislikes,
            p.created_at
        FROM posts p
        WHERE p.id = ANY($1::int[])
        """
        rows = await self._fetch(sql, post_ids)
        return [dict(r) for r in rows]
    
    async def fetch_comments_by_ids(self, comment_ids: List[int]) -> List[Dict[str, Any]]:
        if not comment_ids:
            return []
        sql = """
        SELECT
            id,
            user_id,
            post_id,
            title,
            content,
            image,
            COALESCE(likes, 0)    AS likes,
            COALESCE(dislikes, 0) AS dislikes,
            created_at
        FROM comments
        WHERE id = ANY($1::int[])
        ORDER BY created_at DESC
        """
        rows = await self._fetch(sql, comment_ids)
        return [dict(r) for r in rows]

    async def fetch_user_by_email(self, email: str) -> Optional[Dict[str, Any]]:
        async with self._conn() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, email, created_at
                FROM users
                WHERE email = $1
                """,
                email,
            )
            return dict(row) if row else None
        
    async def fetch_site_location(self, site_id: int) -> Optional[Dict[str, Any]]:
        async with self._conn() as conn:
            row = await conn.fetchrow(
                """
                SELECT
                  ST_X(location::geometry) AS longitude,
                  ST_Y(location::geometry) AS latitude
                FROM historical_sites
                WHERE id = $1
                """,
                site_id,
            )
            return dict(row) if row else None

    async def fetch_sites_within_bounds(
        self,
        ne_lat: float,
        ne_lng: float,
        sw_lat: float,
        sw_lng: float,
        tags: Optional[List[str]] = None,  # NEW
    ) -> List[Dict[str, Any]]:
        tag_array = None
        if tags:
            tag_array = [t.strip().lower() for t in tags if t and t.strip()]

        async with self._conn() as conn:
            rows = await conn.fetch(
                """
                SELECT
                hs.id,
                hs.user_id,
                hs.title,
                hs.description,
                hs.image,
                hs.likes,
                hs.dislikes,
                hs.created_at,
                ST_Y(hs.location::geometry) AS latitude,
                ST_X(hs.location::geometry) AS longitude,
                COALESCE(
                    ARRAY_AGG(DISTINCT t2.name) FILTER (WHERE t2.name IS NOT NULL),
                    '{}'
                ) AS tags
                FROM historical_sites hs
                -- LEFT join only for aggregation of all tags for this site
                LEFT JOIN historical_site_tags hst2 ON hst2.site_id = hs.id
                LEFT JOIN tags t2 ON t2.id = hst2.tag_id
                WHERE
                ST_Within(
                    hs.location::geometry,
                    ST_MakeEnvelope(
                    $4,  -- minX = sw_lng
                    $3,  -- minY = sw_lat
                    $2,  -- maxX = ne_lng
                    $1,  -- maxY = ne_lat
                    4326
                    )
                )
                AND (
                    $5::text[] IS NULL
                    OR cardinality($5::text[]) = 0
                    OR EXISTS (
                    SELECT 1
                    FROM historical_site_tags hst
                    JOIN tags t ON t.id = hst.tag_id
                    WHERE hst.site_id = hs.id
                        AND t.name = ANY($5::text[])
                    )
                )
                GROUP BY
                hs.id, hs.user_id, hs.title, hs.description, hs.image,
                hs.likes, hs.dislikes, hs.created_at, hs.location
                LIMIT 1000
                """,
                ne_lat, ne_lng, sw_lat, sw_lng, tag_array,
            )
            # asyncpg returns PostgreSQL text[] as Python list[str] automatically
            return [dict(r) for r in rows]

    async def insert_historical_site(
        self,
        user_id: int,
        title: str,
        description: Optional[str],
        latitude: float,
        longitude: float,
        image: Optional[str] = None,          # was image_url
        tags: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        # normalize tags: trim/lower/dedupe
        norm_tags: List[str] = []
        if tags:
            seen = set()
            for t in (s.strip().lower() for s in tags if s and s.strip()):
                if t not in seen:
                    seen.add(t)
                    norm_tags.append(t)

        async with self._conn() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    INSERT INTO historical_sites (user_id, title, description, location, image, likes, dislikes)
                    VALUES ($1, $2, $3, ST_SetSRID(ST_MakePoint($4, $5), 4326), $6, 0, 0)
                    RETURNING
                        id,
                        user_id,
                        title,
                        description,
                        image,
                        likes,
                        dislikes,
                        created_at,
                        ST_Y(location::geometry)::float  AS latitude,
                        ST_X(location::geometry)::float  AS longitude;
                    """,
                    user_id,
                    title,
                    description,
                    longitude,
                    latitude,
                    image,          # <- key goes here
                )
                site = dict(row)
                site_id = site["id"]

                if norm_tags:
                    await conn.execute(
                        """
                        WITH norm AS (
                            SELECT DISTINCT t AS name FROM unnest($2::text[]) AS t
                        ),
                        ins AS (
                            INSERT INTO tags(name)
                            SELECT name FROM norm
                            ON CONFLICT (name) DO NOTHING
                            RETURNING id, name
                        ),
                        all_tags AS (
                            SELECT id, name FROM ins
                            UNION
                            SELECT tg.id, tg.name
                            FROM tags tg
                            JOIN norm n ON tg.name = n.name
                        )
                        INSERT INTO historical_site_tags (site_id, tag_id)
                        SELECT $1, id FROM all_tags
                        ON CONFLICT DO NOTHING;
                        """,
                        site_id,
                        norm_tags,
                    )
                    site["tags"] = norm_tags
                else:
                    site["tags"] = []

                return site

            
    async def increment_site_like(self, site_id: int) -> dict:
        sql = """
        UPDATE historical_sites
           SET likes = COALESCE(likes, 0) + 1
         WHERE id = $1
     RETURNING id, user_id, title, description, image,
               likes, dislikes, created_at, ST_Y(location::geometry)::float  AS latitude,
                    ST_X(location::geometry)::float  AS longitude;
        """
        row = await self._fetchrow(sql, site_id)   # implement _fetchrow using asyncpg
        if not row:
            raise ValueError(f"site not found: {site_id}")
        return dict(row)
    
    async def decrement_site_like(self, site_id: int) -> dict:
        sql = """
        UPDATE historical_sites
           SET likes = GREATEST(COALESCE(likes, 0) - 1, 0)
         WHERE id = $1
     RETURNING id, user_id, title, description, image,
               likes, dislikes, created_at, ST_Y(location::geometry)::float  AS latitude,
                    ST_X(location::geometry)::float  AS longitude;
        """
        row = await self._fetchrow(sql, site_id)   # implement _fetchrow using asyncpg
        if not row:
            raise ValueError(f"site not found: {site_id}")
        return dict(row)
                
    async def remove_site_tag_by_name(self, site_id: int, tag_name: str, user_id: int) -> dict | None:
        # normalize
        name = tag_name.strip().lower()
        if not name:
            return None

        async with self._conn() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    WITH tgt_site AS (
                    SELECT id
                    FROM historical_sites
                    WHERE id = $1 AND user_id = $2
                    FOR UPDATE
                    ),
                    tgt_tag AS (
                    SELECT id FROM tags WHERE name = $3
                    ),
                    del_link AS (
                    DELETE FROM historical_site_tags hst
                    USING tgt_site s, tgt_tag t
                    WHERE hst.site_id = s.id
                        AND hst.tag_id = t.id
                    RETURNING hst.tag_id
                    )
                    SELECT
                    hs.id,
                    hs.user_id,
                    hs.title,
                    hs.description,
                    hs.image,
                    hs.likes,
                    hs.dislikes,
                    hs.created_at,
                    ST_Y(hs.location::geometry) AS latitude,
                    ST_X(hs.location::geometry) AS longitude,
                    COALESCE(
                        ARRAY_AGG(DISTINCT tt.name) FILTER (WHERE tt.name IS NOT NULL),
                        '{}'
                    ) AS tags
                    FROM historical_sites hs
                    LEFT JOIN historical_site_tags hst2 ON hst2.site_id = hs.id
                    LEFT JOIN tags tt ON tt.id = hst2.tag_id
                    WHERE hs.id IN (SELECT id FROM tgt_site)
                    GROUP BY hs.id, hs.user_id, hs.title, hs.description, hs.image,
                            hs.likes, hs.dislikes, hs.created_at, hs.location;
                    """,
                    site_id, user_id, name,
                )
                return dict(row) if row else None

        
            
    async def add_site_tags(self, site_id: int, tags: List[str]) -> Dict[str, Any]:
    # normalize in Python: trim/lower/dedupe, drop empties
        norm = []
        seen = set()
        for t in (s.strip().lower() for s in tags if s and s.strip()):
            if t not in seen:
                seen.add(t)
                norm.append(t)

        async with self._conn() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    WITH norm AS (
                    SELECT DISTINCT t AS name
                    FROM unnest($2::text[]) AS t
                    ),
                    ins AS (
                    INSERT INTO tags (name)
                    SELECT name FROM norm
                    ON CONFLICT (name) DO NOTHING
                    RETURNING id, name
                    ),
                    all_tags AS (
                    -- union newly inserted + already existing
                    SELECT id, name FROM ins
                    UNION
                    SELECT tg.id, tg.name
                    FROM tags tg
                    JOIN norm n ON tg.name = n.name
                    ),
                    linked AS (
                    INSERT INTO historical_site_tags (site_id, tag_id)
                    SELECT $1, id FROM all_tags
                    ON CONFLICT DO NOTHING
                    RETURNING site_id
                    )
                    SELECT
                    hs.id,
                    hs.user_id,
                    hs.title,
                    hs.description,
                    hs.image,
                    hs.likes,
                    hs.dislikes,
                    hs.created_at,
                    ST_Y(hs.location::geometry) AS latitude,
                    ST_X(hs.location::geometry) AS longitude,
                    COALESCE(
                        ARRAY_AGG(DISTINCT t2.name) FILTER (WHERE t2.name IS NOT NULL),
                        '{}'
                    ) AS tags
                    FROM historical_sites hs
                    LEFT JOIN historical_site_tags hst2 ON hst2.site_id = hs.id
                    LEFT JOIN tags t2 ON t2.id = hst2.tag_id
                    WHERE hs.id = $1
                    GROUP BY hs.id, hs.user_id, hs.title, hs.description, hs.image,
                            hs.likes, hs.dislikes, hs.created_at, hs.location;
                    """,
                    site_id, norm
                )

            if row is None:
                # site_id doesn’t exist; FK would also catch this if you tried to insert,
                # but we return a cleaner error:
                raise ValueError(f"Site {site_id} not found")

            return dict(row)

    async def fetch_sites_by_user(self, user_id: int) -> list[dict]:
        async with self._conn() as conn:
            rows = await conn.fetch(
                """
                SELECT
                id, user_id, title, description, image, likes, dislikes, created_at,
                ST_Y(location::geometry) AS latitude,
                ST_X(location::geometry) AS longitude
                FROM historical_sites
                WHERE user_id = $1
                ORDER BY created_at DESC
                """,
                user_id,
            )
            return [dict(r) for r in rows]
        
        
    async def delete_site_tx(
        self,
        site_id: int,
        user_id: int,
        is_moderator: bool = False,
    ) -> dict:
        async with self._conn() as conn:
            async with conn.transaction():
                if is_moderator:
                    # Moderator: can delete any site by id
                    row = await conn.fetchrow(
                        """
                        WITH tgt_site AS (
                          SELECT hs.id, hs.image
                          FROM historical_sites hs
                          WHERE hs.id = $1
                          FOR UPDATE
                        ),
                        post_ids AS (
                          SELECT p.id
                          FROM posts p
                          JOIN tgt_site s ON p.site_id = s.id
                        ),
                        del_comments AS (
                          DELETE FROM comments c
                          USING post_ids p
                          WHERE c.post_id = p.id
                          RETURNING c.id
                        ),
                        del_posts AS (
                          DELETE FROM posts p
                          USING post_ids pid
                          WHERE p.id = pid.id
                          RETURNING p.id
                        ),
                        del_tags AS (
                          DELETE FROM historical_site_tags hst
                          USING tgt_site s
                          WHERE hst.site_id = s.id
                          RETURNING hst.site_id
                        ),
                        del_site AS (
                          DELETE FROM historical_sites hs
                          USING tgt_site s
                          WHERE hs.id = s.id
                          RETURNING hs.id, hs.image
                        )
                        SELECT
                          (SELECT COUNT(*) FROM del_comments) AS deleted_comments,
                          (SELECT COUNT(*) FROM del_posts)    AS deleted_posts,
                          (SELECT COALESCE(array_agg(id), '{}') FROM del_posts)    AS deleted_post_ids,
                          (SELECT COALESCE(array_agg(id), '{}') FROM del_comments) AS deleted_comment_ids,
                          (SELECT id    FROM del_site LIMIT 1) AS deleted_site_id,
                          (SELECT image FROM del_site LIMIT 1) AS site_image
                        ;
                        """,
                        site_id,
                    )
                else:
                    # Normal user: must own the site
                    row = await conn.fetchrow(
                        """
                        WITH tgt_site AS (
                          SELECT hs.id, hs.image
                          FROM historical_sites hs
                          WHERE hs.id = $1 AND hs.user_id = $2
                          FOR UPDATE
                        ),
                        post_ids AS (
                          SELECT p.id
                          FROM posts p
                          JOIN tgt_site s ON p.site_id = s.id
                        ),
                        del_comments AS (
                          DELETE FROM comments c
                          USING post_ids p
                          WHERE c.post_id = p.id
                          RETURNING c.id
                        ),
                        del_posts AS (
                          DELETE FROM posts p
                          USING post_ids pid
                          WHERE p.id = pid.id
                          RETURNING p.id
                        ),
                        del_tags AS (
                          DELETE FROM historical_site_tags hst
                          USING tgt_site s
                          WHERE hst.site_id = s.id
                          RETURNING hst.site_id
                        ),
                        del_site AS (
                          DELETE FROM historical_sites hs
                          USING tgt_site s
                          WHERE hs.id = s.id
                          RETURNING hs.id, hs.image
                        )
                        SELECT
                          (SELECT COUNT(*) FROM del_comments) AS deleted_comments,
                          (SELECT COUNT(*) FROM del_posts)    AS deleted_posts,
                          (SELECT COALESCE(array_agg(id), '{}') FROM del_posts)    AS deleted_post_ids,
                          (SELECT COALESCE(array_agg(id), '{}') FROM del_comments) AS deleted_comment_ids,
                          (SELECT id    FROM del_site LIMIT 1) AS deleted_site_id,
                          (SELECT image FROM del_site LIMIT 1) AS site_image
                        ;
                        """,
                        site_id,
                        user_id,
                    )

            if not row or row["deleted_site_id"] is None:
                return {"success": False, "code": "NOT_FOUND_OR_FORBIDDEN"}

            return {
                "success": True,
                "code": "OK",
                "deletedSiteId": row["deleted_site_id"],
                "deletedPosts": int(row["deleted_posts"] or 0),
                "deletedComments": int(row["deleted_comments"] or 0),
                "deletedPostIds": list(row["deleted_post_ids"] or []),
                "deletedCommentIds": list(row["deleted_comment_ids"] or []),
            }
    # ---------- Posts & Comments ----------


    async def delete_post_tx(self, post_id: int, user_id: int) -> dict:
        async with self._conn() as conn:
            async with conn.transaction():
                owned = await conn.fetchval(
                    "SELECT 1 FROM posts WHERE id=$1 AND user_id=$2 FOR UPDATE",
                    post_id, user_id
                )
                if not owned:
                    return {"success": False, "code": "NOT_FOUND_OR_FORBIDDEN"}

                # Delete comments and collect their IDs
                deleted_comments_rows = await conn.fetch(
                    "DELETE FROM comments WHERE post_id=$1 RETURNING id", post_id
                )
                deleted_comment_ids = [r["id"] for r in deleted_comments_rows]

                # Delete the post
                deleted_post = await conn.fetchrow(
                    "DELETE FROM posts WHERE id=$1 RETURNING id", post_id
                )
                if not deleted_post:
                    return {"success": False, "code": "UNKNOWN_ERROR"}

                return {
                    "success": True,
                    "code": "OK",
                    "deletedPostId": deleted_post["id"],
                    "deletedComments": len(deleted_comment_ids),
                    "deletedCommentIds": deleted_comment_ids,   # <-- new
                }


    async def fetch_posts_by_site(self, site_id: int) -> List[Dict[str, Any]]:
        async with self._conn() as conn:
            rows = await conn.fetch(
                "SELECT * FROM posts WHERE site_id = $1",
                site_id,
            )
            return [dict(r) for r in rows]

    async def fetch_post(self, post_id: int) -> Optional[Dict[str, Any]]:
        async with self._conn() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM posts WHERE id = $1",
                post_id,
            )
            return dict(row) if row else None
        
        
    async def delete_comment(self, comment_id: int, user_id: int) -> bool:
        async with self._conn() as conn:
            row = await conn.fetchrow(
                """
                DELETE FROM comments
                WHERE id = $1 AND user_id = $2
                RETURNING id
                """,
                comment_id, user_id,
            )
            return row is not None
        
    async def fetch_comments_by_post(self, post_id: int) -> list[dict]:
        async with self._conn() as conn:
            rows = await conn.fetch(
                """
                SELECT
                id,
                post_id,
                user_id,
                title,
                content,
                image,
                likes,
                dislikes,
                created_at
                FROM comments
                WHERE post_id = $1
                ORDER BY created_at DESC
                """,
                post_id,
            )
            return [dict(r) for r in rows]

    async def insert_post(
        self,
        user_id: int,
        title: str,
        content: str,
        site_id: int,
        image: Optional[str],           # was image_url
    ) -> Dict[str, Any]:
        sql = """
        INSERT INTO posts (user_id, title, content, site_id, image, likes, dislikes)
        VALUES ($1, $2, $3, $4, $5, 0, 0)
        RETURNING
            id,
            user_id,
            site_id,
            title,
            content,
            image,
            likes,
            dislikes,
            created_at
        ;
        """
        async with self._conn() as conn:
            row = await conn.fetchrow(sql, user_id, title, content, site_id, image)
        return dict(row)


    async def insert_comment(
        self,
        user_id: int,
        post_id: int,
        title: str,
        content: str,
        image: Optional[str],           # was image_url
    ) -> Dict[str, Any]:
        sql = """
        INSERT INTO comments (user_id, post_id, title, content, image, likes, dislikes)
        VALUES ($1, $2, $3, $4, $5, 0, 0)
        RETURNING
            id,
            user_id,
            post_id,
            title,
            content,
            image,
            likes,
            dislikes,
            created_at
        ;
        """
        async with self._conn() as conn:
            row = await conn.fetchrow(sql, user_id, post_id, title, content, image)
        return dict(row)

    async def update_post_image(self, post_id: int, image_url: Optional[str]) -> None:
        async with self._conn() as conn:
            await conn.execute(
                "UPDATE posts SET image = $1 WHERE id = $2",
                image_url, post_id,
            )

    async def fetch_comments_by_post(self, post_id: int) -> List[Dict[str, Any]]:
        async with self._conn() as conn:
            rows = await conn.fetch(
                "SELECT * FROM comments WHERE post_id = $1",
                post_id,
            )
            return [dict(r) for r in rows]

    async def fetch_user_by_post(self, post_id: int) -> Optional[Dict[str, Any]]:
        async with self._conn() as conn:
            row = await conn.fetchrow(
                """
                SELECT u.*
                FROM users u
                JOIN posts p ON p.user_id = u.id
                WHERE p.id = $1
                """,
                post_id,
            )
            return dict(row) if row else None
        
    async def fetch_posts_by_user(self, user_id: int) -> list[dict]:
        async with self._conn() as conn:
            rows = await conn.fetch(
                """
                SELECT
                id, user_id, site_id, title, content, image, likes, dislikes, created_at
                FROM posts
                WHERE user_id = $1
                ORDER BY created_at DESC
                """,
                user_id,
            )
            return [dict(r) for r in rows]

    # ---------- Users ----------

    async def fetch_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Return only fields your GraphQL type exposes to avoid KeyErrors."""
        async with self._conn() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, name, email, created_at
                FROM users
                WHERE id = $1
                """,
                user_id,
            )
            return dict(row) if row else None

    async def create_user(self, name: str, email: str) -> Dict[str, Any]:
        async with self._conn() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO users (name, email)
                VALUES ($1, $2)
                RETURNING id, name, email, created_at
                """,
                name, email,
            )
            return dict(row)

    async def fetch_post(self, post_id: int) -> dict:
        sql = """
        SELECT id, user_id, site_id, title, content, image,
               COALESCE(likes, 0)     AS likes,
               COALESCE(dislikes, 0)  AS dislikes,
               created_at
          FROM posts
         WHERE id = $1
        """
        row = await self._fetchrow(sql, post_id)
        if not row:
            raise ValueError(f"post not found: {post_id}")
        return dict(row)

    async def increment_post_like(self, post_id: int) -> dict:
        sql = """
        UPDATE posts
           SET likes = COALESCE(likes, 0) + 1
         WHERE id = $1
     RETURNING id, user_id, site_id, title, content, image,
               COALESCE(likes, 0)     AS likes,
               COALESCE(dislikes, 0)  AS dislikes,
               created_at
        """
        row = await self._fetchrow(sql, post_id)
        if not row:
            raise ValueError(f"post not found: {post_id}")
        return dict(row)

    async def decrement_post_like(self, post_id: int) -> dict:
        sql = """
        UPDATE posts
           SET likes = GREATEST(COALESCE(likes, 0) - 1, 0)
         WHERE id = $1
     RETURNING id, user_id, site_id, title, content, image,
               COALESCE(likes, 0)     AS likes,
               COALESCE(dislikes, 0)  AS dislikes,
               created_at
        """
        row = await self._fetchrow(sql, post_id)
        if not row:
            raise ValueError(f"post not found: {post_id}")
        return dict(row)
    
    async def fetch_all_users_light(self, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        sql = """
        SELECT id AS "pgId",
            email,
            name,
            created_at AS "createdAt"
        FROM users
        ORDER BY id
        """
        if limit is not None:
            sql += " LIMIT $1 OFFSET $2"
            rows = await self._fetch(sql, limit, offset)
        else:
            rows = await self._fetch(sql)

        # profile_pic_url not in schema; set None to satisfy upsert_users shape
        return [
            {
                "pgId": r["pgId"],
                "email": r["email"],
                "name": r["name"],
                "profile_pic_url": None,
                "createdAt": r["createdAt"],
            }
            for r in rows
        ]


# ---------- SITES ----------
    async def fetch_all_sites_light(self, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        sql = """
        SELECT
        hs.id                               AS "pgId",
        hs.title                            AS title,
        hs.description                      AS description,
        hs.image                            AS image_key,
        ST_Y(hs.location::geometry)::float  AS latitude,
        ST_X(hs.location::geometry)::float  AS longitude,
        hs.created_at                       AS "createdAt"
        FROM historical_sites hs
        ORDER BY hs.id
        """
        if limit is not None:
            sql += " LIMIT $1 OFFSET $2"
            rows = await self._fetch(sql, limit, offset)
        else:
            rows = await self._fetch(sql)
        return [dict(r) for r in rows]


    # ---------- POSTS ----------
    async def fetch_all_posts_light(self, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        sql = """
        SELECT
        p.id          AS "pgId",
        p.title       AS title,
        p.content     AS content,
        p.image       AS image,
        COALESCE(p.likes, 0)    AS likes,
        COALESCE(p.dislikes, 0) AS dislikes,
        p.created_at  AS "createdAt",
        p.user_id     AS "userPgId",
        p.site_id     AS "sitePgId"
        FROM posts p
        ORDER BY p.id
        """
        if limit is not None:
            sql += " LIMIT $1 OFFSET $2"
            rows = await self._fetch(sql, limit, offset)
        else:
            rows = await self._fetch(sql)

        return [dict(r) for r in rows]


    # ---------- COMMENTS ----------
    async def fetch_all_comments_light(self, *, limit: int | None = None, offset: int = 0) -> list[dict]:
        sql = """
        SELECT
        c.id          AS "pgId",
        c.title       AS title,
        c.content     AS content,
        c.image       AS image,
        COALESCE(c.likes, 0)    AS likes,
        COALESCE(c.dislikes, 0) AS dislikes,
        c.created_at  AS "createdAt",
        c.user_id     AS "userPgId",
        c.post_id     AS "postPgId"
        FROM comments c
        ORDER BY c.id
        """
        if limit is not None:
            sql += " LIMIT $1 OFFSET $2"
            rows = await self._fetch(sql, limit, offset)
        else:
            rows = await self._fetch(sql)

        return [dict(r) for r in rows]
    
    
    async def fetch_comment(self, comment_id: int) -> dict:
        sql = """
        SELECT id, user_id, post_id, title, content, image,
               COALESCE(likes, 0)    AS likes,
               COALESCE(dislikes, 0) AS dislikes,
               created_at
          FROM comments
         WHERE id = $1
        """
        row = await self._fetchrow(sql, comment_id)
        if not row:
            raise ValueError(f"comment not found: {comment_id}")
        return dict(row)

    async def increment_comment_like(self, comment_id: int) -> dict:
        sql = """
        UPDATE comments
           SET likes = COALESCE(likes, 0) + 1
         WHERE id = $1
     RETURNING id, user_id, post_id, title, content, image,
               COALESCE(likes, 0)    AS likes,
               COALESCE(dislikes, 0) AS dislikes,
               created_at
        """
        row = await self._fetchrow(sql, comment_id)
        if not row:
            raise ValueError(f"comment not found: {comment_id}")
        return dict(row)

    async def decrement_comment_like(self, comment_id: int) -> dict:
        sql = """
        UPDATE comments
           SET likes = GREATEST(COALESCE(likes, 0) - 1, 0)
         WHERE id = $1
     RETURNING id, user_id, post_id, title, content, image,
               COALESCE(likes, 0)    AS likes,
               COALESCE(dislikes, 0) AS dislikes,
               created_at
        """
        row = await self._fetchrow(sql, comment_id)
        if not row:
            raise ValueError(f"comment not found: {comment_id}")
        return dict(row)
    
    async def increment_site_dislike(self, site_id: int) -> dict:
        sql = """
        UPDATE historical_sites
        SET dislikes = COALESCE(dislikes, 0) + 1
        WHERE id = $1
    RETURNING id, user_id, title, description, image,
            likes, dislikes, created_at,
            ST_Y(location::geometry)::float  AS latitude,
            ST_X(location::geometry)::float  AS longitude;
        """
        row = await self._fetchrow(sql, site_id)
        if not row:
            raise ValueError(f"site not found: {site_id}")
        return dict(row)

    async def decrement_site_dislike(self, site_id: int) -> dict:
        sql = """
        UPDATE historical_sites
        SET dislikes = GREATEST(COALESCE(dislikes, 0) - 1, 0)
        WHERE id = $1
    RETURNING id, user_id, title, description, image,
            likes, dislikes, created_at,
            ST_Y(location::geometry)::float  AS latitude,
            ST_X(location::geometry)::float  AS longitude;
        """
        row = await self._fetchrow(sql, site_id)
        if not row:
            raise ValueError(f"site not found: {site_id}")
        return dict(row)
    
    
    async def increment_post_dislike(self, post_id: int) -> dict:
        sql = """
        UPDATE posts
        SET dislikes = COALESCE(dislikes, 0) + 1
        WHERE id = $1
    RETURNING id, user_id, site_id, title, content, image,
            COALESCE(likes, 0) AS likes,
            COALESCE(dislikes, 0) AS dislikes,
            created_at;
        """
        row = await self._fetchrow(sql, post_id)
        if not row:
            raise ValueError(f"post not found: {post_id}")
        return dict(row)

    async def decrement_post_dislike(self, post_id: int) -> dict:
        sql = """
        UPDATE posts
        SET dislikes = GREATEST(COALESCE(dislikes, 0) - 1, 0)
        WHERE id = $1
    RETURNING id, user_id, site_id, title, content, image,
            COALESCE(likes, 0) AS likes,
            COALESCE(dislikes, 0) AS dislikes,
            created_at;
        """
        row = await self._fetchrow(sql, post_id)
        if not row:
            raise ValueError(f"post not found: {post_id}")
        return dict(row)
    
    
    async def increment_comment_dislike(self, comment_id: int) -> dict:
        sql = """
        UPDATE comments
           SET dislikes = COALESCE(dislikes, 0) + 1
         WHERE id = $1
     RETURNING id, user_id, post_id, title, content, image,
               COALESCE(likes, 0)    AS likes,
               COALESCE(dislikes, 0) AS dislikes,
               created_at;
        """
        row = await self._fetchrow(sql, comment_id)
        if not row:
            raise ValueError(f"comment not found: {comment_id}")
        return dict(row)

    async def decrement_comment_dislike(self, comment_id: int) -> dict:
        sql = """
        UPDATE comments
           SET dislikes = GREATEST(COALESCE(dislikes, 0) - 1, 0)
         WHERE id = $1
     RETURNING id, user_id, post_id, title, content, image,
               COALESCE(likes, 0)    AS likes,
               COALESCE(dislikes, 0) AS dislikes,
               created_at;
        """
        row = await self._fetchrow(sql, comment_id)
        if not row:
            raise ValueError(f"comment not found: {comment_id}")
        return dict(row)

    async def fetch_comment(self, comment_id: int) -> dict:
        sql = """
        SELECT id, user_id, post_id, title, content, image,
               COALESCE(likes, 0)    AS likes,
               COALESCE(dislikes, 0) AS dislikes,
               created_at
          FROM comments
         WHERE id = $1
        """
        row = await self._fetchrow(sql, comment_id)
        if not row:
            raise ValueError(f"comment not found: {comment_id}")
        return dict(row)
    
    
    async def migrate_add_reports_and_user_tags(self) -> None:
        """
        One-time, idempotent migration:
          - Add `reports INT NOT NULL DEFAULT 0` to posts, historical_sites, comments
          - Create user_tags(user_id, tag_id) with FK -> users/tags and composite PK
        Safe to run multiple times.
        """
        sql = """
        DO $$
        BEGIN
          -- posts.reports
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'posts' AND column_name = 'reports'
          ) THEN
            ALTER TABLE public.posts ADD COLUMN reports INTEGER NOT NULL DEFAULT 0;
          ELSE
            ALTER TABLE public.posts ALTER COLUMN reports SET DEFAULT 0;
            UPDATE public.posts SET reports = 0 WHERE reports IS NULL;
            ALTER TABLE public.posts ALTER COLUMN reports SET NOT NULL;
          END IF;

          -- historical_sites.reports
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'historical_sites' AND column_name = 'reports'
          ) THEN
            ALTER TABLE public.historical_sites ADD COLUMN reports INTEGER NOT NULL DEFAULT 0;
          ELSE
            ALTER TABLE public.historical_sites ALTER COLUMN reports SET DEFAULT 0;
            UPDATE public.historical_sites SET reports = 0 WHERE reports IS NULL;
            ALTER TABLE public.historical_sites ALTER COLUMN reports SET NOT NULL;
          END IF;

          -- comments.reports
          IF NOT EXISTS (
            SELECT 1 FROM information_schema.columns
            WHERE table_schema = 'public' AND table_name = 'comments' AND column_name = 'reports'
          ) THEN
            ALTER TABLE public.comments ADD COLUMN reports INTEGER NOT NULL DEFAULT 0;
          ELSE
            ALTER TABLE public.comments ALTER COLUMN reports SET DEFAULT 0;
            UPDATE public.comments SET reports = 0 WHERE reports IS NULL;
            ALTER TABLE public.comments ALTER COLUMN reports SET NOT NULL;
          END IF;
        END
        $$;

        -- user_tags M:N table for user preferences
        CREATE TABLE IF NOT EXISTS public.user_tags (
          user_id INTEGER NOT NULL REFERENCES public.users(id) ON DELETE CASCADE,
          tag_id  INTEGER NOT NULL REFERENCES public.tags(id)  ON DELETE CASCADE,
          created_at TIMESTAMP DEFAULT NOW(),
          PRIMARY KEY (user_id, tag_id)
        );

        -- Helpful index for reverse lookups (find users by tag quickly)
        CREATE INDEX IF NOT EXISTS idx_user_tags_tag_id ON public.user_tags(tag_id);
        """
        async with self._conn() as conn:
            await conn.execute(sql)
            
            
            
    async def add_user_tags(self, user_id: int, tags: List[str]) -> Dict[str, Any]:
        """
        Upsert tag names into `tags`, link them in `user_tags(user_id, tag_id)`,
        and return the user's tag list.
        """
        async with self._conn() as conn:
            async with conn.transaction():
                row = await conn.fetchrow(
                    """
                    WITH norm AS (
                      SELECT DISTINCT lower(trim(t)) AS name
                      FROM unnest($2::text[]) AS t
                      WHERE t IS NOT NULL AND length(trim(t)) > 0
                    ),
                    ins_tags AS (
                      INSERT INTO tags (name)
                      SELECT name FROM norm
                      ON CONFLICT (name) DO NOTHING
                      RETURNING id, name
                    ),
                    all_tags AS (
                      SELECT id, name FROM ins_tags
                      UNION
                      SELECT tg.id, tg.name
                      FROM tags tg
                      JOIN norm n ON n.name = tg.name
                    ),
                    link AS (
                      INSERT INTO user_tags (user_id, tag_id)
                      SELECT $1, id FROM all_tags
                      ON CONFLICT DO NOTHING
                      RETURNING user_id
                    )
                    SELECT
                      $1::int AS user_id,
                      COALESCE(
                        ARRAY_AGG(DISTINCT t2.name ORDER BY t2.name)
                        FILTER (WHERE t2.name IS NOT NULL),
                        '{}'
                      ) AS tags
                    FROM user_tags ut
                    LEFT JOIN tags t2 ON t2.id = ut.tag_id
                    WHERE ut.user_id = $1
                    """,
                    user_id, tags
                )

        if row is None:
            # Shouldn't happen if user exists; return empty as a safe fallback
            return {"user_id": user_id, "tags": []}
        return {"user_id": int(row["user_id"]), "tags": list(row["tags"])}
    
    async def fetch_user_tags(self, user_id: int) -> List[str]:
        """
        Get the current tag list for a user.
        """
        async with self._conn() as conn:
            rows = await conn.fetch(
                """
                SELECT t.name
                FROM user_tags ut
                JOIN tags t ON t.id = ut.tag_id
                WHERE ut.user_id = $1
                ORDER BY t.name
                """,
                user_id
            )
        return [r["name"] for r in rows]
    
    async def increment_site_report(self, site_id: int) -> dict:
        sql = """
        UPDATE historical_sites
           SET reports = COALESCE(reports, 0) + 1
         WHERE id = $1
     RETURNING id, user_id, title, description, image,
               COALESCE(likes,0) AS likes,
               COALESCE(dislikes,0) AS dislikes,
               COALESCE(reports,0) AS reports,
               created_at,
               ST_Y(location::geometry)::float  AS latitude,
               ST_X(location::geometry)::float  AS longitude
        """
        row = await self._fetchrow(sql, site_id)
        if not row:
            raise ValueError(f"site not found: {site_id}")
        return dict(row)
    
    async def increment_post_report(self, post_id: int) -> dict:
        sql = """
        UPDATE posts
        SET reports = COALESCE(reports, 0) + 1
        WHERE id = $1
    RETURNING id, user_id, site_id, title, content, image,
            likes, dislikes, created_at;
        """
        row = await self._fetchrow(sql, post_id)
        if not row:
            raise ValueError(f"post not found: {post_id}")
        return dict(row)
    
    
    async def increment_comment_report(self, comment_id: int) -> dict:
        sql = """
        UPDATE comments
        SET reports = COALESCE(reports, 0) + 1
        WHERE id = $1
    RETURNING id, user_id, post_id, title, content, image,
            likes, dislikes, created_at;
        """
        row = await self._fetchrow(sql, comment_id)
        if not row:
            raise ValueError(f"comment not found: {comment_id}")
        return dict(row)
    
    async def set_site_image(
        self,
        site_id: int,
        image: str,
    ) -> Dict[str, Any]:
        """
        Update the image key for a historical site and return the updated site row.
        """
        sql = """
        UPDATE historical_sites
        SET image = $2
        WHERE id = $1
        RETURNING
            id,
            user_id,
            title,
            description,
            image,
            likes,
            dislikes,
            created_at,
            ST_Y(location::geometry)::float AS latitude,
            ST_X(location::geometry)::float AS longitude
        ;
        """
        async with self._conn() as conn:
            row = await conn.fetchrow(sql, site_id, image)
        if row is None:
            raise ValueError(f"historical_sites: no site with id={site_id}")
        site = dict(row)
        # NOTE: this does not fetch tags; those are managed via historical_site_tags
        return site
    
    async def set_post_image(
        self,
        post_id: int,
        image: str,
    ) -> Dict[str, Any]:
        """
        Update the image key for a post and return the updated post row.
        """
        sql = """
        UPDATE posts
        SET image = $2
        WHERE id = $1
        RETURNING
            id,
            user_id,
            site_id,
            title,
            content,
            image,
            likes,
            dislikes,
            created_at
        ;
        """
        async with self._conn() as conn:
            row = await conn.fetchrow(sql, post_id, image)

        if row is None:
            raise ValueError(f"posts: no post with id={post_id}")

        return dict(row)
    
    
    async def set_comment_image(
        self,
        comment_id: int,
        image: str,
    ) -> Dict[str, Any]:
        """
        Update the image key for a comment and return the updated comment row.
        """
        sql = """
        UPDATE comments
        SET image = $2
        WHERE id = $1
        RETURNING
            id,
            user_id,
            post_id,
            title,
            content,
            image,
            likes,
            dislikes,
            created_at
        ;
        """
        async with self._conn() as conn:
            row = await conn.fetchrow(sql, comment_id, image)

        if row is None:
            raise ValueError(f"comments: no comment with id={comment_id}")

        return dict(row)
    
    async def delete_comment_by_id(self, comment_id: int) -> bool:
        sql = "DELETE FROM comments WHERE id = $1"
        async with self._conn() as conn:
            res = await conn.execute(sql, comment_id)
        return res.endswith("1")
    
    
    async def fetch_popular_sites_near(
        self,
        latitude: float,
        longitude: float,
        radius_meters: float,
        limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Return up to `limit` sites within `radius_meters` of (latitude, longitude),
        ordered by likes (desc), then created_at (desc),
        including tags + lat/lng derived from PostGIS location.
        """
        sql = """
        SELECT
            s.id,
            s.user_id,
            s.title,
            COALESCE(s.description, '') AS description,
            s.image,
            COALESCE(s.likes, 0)    AS likes,
            COALESCE(s.dislikes, 0) AS dislikes,
            s.created_at,
            ST_Y(s.location::geometry)::float AS latitude,
            ST_X(s.location::geometry)::float AS longitude,
            COALESCE(
              ARRAY_AGG(t.name ORDER BY t.name)
              FILTER (WHERE t.name IS NOT NULL),
              '{}'
            ) AS tags
        FROM historical_sites s
        LEFT JOIN historical_site_tags st ON st.site_id = s.id
        LEFT JOIN tags t ON t.id = st.tag_id
        WHERE ST_DWithin(
            s.location::geography,
            ST_SetSRID(ST_MakePoint($2, $1), 4326)::geography,  -- ($2 = lon, $1 = lat)
            $3
        )
        GROUP BY s.id
        ORDER BY COALESCE(s.likes, 0) DESC, s.created_at DESC
        LIMIT $4
        ;
        """
        # NOTE: PostGIS ST_MakePoint(lon, lat), so we pass longitude as $2, latitude as $1
        rows = await self._fetch(sql, latitude, longitude, radius_meters, limit)
        return [dict(r) for r in rows]
    
    
    async def fetch_users_by_ids_light(self, user_ids: List[int]) -> List[Dict[str, Any]]:
        """
        Fetch basic user info for a set of user IDs.
        Shape matches the User type: id, name, email, created_at, profile_pic_url.
        """
        if not user_ids:
            return []

        sql = """
        SELECT
            id,
            name,
            email,
            created_at,
            profile_pic_url
        FROM users
        WHERE id = ANY($1::int[])
        """
        rows = await self._fetch(sql, user_ids)
        return [dict(r) for r in rows]