# =============================================================
# auth.py — JWT Authentication + RBAC + Security Hardening
# NABDH AI Maintenance Platform v4
# =============================================================

import os
import re
import logging
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Annotated, Optional
from uuid import uuid4

import redis as _redis_lib
from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
from passlib.context import CryptContext
from pydantic import BaseModel, Field, ConfigDict

import config
import database

logger = logging.getLogger(__name__)

# =============================================================
# PASSWORD HASHING
# =============================================================

_pwd_context = CryptContext(schemes=["sha256_crypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# =============================================================
# PASSWORD POLICY
# =============================================================

_PASSWORD_RULES: list[tuple[str, str]] = [
    (r".{8,}",        "Must be at least 8 characters long."),
    (r"[A-Z]",        "Must contain at least one uppercase letter (A-Z)."),
    (r"\d",           "Must contain at least one digit (0-9)."),
    (r"[!@#$%^&*]",   "Must contain at least one special character (!@#$%^&*)."),
]


def validate_password(password: str) -> list[str]:
    """
    Returns a list of unmet policy rules.
    Empty list means the password is valid.
    """
    return [msg for pattern, msg in _PASSWORD_RULES if not re.search(pattern, password)]


# =============================================================
# ROLE HIERARCHY
# =============================================================

class UserRole(str, Enum):
    VIEWER   = "viewer"    # read-only: history, analytics, alerts
    OPERATOR = "operator"  # viewer + predict + acknowledge alerts
    ADMIN    = "admin"     # operator + audit + register users + security logs

_ROLE_LEVEL: dict[UserRole, int] = {
    UserRole.VIEWER:   0,
    UserRole.OPERATOR: 1,
    UserRole.ADMIN:    2,
}


# =============================================================
# USER MODEL
# =============================================================

class User(BaseModel):
    username:        str
    hashed_password: str
    role:            UserRole
    is_active:       bool = True


class UserPublic(BaseModel):
    username: str
    role:     UserRole


# =============================================================
# TOKEN MODELS
# =============================================================

class Token(BaseModel):
    access_token:  str
    refresh_token: str
    token_type:    str = "bearer"
    expires_in:    int = Field(description="Access token lifetime in seconds")


class TokenPayload(BaseModel):
    sub:  str
    role: str
    type: str   # "access" | "refresh"
    jti:  str   # unique token ID — used for revocation


class RefreshRequest(BaseModel):
    refresh_token: str


class LogoutRequest(BaseModel):
    refresh_token: str


class RegisterRequest(BaseModel):
    model_config = ConfigDict(strict=True, extra="forbid")
    username: str  = Field(min_length=3, max_length=50)
    password: str  = Field(min_length=8)
    role:     UserRole = UserRole.VIEWER


# =============================================================
# REDIS TOKEN STORE
# Handles: revocation, active refresh tracking, reuse detection.
# Falls back to in-memory if REDIS_URL is not set (dev only).
# =============================================================

class _TokenStore:
    """
    Redis-backed store for:
      - revoked:{jti}              → "1"  TTL = remaining token lifetime
      - active_refresh:{jti}       → username  TTL = refresh token lifetime
      - user_sessions:{username}   → set of active refresh JTIs
    """

    def __init__(self) -> None:
        self._redis: Optional[_redis_lib.Redis] = None
        self._fallback_revoked: set[str]        = set()

        if config.REDIS_URL:
            try:
                pool = _redis_lib.ConnectionPool.from_url(
                    config.REDIS_URL,
                    decode_responses=True,
                    max_connections=10,
                )
                r = _redis_lib.Redis(connection_pool=pool)
                r.ping()
                self._redis = r
                logger.info("Token store: Redis connected — %s", config.REDIS_URL)
            except Exception as exc:
                raise RuntimeError(
                    f"REDIS_URL is configured but connection failed: {exc}. "
                    "Ensure Redis is running or remove REDIS_URL to use in-memory fallback."
                )
        else:
            logger.warning(
                "REDIS_URL not set — using in-memory token store. "
                "Revoked tokens will NOT survive restart. Set REDIS_URL for production."
            )

    # ── Revocation ──────────────────────────────────────────────

    def revoke(self, jti: str, ttl_seconds: int) -> None:
        """Mark a token as revoked for the remainder of its natural lifetime."""
        if ttl_seconds <= 0:
            return
        if self._redis:
            self._redis.setex(f"revoked:{jti}", ttl_seconds, "1")
        else:
            self._fallback_revoked.add(jti)

    def is_revoked(self, jti: str) -> bool:
        if self._redis:
            return bool(self._redis.exists(f"revoked:{jti}"))
        return jti in self._fallback_revoked

    # ── Active refresh tracking ──────────────────────────────────

    def track_refresh(self, username: str, jti: str, ttl_seconds: int) -> None:
        """Register a newly issued refresh token as active."""
        if self._redis:
            self._redis.setex(f"active_refresh:{jti}", ttl_seconds, username)
            self._redis.sadd(f"user_sessions:{username}", jti)
            self._redis.expire(f"user_sessions:{username}", ttl_seconds)

    def is_active_refresh(self, jti: str) -> bool:
        """
        Returns True if the refresh token is currently active (not consumed or expired).
        In fallback mode, always returns True — we cannot track without Redis.
        """
        if self._redis:
            return bool(self._redis.exists(f"active_refresh:{jti}"))
        return True

    def consume_refresh(self, jti: str, remaining_ttl: int, username: str) -> None:
        """
        Consume a refresh token: remove from active set, add to revoked.
        Called when a valid refresh token is used to issue a new pair.
        """
        if self._redis:
            self._redis.delete(f"active_refresh:{jti}")
            self._redis.srem(f"user_sessions:{username}", jti)
            self.revoke(jti, remaining_ttl)
        else:
            self._fallback_revoked.add(jti)

    def wipe_user_sessions(self, username: str) -> list[str]:
        """
        Revoke ALL active refresh tokens for a user.
        Called on reuse detection — assumes the account is compromised.
        Returns list of wiped JTIs for audit logging.
        """
        wiped: list[str] = []
        max_ttl = config.REFRESH_TOKEN_EXPIRE_DAYS * 86400
        if self._redis:
            jtis = self._redis.smembers(f"user_sessions:{username}")
            for jti in jtis:
                self._redis.delete(f"active_refresh:{jti}")
                self.revoke(jti, max_ttl)
                wiped.append(jti)
            self._redis.delete(f"user_sessions:{username}")
        return wiped


_token_store = _TokenStore()


# =============================================================
# IN-MEMORY USER STORE
# Phase 1 only — replaced by PostgreSQL in Phase 2.
# =============================================================

def _build_user_store() -> dict[str, User]:
    store: dict[str, User] = {}

    admin_pass = os.getenv("ADMIN_PASSWORD", "admin123")
    if admin_pass in ("admin123", "REPLACE_WITH_STRONG_PASSWORD"):
        logger.warning(
            "ADMIN_PASSWORD is a default value — change it in .env before any deployment."
        )

    for env_name, env_pass, role in [
        ("ADMIN_USERNAME",    os.getenv("ADMIN_PASSWORD",    "admin123"),    UserRole.ADMIN),
        ("OPERATOR_USERNAME", os.getenv("OPERATOR_PASSWORD", "operator123"), UserRole.OPERATOR),
        ("VIEWER_USERNAME",   os.getenv("VIEWER_PASSWORD",   "viewer123"),   UserRole.VIEWER),
    ]:
        username = os.getenv(env_name, role.value)
        store[username] = User(
            username        = username,
            hashed_password = hash_password(env_pass),
            role            = role,
        )

    return store


_USER_STORE: dict[str, User] = _build_user_store()


# =============================================================
# SECURITY AUDIT HELPERS
# =============================================================

def _trace() -> str:
    return str(uuid4())


def _ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _ua(request: Request) -> str:
    return request.headers.get("user-agent", "")


def _log_event(
    event_type: str,
    severity:   str,
    request:    Request,
    username:   Optional[str] = None,
    detail:     Optional[dict] = None,
) -> str:
    trace_id = _trace()
    try:
        database.insert_security_event(
            trace_id   = trace_id,
            event_type = event_type,
            severity   = severity,
            username   = username,
            ip_address = _ip(request),
            user_agent = _ua(request),
            detail     = detail,
        )
    except Exception as exc:
        logger.warning("Security audit write failed: %s", exc)

    if severity == "CRITICAL":
        logger.critical(
            "[SECURITY][%s] %s — user=%s ip=%s detail=%s",
            trace_id, event_type, username, _ip(request), detail,
        )
    elif severity == "WARNING":
        logger.warning(
            "[SECURITY][%s] %s — user=%s ip=%s",
            trace_id, event_type, username, _ip(request),
        )
    else:
        logger.info(
            "[SECURITY][%s] %s — user=%s ip=%s",
            trace_id, event_type, username, _ip(request),
        )
    return trace_id


# =============================================================
# JWT UTILITIES
# =============================================================

def _create_token(
    sub:        str,
    role:       str,
    token_type: str,
    expires:    timedelta,
) -> tuple[str, str, datetime]:
    """
    Returns (encoded_token, jti, expires_at).
    The JTI and expiry are returned so the caller can track them.
    """
    jti        = str(uuid4())
    expires_at = datetime.now(timezone.utc) + expires
    payload    = {
        "sub":  sub,
        "role": role,
        "type": token_type,
        "jti":  jti,
        "iat":  datetime.now(timezone.utc),
        "exp":  expires_at,
    }
    token = jwt.encode(payload, config.JWT_SECRET_KEY, algorithm=config.JWT_ALGORITHM)
    return token, jti, expires_at


def create_access_token(username: str, role: str) -> tuple[str, str, datetime]:
    return _create_token(
        sub        = username,
        role       = role,
        token_type = "access",
        expires    = timedelta(minutes=config.ACCESS_TOKEN_EXPIRE_MINUTES),
    )


def create_refresh_token(username: str, role: str) -> tuple[str, str, datetime]:
    return _create_token(
        sub        = username,
        role       = role,
        token_type = "refresh",
        expires    = timedelta(days=config.REFRESH_TOKEN_EXPIRE_DAYS),
    )


def _decode_token(token: str) -> TokenPayload:
    try:
        payload = jwt.decode(
            token,
            config.JWT_SECRET_KEY,
            algorithms=[config.JWT_ALGORITHM],
        )
        return TokenPayload(
            sub  = payload["sub"],
            role = payload["role"],
            type = payload["type"],
            jti  = payload["jti"],
        )
    except JWTError as exc:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = f"Token validation failed: {exc}",
            headers     = {"WWW-Authenticate": "Bearer"},
        )


def _remaining_ttl(token: str) -> int:
    """Return seconds until a token expires (0 if already expired)."""
    try:
        payload = jwt.decode(
            token,
            config.JWT_SECRET_KEY,
            algorithms=[config.JWT_ALGORITHM],
        )
        exp = payload.get("exp", 0)
        remaining = int(exp - datetime.now(timezone.utc).timestamp())
        return max(remaining, 0)
    except Exception:
        return 0


# =============================================================
# FASTAPI DEPENDENCIES
# =============================================================

_oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/login")


def get_current_user(
    request: Request,
    token:   Annotated[str, Depends(_oauth2_scheme)],
) -> User:
    try:
        payload = _decode_token(token)
    except HTTPException as exc:
        _log_event(
            event_type = "unauthorized",
            severity   = "WARNING",
            request    = request,
            detail     = {"reason": exc.detail, "endpoint": str(request.url.path)},
        )
        raise

    if payload.type != "access":
        _log_event("unauthorized", "WARNING", request,
                   detail={"reason": "Refresh token used as access token", "endpoint": str(request.url.path)})
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Expected an access token, not a refresh token.",
        )

    if _token_store.is_revoked(payload.jti):
        _log_event("unauthorized", "WARNING", request, username=payload.sub,
                   detail={"reason": "Revoked access token presented", "jti": payload.jti})
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Token has been revoked.",
            headers     = {"WWW-Authenticate": "Bearer"},
        )

    user = _USER_STORE.get(payload.sub)
    if not user:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found.")
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled.")

    return user


def require_role(minimum_role: UserRole):
    """Returns a FastAPI dependency that enforces a minimum role level."""
    def _check(
        request:      Request,
        current_user: Annotated[User, Depends(get_current_user)],
    ) -> User:
        if _ROLE_LEVEL[current_user.role] < _ROLE_LEVEL[minimum_role]:
            _log_event(
                event_type = "unauthorized",
                severity   = "WARNING",
                request    = request,
                username   = current_user.username,
                detail     = {
                    "reason":   f"Insufficient role: '{current_user.role}' < '{minimum_role}'",
                    "endpoint": str(request.url.path),
                },
            )
            raise HTTPException(
                status_code = status.HTTP_403_FORBIDDEN,
                detail = (
                    f"Access denied. Your role '{current_user.role.value}' does not meet "
                    f"the required minimum role '{minimum_role.value}'."
                ),
            )
        return current_user
    return _check


require_viewer   = Depends(require_role(UserRole.VIEWER))
require_operator = Depends(require_role(UserRole.OPERATOR))
require_admin    = Depends(require_role(UserRole.ADMIN))


# =============================================================
# AUTH ROUTER
# =============================================================

router = APIRouter(prefix="/auth", tags=["Authentication"])


@router.post("/login", response_model=Token, summary="Obtain JWT access + refresh tokens")
def login(
    request: Request,
    form:    Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    user = _USER_STORE.get(form.username)

    if not user or not verify_password(form.password, user.hashed_password):
        _log_event(
            event_type = "login_failure",
            severity   = "WARNING",
            request    = request,
            username   = form.username,
            detail     = {"reason": "Incorrect username or password"},
        )
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Incorrect username or password.",
            headers     = {"WWW-Authenticate": "Bearer"},
        )

    if not user.is_active:
        _log_event("login_failure", "WARNING", request, username=form.username,
                   detail={"reason": "Account disabled"})
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Account is disabled.")

    access_token,  access_jti,  _          = create_access_token(user.username, user.role.value)
    refresh_token, refresh_jti, refresh_exp = create_refresh_token(user.username, user.role.value)

    refresh_ttl = int((refresh_exp - datetime.now(timezone.utc)).total_seconds())
    _token_store.track_refresh(user.username, refresh_jti, refresh_ttl)

    _log_event("login_success", "INFO", request, username=user.username,
               detail={"role": user.role.value})

    return Token(
        access_token  = access_token,
        refresh_token = refresh_token,
        expires_in    = config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/refresh", response_model=Token, summary="Exchange refresh token for new token pair")
def refresh(
    request: Request,
    body:    RefreshRequest,
) -> Token:
    payload = _decode_token(body.refresh_token)

    if payload.type != "refresh":
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Expected a refresh token, not an access token.",
        )

    # ── Reuse detection ───────────────────────────────────────
    if _token_store.is_revoked(payload.jti):
        # This token was already consumed — token reuse detected.
        # The refresh token family is compromised. Wipe all sessions.
        wiped = _token_store.wipe_user_sessions(payload.sub)
        _log_event(
            event_type = "token_reuse",
            severity   = "CRITICAL",
            request    = request,
            username   = payload.sub,
            detail     = {
                "revoked_jti":  payload.jti,
                "sessions_wiped": len(wiped),
                "message": "Refresh token reuse detected — all sessions invalidated",
            },
        )
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = (
                "Security alert: this refresh token has already been used. "
                "All sessions have been invalidated. Please log in again."
            ),
        )

    if not _token_store.is_active_refresh(payload.jti):
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "Refresh token is not active or has expired.",
        )

    user = _USER_STORE.get(payload.sub)
    if not user or not user.is_active:
        raise HTTPException(
            status_code = status.HTTP_401_UNAUTHORIZED,
            detail      = "User not found or account is disabled.",
        )

    # ── Rotate: consume old, issue new ────────────────────────
    remaining = _remaining_ttl(body.refresh_token)
    _token_store.consume_refresh(payload.jti, remaining, user.username)

    new_access,  new_access_jti,  _              = create_access_token(user.username, user.role.value)
    new_refresh, new_refresh_jti, new_refresh_exp = create_refresh_token(user.username, user.role.value)

    new_refresh_ttl = int((new_refresh_exp - datetime.now(timezone.utc)).total_seconds())
    _token_store.track_refresh(user.username, new_refresh_jti, new_refresh_ttl)

    _log_event(
        event_type = "token_refresh",
        severity   = "INFO",
        request    = request,
        username   = user.username,
        detail     = {"old_jti": payload.jti, "new_jti": new_refresh_jti},
    )

    return Token(
        access_token  = new_access,
        refresh_token = new_refresh,
        expires_in    = config.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
    )


@router.post("/logout", status_code=status.HTTP_200_OK, summary="Revoke current session tokens")
def logout(
    request:      Request,
    body:         LogoutRequest,
    current_user: Annotated[User, Depends(get_current_user)],
) -> dict:
    remaining = _remaining_ttl(body.refresh_token)
    try:
        payload = _decode_token(body.refresh_token)
        _token_store.consume_refresh(payload.jti, remaining, current_user.username)
    except Exception:
        pass  # Best-effort revocation

    logger.info("Logout — user='%s'", current_user.username)
    return {"message": "Successfully logged out."}


@router.post(
    "/register",
    response_model = UserPublic,
    status_code    = status.HTTP_201_CREATED,
    summary        = "Create a new user account (admin only)",
)
def register(
    request:      Request,
    body:         RegisterRequest,
    current_user: Annotated[User, Depends(require_role(UserRole.ADMIN))],
) -> UserPublic:
    # Validate password policy
    violations = validate_password(body.password)
    if violations:
        raise HTTPException(
            status_code = status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail      = {"message": "Password does not meet policy requirements.", "violations": violations},
        )

    if body.username in _USER_STORE:
        raise HTTPException(
            status_code = status.HTTP_409_CONFLICT,
            detail      = f"Username '{body.username}' already exists.",
        )

    new_user = User(
        username        = body.username,
        hashed_password = hash_password(body.password),
        role            = body.role,
    )
    _USER_STORE[body.username] = new_user

    logger.info(
        "User registered — username='%s' role='%s' by admin='%s'",
        body.username, body.role.value, current_user.username,
    )
    # Note: Phase 1 stores users in memory. They will not persist across restarts.
    # Phase 2 (PostgreSQL) will provide durable user storage.
    return UserPublic(username=new_user.username, role=new_user.role)


@router.get("/me", response_model=UserPublic, summary="Return the current authenticated user")
def get_me(
    current_user: Annotated[User, Depends(get_current_user)],
) -> UserPublic:
    return UserPublic(username=current_user.username, role=current_user.role)
