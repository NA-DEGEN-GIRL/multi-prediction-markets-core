"""
Rate limiting utilities.

This module provides rate limiting functionality that can be used
independently of the REST client.
"""

import asyncio
import time
from dataclasses import dataclass


@dataclass
class RateLimitConfig:
    """Rate limit configuration."""

    requests_per_second: float = 10.0
    burst_size: int = 10


class TokenBucketRateLimiter:
    """
    Token bucket rate limiter for controlling request rates.

    This implementation allows burst traffic up to the bucket size,
    then throttles to the configured rate.

    Example:
        ```python
        limiter = TokenBucketRateLimiter(rate=10.0, burst=20)

        async def make_request():
            await limiter.acquire()
            # Make actual request
        ```
    """

    def __init__(self, rate: float, burst: int | None = None) -> None:
        """
        Initialize rate limiter.

        Args:
            rate: Requests per second
            burst: Maximum burst size (defaults to rate)
        """
        self.rate = rate
        self.burst = burst or int(rate)
        self.tokens = float(self.burst)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self, tokens: int = 1) -> float:
        """
        Acquire tokens, waiting if necessary.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            Time waited in seconds
        """
        async with self._lock:
            waited = 0.0

            while True:
                now = time.monotonic()
                elapsed = now - self.last_update

                # Refill tokens
                self.tokens = min(
                    self.burst,
                    self.tokens + elapsed * self.rate,
                )
                self.last_update = now

                if self.tokens >= tokens:
                    self.tokens -= tokens
                    return waited

                # Calculate wait time
                wait_time = (tokens - self.tokens) / self.rate
                await asyncio.sleep(wait_time)
                waited += wait_time

    def try_acquire(self, tokens: int = 1) -> bool:
        """
        Try to acquire tokens without waiting.

        Args:
            tokens: Number of tokens to acquire

        Returns:
            True if tokens were acquired, False otherwise
        """
        now = time.monotonic()
        elapsed = now - self.last_update

        self.tokens = min(
            self.burst,
            self.tokens + elapsed * self.rate,
        )
        self.last_update = now

        if self.tokens >= tokens:
            self.tokens -= tokens
            return True
        return False

    @property
    def available_tokens(self) -> float:
        """Get current number of available tokens."""
        now = time.monotonic()
        elapsed = now - self.last_update
        return min(self.burst, self.tokens + elapsed * self.rate)


class SlidingWindowRateLimiter:
    """
    Sliding window rate limiter.

    Tracks requests within a time window and enforces limits.
    More accurate than token bucket but uses more memory.

    Example:
        ```python
        limiter = SlidingWindowRateLimiter(max_requests=100, window_seconds=60)

        async def make_request():
            await limiter.acquire()
            # Make actual request
        ```
    """

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        """
        Initialize sliding window rate limiter.

        Args:
            max_requests: Maximum requests allowed in window
            window_seconds: Window size in seconds
        """
        self.max_requests = max_requests
        self.window_seconds = window_seconds
        self._timestamps: list[float] = []
        self._lock = asyncio.Lock()

    async def acquire(self) -> float:
        """
        Acquire permission to make a request.

        Returns:
            Time waited in seconds
        """
        async with self._lock:
            waited = 0.0
            now = time.monotonic()

            # Remove old timestamps
            cutoff = now - self.window_seconds
            self._timestamps = [t for t in self._timestamps if t > cutoff]

            while len(self._timestamps) >= self.max_requests:
                # Wait until oldest request expires
                oldest = self._timestamps[0]
                wait_time = oldest + self.window_seconds - now + 0.001
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                    waited += wait_time
                    now = time.monotonic()

                # Cleanup again
                cutoff = now - self.window_seconds
                self._timestamps = [t for t in self._timestamps if t > cutoff]

            self._timestamps.append(now)
            return waited

    @property
    def current_usage(self) -> int:
        """Get current number of requests in window."""
        now = time.monotonic()
        cutoff = now - self.window_seconds
        return sum(1 for t in self._timestamps if t > cutoff)

    @property
    def available_requests(self) -> int:
        """Get number of requests available."""
        return max(0, self.max_requests - self.current_usage)
