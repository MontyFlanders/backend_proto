from app.services.s3_service import S3Service
import strawberry
from typing import Optional, List
from strawberry.types import Info
from datetime import datetime


@strawberry.type
class UserLight:
    pg_id: int
    email: str
    name: str
    created_at: datetime

@strawberry.type
class UserTagSet:
    user_id: int
    tags: List[str]

@strawberry.type
class DeclineFriendRequestResult:
    declined: bool
    relationshipsDeleted: int = 0

@strawberry.type
class RemoveFriendResult:
    success: bool
    removed: int

@strawberry.type
class FriendUser:
    userId: int
    name: Optional[str]

@strawberry.type
class RespondFriendResult:
    accepted: bool

@strawberry.type
class OutgoingFriend:
    user_id: int
    name: Optional[str] = None

@strawberry.type
class FriendRequestResult:
    code: str
    pending: bool          # True if a request exists after the toggle
    created: bool          # True if we just created it (False if we deleted it)
    relationshipsCreated: int = 0
    relationshipsDeleted: int = 0

@strawberry.type
class DeletePostResult:
    success: bool
    code: str
    deletedPostId: Optional[int] = None
    deletedComments: int = 0
    deletedCommentIds: List[int] = strawberry.field(default_factory=list)
    
@strawberry.type
class DeleteSiteResult:
    success: bool
    code: str
    deletedSiteId: Optional[int] = None
    deletedPosts: int = 0
    deletedComments: int = 0
    deletedPostIds: List[int] = strawberry.field(default_factory=list)
    deletedCommentIds: List[int] = strawberry.field(default_factory=list)
    
@strawberry.type
class User:
    id: int
    name: str
    email: str
    created_at: datetime
    profile_pic_url: Optional[str] = None  # <- add this

@strawberry.type
class Location:
    latitude: float
    longitude: float
    

@strawberry.input
class HistoricalSiteInput:
    title: str
    description: Optional[str] = None
    latitude: float
    longitude: float
    image_key: Optional[str] = None
    tags: Optional[List[str]] = None   # NEW
    
@strawberry.type
class Comment:
    id: int
    post_id: int
    user_id: int
    title: str
    content: str
    image: Optional[str] = None
    likes: int = 0
    dislikes: int = 0
    created_at: datetime
    
    @strawberry.field
    async def image_url(self, info: Info) -> Optional[str]:
        if not self.image:
            return None
        s3: S3Service = info.context["s3_service"]
        return await s3.generate_download_url(self.image)

@strawberry.type
class Post:
    id: int
    user_id: int
    site_id: int
    title: str
    content: str
    image: Optional[str] = None
    likes: int = 0
    dislikes: int = 0
    created_at: datetime


    @strawberry.field
    async def author(self, info: Info) -> User:
        data = await info.context["graph_service"].get_user_by_post(self.id)
        return User(**data)

    @strawberry.field
    async def comments(self, info: Info) -> list[Comment]:
        data = await info.context["graph_service"].get_comments_by_post(self.id)
        return [Comment(**{k: v for k, v in d.items() if k != "reports"}) for d in data]
    
    @strawberry.field
    async def image_url(self, info: Info) -> Optional[str]:
        if not self.image:
            return None
        s3: S3Service = info.context["s3_service"]
        return await s3.generate_download_url(self.image)


@strawberry.type
class Site:
    id: int
    user_id: strawberry.Private[int]
    title: str
    description: str
    image: Optional[str] = None
    likes: int = 0
    dislikes: int = 0
    created_at: datetime
    latitude: float
    longitude: float
    tags: List[str] = strawberry.field(default_factory=list)  # ← NEW

    @strawberry.field
    async def location(self, info: Info) -> Location:
        data = await info.context["graph_service"].get_site_location(self.id)
        return Location(**data)

    @strawberry.field
    async def posts(self, info: Info) -> list[Post]:
        rows = await info.context["graph_service"].get_posts_by_site(self.id)

        return [
            Post(**{k: v for k, v in row.items() if k != "reports"})
            for row in rows
        ]
        
    @strawberry.field
    async def image_url(self, info: Info) -> Optional[str]:
        if not self.image:
            return None
        s3: S3Service = info.context["s3_service"]
        return await s3.generate_download_url(self.image)

    

