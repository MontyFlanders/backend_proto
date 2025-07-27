from app.services.postgresql_adapter import PostgresAdapter
from app.services.neo4j_adapter import Neo4jAdapter
from app.services.s3_service import S3Service
from app.resolvers.types import HistoricalSiteInput, User
from typing import Optional

# we use this class to unify s3/pg/neo
class GraphService:
    
    def __init__(self):
        self.pg = PostgresAdapter()
        self.neo = Neo4jAdapter()

    async def get_site(self, site_id: int) -> dict:
        return await self.pg.fetch_one_site(site_id)

    async def get_site_location(self, site_id: int) -> dict:
        return await self.pg.fetch_site_location(site_id)

    async def get_posts_by_site(self, site_id: int) -> list[dict]:
        return await self.pg.fetch_posts_by_site(site_id)

    async def get_post(self, post_id: int) -> dict:
        return await self.pg.fetch_post(post_id)

    async def get_user_by_post(self, post_id: int) -> dict:
        return await self.pg.fetch_user_by_post(post_id)

    async def get_comments_by_post(self, post_id: int) -> list[dict]:
        return await self.pg.fetch_comments_by_post(post_id)

    async def get_user(self, user_id: int) -> dict:
        return await self.pg.fetch_user(user_id)

    async def get_connected_sites(self, site_id: int):
        return self.neo.get_connected_sites(site_id)

    async def set_post_image(self, post_id: int, image_url: str):
        await self.pg.update_post_image(post_id, image_url)

    async def create_post(self, user_id, title, content, site_id, image_url):
        await self.pg.insert_post(user_id, title, content, site_id, image_url)

    async def create_comment(self, user_id, post_id, title, content, image_url):
        await self.pg.insert_comment(user_id, post_id, title, content, image_url)

    async def add_historical_site(self, input: HistoricalSiteInput, s3: S3Service):
        image_url = s3.get_object_url(input.image_key) if input.image_key else None

        return await self.pg.insert_historical_site(
            user_id=input.user_id,
            title=input.title,
            description=input.description,
            latitude=input.latitude,
            longitude=input.longitude,
            image_url=image_url,
        )

    async def create_user(self, name, email) -> User:
        return await self.pg.create_user(name, email)
