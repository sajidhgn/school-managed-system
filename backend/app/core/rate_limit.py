"""Shared fixed-window rate limiting with Redis and an in-process fallback."""

from __future__ import annotations

import asyncio
import hashlib
import time

from redis.exceptions import RedisError

from app.core.cache import get_cache
from app.core.exceptions import RateLimitError
from app.core.logging import get_logger

logger = get_logger(__name__)

_memory: dict[str, tuple[int, float]] = {}
_memory_lock = asyncio.Lock()


async def reset_memory_rate_limits() -> None:
    """Clear the local fallback; used when a test app starts in Redis-free mode."""
    async with _memory_lock:
        _memory.clear()


def privacy_key(value: str) -> str:
    """Hash emails/IPs so Redis keys do not become a directory of user data."""
    return hashlib.sha256(value.strip().lower().encode()).hexdigest()[:32]


async def enforce_rate_limit(
    scope: str,
    identity: str,
    *,
    limit: int,
    window_seconds: int,
) -> None:
    key = f"rate:{scope}:{privacy_key(identity)}"
    client = get_cache()

    if client is not None:
        try:
            count = int(await client.incr(key))
            if count == 1:
                await client.expire(key, window_seconds)
            ttl = int(await client.ttl(key))
            retry_after = ttl if ttl > 0 else window_seconds
        except RedisError as exc:
            logger.warning("rate_limit_redis_failed", scope=scope, error=str(exc))
        else:
            if count > limit:
                raise RateLimitError(details={"retry_after": retry_after, "limit": limit})
            return

    now = time.monotonic()
    async with _memory_lock:
        count, expires_at = _memory.get(key, (0, now + window_seconds))
        if expires_at <= now:
            count, expires_at = 0, now + window_seconds
        count += 1
        _memory[key] = (count, expires_at)
        retry_after = max(1, int(expires_at - now))

    if count > limit:
        raise RateLimitError(details={"retry_after": retry_after, "limit": limit})
