import strawberry
from typing import Optional
from strawberry.types import Info
from app.resolvers.types import Site, Post, User

@strawberry.type
class Query:
    @strawberry.field
    async def site(self, info: Info, id: int) -> Site:
        graph_service = info.context["graph_service"]
        data = await graph_service.get_site(id)
        if data is None:
            return None 
        data.pop("location", None)
        return Site(**data)
    
    @strawberry.field
    async def post(self, info: Info, id: int) -> Optional[Post]:
        data = await info.context["graph_service"].get_post(id)
        if data is None:
            return None
        return Post(**data)

    @strawberry.field
    async def user(self, info: Info, id: int) -> Optional[User]:
        data = await info.context["graph_service"].get_user(id)
        if data is None:
            return None
        return User(**data)
