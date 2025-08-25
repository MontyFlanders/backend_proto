# app/main.py
import os
from fastapi import FastAPI, Request, HTTPException, Response
from starlette.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
from authlib.common.security import generate_token
from authlib.oauth2.rfc7636 import create_s256_code_challenge
import asyncpg
from strawberry.fastapi import GraphQLRouter
from . import graphql_schema
from app.services.graph_service import GraphService
from app.services.s3_service import S3Service
from app.security.sessions import MemorySessions  # your simple in-memory sessions
# add near your other imports
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

PUBLIC_PATHS = {
    "/",
    "/me",
    "/auth/login",
    "/auth/callback",
    "/auth/logout",
    "/healthz",
}

async def get_db():
    return await asyncpg.connect(
        host=os.getenv("DB_HOST", "postgis"),
        port=int(os.getenv("DB_PORT", "5432")),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        database=os.getenv("DB_NAME"),
    )

class RequireAuthForGraphQL(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        path = request.url.path

        # Allow public paths (and static assets if you have them)
        if path in PUBLIC_PATHS or path.startswith("/static"):
            return await call_next(request)

        # Require session for /graphql (both GET and POST)
        if path.startswith("/graphql"):
            sid = request.cookies.get(SESSION_COOKIE)
            sess = app.state.sessions.get(sid) if sid else None
            if not sess:
                return JSONResponse({"detail": "Not authenticated"}, status_code=401)

        return await call_next(request)

# register it after creating `app = FastAPI()`


# --- Config -------------------------------------------------------------------
SESSION_COOKIE = "sid" 
SESSION_TTL = 7 * 24 * 3600

OIDC_ISSUER = os.getenv("OIDC_ISSUER")
OIDC_CLIENT_ID = os.getenv("OIDC_CLIENT_ID")
OIDC_CLIENT_SECRET = os.getenv("OIDC_CLIENT_SECRET")  # may be None for Public + PKCE
APP_BASE_URL = os.getenv("APP_BASE_URL", "http://localhost:8000")
REDIRECT_URI = f"{APP_BASE_URL}/auth/callback"
SECURE_COOKIE = APP_BASE_URL.startswith("https://")  # __Host_ requires Secure

# --- App & sessions -----------------------------------------------------------
app = FastAPI()
app.add_middleware(SessionMiddleware, secret_key=os.getenv("FASTAPI_SESSION_SECRET"))
app.add_middleware(RequireAuthForGraphQL)
app.state.sessions = MemorySessions(ttl_seconds=SESSION_TTL)

# --- OAuth (Keycloak) ---------------------------------------------------------
oauth = OAuth()
# replace server_metadata_url=... with explicit server_metadata
oauth.register(
    name="keycloak",
    client_id=OIDC_CLIENT_ID,
    client_secret=OIDC_CLIENT_SECRET,

    authorize_url="http://localhost:8080/realms/dev/protocol/openid-connect/auth",
    access_token_url="http://keycloak:8080/realms/dev/protocol/openid-connect/token",
    client_kwargs={"scope": "openid email profile"},

    # IMPORTANT: use a URL; Authlib will fetch + cache this
    server_metadata_url="http://127.0.0.1:8000/.well-known/kc-oidc.json",
)


def set_session_cookie(resp: Response, sid: str):
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=sid,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL,
        path="/",
        secure=SECURE_COOKIE  # set True in prod/HTTPS
    )

# --- Auth routes --------------------------------------------------------------
@app.get("/auth/login")
async def login(request: Request):
    code_verifier = generate_token(48)
    request.session["code_verifier"] = code_verifier
    code_challenge = create_s256_code_challenge(code_verifier)

    redirect_uri = str(request.url_for("auth_callback"))  # dynamic host/port

    return await oauth.keycloak.authorize_redirect(
        request,
        redirect_uri=redirect_uri,
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )

# add near your other routes
@app.get("/.well-known/kc-oidc.json")
async def kc_oidc_metadata():
    return {
        "issuer": "http://localhost:8080/realms/dev",
        "jwks_uri": "http://keycloak:8080/realms/dev/protocol/openid-connect/certs",
        "userinfo_endpoint": "http://keycloak:8080/realms/dev/protocol/openid-connect/userinfo",
        "end_session_endpoint": "http://localhost:8080/realms/dev/protocol/openid-connect/logout",
    }


@app.get("/_debug/oidc")
async def debug_oidc():
    return oauth.keycloak.server_metadata

@app.get("/auth/callback")
async def auth_callback(request: Request):
    if err := request.query_params.get("error"):
        raise HTTPException(
            status_code=400,
            detail=f"OIDC error: {err} - {request.query_params.get('error_description')}"
        )

    code_verifier = request.session.pop("code_verifier", None)
    token = await oauth.keycloak.authorize_access_token(
        request, code_verifier=code_verifier
    )

    nonce = request.session.pop("oidc_nonce", None)

    # Decode claims (prefer ID token; fallback to userinfo)
    if token.get("id_token"):
        try:
            # Newer Authlib: no request arg
            claims = await oauth.keycloak.parse_id_token(token, nonce=nonce)
        except TypeError:
            # Older Authlib requires request first
            claims = await oauth.keycloak.parse_id_token(request, token, nonce=nonce)
    else:
        resp = await oauth.keycloak.get("userinfo", token=token)
        claims = resp.json()

    # Pull fields with safe fallbacks
    issuer = claims.get("iss") or oauth.keycloak.server_metadata["issuer"]
    subject = claims["sub"]  # userinfo always has "sub"

    email = claims.get("email")
    name = claims.get("name") or claims.get("preferred_username") or email or subject

    provider = "keycloak"

    # --- upsert local user ---
    conn = await get_db()
    try:
        row = await conn.fetchrow("""
            SELECT user_id FROM user_identities
            WHERE provider=$1 AND issuer=$2 AND subject=$3
        """, provider, issuer, subject)

        if row:
            user_id = row["user_id"]
        else:
            user_id = (await conn.fetchrow("""
                INSERT INTO users(email, name) VALUES($1, $2)
                RETURNING id
            """, email, name))["id"]

            await conn.execute("""
                INSERT INTO user_identities (user_id, provider, issuer, subject, email)
                VALUES ($1, $2, $3, $4, $5)
                ON CONFLICT (provider, issuer, subject)
                DO UPDATE SET email=EXCLUDED.email
            """, user_id, provider, issuer, subject, email)
    finally:
        await conn.close()

    # Session payload (use the values you defined above)
    payload = {
        "user_id": user_id,
        "issuer": issuer,
        "subject": subject,
        "email": email,
        "name": name,
        "roles": ["user"],
        "id_token": token.get("id_token"),  # for SSO logout
    }

    sid = app.state.sessions.create(payload)
    resp = RedirectResponse(url="/")
    set_session_cookie(resp, sid)
    return resp


@app.post("/auth/logout")
async def logout(request: Request):
    sid = request.cookies.get(SESSION_COOKIE)
    id_token_hint = None
    if sid:
        sess = app.state.sessions.get(sid)
        if sess:
            id_token_hint = sess.get("id_token")
        app.state.sessions.delete(sid)

    # Optional SSO logout
    try:
        metadata = await oauth.keycloak.load_server_metadata()
        end_session = metadata.get("end_session_endpoint")
    except Exception:
        end_session = None

    resp = JSONResponse({"ok": True})
    resp.delete_cookie(SESSION_COOKIE, path="/")
    if end_session and id_token_hint:
        return RedirectResponse(
            url=f"{end_session}?id_token_hint={id_token_hint}&post_logout_redirect_uri={APP_BASE_URL}/"
        )
    return resp

@app.get("/me")
async def me(request: Request):
    sid = request.cookies.get(SESSION_COOKIE)
    data = app.state.sessions.get(sid) if sid else None
    return {"session": bool(sid), "data": data}

# --- GraphQL wiring -----------------------------------------------------------
async def get_context(request: Request):
    return {
        "graph_service": GraphService(),
        "s3_service": S3Service(),
        "session": app.state.sessions.get(request.cookies.get(SESSION_COOKIE)) if request.cookies else None,
    }

graphql_app = GraphQLRouter(
    graphql_schema.schema,
    context_getter=get_context,
)
app.include_router(graphql_app, prefix="/graphql")

# --- Startup ------------------------------------------------------------------
@app.on_event("startup")
async def startup():
    s3 = S3Service()
    try:
        s3.s3.head_bucket(Bucket=s3.bucket)
    except Exception:
        s3.s3.create_bucket(Bucket=s3.bucket)
