import strawberry
from typing import Optional
from strawberry.types import Info
from datetime import datetime


@strawberry.type
class User:
    id: int
    name: str
    email: str
    created_at: datetime

@strawberry.type
class Location:
    latitude: float
    longitude: float
    
@strawberry.input
class HistoricalSiteInput:
    user_id: int
    title: str
    description: str
    latitude: float
    longitude: float
    image_key: Optional[str] = None
    
@strawberry.type
class Comment:
    id: int
    title: str
    content: str
    image: Optional[str] = None
    likes: int = 0
    dislikes: int = 0
    created_at: datetime

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
        return [Comment(**d) for d in data]


@strawberry.type
class Site:
    id: int
    user_id: int
    title: str
    description: str
    image: Optional[str] = None
    likes: int = 0
    dislikes: int = 0
    created_at: datetime


    @strawberry.field
    async def location(self, info: Info) -> Location:
        data = await info.context["graph_service"].get_site_location(self.id)
        return Location(**data)

    @strawberry.field
    async def posts(self, info: Info) -> list[Post]:
        posts = await info.context["graph_service"].get_posts_by_site(self.id)
        return [Post(**post) for post in posts]     
    

