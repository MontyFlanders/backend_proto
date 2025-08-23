# app/main.py
import os
from fastapi import FastAPI, Request, HTTPException, Response
from starlette.responses import RedirectResponse, JSONResponse
from starlette.middleware.sessions import SessionMiddleware
from authlib.integrations.starlette_client import OAuth
from authlib.common.security import generate_token
from authlib.oauth2.rfc7636 import create_s256_code_challenge

from strawberry.fastapi import GraphQLRouter
from . import graphql_schema
from app.services.graph_service import GraphService
from app.services.s3_service import S3Service
from app.security.sessions import MemorySessions  # your simple in-memory sessions

# --- Config -------------------------------------------------------------------
SESSION_COOKIE = "__Host_sid"  # For local HTTP, consider using just "sid"
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
app.state.sessions = MemorySessions(ttl_seconds=SESSION_TTL)

# --- OAuth (Keycloak) ---------------------------------------------------------
oauth = OAuth()
oauth.register(
    name="keycloak",
    client_id=OIDC_CLIENT_ID,
    client_secret=OIDC_CLIENT_SECRET,
    # Front-channel (browser) → localhost on host
    authorize_url="http://localhost:8080/realms/dev/protocol/openid-connect/auth",
    # Back-channel (API container) → service DNS name
    access_token_url="http://keycloak:8080/realms/dev/protocol/openid-connect/token",
    client_kwargs={"scope": "openid email profile"},
    # Minimal metadata so parse_id_token validates 'iss' and fetches JWKS
    server_metadata={
        "issuer": "http://localhost:8080/realms/dev",
        "jwks_uri": "http://keycloak:8080/realms/dev/protocol/openid-connect/certs",
        "userinfo_endpoint": "http://keycloak:8080/realms/dev/protocol/openid-connect/userinfo",
        "end_session_endpoint": "http://localhost:8080/realms/dev/protocol/openid-connect/logout",
    },
)

def set_session_cookie(resp: Response, sid: str):
    resp.set_cookie(
        key=SESSION_COOKIE,
        value=sid,
        httponly=True,
        samesite="lax",
        max_age=SESSION_TTL,
        path="/",
        secure=SECURE_COOKIE,  # set True in prod/HTTPS
    )

# --- Auth routes --------------------------------------------------------------
@app.get("/auth/login")
async def login(request: Request):
    # PKCE: create verifier + S256 challenge
    code_verifier = generate_token(48)  # RFC 7636: 43–128 chars
    request.session["code_verifier"] = code_verifier
    code_challenge = create_s256_code_challenge(code_verifier)

    return await oauth.keycloak.authorize_redirect(
        request,
        redirect_uri=REDIRECT_URI,
        code_challenge=code_challenge,
        code_challenge_method="S256",
    )

@app.get("/auth/callback")
async def auth_callback(request: Request):
    if err := request.query_params.get("error"):
        raise HTTPException(
            status_code=400,
            detail=f"OIDC error: {err} - {request.query_params.get('error_description')}"
        )

    code_verifier = request.session.pop("code_verifier", None)
    token = await oauth.keycloak.authorize_access_token(
        request,
        code_verifier=code_verifier,
    )
    claims = await oauth.keycloak.parse_id_token(request, token)

    iss = claims["iss"]; sub = claims["sub"]
    email = claims.get("email")
    name = claims.get("name") or claims.get("preferred_username")

    # TODO: look up or create your local user here from (iss, sub)
    user_id = 1

    payload = {
        "user_id": user_id,
        "issuer": iss,
        "subject": sub,
        "email": email,
        "name": name,
        "roles": ["user"],
        "id_token": token.get("id_token"),  # optional (for SSO logout)
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
