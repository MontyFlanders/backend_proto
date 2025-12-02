# app/main.py
import os
import logging
from app.services.postgresql_adapter import PostgresAdapter
from fastapi import FastAPI, Request
from starlette.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware
from strawberry.fastapi import GraphQLRouter
from typing import Any, Dict
from app import graphql_schema
from app.services.graph_service import GraphService
from app.services.s3_service import S3Service
from app.security.oidc import verify_access_token
from app.db import get_pg_pool, ensure_user_from_claims
# NEW: async Neo4j adapter (your async version)
from app.services.neo4j_adapter import Neo4jAdapter

logger = logging.getLogger("uvicorn")

PUBLIC_PATHS = {"/", "/healthz"}

# --- Auth middleware: Bearer-only for /graphql --------------------------------
class RequireBearerForGraphQL(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)

        if path.startswith("/graphql"):
            auth = request.headers.get("authorization") or request.headers.get("Authorization")
            if not auth or not auth.lower().startswith("bearer "):
                return JSONResponse({"detail": "missing_bearer_token"}, status_code=401)
            token = auth.split(" ", 1)[1].strip()

            try:
                claims = await verify_access_token(token)
            except Exception as e:
                return JSONResponse({"detail": f"invalid_token: {e}"}, status_code=401)

            request.state.jwt_claims = claims
            request.state.user_id = claims.get("sub")

            # Ensure the user exists/updated in Postgres
            try:
                user = await ensure_user_from_claims(claims)
                request.state.app_user = user
            except Exception:
                logger.exception("ensure_user_from_claims failed")

            # Optional: mirror user to Neo on each request (tiny scale OK).
            try:
                neo = Neo4jAdapter()
                stats = await neo.upsert_users([{
                    "pgId": user["id"],
                    "email": user["email"],
                    "name": user["name"],
                    "profile_pic_url": user.get("profile_pic_url"),
                }])
            except Exception as e:
                logger.warning("neo4j upsert_users failed (non-fatal): %s", e)
            finally:
                try:
                    await neo.close()
                except Exception:
                    pass

            return await call_next(request)

# --- App ----------------------------------------------------------------------
app = FastAPI()
app.add_middleware(RequireBearerForGraphQL)

@app.get("/healthz")
async def healthz():
    return {"ok": True}

# GraphQL context: surface services + identity
async def get_context(request: Request):
    return {
        "graph_service": GraphService(),
        "s3_service": S3Service(),
        "user_id": getattr(request.state, "user_id", None),
        "jwt_claims": getattr(request.state, "jwt_claims", None),
        "app_user": getattr(request.state, "app_user", None),
    }

graphql_app = GraphQLRouter(graphql_schema.schema, context_getter=get_context)
app.include_router(graphql_app, prefix="/graphql")

# --- Lifecycle ---------------------------------------------------------------
@app.on_event("startup")
async def startup():
    # S3 bucket existence check (lightweight)
    try:
        s3 = S3Service()
        s3.s3.head_bucket(Bucket=s3.bucket)
        logger.info("S3: bucket %s is reachable in region %s", s3.bucket, s3.region)
    except Exception:
        logger.exception("S3: bucket check failed")
    try:
        await get_pg_pool()
        logger.info("PG: pool ready")
        # try:
        #     pg = PostgresAdapter()
        #     await pg.migrate_add_reports_and_user_tags()
        #     logger.info("PG: migrate_add_reports_and_user_tags succeeded")
        # except Exception:
        #     logger.exception("PG: migrate_add_reports_and_user_tags FAILED")
    except Exception:
        logger.exception("PG: pool warm FAILED")


    # Ensure Neo4j constraints upfront (runs once, idempotent)
    logger.info("Ensuring Neo4j constraints… NEO4J_URI=%r", os.getenv("NEO4J_URI"))
    neo = Neo4jAdapter()
    try:
        await neo.ensure_constraints_with_retry()
        # If you want to bootstrap graph from PG on start (small data):
        # await bootstrap_graph_from_postgres(neo)
    finally:
        await neo.close()

@app.on_event("shutdown")
async def shutdown():
    # Close PG pool
    pool = await get_pg_pool()
    await pool.close()
    

# Optional: tiny bootstrap function if you decide to sync PG→Neo on startup
async def bootstrap_graph_from_postgres(neo):
    from app.services.postgresql_adapter import PostgresAdapter

    pg = PostgresAdapter()

    # ---- Fetch all from PG
    users    = [dict(r) for r in await pg.fetch_all_users_light()]
    sites    = [dict(r) for r in await pg.fetch_all_sites_light()]
    posts    = [dict(r) for r in await pg.fetch_all_posts_light()]
    comments = [dict(r) for r in await pg.fetch_all_comments_light()]

    def _log_result(kind: str, count: int, res: Dict[str, Any] | None):
        if count == 0:
            logger.info("neo4j upsert %-8s: skipped (no rows)", kind)
            return
        if not res:
            logger.warning("neo4j upsert %-8s: no result returned (n=%d)", kind, count)
            return
        logger.info(
            "neo4j upsert %-8s: n=%d | nodes_created=%d nodes_deleted=%d "
            "rels_created=%d rels_deleted=%d props_set=%d contains_updates=%s",
            kind, count,
            res.get("nodes_created", 0), res.get("nodes_deleted", 0),
            res.get("relationships_created", 0), res.get("relationships_deleted", 0),
            res.get("properties_set", 0), res.get("contains_updates"),
        )

    # ---- Upserts with robust logging
    try:
        res = await neo.upsert_users(users) if users else None
        _log_result("users", len(users), res)
    except Exception:
        logger.exception("neo4j upsert_users failed")

    try:
        res = await neo.upsert_sites(sites) if sites else None
        _log_result("sites", len(sites), res)
    except Exception:
        logger.exception("neo4j upsert_sites failed")

    try:
        res = await neo.upsert_posts(posts) if posts else None
        _log_result("posts", len(posts), res)
    except Exception:
        logger.exception("neo4j upsert_posts failed")

    try:
        res = await neo.upsert_comments(comments) if comments else None
        _log_result("comments", len(comments), res)
    except Exception:
        logger.exception("neo4j upsert_comments failed")
