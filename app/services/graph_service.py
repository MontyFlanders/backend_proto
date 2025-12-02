from app.services.postgresql_adapter import PostgresAdapter
from app.services.s3_service import S3Service
from app.resolvers.types import HistoricalSiteInput, User
from app.services.neo4j_adapter import Neo4jAdapter  # NEW
from typing import Optional, List, Dict, Any
import logging
log = logging.getLogger("uvicorn")



# we use this class to unify s3/pg/neo
class GraphService:
    
    
    def __init__(self):
        self.pg = PostgresAdapter()
        self.neo = Neo4jAdapter()  # NEW

    async def like_site(self, site_id: int, user_id: int) -> dict:
            """
            Toggle 'like' for (user_id, site_id):
            - If the (LIKES) edge didn't exist, create it and increment PG like count.
            - If it already existed, delete it and decrement PG like count.
            Returns the updated site row from PG either way.
            """
            try:
                stats = await self.neo.create_user_likes_site_edge(
                    user_pg_id=user_id,
                    site_pg_id=site_id,
                )
                log.info("neo4j toggle LIKES stats: %s", stats)
            except Exception:
                log.exception("neo4j toggle LIKES failed for user=%s site=%s", user_id, site_id)
                # Neo failed → don't touch PG count; return current site
                return await self.pg.fetch_one_site(site_id)

            # Apply counter in PG only when Neo actually changed something
            created = stats.get("relationships_created", 0) > 0
            deleted = stats.get("relationships_deleted", 0) > 0

            if created:
                return await self.pg.increment_site_like(site_id)
            elif deleted:
                return await self.pg.decrement_site_like(site_id)
            else:
                # Shouldn’t happen, but fall back to current state
                return await self.pg.fetch_one_site(site_id)
            
    async def dislike_site(self, site_id: int, user_id: int) -> dict:
        """
        Toggle 'dislike' for (user_id, site_id):
        - If the (DISLIKES) edge didn't exist, create it and increment PG dislike count.
        - If it already existed, delete it and decrement PG dislike count.
        Returns the updated site row from PG either way.
        """
        try:
            stats = await self.neo.create_user_dislikes_site_edge(
                user_pg_id=user_id,
                site_pg_id=site_id,
            )
            log.info("neo4j toggle DISLIKES stats: %s", stats)
        except Exception:
            log.exception("neo4j toggle DISLIKES failed for user=%s site=%s", user_id, site_id)
            # Neo failed → don't touch PG count; return current site
            return await self.pg.fetch_one_site(site_id)

        created = stats.get("relationships_created", 0) > 0
        deleted = stats.get("relationships_deleted", 0) > 0

        if created:
            return await self.pg.increment_site_dislike(site_id)
        elif deleted:
            return await self.pg.decrement_site_dislike(site_id)
        else:
            return await self.pg.fetch_one_site(site_id)
        
    async def dislike_post(self, post_id: int, user_id: int) -> dict:
        """
        Toggle 'dislike' for (user_id, post_id):
        - If the (DISLIKES) edge didn't exist, create it and increment PG dislike count.
        - If it already existed, delete it and decrement PG dislike count.
        Returns the updated post row from PG.
        """
        try:
            stats = await self.neo.create_user_dislikes_post_edge(
                user_pg_id=user_id,
                post_pg_id=post_id,
            )
            log.info("neo4j toggle DISLIKES(Post) stats: %s", stats)
        except Exception:
            log.exception("neo4j toggle DISLIKES(Post) failed for user=%s post=%s", user_id, post_id)
            # Neo failed → don't change PG count; return current post
            return await self.pg.fetch_post(post_id)

        created = stats.get("relationships_created", 0) > 0
        deleted = stats.get("relationships_deleted", 0) > 0

        if created:
            return await self.pg.increment_post_dislike(post_id)
        elif deleted:
            return await self.pg.decrement_post_dislike(post_id)
        else:
            return await self.pg.fetch_post(post_id)
        
        
    async def dislike_comment(self, comment_id: int, user_id: int) -> dict:
        """
        Toggle 'dislike' for (user_id, comment_id):
        - If the (DISLIKES) edge didn't exist, create it and increment PG dislike count.
        - If it already existed, delete it and decrement PG dislike count.
        Returns the updated comment row from PG.
        """
        try:
            stats = await self.neo.create_user_dislikes_comment_edge(
                user_pg_id=user_id,
                comment_pg_id=comment_id,
            )
            log.info("neo4j toggle DISLIKES(Comment) stats: %s", stats)
        except Exception:
            log.exception("neo4j toggle DISLIKES(Comment) failed for user=%s comment=%s", user_id, comment_id)
            # Neo failed → don't change PG count; return current comment
            return await self.pg.fetch_comment(comment_id)

        created = stats.get("relationships_created", 0) > 0
        deleted = stats.get("relationships_deleted", 0) > 0

        if created:
            return await self.pg.increment_comment_dislike(comment_id)
        elif deleted:
            return await self.pg.decrement_comment_dislike(comment_id)
        else:
            # Should not happen; fall back to current state
            return await self.pg.fetch_comment(comment_id)
        
    async def toggle_friend_request(self, to_user_id: int, user_id: int) -> dict:
        """
        Send or cancel a friend request from user_id -> to_user_id.
        No PG writes; purely Neo edge toggle.
        """
        if user_id == to_user_id:
            return {"pending": False, "created": False, "code": "CANNOT_REQUEST_SELF"}

        try:
            stats = await self.neo.toggle_friend_request_edge(
                from_user_pg_id=user_id, to_user_pg_id=to_user_id
            )
            log.info("neo4j toggle FRIEND_REQUEST stats: %s", stats)
            return {
                "pending": bool(stats.get("pending")),
                "created": bool(stats.get("created_flag")),
                "relationshipsCreated": stats.get("relationships_created", 0),
                "relationshipsDeleted": stats.get("relationships_deleted", 0),
                "code": "OK",
            }
        except Exception:
            log.exception(
                "neo4j toggle FRIEND_REQUEST failed for from=%s to=%s",
                user_id, to_user_id
            )
            return {"pending": False, "created": False, "code": "GRAPH_ERROR"}
            
    async def get_outgoing_requests(self, user_id: int) -> List[Dict[str, Any]]:
        try:
            rows = await self.neo.get_outgoing_friend_requests(user_id)
            log.info("neo4j outgoing friend requests count=%d", len(rows))
            return rows
        except Exception:
            log.exception("neo4j get_outgoing_friend_requests failed for user=%s", user_id)
            return []    
        
    async def get_incoming_requests(self, user_id: int) -> List[Dict[str, Any]]:
        try:
            rows = await self.neo.get_incoming_friend_requests(user_id)
            log.info("neo4j incoming friend requests count=%d", len(rows))
            return rows
        except Exception:
            log.exception("neo4j get_incoming_friend_requests failed for user=%s", user_id)
            return []    
        
    async def accept_friend_request(self, user_id: int, from_user_id: int) -> dict:
        try:
            stats = await self.neo.accept_friend_request(me_pg_id=user_id,
                                                         from_user_pg_id=from_user_id)
            log.info("neo4j accept_friend_request: %s", stats)
            return {"accepted": bool(stats.get("accepted", False))}
        except Exception:
            log.exception("neo4j accept_friend_request failed for me=%s from=%s",
                          user_id, from_user_id)
            return {"accepted": False}
        
        
    async def decline_friend_request(self, me_id: int, from_id: int) -> Dict[str, Any]:
        try:
            stats = await self.neo.decline_friend_request(me_pg_id=me_id, from_user_pg_id=from_id)
            log.info("neo4j decline_friend_request: %s", stats)
            return {
                "declined": bool(stats.get("declined", False)),
                "relationshipsDeleted": int(stats.get("relationships_deleted", 0)),
            }
        except Exception:
            log.exception("neo4j decline_friend_request failed for me=%s from=%s", me_id, from_id)
            return {"declined": False, "relationshipsDeleted": 0}
        
    async def remove_friend(self, me_user_id: int, other_user_id: int) -> dict:
        """
        Remove friendship between me_user_id and other_user_id in Neo4j.
        Returns {success: bool, removed: int}.
        """
        try:
            stats = await self.neo.remove_friendship(me_user_id, other_user_id)
            log.info("neo4j remove_friendship stats: %s", stats)
            return {"success": True, "removed": int(stats.get("removed", 0))}
        except Exception:
            log.exception("neo4j remove_friendship failed for me=%s other=%s",
                            me_user_id, other_user_id)
            return {"success": False, "removed": 0}

    async def get_friends(self, user_id: int) -> List[Dict[str, Any]]:
        try:
            rows = await self.neo.get_friends(user_id)
            log.info("neo4j get_friends count=%d", len(rows))
            return rows
        except Exception:
            log.exception("neo4j get_friends failed for user=%s", user_id)
            return []
            
    async def get_friend_sites(self, me_user_id: int, friend_user_id: int) -> List[Dict[str, Any]]:
        # 1) check friendship in Neo
        try:
            ok = await self.neo.are_friends(me_user_id, friend_user_id)
        except Exception:
            log.exception("neo4j are_friends failed me=%s friend=%s", me_user_id, friend_user_id)
            return []

        if not ok:
            log.info("get_friend_sites denied: not friends me=%s friend=%s", me_user_id, friend_user_id)
            return []

        # 2) hydrate from PG
        rows = await self.pg.fetch_sites_by_user(friend_user_id)
        # Ensure shape for GraphQL
        for r in rows:
            r.setdefault("likes", 0)
            r.setdefault("dislikes", 0)
            r.setdefault("description", r.get("description") or "")
            r.setdefault("image", r.get("image"))
            # latitude/longitude already selected as floats by your SQL
        return rows    
            
    async def get_friend_posts(self, me_user_id: int, friend_user_id: int) -> List[Dict[str, Any]]:
        # 1) verify friendship in Neo
        try:
            ok = await self.neo.are_friends(me_user_id, friend_user_id)
        except Exception:
            log.exception("neo4j are_friends failed me=%s friend=%s", me_user_id, friend_user_id)
            return []

        if not ok:
            log.info("get_friend_posts denied: not friends me=%s friend=%s", me_user_id, friend_user_id)
            return []

        # 2) hydrate from PG (assumes you already have this)
        rows = await self.pg.fetch_posts_by_user(friend_user_id)

        # Ensure shape your GraphQL Post expects
        for r in rows:
            r.setdefault("likes", 0)
            r.setdefault("dislikes", 0)
            r.setdefault("image", r.get("image"))
            r.setdefault("content", r.get("content") or "")
            r.setdefault("title", r.get("title") or "")
            # site_id may be null; created_at provided by query
        return rows
            
    async def like_post(self, post_id: int, user_id: int) -> dict:
        """
        Toggle 'like' for (user_id, post_id):
        - If the (LIKES) edge didn't exist, create it and increment PG like count.
        - If it already existed, delete it and decrement PG like count.
        Returns the updated post row from PG.
        """
        try:
            stats = await self.neo.create_user_likes_post_edge(
                user_pg_id=user_id,
                post_pg_id=post_id,
            )
            log.info("neo4j toggle LIKES(Post) stats: %s", stats)
        except Exception:
            log.exception("neo4j toggle LIKES(Post) failed for user=%s post=%s", user_id, post_id)
            # Neo failed → don't change PG count; return current post
            return await self.pg.fetch_post(post_id)

        created = stats.get("relationships_created", 0) > 0
        deleted = stats.get("relationships_deleted", 0) > 0

        if created:
            return await self.pg.increment_post_like(post_id)
        elif deleted:
            return await self.pg.decrement_post_like(post_id)
        else:
            # Should not happen, but keep it safe
            return await self.pg.fetch_post(post_id)
        
    async def like_comment(self, comment_id: int, user_id: int) -> dict:
        """
        Toggle 'like' for (user_id, comment_id):
        - If the (LIKES) edge didn't exist, create it and increment PG like count.
        - If it already existed, delete it and decrement PG like count.
        Returns the updated comment row from PG.
        """
        try:
            stats = await self.neo.create_user_likes_comment_edge(
                user_pg_id=user_id,
                comment_pg_id=comment_id,
            )
            log.info("neo4j toggle LIKES(Comment) stats: %s", stats)
        except Exception:
            log.exception("neo4j toggle LIKES(Comment) failed for user=%s comment=%s", user_id, comment_id)
            # Neo failed → don't change PG count; return current comment
            return await self.pg.fetch_comment(comment_id)

        created = stats.get("relationships_created", 0) > 0
        deleted = stats.get("relationships_deleted", 0) > 0

        if created:
            return await self.pg.increment_comment_like(comment_id)
        elif deleted:
            return await self.pg.decrement_comment_like(comment_id)
        else:
            # Fallback to current state
            return await self.pg.fetch_comment(comment_id)
    
    async def my_liked_sites(self, user_id: int) -> List[Dict[str, Any]]:
        # 1) Ask Neo which sites the user likes
        liked_ids = await self.neo.get_liked_site_ids(user_id)
        if not liked_ids:
            return []

        # 2) Hydrate those sites from PG, including tags (M:N)
        sites = await self.pg.fetch_sites_by_ids_with_tags(liked_ids)

        # 3) (Optional) keep Neo's order: sort by the order in liked_ids
        order = {sid: i for i, sid in enumerate(liked_ids)}
        sites.sort(key=lambda r: order.get(int(r["id"]), 10**9))

        # 4) Ensure shapes your GraphQL `Site` expects
        for s in sites:
            s.setdefault("tags", [])
            s.setdefault("image_url", None)
            s.setdefault("title", "")
            s.setdefault("description", "")
            s.setdefault("likes", 0)
            s.setdefault("dislikes", 0)
        return sites
    
    async def my_disliked_sites(self, user_id: int) -> List[Dict[str, Any]]:
        # 1) Ask Neo which sites the user dislikes
        disliked_ids = await self.neo.get_disliked_site_ids(user_id)
        if not disliked_ids:
            return []

        # 2) Hydrate those sites from PG (includes tags M:N)
        sites = await self.pg.fetch_sites_by_ids_with_tags(disliked_ids)

        # 3) Preserve Neo order if you care about it
        order = {sid: i for i, sid in enumerate(disliked_ids)}
        sites.sort(key=lambda r: order.get(int(r["id"]), 10**9))

        # 4) Ensure expected shape for your GraphQL Site
        for s in sites:
            s.setdefault("tags", [])
            s.setdefault("image_url", None)   # keep parity with resolver usage
            s.setdefault("title", "")
            s.setdefault("description", "")
            s.setdefault("likes", 0)
            s.setdefault("dislikes", 0)

        return sites
    
    async def my_liked_posts(self, user_id: int) -> List[Dict[str, Any]]:
        # 1) Post ids from Neo
        liked_ids = await self.neo.get_liked_post_ids(user_id)
        if not liked_ids:
            return []

        # 2) Hydrate from PG
        posts = await self.pg.fetch_posts_by_ids(liked_ids)

        # 3) Keep Neo order (e.g., recent first per Neo query)
        order = {pid: i for i, pid in enumerate(liked_ids)}
        posts.sort(key=lambda r: order.get(int(r["id"]), 10**9))

        # 4) Normalize fields expected by Post type
        for p in posts:
            p.setdefault("image", None)
            p.setdefault("title", "")
            p.setdefault("content", "")
            p.setdefault("likes", 0)
            p.setdefault("dislikes", 0)

        log.info("my_liked_posts hydrated %d posts", len(posts))
        return posts
    
    async def my_disliked_posts(self, user_id: int) -> List[Dict[str, Any]]:
        # 1) Get post ids from Neo (DISLIKES)
        disliked_ids = await self.neo.get_disliked_post_ids(user_id)
        if not disliked_ids:
            return []

        # 2) Hydrate from PG
        posts = await self.pg.fetch_posts_by_ids(disliked_ids)

        # 3) Keep Neo order
        order = {pid: i for i, pid in enumerate(disliked_ids)}
        posts.sort(key=lambda r: order.get(int(r["id"]), 10**9))

        # 4) Normalize for GraphQL Post
        for p in posts:
            p.setdefault("image", None)
            p.setdefault("title", "")
            p.setdefault("content", "")
            p.setdefault("likes", 0)
            p.setdefault("dislikes", 0)

        log.info("my_disliked_posts hydrated %d posts", len(posts))
        return posts

    async def my_liked_comments(self, user_id: int) -> List[Dict[str, Any]]:
        liked_ids = await self.neo.get_liked_comment_ids(user_id)
        if not liked_ids:
            return []

        comments = await self.pg.fetch_comments_by_ids(liked_ids)

        order = {cid: i for i, cid in enumerate(liked_ids)}
        comments.sort(key=lambda r: order.get(int(r["id"]), 10**9))

        # Normalize/ensure fields the GraphQL type expects
        for c in comments:
            c.setdefault("image", None)
            c.setdefault("title", "")
            c.setdefault("content", "")
            c.setdefault("likes", 0)
            c.setdefault("dislikes", 0)
        return comments
    
    
    async def my_disliked_comments(self, user_id: int) -> List[Dict[str, Any]]:
        # 1) Comment ids from Neo (DISLIKES)
        disliked_ids = await self.neo.get_disliked_comment_ids(user_id)
        if not disliked_ids:
            return []

        # 2) Hydrate from PG
        comments = await self.pg.fetch_comments_by_ids(disliked_ids)

        # 3) Preserve Neo order
        order = {cid: i for i, cid in enumerate(disliked_ids)}
        comments.sort(key=lambda r: order.get(int(r["id"]), 10**9))

        # 4) Normalize for GraphQL Comment
        for c in comments:
            c.setdefault("image", None)
            c.setdefault("title", "")
            c.setdefault("content", "")
            c.setdefault("likes", 0)
            c.setdefault("dislikes", 0)

        return comments

    async def get_site(self, site_id: int) -> dict:
        return await self.pg.fetch_one_site(site_id)

    async def get_site_location(self, site_id: int) -> dict:
        return await self.pg.fetch_site_location(site_id)
    
    async def get_user_by_email(self, email: str):
        return await self.pg.fetch_user_by_email(email)
    
    async def get_sites_within_bounds(
        self,
        ne_lat: float,
        ne_lng: float,
        sw_lat: float,
        sw_lng: float,
        tags: Optional[List[str]] = None,  # NEW
    ) -> list[dict]:
        return await self.pg.fetch_sites_within_bounds(ne_lat, ne_lng, sw_lat, sw_lng, tags)

    async def get_posts_by_site(self, site_id: int) -> list[dict]:
        return await self.pg.fetch_posts_by_site(site_id)
    
    async def get_comments_by_post(self, post_id: int) -> list[dict]:
        return await self.pg.fetch_comments_by_post(post_id)
    
    async def delete_comment(self, comment_id: int, user_id: int) -> bool:
        # 1) Delete from Postgres first
        ok = await self.pg.delete_comment(comment_id, user_id)
        if not ok:
            return False

        # 2) Mirror delete in Neo4j (best-effort)
        try:
            stats = await self.neo.delete_comments_by_pg_ids([comment_id])
            log.info("neo4j delete comment stats: %s", stats)
        except Exception:
            log.exception("neo4j delete_comments_by_pg_ids failed for comment_id=%s", comment_id)

        return True
    
    
    
    async def delete_comment_any(self, comment_id: int) -> bool:
        # moderator delete
        return await self.pg.delete_comment_by_id(comment_id=comment_id)
    
    async def delete_site(
        self,
        site_id: int,
        user_id: int,
        is_moderator: bool = False,
    ) -> dict:
        # PG handles ownership vs moderator
        res = await self.pg.delete_site_tx(
            site_id=site_id,
            user_id=user_id,
            is_moderator=is_moderator,
        )

        if not res.get("success"):
            return res  # NOT_FOUND_OR_FORBIDDEN, etc.

        # Fire Neo deletes (best-effort) AFTER PG commit
        try:
            post_ids = list(res.get("deletedPostIds") or [])
            comment_ids = list(res.get("deletedCommentIds") or [])

            if comment_ids:
                stats_c = await self.neo.delete_comments_by_pg_ids(comment_ids)
                log.info("neo4j delete comments stats: %s", stats_c)

            if post_ids:
                stats_p = await self.neo.delete_posts_by_pg_ids(post_ids)
                log.info("neo4j delete posts stats: %s", stats_p)

            if res.get("deletedSiteId") is not None:
                stats_s = await self.neo.delete_site_by_pg_id(int(res["deletedSiteId"]))
                log.info("neo4j delete site stats: %s", stats_s)

        except Exception:
            log.exception("neo4j cascade delete failed for site=%s", site_id)

        return res
    
    async def delete_post(self, post_id: int, user_id: int) -> dict:
        # Run the PG transactional delete first
        res = await self.pg.delete_post_tx(post_id=post_id, user_id=user_id)
        if not res.get("success"):
            return res

        # After PG commit, mirror deletes in Neo4j
        comment_ids = res.get("deletedCommentIds", [])
        try:
            if comment_ids:
                stats_c = await self.neo.delete_comments_by_pg_ids(comment_ids)
                log.info("neo4j delete comments stats: %s", stats_c)
        except Exception:
            log.exception("neo4j delete_comments_by_pg_ids failed for comment_ids=%s", comment_ids)

        try:
            stats_p = await self.neo.delete_posts_by_pg_ids([res["deletedPostId"]])
            log.info("neo4j delete posts stats: %s", stats_p)
        except Exception:
            log.exception("neo4j delete_posts_by_pg_ids failed for post_id=%s", res.get("deletedPostId"))

        return res

    async def get_post(self, post_id: int) -> dict:
        return await self.pg.fetch_post(post_id)
    
    async def get_my_posts(self, user_id: int) -> list[dict]:
        return await self.pg.fetch_posts_by_user(user_id)
    
    async def remove_site_tag_by_name(self, site_id: int, tag_name: str, user_id: int) -> dict | None:
        return await self.pg.remove_site_tag_by_name(site_id=site_id, tag_name=tag_name, user_id=user_id)


    async def get_user_by_post(self, post_id: int) -> dict:
        return await self.pg.fetch_user_by_post(post_id)

    async def get_comments_by_post(self, post_id: int) -> list[dict]:
        return await self.pg.fetch_comments_by_post(post_id)

    async def get_user(self, user_id: int) -> dict:
        return await self.pg.fetch_user(user_id)

    async def get_connected_sites(self, site_id: int):
        return self.neo.get_connected_sites(site_id)


    async def create_post(
        self,
        user_id: int,
        title: str,
        content: str,
        site_id: int,
        image_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a post in Postgres (storing the S3 key) and upsert to Neo4j.
        """
        # 1) Write to Postgres – store the KEY in the image column
        post = await self.pg.insert_post(
            user_id=user_id,
            title=title,
            content=content,
            site_id=site_id,
            image=image_key,        # <-- key, not URL
        )
        # Expected fields: id, user_id, site_id, title, content, image, likes, dislikes, created_at

        # 2) Upsert in Neo (non-blocking for API success)
        try:
            payload = [{
                "pgId": post["id"],
                "title": post["title"],
                "content": post["content"],
                # store key in Neo as well (same as PG 'image' field)
                "image": post.get("image"),
                "likes": post.get("likes"),
                "dislikes": post.get("dislikes"),
                "createdAt": post.get("created_at"),
                "userPgId": post["user_id"],   # (User)-[:AUTHORED]->(Post)
                "sitePgId": post["site_id"],   # (Post)-[:ON_SITE]->(Site)
            }]
            stats = await self.neo.upsert_posts(payload)
            log.info("neo4j upsert_posts: %s", stats)
        except Exception:
            log.exception("neo4j upsert_posts failed for pgId=%s", post.get("id"))

        return post

    async def create_comment(
        self,
        user_id: int,
        post_id: int,
        title: str,
        content: str,
        image_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create a comment in Postgres (storing the S3 key) and upsert to Neo4j.
        """
        # 1) Write to Postgres
        comment = await self.pg.insert_comment(
            user_id=user_id,
            post_id=post_id,
            title=title,
            content=content,
            image=image_key,       # <-- key, not URL
        )
        # Expected fields: id, user_id, post_id, title, content, image, likes, dislikes, created_at

        # 2) Upsert in Neo (non-blocking for API success)
        try:
            payload = [{
                "pgId": comment["id"],
                "title": comment["title"],
                "content": comment["content"],
                "image": comment.get("image"),          # key
                "likes": comment.get("likes"),
                "dislikes": comment.get("dislikes"),
                "createdAt": comment.get("created_at"),
                "userPgId": comment["user_id"],  # (User)-[:COMMENTED]->(Comment)
                "postPgId": comment["post_id"],  # (Comment)-[:ON_POST]->(Post)
            }]
            stats = await self.neo.upsert_comments(payload)
            log.info("neo4j upsert_comments: %s", stats)
        except Exception:
            log.exception("neo4j upsert_comments failed for pgId=%s", comment.get("id"))

        return comment

    async def add_historical_site(
        self,
        input: HistoricalSiteInput,
        user_id: int,
        ) -> Dict[str, Any]:
            """
            Insert a historical site into Postgres (storing the S3 key) and upsert into Neo4j.
            """
            image_key = input.image_key  # may be None

            # 1) Write to Postgres first
            site = await self.pg.insert_historical_site(
                user_id=user_id,
                title=input.title,
                description=input.description,
                latitude=input.latitude,
                longitude=input.longitude,
                image=image_key,          # <-- store key, not URL
                tags=input.tags or [],
            )
            # `site` should include: id, user_id, title, description, latitude, longitude, image, tags, created_at, updated_at, etc.

            # 2) Upsert into Neo4j
            try:
                await self.neo.upsert_sites([{
                    "pgId": site["id"],
                    "title": site["title"],
                    "latitude": site["latitude"],
                    "longitude": site["longitude"],
                    # keep the key in Neo too (you can still resolve URLs at read time)
                    "image": site.get("image"),
                    "description": site.get("description"),
                    "createdAt": site.get("created_at"),
                    "updatedAt": site.get("updated_at"),
                    # you can add tags here too if your Cypher expects them
                    "tags": site.get("tags") or [],
                }])
                log.info("neo4j upsert_sites succeeded for pgId=%s", site["id"])
            except Exception:
                # Don't fail the whole mutation if the graph is temporarily unavailable
                log.exception("neo4j upsert_sites failed for pgId=%s", site.get("id"))

            return site
        
    async def add_user_tags(self, user_id: int, tags: List[str]) -> Dict[str, Any]:
        """
        Normalize strings, ensure tags exist in `tags`, link via `user_tags`,
        and return { user_id, tags: [..] } for the user.
        """
        # normalize/dedupe here (keeps DB function simple & reusable)
        norm: List[str] = []
        seen = set()
        for t in (s.strip().lower() for s in (tags or []) if s and s.strip()):
            if t not in seen:
                seen.add(t)
                norm.append(t)

        try:
            return await self.pg.add_user_tags(user_id=user_id, tags=norm)
        except Exception:
            log.exception("add_user_tags failed for user=%s", user_id)
            # graceful fallback: return current tag set (possibly empty)
            current = await self.pg.fetch_user_tags(user_id)
            return {"user_id": user_id, "tags": current}
        
    async def add_site_tags(self, site_id: int, tags: List[str]) -> Dict[str, Any]:
    # delegate to PG; returns a full site dict incl. tags
        return await self.pg.add_site_tags(site_id=site_id, tags=tags)

    async def create_user(self, name, email) -> User:
        return await self.pg.create_user(name, email)

    async def get_my_preferences(self, user_id: int) -> List[str]:
        tags = await self.pg.fetch_user_tags(user_id)
        # Optional: defensive normalization (if needed)
        return [t.strip().lower() for t in tags if t]
    
    async def report_site(self, site_id: int, user_id: int) -> dict:
        """
        Create a REPORTED edge if missing; only then increment PG 'reports'.
        If the edge already exists, do nothing and just return current site.
        """
        try:
            stats = await self.neo.create_user_reported_site_edge(
                user_pg_id=user_id,
                site_pg_id=site_id,
            )
            log.info("neo4j REPORTED(site) stats: %s", stats)
        except Exception:
            log.exception("neo4j REPORTED(site) failed for user=%s site=%s", user_id, site_id)
            # Neo failed → don't change PG count; return current site state
            return await self.pg.fetch_one_site(site_id)

        if stats.get("created"):
            # Only increment when edge was actually created
            return await self.pg.increment_site_report(site_id)
        else:
            # Already reported previously → no counter change
            return await self.pg.fetch_one_site(site_id)
        

    async def report_post(self, post_id: int, user_id: int) -> dict:
        """
        Report a post once per user:
        - Try to create (User)-[:REPORTED]->(Post) in Neo.
        - If created, increment PG reports.
        - If already existed or Neo fails, do NOT change PG count.
        Returns the current/updated post row from PG.
        """
        try:
            stats = await self.neo.create_user_reported_post_edge(
                user_pg_id=user_id, post_pg_id=post_id
            )
            log.info("neo4j toggle REPORTED(Post) stats: %s", stats)
        except Exception:
            log.exception("neo4j REPORTED(Post) failed for user=%s post=%s", user_id, post_id)
            return await self.pg.fetch_post(post_id)

        created = stats.get("relationships_created", 0) > 0 or stats.get("created_flag") == 1
        if created:
            return await self.pg.increment_post_report(post_id)
        else:
            # Edge already existed → no-op on PG
            return await self.pg.fetch_post(post_id)
        
        
    async def report_comment(self, comment_id: int, user_id: int) -> dict:
        """
        Report a comment once per user:
        - Try to create (User)-[:REPORTED]->(Comment) in Neo.
        - If created, increment PG reports.
        - If already existed or Neo fails, do NOT change PG count.
        Returns the current/updated comment row from PG.
        """
        try:
            stats = await self.neo.create_user_reported_comment_edge(
                user_pg_id=user_id, comment_pg_id=comment_id
            )
            log.info("neo4j toggle REPORTED(Comment) stats: %s", stats)
        except Exception:
            log.exception("neo4j REPORTED(Comment) failed for user=%s comment=%s", user_id, comment_id)
            return await self.pg.fetch_comment(comment_id)  # assumes you have this

        created = stats.get("relationships_created", 0) > 0 or stats.get("created_flag") == 1
        if created:
            return await self.pg.increment_comment_report(comment_id)
        else:
            return await self.pg.fetch_comment(comment_id)
        
        
    async def set_site_image(self, site_id: int, image_key: str) -> Dict[str, Any]:
        """
        Store the S3 key for the site's image in Postgres and update Neo4j.
        """
        # 1) Update PG
        site = await self.pg.set_site_image(site_id, image_key)

        # 2) Upsert into Neo4j (non-fatal on failure)
        try:
            payload = [{
                "pgId": site["id"],
                "title": site["title"],
                "latitude": site["latitude"],
                "longitude": site["longitude"],
                "image": site.get("image"),           # key
                "description": site.get("description"),
                "createdAt": site.get("created_at"),
                "updatedAt": site.get("updated_at"),
            }]
            stats = await self.neo.upsert_sites(payload)
            log.info("neo4j upsert_sites after image update: %s", stats)
        except Exception:
            log.exception("neo4j upsert_sites failed for pgId=%s", site.get("id"))

        log.info(site.get("image"))
        log.info("We got to set site image!")
        return site
    
    async def set_post_image(self, post_id: int, image_key: str) -> Dict[str, Any]:
        """
        Store the S3 key for the post's image in Postgres and update Neo4j.
        """
        # 1) Update Postgres
        post = await self.pg.set_post_image(post_id, image_key)

        # 2) Upsert in Neo4j (non-fatal)
        try:
            payload = [{
                "pgId": post["id"],
                "title": post["title"],
                "content": post["content"],
                "image": post.get("image"),        # S3 key
                "likes": post.get("likes"),
                "dislikes": post.get("dislikes"),
                "createdAt": post.get("created_at"),
                "userPgId": post["user_id"],       # (User)-[:AUTHORED]->(Post)
                "sitePgId": post["site_id"],       # (Post)-[:ON_SITE]->(Site)
            }]
            stats = await self.neo.upsert_posts(payload)
            log.info("neo4j upsert_posts after image update: %s", stats)
        except Exception:
            log.exception("neo4j upsert_posts failed for pgId=%s", post.get("id"))

        return post
    
    
    async def set_comment_image(self, comment_id: int, image_key: str) -> Dict[str, Any]:
        """
        Store the S3 key for the comment's image in Postgres and update Neo4j.
        """
        # 1) Update Postgres
        comment = await self.pg.set_comment_image(comment_id, image_key)

        # 2) Upsert in Neo4j (non-fatal)
        try:
            payload = [{
                "pgId": comment["id"],
                "title": comment["title"],
                "content": comment["content"],
                "image": comment.get("image"),        # S3 key
                "likes": comment.get("likes"),
                "dislikes": comment.get("dislikes"),
                "createdAt": comment.get("created_at"),
                "userPgId": comment["user_id"],       # (User)-[:COMMENTED]->(Comment)
                "postPgId": comment["post_id"],       # (Comment)-[:ON_POST]->(Post)
            }]
            stats = await self.neo.upsert_comments(payload)
            log.info("neo4j upsert_comments after image update: %s", stats)
        except Exception:
            log.exception("neo4j upsert_comments failed for pgId=%s", comment.get("id"))

        return comment
    
    
    async def get_recommended_sites(
        self,
        user_pg_id: int,
        latitude: float,
        longitude: float,
        *,
        radius_miles: float = 100.0,
        nearby_limit: int = 20,
    ) -> List[Dict[str, Any]]:
        """
        Recommended sites based on:
          1) Sites liked by the user's friends (from Neo4j),
          2) PLUS popular nearby sites within `radius_miles`,
        hydrated from Postgres with tags.

        Returns list of dicts shaped like other site payloads:
          {id, user_id, title, description, image, likes, dislikes,
           created_at, latitude, longitude, tags}
        """
        # 1) Friends of the user (Neo4j)
        friends = await self.neo.get_friends(user_pg_id)
        friend_ids = [f["userId"] for f in friends]
        log.info("recommendations: user %s has %d friends", user_pg_id, len(friend_ids))

        # 2) Collect all liked site ids from friends (Neo4j)
        liked_site_ids_set: set[int] = set()
        for fid in friend_ids:
            try:
                liked_ids = await self.neo.get_liked_site_ids(fid)
                liked_site_ids_set.update(liked_ids)
            except Exception:
                log.exception("get_liked_site_ids failed for friend %s", fid)

        liked_site_ids = list(liked_site_ids_set)
        log.info(
            "recommendations: collected %d distinct liked site ids from friends",
            len(liked_site_ids),
        )

        # 3) Hydrate liked sites via Postgres
        friend_liked_sites: List[Dict[str, Any]] = []
        if liked_site_ids:
            try:
                friend_liked_sites = await self.pg.fetch_sites_by_ids_with_tags(liked_site_ids)
            except Exception:
                log.exception("fetch_sites_by_ids_with_tags failed for ids=%r", liked_site_ids)

        # Build a set of site ids we've already got (to avoid duplicates)
        existing_site_ids: set[int] = {int(s["id"]) for s in friend_liked_sites}

        # 4) Get nearby popular sites from Postgres (limit 20 within 100 miles)
        radius_meters = radius_miles * 1609.34  # 100 miles → meters
        nearby_sites: List[Dict[str, Any]] = []
        try:
            nearby_sites = await self.pg.fetch_popular_sites_near(
                latitude=latitude,
                longitude=longitude,
                radius_meters=radius_meters,
                limit=nearby_limit,
            )
        except Exception:
            log.exception("fetch_popular_sites_near failed")

        # 5) Merge friend-liked + nearby, de-duplicating by id
        combined: List[Dict[str, Any]] = []
        combined.extend(friend_liked_sites)

        for site in nearby_sites:
            sid = int(site["id"])
            if sid in existing_site_ids:
                continue
            combined.append(site)
            existing_site_ids.add(sid)

        log.info(
            "recommendations: returning %d sites (friends-liked=%d, nearby=%d)",
            len(combined), len(friend_liked_sites), len(nearby_sites),
        )

        return combined
    
    async def get_recommended_friends(self, user_pg_id: int, limit: int = 20) -> List[Dict[str, Any]]:
        """
        Recommend friends based on friends-of-friends.
        Tags (user_tags) are used to *rank* candidates, but we don't
        require any overlap > 0 for someone to show up.
        """

        # 1) Tags for the current user (may be empty)
        my_tags = set(await self.pg.fetch_user_tags(user_pg_id))
        log.info("friend recs: user %s has %d tags", user_pg_id, len(my_tags))

        # 2) Friends-of-friends from Neo4j (excluding direct friends)
        candidates = await self.neo.get_friends_of_friends(user_pg_id)
        log.info("friend recs: %d raw candidate friends-of-friends", len(candidates))

        if not candidates:
            # Optional: you *could* fallback to direct friends here if you wanted.
            return []

        scored: List[Dict[str, Any]] = []

        # 3) For each candidate, compute overlap (or 0 if no tags)
        for cand in candidates:
            cand_id = cand["userId"]
            cand_name = cand.get("name") or ""

            overlap = 0
            if my_tags:
                try:
                    cand_tags = set(await self.pg.fetch_user_tags(cand_id))
                    overlap = len(my_tags & cand_tags)
                except Exception:
                    log.exception("fetch_user_tags failed for user_id=%s", cand_id)

            scored.append({
                "userId": cand_id,
                "name": cand_name,
                "overlap": overlap,  # used only for sorting
            })

        # 4) Sort by overlap desc, then name as tiebreaker
        scored.sort(key=lambda r: (-r["overlap"], r["name"].lower()))
        rec_ids = [r["userId"] for r in scored[:limit]]

        # 5) Hydrate user rows from Postgres
        users = await self.pg.fetch_users_by_ids_light(rec_ids)
        user_map = {u["id"]: u for u in users}

        ordered_users: List[Dict[str, Any]] = [
            user_map[uid] for uid in rec_ids if uid in user_map
        ]

        log.info("friend recs: returning %d users", len(ordered_users))
        return ordered_users


    async def get_all_posts_light(self) -> list[dict]:
        """
        Fetch all posts in a lightweight shape (no reports, etc.).
        """
        return await self.pg.fetch_all_posts_light()
    
    