# app/security/oidc.py
import os, time, logging
import httpx
from authlib.jose import jwt, JsonWebKey
from authlib.jose.errors import BadSignatureError, ExpiredTokenError, JoseError

log = logging.getLogger("uvicorn")

OIDC_ISSUER   = os.getenv("OIDC_ISSUER")                 # e.g. https://auth.antiquityatlas.com/realms/dev
OIDC_AUDIENCE = os.getenv("OIDC_AUDIENCE", "api")

_JWKS     = None
_JWKS_TS  = 0.0
_JWKS_TTL = 600  # seconds

async def _refresh_jwks():
    """Fetch discovery + JWKS and cache them."""
    global _JWKS, _JWKS_TS
    if not OIDC_ISSUER:
        raise JoseError("missing_oidc_issuer_env")

    config_url = f"{OIDC_ISSUER}/.well-known/openid-configuration"
    log.info("OIDC: fetching discovery: %s", config_url)

    async with httpx.AsyncClient(timeout=10) as client:
        try:
            r = await client.get(config_url)
            r.raise_for_status()
        except Exception as e:
            raise JoseError(f"discovery_fetch_failed: {e}") from e

        jwks_uri = r.json().get("jwks_uri")
        if not jwks_uri:
            raise JoseError("discovery_missing_jwks_uri")

        log.info("OIDC: fetching JWKS: %s", jwks_uri)
        try:
            r2 = await client.get(jwks_uri)
            r2.raise_for_status()
        except Exception as e:
            raise JoseError(f"jwks_fetch_failed: {e}") from e

        try:
            _JWKS = JsonWebKey.import_key_set(r2.json())
        except Exception as e:
            raise JoseError(f"jwks_parse_failed: {e}") from e

        _JWKS_TS = time.time()
        log.info("OIDC: JWKS loaded ok; ttl=%ss", _JWKS_TTL)

async def _get_jwks():
    """Return cached JWKS, refreshing if stale/missing."""
    if _JWKS is None or (time.time() - _JWKS_TS) > _JWKS_TTL:
        await _refresh_jwks()
    return _JWKS

async def verify_access_token(token: str) -> dict:
    jwks = await _get_jwks()

    # Decode & verify signature
    try:
        claims = jwt.decode(token, jwks)
    except BadSignatureError as e:
        raise JoseError("bad_signature") from e
    except JoseError as e:
        raise JoseError(f"decode_failed: {e}") from e

    # ---- Time-based validations (Authlib-compatible) ----
    now = int(time.time())
    try:
        # Newer Authlib supports validate(now=..., leeway=...)
        claims.validate(now=now, leeway=0)
    except TypeError:
        # Older Authlib: validate_exp/nbf/iat require (now, leeway)
        try:
            if "exp" in claims:
                claims.validate_exp(now, 0)
            if "nbf" in claims:
                claims.validate_nbf(now, 0)
            if "iat" in claims:
                claims.validate_iat(now, 0)
        except ExpiredTokenError as e:
            raise JoseError("expired") from e
        except JoseError as e:
            raise JoseError(f"invalid_time_claims:{e}") from e

    # Issuer check
    iss = claims.get("iss")
    if iss != OIDC_ISSUER:
        raise JoseError(f"bad_issuer expected={OIDC_ISSUER} got={iss}")

    # Audience check
    aud = claims.get("aud")
    expected = OIDC_AUDIENCE
    ok = (isinstance(aud, str) and aud == expected) or (
        isinstance(aud, (list, tuple)) and expected in aud
    )
    if not ok:
        raise JoseError(f"bad_audience expected={expected} aud={aud}")

    return dict(claims)