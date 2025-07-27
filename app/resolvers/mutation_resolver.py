import strawberry
from app.services.s3_service import S3Service
from strawberry.types import Info
from app.resolvers.types import Site, HistoricalSiteInput, User 


@strawberry.type
class UploadURL:
    url: str
    key: str

@strawberry.type
class Mutation:
    @strawberry.field
    def get_upload_url(self, filename: str) -> UploadURL:
        result = s3.generate_upload_url(filename)
        return UploadURL(**result)

    @strawberry.field
    async def attach_image_to_post(self, info: Info, post_id: int, key: str) -> bool:
        image_url = s3.get_object_url(key)
        graph = info.context["graph_service"]
        await graph.set_post_image(post_id, image_url)
        return True

    @strawberry.field
    async def create_post(
        self,
        info: Info,
        user_id: int,
        title: str,
        content: str,
        site_id: int,
        image_key: str | None = None
    ) -> bool:
        s3 = info.context["s3_service"]
        image_url = s3.get_object_url(image_key) if image_key else None
        graph = info.context["graph_service"]
        await graph.create_post(user_id, title, content, site_id, image_url)
        return True

    @strawberry.field
    async def create_comment(
        self,
        info: Info,
        user_id: int,
        post_id: int,
        title: str,
        content: str,
        image_key: str | None = None
    ) -> bool:
        s3 = info.context["s3_service"]
        image_url = s3.get_object_url(image_key) if image_key else None
        graph = info.context["graph_service"]
        await graph.create_comment(user_id, post_id, title, content, image_url)
        return True

    @strawberry.field
    async def add_historical_site(self, info: Info, input: HistoricalSiteInput) -> Site:
        graph_service = info.context["graph_service"]
        s3 = info.context["s3_service"]
        result = await graph_service.add_historical_site(input, s3)
        result.pop("location", None)
        return Site(**result)
    
    @strawberry.field
    async def create_user(self, name: str, email: str, info: Info) -> User:
        graph = info.context["graph_service"]
        result = await graph.create_user(name, email)
        return User(**result)