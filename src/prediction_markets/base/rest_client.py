"""
Base REST client with rate limiting and automatic retry.

Features:
- Rate limiting with token bucket algorithm
- Automatic retry with exponential backoff
- Request/response logging
- Session management
"""

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from typing import Any

import aiohttp

from prediction_markets.common.exceptions import (
    AuthenticationError,
    ConnectionError,
    NetworkError,
    RateLimitError,
    TimeoutError,
)

logger = logging.getLogger(__name__)


class HttpMethod(str, Enum):
    """HTTP methods."""

    GET = "GET"
    POST = "POST"
    PUT = "PUT"
    DELETE = "DELETE"
    PATCH = "PATCH"


@dataclass
class RestConfig:
    """REST client configuration."""

    base_url: str
    timeout: float = 30.0  # Request timeout in seconds
    rate_limit_requests: int = 10  # Requests per interval
    rate_limit_interval: float = 1.0  # Interval in seconds
    retry_attempts: int = 3
    retry_delay: float = 1.0  # Initial retry delay
    retry_delay_max: float = 10.0
    retry_multiplier: float = 2.0


@dataclass
class RestResponse:
    """REST API response wrapper."""

    status: int
    data: Any
    headers: dict[str, str]
    elapsed_ms: float


class RateLimiter:
    """Token bucket rate limiter."""

    def __init__(self, rate: int, interval: float) -> None:
        """
        Initialize rate limiter.

        Args:
            rate: Number of requests allowed per interval
            interval: Time interval in seconds
        """
        self.rate = rate
        self.interval = interval
        self.tokens = float(rate)
        self.last_update = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self) -> None:
        """Wait until a token is available."""
        async with self._lock:
            now = time.monotonic()
            elapsed = now - self.last_update
            self.tokens = min(self.rate, self.tokens + elapsed * (self.rate / self.interval))
            self.last_update = now

            if self.tokens < 1:
                wait_time = (1 - self.tokens) * (self.interval / self.rate)
                logger.debug(f"Rate limit: waiting {wait_time:.2f}s")
                await asyncio.sleep(wait_time)
                self.tokens = 0
            else:
                self.tokens -= 1


class BaseRestClient(ABC):
    """
    Base REST client with rate limiting and retry logic.

    Subclasses must implement:
    - _sign_request(method, path, params, data): Add authentication
    - _parse_error(response, data): Parse error response
    - _get_rate_limit_info(response): Extract rate limit info from response
    """

    def __init__(self, config: RestConfig, exchange: str) -> None:
        self.config = config
        self.exchange = exchange

        self._session: aiohttp.ClientSession | None = None
        self._rate_limiter = RateLimiter(
            config.rate_limit_requests,
            config.rate_limit_interval,
        )

        # Metrics
        self._request_count = 0
        self._last_request_time: float | None = None
        self._last_latency_ms: float | None = None

    @property
    def is_initialized(self) -> bool:
        """Check if session is initialized."""
        return self._session is not None and not self._session.closed

    @property
    def last_latency_ms(self) -> float | None:
        """Get latency of last request in milliseconds."""
        return self._last_latency_ms

    # === Abstract Methods ===

    @abstractmethod
    async def _sign_request(
        self,
        method: HttpMethod,
        path: str,
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
        headers: dict[str, str],
    ) -> dict[str, str]:
        """
        Sign request and return updated headers.

        Args:
            method: HTTP method
            path: API endpoint path
            params: Query parameters
            data: Request body data
            headers: Current headers

        Returns:
            Updated headers with authentication
        """
        pass

    @abstractmethod
    def _parse_error(self, status: int, data: Any) -> Exception:
        """
        Parse error response and return appropriate exception.

        Args:
            status: HTTP status code
            data: Response data

        Returns:
            Appropriate exception instance
        """
        pass

    @abstractmethod
    def _get_rate_limit_info(self, headers: dict[str, str]) -> dict[str, Any] | None:
        """
        Extract rate limit information from response headers.

        Returns:
            Dict with 'remaining', 'reset_at', etc. or None if not available
        """
        pass

    # === Session Management ===

    async def init(self) -> None:
        """Initialize HTTP session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=self.config.timeout)
            self._session = aiohttp.ClientSession(
                base_url=self.config.base_url,
                timeout=timeout,
            )
            logger.info(f"[{self.exchange}] REST client initialized")

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session is not None:
            await self._session.close()
            self._session = None
            logger.info(f"[{self.exchange}] REST client closed")

    # === Request Methods ===

    async def request(
        self,
        method: HttpMethod,
        path: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        headers: dict[str, str] | None = None,
        auth_required: bool = True,
    ) -> RestResponse:
        """
        Make HTTP request with rate limiting and retry.

        Args:
            method: HTTP method
            path: API endpoint path
            params: Query parameters
            data: Request body (will be JSON encoded)
            headers: Additional headers
            auth_required: Whether request needs authentication

        Returns:
            RestResponse with status, data, headers, and latency

        Raises:
            NetworkError: On connection/timeout errors
            RateLimitError: When rate limited
            AuthenticationError: On auth failures
        """
        if not self.is_initialized:
            await self.init()

        headers = headers or {}
        headers["Content-Type"] = "application/json"

        if auth_required:
            headers = await self._sign_request(method, path, params, data, headers)

        last_error: Exception | None = None

        for attempt in range(self.config.retry_attempts):
            # Wait for rate limit token
            await self._rate_limiter.acquire()

            start_time = time.monotonic()

            try:
                response = await self._make_request(method, path, params, data, headers)
                self._last_latency_ms = (time.monotonic() - start_time) * 1000
                self._request_count += 1
                self._last_request_time = time.time()

                # Check rate limit info
                rate_limit_info = self._get_rate_limit_info(dict(response.headers))
                if rate_limit_info:
                    logger.debug(f"[{self.exchange}] Rate limit: {rate_limit_info}")

                # Parse response
                response_data = await self._parse_response(response)

                # Handle errors
                if response.status >= 400:
                    error = self._parse_error(response.status, response_data)

                    # Don't retry auth errors or validation errors
                    if isinstance(error, AuthenticationError) or response.status < 500:
                        raise error

                    last_error = error
                else:
                    return RestResponse(
                        status=response.status,
                        data=response_data,
                        headers=dict(response.headers),
                        elapsed_ms=self._last_latency_ms,
                    )

            except aiohttp.ClientConnectorError as e:
                last_error = ConnectionError(
                    f"Connection failed: {e}",
                    exchange=self.exchange,
                )
            except asyncio.TimeoutError:
                last_error = TimeoutError(
                    f"Request timeout after {self.config.timeout}s",
                    exchange=self.exchange,
                    timeout_seconds=self.config.timeout,
                )
            except RateLimitError:
                raise
            except Exception as e:
                last_error = NetworkError(
                    f"Request failed: {e}",
                    exchange=self.exchange,
                )

            # Exponential backoff
            if attempt < self.config.retry_attempts - 1:
                delay = min(
                    self.config.retry_delay * (self.config.retry_multiplier ** attempt),
                    self.config.retry_delay_max,
                )
                logger.warning(
                    f"[{self.exchange}] Request failed (attempt {attempt + 1}), "
                    f"retrying in {delay:.1f}s: {last_error}"
                )
                await asyncio.sleep(delay)

        # All retries exhausted
        raise last_error or NetworkError("Request failed", exchange=self.exchange)

    async def _make_request(
        self,
        method: HttpMethod,
        path: str,
        params: dict[str, Any] | None,
        data: dict[str, Any] | None,
        headers: dict[str, str],
    ) -> aiohttp.ClientResponse:
        """Execute the actual HTTP request."""
        assert self._session is not None

        kwargs: dict[str, Any] = {
            "method": method.value,
            "url": path,
            "headers": headers,
        }

        if params:
            kwargs["params"] = params
        if data:
            kwargs["json"] = data

        return await self._session.request(**kwargs)

    async def _parse_response(self, response: aiohttp.ClientResponse) -> Any:
        """Parse response body."""
        content_type = response.headers.get("Content-Type", "")

        if "application/json" in content_type:
            return await response.json()
        else:
            return await response.text()

    # === Convenience Methods ===

    async def get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        auth_required: bool = True,
    ) -> RestResponse:
        """Make GET request."""
        return await self.request(HttpMethod.GET, path, params=params, auth_required=auth_required)

    async def post(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth_required: bool = True,
    ) -> RestResponse:
        """Make POST request."""
        return await self.request(
            HttpMethod.POST, path, params=params, data=data, auth_required=auth_required
        )

    async def put(
        self,
        path: str,
        data: dict[str, Any] | None = None,
        params: dict[str, Any] | None = None,
        auth_required: bool = True,
    ) -> RestResponse:
        """Make PUT request."""
        return await self.request(
            HttpMethod.PUT, path, params=params, data=data, auth_required=auth_required
        )

    async def delete(
        self,
        path: str,
        params: dict[str, Any] | None = None,
        auth_required: bool = True,
    ) -> RestResponse:
        """Make DELETE request."""
        return await self.request(
            HttpMethod.DELETE, path, params=params, auth_required=auth_required
        )
