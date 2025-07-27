from fastapi import FastAPI, Request
from strawberry.fastapi import GraphQLRouter
from . import graphql_schema
from app.services.graph_service import GraphService
from app.services.s3_service import S3Service

app = FastAPI()

# get fresh context for each request
async def get_context(request: Request):
    return {
        "graph_service": GraphService(),
        "s3_service": S3Service(),  
    }

graphql_app = GraphQLRouter(
    graphql_schema.schema,
    context_getter=get_context,
)

app.include_router(graphql_app, prefix="/graphql")

@app.on_event("startup")
async def startup():
    s3 = S3Service()
    try:
        s3.s3.head_bucket(Bucket=s3.bucket)
    except:
        s3.s3.create_bucket(Bucket=s3.bucket)
