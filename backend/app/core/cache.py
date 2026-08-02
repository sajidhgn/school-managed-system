"""Redis client and the permission cache (spec §4.2).

WHY THIS FILE EXISTS
    Permissions are deliberately NOT embedded in the access token. Only `pv`, the
    role's `permissions_version`, is. That means every authorised request must
    resolve a role's permission set from somewhere -- and "somewhere" cannot be a
    Postgres join on the hot path of every request in the system.

RESPONSIBILITY
    Own the Redis connection and the cache-aside protocol for permission sets.
    It does NOT read Postgres; the caller supplies a loader. That keeps this module
    free of any dependency on the RBAC schema and makes it testable with a fake.

INTERACTIONS
    * `api/deps.py::require()` calls `get_role_permissions` on every guarded route.
    * `modules/rbac/service.py` bumps `permissions_version`, which is what actually
      invalidates the cache.

=============================================================================
THE VERSION IN THE KEY IS THE INVALIDATION STRATEGY
=============================================================================
    Key shape: `perm:{role_id}:{pv}`.

    When a principal edits a role, `roles.permissions_version` increments. Every
    access token minted before that edit carries the OLD `pv`, so on its next
    request it looks up a key that no longer describes current state -- and the
    dependency detects the mismatch against the database row and re-resolves.
    New tokens carry the new `pv` and hit a fresh key.

    WHY NOT JUST DELETE THE KEY ON EDIT
        Because deletion is a race. Between the DELETE and the next write, a
        concurrent request can repopulate the old key from a snapshot it read
        before the edit committed, and the stale set then lives until TTL. Making
        the version part of the key means the old value is never *consulted* again,
        so it does not matter when it is evicted. This is the difference between
        "revocation usually takes effect" and "revocation takes effect".

    THIS IS THE FIX FOR THE CLASSIC BUG the spec calls out: a principal revokes a
    teacher's access and it silently takes a full token lifetime to apply. Here it
    applies on the teacher's very next request.

DEGRADED MODE
    Every operation swallows connection errors and reports a miss. Redis being down
    must slow the system (falling back to Postgres), never break it -- an
    authorisation system that fails closed on a cache outage is an outage.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from redis.asyncio import Redis
from redis.exceptions import RedisError

from app.core.config import Settings, get_settings
from app.core.logging import get_logger

logger = get_logger(__name__)

_client: Redis | None = None

# Separator chosen so a permission code (which contains ':') cannot be confused with
# the delimiter. Codes never contain a newline, so this is unambiguous.
_MEMBER_SEP = "\n"


def init_cache(settings: Settings | None = None) -> Redis | None:
    """Create the Redis client. Idempotent; called from lifespan startup."""
    global _client
    settings = settings or get_settings()

    if not settings.REDIS_ENABLED:
        return None
    if _client is not None:
        return _client

    _client = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
        health_check_interval=30,
    )
    logger.info("redis_initialised", url=settings.REDIS_URL)
    return _client


async def dispose_cache() -> None:
    """Close the Redis connection pool. Called from lifespan shutdown."""
    global _client
    if _client is not None:
        await _client.aclose()
        logger.info("redis_disposed")
    _client = None


def get_cache() -> Redis | None:
    """The live client, or None when Redis is disabled or not yet initialised."""
    return _client


def permission_key(role_id: str, permissions_version: int) -> str:
    return f"perm:{role_id}:{permissions_version}"


async def get_role_permissions(
    role_id: str,
    permissions_version: int,
    loader: Callable[[], Awaitable[frozenset[str]]],
    *,
    settings: Settings | None = None,
) -> frozenset[str]:
    """Cache-aside read of a role's permission set.

    On a miss (or with Redis unavailable) the `loader` coroutine is awaited to fetch
    the authoritative set from Postgres, and the result is written back.

    An EMPTY set is a legitimate, cacheable answer -- a freshly created custom role
    with no permissions yet. Redis cannot store an empty set, so the sentinel below
    distinguishes "cached: this role has no permissions" from "not cached". Without
    it, every request against a permission-less role would fall through to Postgres,
    which is precisely the role an attacker probing an unconfigured account would
    hit hardest.
    """
    settings = settings or get_settings()
    client = get_cache()
    key = permission_key(role_id, permissions_version)

    if client is not None:
        try:
            cached = await client.get(key)
            if cached is not None:
                # The client is built with `decode_responses=True`, so values are
                # `str`. redis-py's type stubs still describe the bytes case, so the
                # narrowing is explicit here rather than an ignore comment.
                text = cached.decode() if isinstance(cached, bytes) else str(cached)
                return frozenset(text.split(_MEMBER_SEP)) if text else frozenset()
        except RedisError as exc:
            # Warn, do not raise: a cache outage degrades latency, not correctness.
            logger.warning("permission_cache_read_failed", key=key, error=str(exc))

    permissions = await loader()

    if client is not None:
        try:
            await client.set(
                key,
                _MEMBER_SEP.join(sorted(permissions)),
                ex=settings.PERMISSION_CACHE_TTL_SECONDS,
            )
        except RedisError as exc:
            logger.warning("permission_cache_write_failed", key=key, error=str(exc))

    return permissions


async def invalidate_role_permissions(role_id: str, permissions_version: int) -> None:
    """Best-effort eviction of one specific version of a role's cached set.

    Strictly an optimisation. Correctness comes from `permissions_version` being
    part of the key -- after a bump, nothing reads the old key again regardless of
    whether this succeeded. Called anyway so that a busy role's superseded entries
    do not sit in memory for the full TTL.
    """
    client = get_cache()
    if client is None:
        return
    try:
        await client.delete(permission_key(role_id, permissions_version))
    except RedisError as exc:
        logger.warning("permission_cache_invalidate_failed", role_id=role_id, error=str(exc))
