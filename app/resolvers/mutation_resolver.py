import strawberry
from app.services.s3_service import S3Service
from strawberry.types import Info
from app.resolvers.types import DeclineFriendRequestResult, RemoveFriendResult, Site, HistoricalSiteInput, User, DeletePostResult, DeleteSiteResult, Post, Comment, FriendRequestResult, RespondFriendResult, UserTagSet
from graphql import GraphQLError
from datetime import datetime
from typing import List, Optional, Dict, Any
import json


import logging
log = logging.getLogger("uvicorn")


ALLOWED_SITE_KEYS = {
    "id", "user_id", "title", "description", "image",
    "likes", "dislikes", "created_at", "latitude", "longitude", "tags",
}

def row_to_site_kwargs(row: Dict[str, Any]) -> Dict[str, Any]:
    data = {k: row[k] for k in ALLOWED_SITE_KEYS if k in row}

    # Defaults/coercions
    data["likes"] = int(data.get("likes") or 0)
    data["dislikes"] = int(data.get("dislikes") or 0)

    ca = data.get("created_at")
    if isinstance(ca, str):
        data["created_at"] = datetime.fromisoformat(ca.replace("Z", "+00:00"))

    for k in ("latitude", "longitude"):
        if k in data and data[k] is not None:
            data[k] = float(data[k])

    if "tags" in data and data["tags"] is not None and not isinstance(data["tags"], list):
        data["tags"] = list(data["tags"])

    return data

@strawberry.type
class UploadURL:
    url: str
    key: str

@strawberry.type
class Mutation:
    
    @strawberry.field  
    async def get_upload_url(self, info: Info, filename: str) -> UploadURL:
        s3: S3Service = info.context["s3_service"]
        result = await s3.generate_upload_url(filename)
        url = UploadURL(**result)
        return url
    
    
    @strawberry.field
    async def delete_comment(self, info: Info, comment_id: int) -> bool:
        app_user = info.context.get("app_user")
        if not app_user:
            raise GraphQLError("Not authenticated")
        user_id = app_user["id"]
        is_moderator = "moderator" in (info.context["jwt_claims"] or {}).get("realm_access", {}).get("roles", [])

        claims = info.context.get("jwt_claims")
        log.info(json.dumps(claims, indent=2, sort_keys=True, default=str))
        graph = info.context["graph_service"]
        
        if is_moderator:
        # Moderator can delete any comment
            deleted = await graph.delete_comment_any(comment_id=comment_id)
        else:
        # Normal user: only their own comment
            deleted = await graph.delete_comment(comment_id=comment_id, user_id=user_id)
        
        if not deleted:
            # Either not found, or not owned by this user
            raise GraphQLError("Not found or not authorized to delete this comment")
        return True

    @strawberry.mutation
    async def create_post(
        self,
        info: Info,
        title: str,
        content: str,
        site_id: int,
        image_key: Optional[str] = None,
    ) -> Post:
        app_user = info.context.get("app_user")
        if not app_user:
            raise GraphQLError("Not authenticated")

        user_id = app_user["id"]

        graph = info.context["graph_service"]

        # This returns the row dict from Postgres (via GraphService)
        post: Dict[str, Any] = await graph.create_post(
            user_id=user_id,
            title=title,
            content=content,
            site_id=site_id,
            image_key=image_key,  # S3 key, may be None
        )

        # Build the Post type from the returned dict
        return Post(
            id=int(post["id"]),
            user_id=int(post["user_id"]),
            site_id=int(post["site_id"]),
            title=post["title"],
            content=post["content"],
            image=post.get("image"),  # S3 key column
            likes=int(post.get("likes") or 0),
            dislikes=int(post.get("dislikes") or 0),
            created_at=post["created_at"],
        )

    
    @strawberry.mutation
    async def addUserTags(self, info: Info, tags: List[str]) -> UserTagSet:
        """
        Add (or keep) tags on the current user (from token).
        Returns the full deduped+normalized tag list for the user.
        """
        uid = info.context["app_user"]["id"]  # PG user id from claims
        res = await info.context["graph_service"].add_user_tags(user_id=uid, tags=tags)
        return UserTagSet(user_id=int(res["user_id"]), tags=list(res["tags"]))

    @strawberry.field
    async def addSiteTags(self, info: Info, siteId: int, tags: List[str]) -> Site:
        # normalize & pass to service
        graph_service = info.context["graph_service"]
        site = await graph_service.add_site_tags(site_id=siteId, tags=tags)
        return Site(**site)  # site dict should include tags array
    
    @strawberry.mutation
    async def like_site(self, info: Info, site_id: int) -> Site:
        uid = info.context["app_user"]["id"]  # from claims
        site = await info.context["graph_service"].like_site(site_id=site_id, user_id=uid)

        # map DB row -> GraphQL Site
        return Site(
            id=int(site["id"]),
            user_id=int(site["user_id"]),
            title=site["title"],
            description=site.get("description") or "",
            image=site.get("image"),
            likes=int(site.get("likes") or 0),
            dislikes=int(site.get("dislikes") or 0),
            created_at=site["created_at"],
            latitude=float(site["latitude"]),
            longitude=float(site["longitude"]),
            tags=list(site.get("tags", [])),
        )
        
    @strawberry.mutation
    async def dislike_site(self, info: Info, site_id: int) -> Site:
        uid = info.context["app_user"]["id"]  # from claims
        site = await info.context["graph_service"].dislike_site(site_id=site_id, user_id=uid)

        return Site(
            id=int(site["id"]),
            user_id=int(site["user_id"]),
            title=site["title"],
            description=site.get("description") or "",
            image=site.get("image"),
            likes=int(site.get("likes") or 0),
            dislikes=int(site.get("dislikes") or 0),
            created_at=site["created_at"],
            latitude=float(site["latitude"]),
            longitude=float(site["longitude"]),
            tags=list(site.get("tags", [])),
        )
        
    @strawberry.mutation
    async def like_post(self, info: Info, post_id: int) -> Post:
        uid = info.context["app_user"]["id"]  # from claims
        post = await info.context["graph_service"].like_post(post_id=post_id, user_id=uid)
        return Post(
            id=int(post["id"]),
            user_id=int(post["user_id"]),
            site_id=int(post["site_id"]) if post.get("site_id") is not None else None,
            title=post["title"],
            content=post["content"],
            image=post.get("image"),
            likes=int(post.get("likes") or 0),
            dislikes=int(post.get("dislikes") or 0),
            created_at=post["created_at"],
        )
        
    @strawberry.mutation
    async def dislike_post(self, info: Info, post_id: int) -> Post:
        uid = info.context["app_user"]["id"]
        post = await info.context["graph_service"].dislike_post(post_id=post_id, user_id=uid)
        return Post(
            id=int(post["id"]),
            user_id=int(post["user_id"]),
            site_id=int(post["site_id"]) if post.get("site_id") is not None else None,
            title=post["title"],
            content=post["content"],
            image=post.get("image"),
            likes=int(post.get("likes") or 0),
            dislikes=int(post.get("dislikes") or 0),
            created_at=post["created_at"],
        )    
        
    @strawberry.mutation
    async def like_comment(self, info: Info, comment_id: int) -> Comment:
        uid = info.context["app_user"]["id"]  # from claims
        row = await info.context["graph_service"].like_comment(comment_id=comment_id, user_id=uid)
        return Comment(
            id=int(row["id"]),
            user_id=int(row["user_id"]),
            post_id=int(row["post_id"]) if row.get("post_id") is not None else None,
            title=row["title"],
            content=row["content"],
            image=row.get("image"),
            likes=int(row.get("likes") or 0),
            dislikes=int(row.get("dislikes") or 0),
            created_at=row["created_at"],
        )
        
    @strawberry.mutation
    async def dislike_comment(self, info: Info, comment_id: int) -> Comment:
        uid = info.context["app_user"]["id"]  # from claims
        row = await info.context["graph_service"].dislike_comment(
            comment_id=comment_id,
            user_id=uid,
        )
        return Comment(
            id=int(row["id"]),
            user_id=int(row["user_id"]) if row.get("user_id") is not None else None,
            post_id=int(row["post_id"]) if row.get("post_id") is not None else None,
            title=row["title"],
            content=row["content"],
            image=row.get("image"),
            likes=int(row.get("likes") or 0),
            dislikes=int(row.get("dislikes") or 0),
            created_at=row["created_at"],
        )
    
    @strawberry.field
    async def delete_post(self, info: Info, post_id: int) -> DeletePostResult:
        app_user = info.context.get("app_user")
        if not app_user:
            raise GraphQLError("Not authenticated")
        result = await info.context["graph_service"].delete_post(post_id, app_user["id"])
        if not result.get("success"):
            raise GraphQLError("Not found or not authorized")
        return DeletePostResult(**result)
    
    @strawberry.field
    async def delete_site(self, info: Info, site_id: int) -> DeleteSiteResult:
        app_user = info.context.get("app_user")
        if not app_user:
            raise GraphQLError("Not authenticated")
        user_id = app_user["id"]

        claims = info.context.get("jwt_claims") or {}
        realm_access = claims.get("realm_access") or {}
        roles = realm_access.get("roles") or []
        is_moderator = "moderator" in roles

        graph = info.context["graph_service"]
        result = await graph.delete_site(
            site_id=site_id,
            user_id=user_id,
            is_moderator=is_moderator,
        )

        if not result.get("success"):
            # Hide whether it was missing vs unauthorized
            raise GraphQLError("Not found or not authorized")

        return DeleteSiteResult(
            success=bool(result.get("success")),
            code=str(result.get("code")),
            deletedSiteId=result.get("deletedSiteId"),
            deletedPosts=int(result.get("deletedPosts") or 0),
            deletedComments=int(result.get("deletedComments") or 0),
            deletedPostIds=list(result.get("deletedPostIds") or []),
            deletedCommentIds=list(result.get("deletedCommentIds") or []),
        )
        

    @strawberry.field
    async def removeSiteTag(self, info: Info, siteId: int, tagName: str) -> Site:
        app_user = info.context.get("app_user")
        if not app_user:
            raise GraphQLError("Not authenticated")

        site = await info.context["graph_service"].remove_site_tag_by_name(
            site_id=siteId,
            tag_name=tagName,
            user_id=app_user["id"],
        )
        if site is None:
            raise GraphQLError("Not found or not authorized")
        return Site(**site)
    
    @strawberry.field
    async def create_comment(
        self,
        info: Info,
        post_id: int,
        title: str,
        content: str,
        image_key: Optional[str] = None,
    ) -> bool:
        app_user = info.context.get("app_user")
        if not app_user:
            raise GraphQLError("Not authenticated")

        user_id = app_user["id"]
        graph = info.context["graph_service"]

        await graph.create_comment(user_id, post_id, title, content, image_key)
        return True
    
    
    @strawberry.mutation
    async def add_historical_site(self, info: Info, input: HistoricalSiteInput) -> Site:
        uid = info.context["app_user"]["id"]

        site = await info.context["graph_service"].add_historical_site(
            input=input,
            user_id=uid,
        )

        return Site(
            id=int(site["id"]),
            user_id=uid,
            title=site["title"],
            description=site.get("description") or "",
            image=site.get("image"),              # key from PG
            likes=int(site.get("likes") or 0),
            dislikes=int(site.get("dislikes") or 0),
            created_at=site["created_at"],
            latitude=float(site["latitude"]),
            longitude=float(site["longitude"]),
            tags=list(site.get("tags", [])),
        )
    
    @strawberry.field
    async def create_user(self, name: str, email: str, info: Info) -> User:
        graph = info.context["graph_service"]
        result = await graph.create_user(name, email)
        return User(**result)
    
    @strawberry.mutation
    async def toggle_friend_request(self, info: Info, to_user_id: int) -> FriendRequestResult:
        uid = info.context["app_user"]["id"]
        res = await info.context["graph_service"].toggle_friend_request(
            to_user_id=to_user_id, user_id=uid
        )
        return FriendRequestResult(**res)
    
    @strawberry.mutation
    async def accept_friend_request(self, info, from_user_id: int) -> RespondFriendResult:
        me = info.context["app_user"]["id"]
        res = await info.context["graph_service"].accept_friend_request(
            user_id=me, from_user_id=from_user_id
        )
        return RespondFriendResult(accepted=bool(res.get("accepted")))
    
    @strawberry.mutation
    async def declineFriendRequest(self, info: Info, fromUserId: int) -> DeclineFriendRequestResult:
        uid = info.context["app_user"]["id"]
        res = await info.context["graph_service"].decline_friend_request(me_id=uid, from_id=fromUserId)
        return DeclineFriendRequestResult(**res)

    @strawberry.mutation
    async def attach_image_to_site(self, info: Info, site_id: int, key: str) -> Site:
        app_user = info.context.get("app_user")
        if not app_user:
            raise GraphQLError("Not authenticated")

        graph = info.context["graph_service"]
        log.info(key)
        site: Dict[str, Any] = await graph.set_site_image(site_id, key)

        return Site(
            id=int(site["id"]),
            user_id=int(site["user_id"]),
            title=site["title"],
            description=site.get("description") or "",
            image=site.get("image"),  # S3 key
            likes=int(site.get("likes") or 0),
            dislikes=int(site.get("dislikes") or 0),
            created_at=site["created_at"],
            latitude=float(site["latitude"]),
            longitude=float(site["longitude"]),
            tags=list(site.get("tags", [])),  # will be [] from this path
        )
    
    @strawberry.mutation
    async def attach_image_to_post(self, info: Info, post_id: int, key: str) -> Post:
        app_user = info.context.get("app_user")
        if not app_user:
            raise GraphQLError("Not authenticated")

        graph = info.context["graph_service"]
        post: Dict[str, Any] = await graph.set_post_image(post_id, key)

        return Post(
            id=int(post["id"]),
            user_id=int(post["user_id"]),
            site_id=int(post["site_id"]),
            title=post["title"],
            content=post["content"],
            image=post.get("image"),  # S3 key
            likes=int(post.get("likes") or 0),
            dislikes=int(post.get("dislikes") or 0),
            created_at=post["created_at"],
        )
    
    
    @strawberry.mutation
    async def removeFriend(self, info: Info, otherUserId: int) -> RemoveFriendResult:
        me_id = info.context["app_user"]["id"]
        res = await info.context["graph_service"].remove_friend(
            me_user_id=me_id,
            other_user_id=otherUserId,
        )
        return RemoveFriendResult(success=bool(res["success"]),
                                  removed=int(res["removed"]))
        
    @strawberry.mutation
    async def report_site(self, info: Info, site_id: int) -> Site:
        uid = info.context["app_user"]["id"]
        site = await info.context["graph_service"].report_site(site_id=site_id, user_id=uid)
        return Site(
            id=int(site["id"]),
            user_id=int(site["user_id"]) if site.get("user_id") is not None else None,
            title=site.get("title") or "",
            description=site.get("description") or "",
            image=site.get("image"),
            likes=int(site.get("likes") or 0),
            dislikes=int(site.get("dislikes") or 0),
            created_at=site["created_at"],
            latitude=float(site["latitude"]) if site.get("latitude") is not None else 0.0,
            longitude=float(site["longitude"]) if site.get("longitude") is not None else 0.0,
            # tags aren’t needed here; keep default empty if your Site includes tags
            tags=list(site.get("tags") or []),
            # if your Site type includes `reports`, add it:
            # reports=int(site.get("reports") or 0),
        )
        
    @strawberry.mutation
    async def report_post(self, info: Info, post_id: int) -> Post:
        uid = info.context["app_user"]["id"]
        post = await info.context["graph_service"].report_post(post_id=post_id, user_id=uid)
        return Post(
            id=int(post["id"]),
            user_id=int(post["user_id"]),
            site_id=int(post["site_id"]) if post.get("site_id") is not None else None,
            title=post["title"],
            content=post["content"],
            image=post.get("image"),
            likes=int(post.get("likes") or 0),
            dislikes=int(post.get("dislikes") or 0),
            created_at=post["created_at"],
        )
        
        
    @strawberry.mutation
    async def report_comment(self, info: Info, comment_id: int) -> Comment:
        uid = info.context["app_user"]["id"]
        c = await info.context["graph_service"].report_comment(comment_id=comment_id, user_id=uid)
        return Comment(
            id=int(c["id"]),
            user_id=int(c["user_id"]),
            post_id=int(c["post_id"]) if c.get("post_id") is not None else None,
            title=c["title"],
            content=c["content"],
            image=c.get("image"),
            likes=int(c.get("likes") or 0),
            dislikes=int(c.get("dislikes") or 0),
            created_at=c["created_at"],
        )
        
        
    @strawberry.mutation
    async def attach_image_to_comment(
        self,
        info: Info,
        comment_id: int,
        key: str,
    ) -> Comment:
        app_user = info.context.get("app_user")
        if not app_user:
            raise GraphQLError("Not authenticated")

        graph = info.context["graph_service"]
        comment: Dict[str, Any] = await graph.set_comment_image(comment_id, key)

        return Comment(
            id=int(comment["id"]),
            post_id=int(comment["post_id"]),
            user_id=int(comment["user_id"]),
            title=comment["title"],
            content=comment["content"],
            image=comment.get("image"),  # S3 key
            likes=int(comment.get("likes") or 0),
            dislikes=int(comment.get("dislikes") or 0),
            created_at=comment["created_at"],
        )