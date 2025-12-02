import strawberry
import os
from typing import Optional, List
from strawberry.types import Info
from app.resolvers.types import Site, Post, User, Comment, OutgoingFriend, FriendUser, UserLight
from graphql import GraphQLError
from app.services.openai_client import get_openai_client
import anyio



@strawberry.type
class Query:
    
    
    @strawberry.field
    async def site(self, info: Info, id: int) -> Site | None:
        graph_service = info.context["graph_service"]
        r = await graph_service.get_site(id)
        if r is None:
            return None

        return Site(
            id=int(r["id"]),
            user_id=int(r["user_id"]) if r.get("user_id") is not None else None,
            title=r.get("title") or "",
            description=r.get("description") or "",
            image=r.get("image_url"),  # or r.get("image") if you changed the SQL
            likes=int(r.get("likes") or 0),
            dislikes=int(r.get("dislikes") or 0),
            created_at=r.get("created_at"),
            latitude=float(r["latitude"]) if r.get("latitude") is not None else 0.0,
            longitude=float(r["longitude"]) if r.get("longitude") is not None else 0.0,
            tags=list(r.get("tags") or []),
        )

    
    @strawberry.field
    async def post(self, info: Info, id: int) -> Optional[Post]:
        data = await info.context["graph_service"].get_post(id)
        if data is None:
            return None

        # Drop the "reports" field if present
        data.pop("reports", None)

        return Post(**data)


    @strawberry.field
    async def my_sites(self, info: Info) -> list[Site]:
        uid = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].pg.fetch_sites_by_user(uid)
        return [Site(**r) for r in rows]
    
    @strawberry.field
    async def my_posts(self, info: Info) -> list[Post]:
        uid = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].get_my_posts(uid)
        return [Post(**r) for r in rows]
    
    # remove later 
    @strawberry.field
    async def user(self, info: Info) -> Optional[User]:
        claims = info.context.get("jwt_claims")
        if not claims or not claims.get("email"):
            # token missing or email scope not granted
            raise GraphQLError("Not authenticated or email missing in token")

        email = claims["email"]
        # If you added get_user_by_email on GraphService:
        data = await info.context["graph_service"].get_user_by_email(email)
        # Alternatively, call the adapter directly:
        # data = await PostgresAdapter().fetch_user_by_email(email)

        return User(**data) if data else None
    

    
    @strawberry.field
    async def get_friend_sites(self, info: Info, friend_user_id: int) -> List[Site]:
        me = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].get_friend_sites(me_user_id=me, friend_user_id=friend_user_id)
        return [
            Site(
                id=int(r["id"]),
                user_id=int(r["user_id"]) if r.get("user_id") is not None else None,
                title=r.get("title") or "",
                description=r.get("description") or "",
                image=r.get("image"),
                likes=int(r.get("likes") or 0),
                dislikes=int(r.get("dislikes") or 0),
                created_at=r.get("created_at"),
                latitude=float(r["latitude"]) if r.get("latitude") is not None else 0.0,
                longitude=float(r["longitude"]) if r.get("longitude") is not None else 0.0,
                tags=[],  # friend sites don’t include tags per your note
            )
            for r in rows
        ]

    @strawberry.field
    async def get_friend_posts(self, info: Info, friend_user_id: int) -> List[Post]:
        me = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].get_friend_posts(
            me_user_id=me, friend_user_id=friend_user_id
        )
        return [
            Post(
                id=int(r["id"]),
                user_id=int(r["user_id"]) if r.get("user_id") is not None else None,
                site_id=int(r["site_id"]) if r.get("site_id") is not None else None,
                title=r.get("title") or "",
                content=r.get("content") or "",
                image=r.get("image"),
                likes=int(r.get("likes") or 0),
                dislikes=int(r.get("dislikes") or 0),
                created_at=r.get("created_at"),
            )
            for r in rows
        ]
        
    @strawberry.field
    async def my_preferences(self, info: Info) -> List[str]:
        uid = info.context["app_user"]["id"]
        try:
            tags = await info.context["graph_service"].get_my_preferences(user_id=uid)
            return tags
        except Exception:
            return []

    @strawberry.field
    async def sitesWithinBounds(
        self,
        info: Info,
        neLat: float,
        neLng: float,
        swLat: float,
        swLng: float,
        tags: Optional[List[str]] = None,   # NEW
    ) -> list[Site]:
        rows = await info.context["graph_service"].get_sites_within_bounds(
            neLat, neLng, swLat, swLng, tags  # pass through
        )
        return [Site(**r) for r in rows]
    
    @strawberry.field
    async def my_liked_sites(self, info: Info) -> List[Site]:
        uid = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].my_liked_sites(user_id=uid)
        return [
            Site(
                id=int(r["id"]),
                user_id=int(r["user_id"]) if r.get("user_id") is not None else None,
                title=r.get("title") or "",
                description=r.get("description") or "",
                image=r.get("image_url"),
                likes=int(r.get("likes") or 0),
                dislikes=int(r.get("dislikes") or 0),
                created_at=r.get("created_at"),
                latitude=float(r["latitude"]) if r.get("latitude") is not None else 0.0,
                longitude=float(r["longitude"]) if r.get("longitude") is not None else 0.0,
                tags=list(r.get("tags") or []),
            ) for r in rows
        ]
        
    @strawberry.field
    async def my_disliked_sites(self, info: Info) -> List[Site]:
        uid = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].my_disliked_sites(user_id=uid)
        return [
            Site(
                id=int(r["id"]),
                user_id=int(r["user_id"]) if r.get("user_id") is not None else None,
                title=r.get("title") or "",
                description=r.get("description") or "",
                image=r.get("image_url"),  # keep consistent with your liked flow
                likes=int(r.get("likes") or 0),
                dislikes=int(r.get("dislikes") or 0),
                created_at=r.get("created_at"),
                latitude=float(r["latitude"]) if r.get("latitude") is not None else 0.0,
                longitude=float(r["longitude"]) if r.get("longitude") is not None else 0.0,
                tags=list(r.get("tags") or []),
            ) for r in rows
        ]
        
    @strawberry.field
    async def my_liked_posts(self, info) -> List[Post]:
        uid = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].my_liked_posts(user_id=uid)
        return [
            Post(
                id=int(r["id"]),
                user_id=int(r["user_id"]) if r.get("user_id") is not None else None,
                site_id=int(r["site_id"]) if r.get("site_id") is not None else None,
                title=r.get("title") or "",
                content=r.get("content") or "",
                image=r.get("image"),
                likes=int(r.get("likes") or 0),
                dislikes=int(r.get("dislikes") or 0),
                created_at=r.get("created_at"),
            )
            for r in rows
        ]    
        
    @strawberry.field
    async def my_disliked_posts(self, info) -> List[Post]:
        uid = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].my_disliked_posts(user_id=uid)
        return [
            Post(
                id=int(r["id"]),
                user_id=int(r["user_id"]) if r.get("user_id") is not None else None,
                site_id=int(r["site_id"]) if r.get("site_id") is not None else None,
                title=r.get("title") or "",
                content=r.get("content") or "",
                image=r.get("image"),
                likes=int(r.get("likes") or 0),
                dislikes=int(r.get("dislikes") or 0),
                created_at=r.get("created_at"),
            )
            for r in rows
        ]    
        
    @strawberry.field
    async def my_liked_comments(self, info: Info) -> List[Comment]:
        uid = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].my_liked_comments(user_id=uid)
        return [
            Comment(
                id=int(r["id"]),
                user_id=int(r["user_id"]) if r.get("user_id") is not None else None,
                post_id=int(r["post_id"]) if r.get("post_id") is not None else None,
                title=r.get("title") or "",
                content=r.get("content") or "",
                image=r.get("image"),
                likes=int(r.get("likes") or 0),
                dislikes=int(r.get("dislikes") or 0),
                created_at=r.get("created_at"),
            )
            for r in rows
        ]
        
    @strawberry.field
    async def get_incoming_requests(self, info) -> List[OutgoingFriend]:
        uid = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].get_incoming_requests(user_id=uid)
        return [
            OutgoingFriend(
                user_id=int(r["userId"]),
                name=r.get("name"),
            )
            for r in rows
        ]
    
    @strawberry.field
    async def getFriends(self, info) -> List[FriendUser]:
        uid = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].get_friends(user_id=uid)
        return [FriendUser(userId=r["userId"], name=r.get("name")) for r in rows]
    
    
    @strawberry.field  # Exposed as getOutgoingRequests in GraphQL
    async def get_outgoing_requests(self, info: Info) -> List[OutgoingFriend]:
        uid = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].get_outgoing_requests(user_id=uid)
        # map to GraphQL type (rename key to user_id for schema)
        return [OutgoingFriend(user_id=r["userId"], name=r.get("name")) for r in rows]
        
    @strawberry.field
    async def posts_by_site(self, info: Info, site_id: int) -> list[Post]:
        rows = await info.context["graph_service"].get_posts_by_site(site_id)
        # Map explicitly to avoid KeyErrors or extra fields mismatches
        return [
            Post(
                id=r["id"],
                title=r["title"],
                content=r["content"],
                user_id=r["user_id"],
                site_id=r["site_id"],
                image=r.get("image"),
                likes=r.get("likes", 0),
                dislikes=r.get("dislikes", 0),
                created_at=r["created_at"],
            )
            for r in rows
        ]
        
    @strawberry.field
    async def comments_by_post(self, info: Info, post_id: int) -> list[Comment]:
        rows = await info.context["graph_service"].get_comments_by_post(post_id)
        # Map explicitly to avoid KeyErrors / extra fields
        return [
            Comment(
                id=r["id"],
                post_id=r["post_id"],
                user_id=r["user_id"],
                title=r["title"],
                content=r["content"],
                image=r.get("image"),
                likes=r.get("likes", 0),
                dislikes=r.get("dislikes", 0),
                created_at=r["created_at"],
            )
            for r in rows
        ]


    @strawberry.field
    async def my_disliked_comments(self, info: Info) -> List[Comment]:
        uid = info.context["app_user"]["id"]
        rows = await info.context["graph_service"].my_disliked_comments(user_id=uid)
        return [
            Comment(
                id=int(r["id"]),
                user_id=int(r["user_id"]) if r.get("user_id") is not None else None,
                post_id=int(r["post_id"]) if r.get("post_id") is not None else None,
                title=r.get("title") or "",
                content=r.get("content") or "",
                image=r.get("image"),
                likes=int(r.get("likes") or 0),
                dislikes=int(r.get("dislikes") or 0),
                created_at=r.get("created_at"),
            )
            for r in rows
        ]
        
        
        
    @strawberry.field
    async def users_light(
        self,
        info: Info,
        limit: int | None = None,
        offset: int = 0,
    ) -> List[UserLight]:
        pg = info.context["graph_service"].pg  # or however you access PostgresAdapter
        rows = await pg.fetch_all_users_light(limit=limit, offset=offset)
        return [
            UserLight(
                pg_id=u["pgId"],
                email=u["email"],
                name=u["name"],
                created_at=u["createdAt"],
            )
            for u in rows
        ]
        
        
    @strawberry.field
    async def get_recommended_sites(
        self,
        info: Info,
        latitude: float,
        longitude: float,
    ) -> List[Site]:
        """
        Recommendation endpoint:
        - uses current user (from JWT)
        - combines friends' liked sites (Neo4j)
        - plus popular nearby sites (Postgres)
        """
        app_user = info.context.get("app_user")
        if not app_user:
            raise GraphQLError("Not authenticated")

        user_id = app_user["id"]

        graph = info.context["graph_service"]
        rows = await graph.get_recommended_sites(
            user_pg_id=user_id,
            latitude=latitude,
            longitude=longitude,
        )

        # Build Site objects from dict rows
        return [
            Site(
                id=int(r["id"]),
                user_id=int(r["user_id"]),
                title=r["title"],
                description=r.get("description") or "",
                image=r.get("image"),
                likes=int(r.get("likes") or 0),
                dislikes=int(r.get("dislikes") or 0),
                created_at=r["created_at"],
                latitude=float(r["latitude"]),
                longitude=float(r["longitude"]),
                tags=list(r.get("tags") or []),
            )
            for r in rows
        ]
        
        
    @strawberry.field
    async def recommended_friends(self, info: Info) -> List[User]:
        app_user = info.context.get("app_user")
        if not app_user:
            raise GraphQLError("Not authenticated")

        user_id = app_user["id"]
        graph = info.context["graph_service"]

        rows = await graph.get_recommended_friends(user_pg_id=user_id)

        return [
            User(
                id=row["id"],
                name=row["name"],
                email=row["email"],
                created_at=row["created_at"],
                profile_pic_url=row.get("profile_pic_url"),
            )
            for row in rows
        ]
        
    @strawberry.field
    async def all_posts_light(self, info: Info) -> List[Post]:
        app_user = info.context.get("app_user")
        if not app_user:
            raise GraphQLError("Not authenticated")

        graph = info.context["graph_service"]
        rows = await graph.get_all_posts_light()

        return [
            Post(
                id=row["pgId"],
                user_id=row["userPgId"],
                site_id=row["sitePgId"],
                title=row["title"],
                content=row["content"],
                image=row.get("image"),
                likes=int(row.get("likes") or 0),
                dislikes=int(row.get("dislikes") or 0),
                created_at=row["createdAt"],
            )
            for row in rows
        ]
        
    @strawberry.field
    async def ask_atlas(self, info: Info, siteId: int, prompt: str) -> str:
        # Make sure the key is there (good defensive check)
        if "OPENAI_API_KEY" not in os.environ:
            raise GraphQLError("OpenAI API key not found in environment variables!")

        graph = info.context["graph_service"]
        site = await graph.get_site(siteId)

        desc = site.get("description") or ""
        lng = site.get("longitude")
        lat = site.get("latitude")

        # Build context for the model
        user_message = (
            "You are Antiquity Atlas, an assistant that explains historical sites.\n\n"
            f"Site description: {desc}\n"
            f"Latitude: {lat}\n"
            f"Longitude: {lng}\n\n"
            f"User question: {prompt}"
        )

        client = get_openai_client()

        # Run sync OpenAI client in a worker thread so we don't block the event loop
        def _call_openai() -> str:
            resp = client.chat.completions.create(
                model=os.getenv("OPENAI_MODEL", "gpt-4.1-mini"),  # or whatever you configure
                messages=[
                    {"role": "system", "content": "You are Antiquity Atlas, a helpful tour guide, willing to help Antiquity Atlas users to learn more about historical sites."},
                    {"role": "user", "content": user_message},
                ],
            )
            return resp.choices[0].message.content

        answer = await anyio.to_thread.run_sync(_call_openai)

        return answer
            