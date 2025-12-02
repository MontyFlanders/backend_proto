# app/services/neo4j_adapter.py
import os
from typing import Any, Dict, List, Optional
from neo4j import AsyncGraphDatabase, AsyncDriver
import asyncio, logging
from neo4j.exceptions import ServiceUnavailable


log = logging.getLogger("neo4j")


class Neo4jAdapter:
    def __init__(self) -> None:
        uri = os.getenv("NEO4J_URI")
        if not uri:
            raise RuntimeError("NEO4J_URI is required, e.g. bolt://neo4j.local:7687")

        user = os.getenv("NEO4J_USER", "neo4j")
        password = os.getenv("NEO4J_PASSWORD")
        if not password:
            auth = os.getenv("NEO4J_AUTH")
            if not auth or "/" not in auth:
                raise RuntimeError("Provide NEO4J_PASSWORD or NEO4J_AUTH='neo4j/<password>'")
            _, password = auth.split("/", 1)

        self._driver: AsyncDriver = AsyncGraphDatabase.driver(uri, auth=(user, password))

    async def close(self) -> None:
        await self._driver.close()
        
        
    async def upsert_users(self, users: list[dict]) -> dict:
        """
        Each user dict should include:
        { "pgId": int|str, "email": str|None, "name": str|None, "profile_pic_url": str|None }
        """
        cypher = """
        UNWIND $users AS u
        MERGE (x:User {pgId: u.pgId})
        ON CREATE SET
        x.email           = u.email,
        x.name            = u.name,
        x.profile_pic_url = u.profile_pic_url,
        x.createdAt       = datetime()
        ON MATCH SET
        x.email           = coalesce(u.email, x.email),
        x.name            = coalesce(u.name, x.name),
        x.profile_pic_url = coalesce(u.profile_pic_url, x.profile_pic_url),
        x.updatedAt       = datetime()
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, users=users)
            summary = await result.consume()

        c = summary.counters
        return {
            "contains_updates": getattr(c, "contains_updates", None),
            "nodes_created": c.nodes_created,
            "nodes_deleted": c.nodes_deleted,
            "properties_set": c.properties_set,
            "labels_added": c.labels_added,
            "labels_removed": c.labels_removed,
            "relationships_created": c.relationships_created,
            "relationships_deleted": c.relationships_deleted,
        }

    async def upsert_posts(self, posts: list[dict]) -> dict:
        """
        Each post dict may include:
        {
        "pgId": int|str,                # REQUIRED
        "title": str|None,
        "content": str|None,
        "image": str|None,
        "likes": int|None,
        "dislikes": int|None,
        "createdAt": str|datetime|None, # optional; defaults to datetime() on create
        "userPgId": int|str|None,       # optional relationship: (User)-[:AUTHORED]->(Post)
        "sitePgId": int|str|None        # optional relationship: (Post)-[:ON_SITE]->(Site)
        }
        """
        cypher = """
        UNWIND $posts AS p
        MERGE (x:Post {pgId: p.pgId})
        ON CREATE SET
        x.title     = p.title,
        x.content   = p.content,
        x.image     = p.image,
        x.likes     = coalesce(p.likes, 0),
        x.dislikes  = coalesce(p.dislikes, 0),
        x.createdAt = coalesce(p.createdAt, datetime())
        ON MATCH SET
        x.title     = coalesce(p.title, x.title),
        x.content   = coalesce(p.content, x.content),
        x.image     = coalesce(p.image, x.image),
        x.likes     = coalesce(p.likes, x.likes),
        x.dislikes  = coalesce(p.dislikes, x.dislikes),
        x.updatedAt = datetime()

        // Optional author link
        FOREACH (uid IN CASE WHEN p.userPgId IS NULL THEN [] ELSE [p.userPgId] END |
        MERGE (u:User {pgId: uid})
        MERGE (u)-[:AUTHORED]->(x)
        )

        // Optional site link
        FOREACH (sid IN CASE WHEN p.sitePgId IS NULL THEN [] ELSE [p.sitePgId] END |
        MERGE (s:Site {pgId: sid})
        MERGE (x)-[:ON_SITE]->(s)
        )
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, posts=posts)
            summary = await result.consume()

        c = summary.counters
        return {
            "contains_updates": getattr(c, "contains_updates", None),
            "nodes_created": c.nodes_created,
            "nodes_deleted": c.nodes_deleted,
            "properties_set": c.properties_set,
            "labels_added": c.labels_added,
            "labels_removed": c.labels_removed,
            "relationships_created": c.relationships_created,
            "relationships_deleted": c.relationships_deleted,
        }


    async def upsert_comments(self, comments: list[dict]) -> dict:
        """
        Each comment dict may include:
        {
        "pgId": int|str,                # REQUIRED
        "title": str|None,
        "content": str|None,
        "image": str|None,
        "likes": int|None,
        "dislikes": int|None,
        "createdAt": str|datetime|None, # optional; defaults to datetime() on create
        "userPgId": int|str|None,       # optional relationship: (User)-[:COMMENTED]->(Comment)
        "postPgId": int|str|None        # optional relationship: (Comment)-[:ON_POST]->(Post)
        }
        """
        cypher = """
        UNWIND $comments AS cmt
        MERGE (x:Comment {pgId: cmt.pgId})
        ON CREATE SET
        x.title     = cmt.title,
        x.content   = cmt.content,
        x.image     = cmt.image,
        x.likes     = coalesce(cmt.likes, 0),
        x.dislikes  = coalesce(cmt.dislikes, 0),
        x.createdAt = coalesce(cmt.createdAt, datetime())
        ON MATCH SET
        x.title     = coalesce(cmt.title, x.title),
        x.content   = coalesce(cmt.content, x.content),
        x.image     = coalesce(cmt.image, x.image),
        x.likes     = coalesce(cmt.likes, x.likes),
        x.dislikes  = coalesce(cmt.dislikes, x.dislikes),
        x.updatedAt = datetime()

        // Optional commenter link
        FOREACH (uid IN CASE WHEN cmt.userPgId IS NULL THEN [] ELSE [cmt.userPgId] END |
        MERGE (u:User {pgId: uid})
        MERGE (u)-[:COMMENTED]->(x)
        )

        // Optional post link
        FOREACH (pid IN CASE WHEN cmt.postPgId IS NULL THEN [] ELSE [cmt.postPgId] END |
        MERGE (p:Post {pgId: pid})
        MERGE (x)-[:ON_POST]->(p)
        )
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, comments=comments)
            summary = await result.consume()

        c = summary.counters
        return {
            "contains_updates": getattr(c, "contains_updates", None),
            "nodes_created": c.nodes_created,
            "nodes_deleted": c.nodes_deleted,
            "properties_set": c.properties_set,
            "labels_added": c.labels_added,
            "labels_removed": c.labels_removed,
            "relationships_created": c.relationships_created,
            "relationships_deleted": c.relationships_deleted,
        }

    async def upsert_sites(self, sites: list[dict]) -> dict:
            """
            Each site dict should look like:
            {
                "pgId": <int|str>,   # REQUIRED (matches unique constraint)
                "title": str|None,
                "description": str|None,
                "image_key": str|None,      # or image_url if you prefer
                "latitude": float|None,
                "longitude": float|None,
                "created_at": datetime|str|None,
            }
            """
            cypher = """
            UNWIND $sites AS s
            MERGE (n:Site {pgId: s.pgId})

            ON CREATE SET
            n.title       = s.title,
            n.description = s.description,
            n.image_key   = s.image_key,
            n.latitude    = s.latitude,
            n.longitude   = s.longitude,
            n.location    = CASE
                                WHEN s.latitude IS NOT NULL AND s.longitude IS NOT NULL
                                THEN point({latitude: s.latitude, longitude: s.longitude})
                                ELSE NULL
                            END,
            n.createdAt   = coalesce(s.created_at, datetime())

            ON MATCH SET
            n.title       = coalesce(s.title, n.title),
            n.description = coalesce(s.description, n.description),
            n.image_key   = coalesce(s.image_key, n.image_key),
            n.latitude    = coalesce(s.latitude, n.latitude),
            n.longitude   = coalesce(s.longitude, n.longitude),
            n.location    = CASE
                                WHEN s.latitude IS NOT NULL AND s.longitude IS NOT NULL
                                THEN point({latitude: s.latitude, longitude: s.longitude})
                                ELSE n.location
                            END,
            n.updatedAt   = datetime()

            // Optional tag attachments (no-op if s.tags is null)
            FOREACH (t IN coalesce(s.tags, []) |
            MERGE (tg:Tag {name: toLower(t)})
            MERGE (n)-[:HAS_TAG]->(tg)
            )
            """
            async with self._driver.session() as sess:
                res = await sess.run(cypher, sites=sites)
                summary = await res.consume()

            c = summary.counters
            return {
                "contains_updates": getattr(c, "contains_updates", None),
                "nodes_created": c.nodes_created,
                "nodes_deleted": c.nodes_deleted,
                "properties_set": c.properties_set,
                "labels_added": c.labels_added,
                "labels_removed": c.labels_removed,
                "relationships_created": c.relationships_created,
                "relationships_deleted": c.relationships_deleted,
            }
            
            
    async def create_user_likes_site_edge(self, user_pg_id: int, site_pg_id: int) -> dict:
        cypher = """
        MERGE (u:User {pgId: $uid})
        MERGE (s:Site {pgId: $sid})
        WITH u, s
        OPTIONAL MATCH (u)-[r:LIKES]->(s)
        WITH u, s, r, (r IS NULL) AS missing
        FOREACH (_ IN CASE WHEN missing THEN [1] ELSE [] END |
        CREATE (u)-[:LIKES {createdAt: datetime()}]->(s)
        )
        FOREACH (_ IN CASE WHEN missing THEN [] ELSE [1] END |
        DELETE r
        )
        RETURN missing AS created, EXISTS((u)-[:LIKES]->(s)) AS liked
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, uid=user_pg_id, sid=site_pg_id)
            row = await result.single()
            summary = await result.consume()

        c = summary.counters
        return {
            "liked": bool(row["liked"]),
            "created_flag": 1 if row["created"] else 0,
            "relationships_created": c.relationships_created,
            "relationships_deleted": c.relationships_deleted,
            "properties_set": c.properties_set,
            "contains_updates": getattr(c, "contains_updates", None),
        }
        
    async def create_user_dislikes_site_edge(self, user_pg_id: int, site_pg_id: int) -> dict:
        cypher = """
        MERGE (u:User {pgId: $uid})
        MERGE (s:Site {pgId: $sid})
        WITH u, s
        OPTIONAL MATCH (u)-[r:DISLIKES]->(s)
        WITH u, s, r, (r IS NULL) AS missing
        FOREACH (_ IN CASE WHEN missing THEN [1] ELSE [] END |
        CREATE (u)-[:DISLIKES {createdAt: datetime()}]->(s)
        )
        FOREACH (_ IN CASE WHEN missing THEN [] ELSE [1] END |
        DELETE r
        )
        RETURN missing AS created, EXISTS((u)-[:DISLIKES]->(s)) AS disliked
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, uid=user_pg_id, sid=site_pg_id)
            row = await result.single()
            summary = await result.consume()

        c = summary.counters
        return {
            "disliked": bool(row["disliked"]),
            "created_flag": 1 if row["created"] else 0,
            "relationships_created": c.relationships_created,
            "relationships_deleted": c.relationships_deleted,
            "properties_set": c.properties_set,
            "contains_updates": getattr(c, "contains_updates", None),
        }
        
    async def create_user_dislikes_post_edge(self, user_pg_id: int, post_pg_id: int) -> dict:
        cypher = """
        MERGE (u:User {pgId: $uid})
        MERGE (p:Post {pgId: $pid})
        WITH u, p
        OPTIONAL MATCH (u)-[r:DISLIKES]->(p)
        WITH u, p, r, (r IS NULL) AS missing
        FOREACH (_ IN CASE WHEN missing THEN [1] ELSE [] END |
        CREATE (u)-[:DISLIKES {createdAt: datetime()}]->(p)
        )
        FOREACH (_ IN CASE WHEN missing THEN [] ELSE [1] END |
        DELETE r
        )
        RETURN missing AS created, EXISTS((u)-[:DISLIKES]->(p)) AS disliked
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, uid=user_pg_id, pid=post_pg_id)
            row = await result.single()
            summary = await result.consume()

        c = summary.counters
        return {
            "disliked": bool(row["disliked"]),
            "created_flag": 1 if row["created"] else 0,
            "relationships_created": c.relationships_created,
            "relationships_deleted": c.relationships_deleted,
            "properties_set": c.properties_set,
            "contains_updates": getattr(c, "contains_updates", None),
        }
        
    async def create_user_likes_comment_edge(self, user_pg_id: int, comment_pg_id: int) -> dict:
        cypher = """
        MERGE (u:User {pgId: $uid})
        MERGE (c:Comment {pgId: $cid})
        WITH u, c
        OPTIONAL MATCH (u)-[r:LIKES]->(c)
        WITH u, c, r, (r IS NULL) AS missing
        FOREACH (_ IN CASE WHEN missing THEN [1] ELSE [] END |
          CREATE (u)-[:LIKES {createdAt: datetime()}]->(c)
        )
        FOREACH (_ IN CASE WHEN missing THEN [] ELSE [1] END |
          DELETE r
        )
        RETURN missing AS created, EXISTS((u)-[:LIKES]->(c)) AS liked
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, uid=user_pg_id, cid=comment_pg_id)
            row = await result.single()
            summary = await result.consume()

        c = summary.counters
        return {
            "liked": bool(row["liked"]),
            "created_flag": 1 if row["created"] else 0,
            "relationships_created": c.relationships_created,
            "relationships_deleted": c.relationships_deleted,
            "properties_set": c.properties_set,
            "contains_updates": getattr(c, "contains_updates", None),
        }
    
    async def create_user_likes_post_edge(self, user_pg_id: int, post_pg_id: int) -> dict:
        cypher = """
        MERGE (u:User {pgId: $uid})
        MERGE (p:Post {pgId: $pid})
        WITH u, p
        OPTIONAL MATCH (u)-[r:LIKES]->(p)
        WITH u, p, r, (r IS NULL) AS missing
        FOREACH (_ IN CASE WHEN missing THEN [1] ELSE [] END |
          CREATE (u)-[:LIKES {createdAt: datetime()}]->(p)
        )
        FOREACH (_ IN CASE WHEN missing THEN [] ELSE [1] END |
          DELETE r
        )
        RETURN missing AS created, EXISTS((u)-[:LIKES]->(p)) AS liked
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, uid=user_pg_id, pid=post_pg_id)
            row = await result.single()
            summary = await result.consume()

        c = summary.counters
        return {
            "liked": bool(row["liked"]),
            "created_flag": 1 if row["created"] else 0,
            "relationships_created": c.relationships_created,
            "relationships_deleted": c.relationships_deleted,
            "properties_set": c.properties_set,
            "contains_updates": getattr(c, "contains_updates", None),
        }
        
    async def delete_posts_by_pg_ids(self, post_ids: list[int]) -> dict:
        if not post_ids:
            return {"nodes_deleted": 0, "relationships_deleted": 0}
        cypher = """
        UNWIND $ids AS pid
        MATCH (p:Post {pgId: pid})
        DETACH DELETE p
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, ids=post_ids)
            summary = await result.consume()
        c = summary.counters
        return {
            "nodes_deleted": c.nodes_deleted,
            "relationships_deleted": c.relationships_deleted,
            "contains_updates": getattr(c, "contains_updates", None),
        }
        
    async def delete_comments_by_pg_ids(self, comment_ids: list[int]) -> dict:
        if not comment_ids:
            return {"nodes_deleted": 0, "relationships_deleted": 0}
        cypher = """
        UNWIND $ids AS cid
        MATCH (c:Comment {pgId: cid})
        DETACH DELETE c
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, ids=comment_ids)
            summary = await result.consume()
        c = summary.counters
        return {"nodes_deleted": c.nodes_deleted, "relationships_deleted": c.relationships_deleted}
        
        
    async def delete_site_by_pg_id(self, site_id: int) -> dict:
        cypher = """
        MATCH (s:Site {pgId: $sid})
        DETACH DELETE s
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, sid=site_id)
            summary = await result.consume()
        c = summary.counters
        return {
            "nodes_deleted": c.nodes_deleted,
            "relationships_deleted": c.relationships_deleted,
            "contains_updates": getattr(c, "contains_updates", None),
        }
        # ---------- one-time bootstrapping ----------
    async def ensure_constraints(self) -> None:
        """Idempotent. Safe to call at startup."""
        stmts = [
            "CREATE CONSTRAINT user_pg_id IF NOT EXISTS FOR (u:User) REQUIRE u.pgId IS UNIQUE",
            "CREATE CONSTRAINT site_pg_id IF NOT EXISTS FOR (s:Site) REQUIRE s.pgId IS UNIQUE",
            "CREATE CONSTRAINT post_pg_id IF NOT EXISTS FOR (p:Post) REQUIRE p.pgId IS UNIQUE",
            "CREATE CONSTRAINT comment_pg_id IF NOT EXISTS FOR (c:Comment) REQUIRE c.pgId IS UNIQUE",
            # optional geo/lookup index
            "CREATE INDEX site_lat_lon IF NOT EXISTS FOR (s:Site) ON (s.latitude, s.longitude)",
        ]
        async with self._driver.session() as sess:
            for cypher in stmts:
                await sess.run(cypher)


    async def ensure_constraints_with_retry(neo, attempts=50, delay=3):
        for i in range(1, attempts+1):
            try:
                await neo.ensure_constraints()
                log.info("Neo4j constraints ensured.")
                return
            except ServiceUnavailable as e:
                log.warning("Neo4j not reachable (attempt %d/%d): %s", i, attempts, e)
            except Exception as e:
                log.exception("Unexpected error ensuring constraints (attempt %d/%d)", i, attempts)
            await asyncio.sleep(delay)
        log.error("Gave up ensuring Neo4j constraints after %d attempts.", attempts)
        
        
    async def get_liked_site_ids(self, user_pg_id: int) -> List[int]:
        cypher = """
        MATCH (u:User {pgId: $user_pg_id})-[:LIKES]->(s:Site)
        RETURN s.pgId AS pgId
        ORDER BY coalesce(s.updatedAt, s.createdAt) DESC
        """
        async with self._driver.session() as sess:
            res = await sess.run(cypher, user_pg_id=user_pg_id)
            ids: List[int] = []
            async for rec in res:
                # pgId was stored as an int when upserting sites
                ids.append(int(rec["pgId"]))
        return ids
    
    async def get_liked_post_ids(self, user_pg_id: int) -> List[int]:
        cypher = """
        MATCH (u:User {pgId: $uid})-[:LIKES]->(p:Post)
        RETURN p.pgId AS pgId
        ORDER BY coalesce(p.updatedAt, p.createdAt) DESC
        """
        async with self._driver.session() as sess:
            res = await sess.run(cypher, uid=user_pg_id)
            ids: List[int] = []
            async for rec in res:
                ids.append(int(rec["pgId"]))
        return ids
    
    async def get_liked_comment_ids(self, user_pg_id: int) -> List[int]:
        cypher = """
        MATCH (u:User {pgId: $user_pg_id})-[:LIKES]->(c:Comment)
        RETURN c.pgId AS pgId
        ORDER BY coalesce(c.updatedAt, c.createdAt) DESC
        """
        async with self._driver.session() as sess:
            res = await sess.run(cypher, user_pg_id=user_pg_id)
            ids: List[int] = []
            async for rec in res:
                ids.append(int(rec["pgId"]))
        return ids
    
    
    async def toggle_friend_request_edge(self, from_user_pg_id: int, to_user_pg_id: int) -> Dict:
        """
        If (from)-[:FRIEND_REQUEST]->(to) exists, delete it (cancel).
        If it doesn't, create it (send).
        Returns flags and write counters.
        """
        if from_user_pg_id == to_user_pg_id:
            # No self-requests
            return {
                "pending": False,
                "created_flag": 0,
                "relationships_created": 0,
                "relationships_deleted": 0,
                "properties_set": 0,
                "contains_updates": False,
            }

        cypher = """
        MERGE (a:User {pgId: $from_})
        MERGE (b:User {pgId: $to})
        WITH a, b
        OPTIONAL MATCH (a)-[r:FRIEND_REQUEST]->(b)
        WITH a, b, r, (r IS NULL) AS missing
        FOREACH (_ IN CASE WHEN missing THEN [1] ELSE [] END |
          CREATE (a)-[:FRIEND_REQUEST {createdAt: datetime()}]->(b)
        )
        FOREACH (_ IN CASE WHEN missing THEN [] ELSE [1] END |
          DELETE r
        )
        RETURN missing AS created, EXISTS((a)-[:FRIEND_REQUEST]->(b)) AS pending
        """

        async with self._driver.session() as sess:
            result = await sess.run(
                cypher,
                from_ =from_user_pg_id,
                to=to_user_pg_id,
            )
            row = await result.single()
            summary = await result.consume()

        c = summary.counters
        return {
            "pending": bool(row["pending"]),         # True if request is now present
            "created_flag": 1 if row["created"] else 0,  # 1 if we created it this call
            "relationships_created": c.relationships_created,
            "relationships_deleted": c.relationships_deleted,
            "properties_set": c.properties_set,
            "contains_updates": getattr(c, "contains_updates", None),
        }
    
    async def create_user_dislikes_comment_edge(self, user_pg_id: int, comment_pg_id: int) -> dict:
        cypher = """
        MERGE (u:User {pgId: $uid})
        MERGE (c:Comment {pgId: $cid})
        WITH u, c
        OPTIONAL MATCH (u)-[r:DISLIKES]->(c)
        WITH u, c, r, (r IS NULL) AS missing
        FOREACH (_ IN CASE WHEN missing THEN [1] ELSE [] END |
          CREATE (u)-[:DISLIKES {createdAt: datetime()}]->(c)
        )
        FOREACH (_ IN CASE WHEN missing THEN [] ELSE [1] END |
          DELETE r
        )
        RETURN missing AS created, EXISTS((u)-[:DISLIKES]->(c)) AS disliked
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, uid=user_pg_id, cid=comment_pg_id)
            row = await result.single()
            summary = await result.consume()

        c = summary.counters
        return {
            "disliked": bool(row["disliked"]),
            "created_flag": 1 if row["created"] else 0,
            "relationships_created": c.relationships_created,
            "relationships_deleted": c.relationships_deleted,
            "properties_set": c.properties_set,
            "contains_updates": getattr(c, "contains_updates", None),
        }
        
        
        
    async def get_outgoing_friend_requests(self, user_pg_id: int) -> List[Dict]:
        """
        Return a list of { userId: int, name: str|None } for
        users that CURRENT USER has sent a FRIEND_REQUEST to.
        """
        cypher = """
        MATCH (me:User {pgId: $uid})-[r:FRIEND_REQUEST]->(u:User)
        RETURN u.pgId AS userId, u.name AS name
        ORDER BY coalesce(r.createdAt, u.createdAt) DESC
        """
        out: List[Dict] = []
        async with self._driver.session() as sess:
            res = await sess.run(cypher, uid=user_pg_id)
            async for rec in res:
                out.append({
                    "userId": int(rec["userId"]),
                    "name": rec.get("name"),
                })
        return out
    

    async def get_incoming_friend_requests(self, user_pg_id: int) -> List[Dict]:
        """
        Return a list of { userId: int, name: str|None } for users who have
        SENT a FRIEND_REQUEST *to* `user_pg_id`. Pure Neo, no PG.
        """
        cypher = """
        MATCH (u:User)-[r:FRIEND_REQUEST]->(me:User {pgId: $uid})
        RETURN u.pgId AS userId, u.name AS name
        ORDER BY coalesce(r.createdAt, u.createdAt) DESC
        """
        out: List[Dict] = []
        async with self._driver.session() as sess:
            res = await sess.run(cypher, uid=user_pg_id)
            async for rec in res:
                out.append({
                    "userId": int(rec["userId"]),
                    "name": rec.get("name"),
                })
        return out
    
    
    async def accept_friend_request(self, me_pg_id: int, from_user_pg_id: int) -> dict:
        """
        Accept an incoming friend request from `from_user_pg_id` to `me_pg_id`.
        If the request exists, delete it and create mutual FRIEND edges.
        Returns {accepted: bool, relationships_created: int, relationships_deleted: int}.
        """
        cypher = """
        MATCH (me:User {pgId: $me})
        MATCH (other:User {pgId: $_from})
        OPTIONAL MATCH (other)-[req:FRIEND_REQUEST]->(me)
        WITH me, other, req
        // Only proceed when the incoming request exists
        FOREACH (_ IN CASE WHEN req IS NULL THEN [] ELSE [1] END |
        DELETE req
        )
        FOREACH (_ IN CASE WHEN req IS NULL THEN [] ELSE [1] END |
        MERGE (me)-[f1:FRIEND]->(other)
            ON CREATE SET f1.createdAt = datetime()
        MERGE (other)-[f2:FRIEND]->(me)
            ON CREATE SET f2.createdAt = datetime()
        )
        RETURN req IS NOT NULL AS accepted
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, me=me_pg_id, _from=from_user_pg_id)
            row = await result.single()  # will always return one row with {accepted: bool}
            summary = await result.consume()

        c = summary.counters
        return {
            "accepted": bool(row and row["accepted"]),
            "relationships_created": c.relationships_created,
            "relationships_deleted": c.relationships_deleted,
            "contains_updates": getattr(c, "contains_updates", None),
        }
            
    async def get_friends(self, user_pg_id: int) -> List[Dict]:
        """
        Return a list of { userId: int, name: str|None } for users who are friends with the given user.
        """
        cypher = """
        MATCH (me:User {pgId: $uid})-[:FRIEND]-(u:User)
        WITH DISTINCT u
        RETURN u.pgId AS userId, u.name AS name
        ORDER BY coalesce(u.updatedAt, u.createdAt) DESC
        """
        out: List[Dict] = []
        async with self._driver.session() as sess:
            res = await sess.run(cypher, uid=user_pg_id)
            async for rec in res:
                out.append({
                    "userId": int(rec["userId"]),
                    "name": rec.get("name"),
                })
        return out
    
    async def remove_friendship(self, me_pg_id: int, other_pg_id: int) -> Dict:
        """
        Delete both FRIEND edges between the two users, if present.
        Returns {removed: int, relationships_deleted: int, contains_updates: bool|None}.
        """
        cypher = """
        MATCH (me:User {pgId: $me}), (other:User {pgId: $other})
        OPTIONAL MATCH (me)-[f1:FRIEND]->(other)
        OPTIONAL MATCH (other)-[f2:FRIEND]->(me)
        WITH collect(f1) + collect(f2) AS rels
        FOREACH (r IN rels | DELETE r)
        RETURN size(rels) AS removed
        """
        async with self._driver.session() as sess:
            res = await sess.run(cypher, me=me_pg_id, other=other_pg_id)
            row = await res.single()
            summary = await res.consume()

        removed = int(row["removed"]) if row and row.get("removed") is not None else 0
        c = summary.counters
        return {
            "removed": removed,
            "relationships_deleted": c.relationships_deleted,
            "contains_updates": getattr(c, "contains_updates", None),
        }
        
        
    async def decline_friend_request(self, me_pg_id: int, from_user_pg_id: int) -> Dict:
        """
        Delete an incoming FRIEND_REQUEST (from -> me).
        Returns {declined: bool, relationships_deleted: int, contains_updates?: bool}
        """
        cypher = """
        MATCH (me:User {pgId: $me})
        MATCH (other:User {pgId: $_from})
        OPTIONAL MATCH (other)-[req:FRIEND_REQUEST]->(me)
        WITH req
        DELETE req
        RETURN req IS NOT NULL AS declined
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, me=me_pg_id, _from=from_user_pg_id)
            row = await result.single()
            summary = await result.consume()

        c = summary.counters
        return {
            "declined": bool(row and row["declined"]),
            "relationships_deleted": c.relationships_deleted,
            "contains_updates": getattr(c, "contains_updates", None),
        }
        
        
    async def are_friends(self, me_pg_id: int, other_pg_id: int) -> bool:
        cypher = """
        MATCH (a:User {pgId: $me}), (b:User {pgId: $other})
        RETURN EXISTS( (a)-[:FRIEND]->(b) ) AND EXISTS( (b)-[:FRIEND]->(a) ) AS mutual
        """
        async with self._driver.session() as sess:
            res = await sess.run(cypher, me=me_pg_id, other=other_pg_id)
            rec = await res.single()
        return bool(rec and rec["mutual"])
    
    
    async def create_user_reported_site_edge(self, user_pg_id: int, site_pg_id: int) -> dict:
        """
        Create (User)-[:REPORTED]->(Site) only if it doesn't exist.
        Returns {created: bool, relationships_created: int}.
        """
        cypher = """
        MERGE (u:User {pgId: $uid})
        MERGE (s:Site {pgId: $sid})
        WITH u, s
        OPTIONAL MATCH (u)-[r:REPORTED]->(s)
        WITH u, s, r, (r IS NULL) AS missing
        FOREACH (_ IN CASE WHEN missing THEN [1] ELSE [] END |
          CREATE (u)-[:REPORTED {createdAt: datetime()}]->(s)
        )
        RETURN missing AS created
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, uid=user_pg_id, sid=site_pg_id)
            row = await result.single()
            summary = await result.consume()

        c = summary.counters
        return {
            "created": bool(row and row["created"]),
            "relationships_created": c.relationships_created,
            "contains_updates": getattr(c, "contains_updates", None),
        }
        
        
    async def create_user_reported_post_edge(self, user_pg_id: int, post_pg_id: int) -> dict:
        """
        Idempotent "report": creates (User)-[:REPORTED]->(Post) once.
        If it already exists, leaves it in place and reports 0 created.
        """
        cypher = """
        MERGE (u:User {pgId: $uid})
        MERGE (p:Post {pgId: $pid})
        WITH u, p
        OPTIONAL MATCH (u)-[r:REPORTED]->(p)
        WITH u, p, r, (r IS NULL) AS missing
        FOREACH (_ IN CASE WHEN missing THEN [1] ELSE [] END |
        CREATE (u)-[:REPORTED {createdAt: datetime()}]->(p)
        )
        RETURN missing AS created, EXISTS((u)-[:REPORTED]->(p)) AS reported
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, uid=user_pg_id, pid=post_pg_id)
            row = await result.single()
            summary = await result.consume()

        c = summary.counters
        return {
            "reported": bool(row["reported"]),
            "created_flag": 1 if row["created"] else 0,
            "relationships_created": c.relationships_created,
            "properties_set": c.properties_set,
            "contains_updates": getattr(c, "contains_updates", None),
        }
        
    async def create_user_reported_comment_edge(self, user_pg_id: int, comment_pg_id: int) -> dict:
        """
        Idempotent "report": creates (User)-[:REPORTED]->(Comment) once.
        If it already exists, leaves it and reports 0 created.
        """
        cypher = """
        MERGE (u:User {pgId: $uid})
        MERGE (c:Comment {pgId: $cid})
        WITH u, c
        OPTIONAL MATCH (u)-[r:REPORTED]->(c)
        WITH u, c, r, (r IS NULL) AS missing
        FOREACH (_ IN CASE WHEN missing THEN [1] ELSE [] END |
        CREATE (u)-[:REPORTED {createdAt: datetime()}]->(c)
        )
        RETURN missing AS created, EXISTS((u)-[:REPORTED]->(c)) AS reported
        """
        async with self._driver.session() as sess:
            result = await sess.run(cypher, uid=user_pg_id, cid=comment_pg_id)
            row = await result.single()
            summary = await result.consume()

        c = summary.counters
        return {
            "reported": bool(row["reported"]),
            "created_flag": 1 if row["created"] else 0,
            "relationships_created": c.relationships_created,
            "properties_set": c.properties_set,
            "contains_updates": getattr(c, "contains_updates", None),
        }
        
        
    async def get_disliked_site_ids(self, user_pg_id: int) -> List[int]:
        cypher = """
        MATCH (u:User {pgId: $uid})-[:DISLIKES]->(s:Site)
        RETURN s.pgId AS pgId
        ORDER BY coalesce(s.updatedAt, s.createdAt) DESC
        """
        ids: List[int] = []
        async with self._driver.session() as sess:
            res = await sess.run(cypher, uid=user_pg_id)
            async for rec in res:
                ids.append(int(rec["pgId"]))
        return ids
    
    async def get_disliked_post_ids(self, user_pg_id: int) -> List[int]:
        cypher = """
        MATCH (u:User {pgId: $uid})-[:DISLIKES]->(p:Post)
        RETURN p.pgId AS pgId
        ORDER BY coalesce(p.updatedAt, p.createdAt) DESC
        """
        ids: List[int] = []
        async with self._driver.session() as sess:
            res = await sess.run(cypher, uid=user_pg_id)
            async for rec in res:
                ids.append(int(rec["pgId"]))
        return ids
    
    
    
    async def get_disliked_comment_ids(self, user_pg_id: int) -> List[int]:
        cypher = """
        MATCH (u:User {pgId: $uid})-[:DISLIKES]->(c:Comment)
        RETURN c.pgId AS pgId
        ORDER BY coalesce(c.updatedAt, c.createdAt) DESC
        """
        ids: List[int] = []
        async with self._driver.session() as sess:
            res = await sess.run(cypher, uid=user_pg_id)
            async for rec in res:
                ids.append(int(rec["pgId"]))
        return ids
    
    
    async def get_friends_of_friends(self, user_pg_id: int) -> List[Dict]:
        """
        Return distinct friends-of-friends of the given user, excluding:
          - the user themselves
          - their direct friends
        Shape: [{ userId: int, name: str|None }, ...]
        """
        cypher = """
        MATCH (me:User {pgId: $uid})-[:FRIEND]-(f:User)-[:FRIEND]-(cand:User)
        WHERE cand <> me
          AND NOT (me)-[:FRIEND]-(cand)
        WITH DISTINCT cand
        RETURN cand.pgId AS userId, cand.name AS name
        ORDER BY coalesce(cand.updatedAt, cand.createdAt) DESC
        """

        out: List[Dict] = []
        async with self._driver.session() as sess:
            res = await sess.run(cypher, uid=user_pg_id)
            async for rec in res:
                out.append({
                    "userId": int(rec["userId"]),
                    "name": rec.get("name"),
                })
        return out