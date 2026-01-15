"""
Custom exceptions for prediction markets library.

Exception hierarchy:
    PredictionMarketError (base)
    ├── ExchangeError
    │   ├── AuthenticationError
    │   ├── InsufficientFundsError
    │   ├── InvalidOrderError
    │   └── MarketNotFoundError
    ├── NetworkError
    │   ├── ConnectionError
    │   ├── TimeoutError
    │   └── WebSocketError
    └── RateLimitError
"""

from typing import Any


class PredictionMarketError(Exception):
    """Base exception for all prediction market errors."""

    def __init__(self, message: str, exchange: str | None = None, raw: Any = None) -> None:
        self.message = message
        self.exchange = exchange
        self.raw = raw  # Raw error response from exchange
        super().__init__(self.message)

    def __str__(self) -> str:
        if self.exchange:
            return f"[{self.exchange}] {self.message}"
        return self.message


# === Exchange Errors ===


class ExchangeError(PredictionMarketError):
    """General exchange-related error."""

    pass


class AuthenticationError(ExchangeError):
    """Authentication or authorization failure."""

    pass


class InsufficientFundsError(ExchangeError):
    """Insufficient balance to execute order."""

    def __init__(
        self,
        message: str,
        exchange: str | None = None,
        required: float | None = None,
        available: float | None = None,
        raw: Any = None,
    ) -> None:
        super().__init__(message, exchange, raw)
        self.required = required
        self.available = available


class InvalidOrderError(ExchangeError):
    """Invalid order parameters."""

    def __init__(
        self,
        message: str,
        exchange: str | None = None,
        order_params: dict[str, Any] | None = None,
        raw: Any = None,
    ) -> None:
        super().__init__(message, exchange, raw)
        self.order_params = order_params


class MarketNotFoundError(ExchangeError):
    """Market not found or not available."""

    def __init__(
        self,
        message: str,
        exchange: str | None = None,
        market_id: str | None = None,
        raw: Any = None,
    ) -> None:
        super().__init__(message, exchange, raw)
        self.market_id = market_id


class MultipleMarketsError(ExchangeError):
    """Multiple markets found - user needs to select one."""

    def __init__(
        self,
        message: str,
        exchange: str | None = None,
        event_title: str | None = None,
        markets: list[dict[str, Any]] | None = None,
        raw: Any = None,
    ) -> None:
        super().__init__(message, exchange, raw)
        self.event_title = event_title
        self.markets = markets or []


class OrderNotFoundError(ExchangeError):
    """Order not found."""

    def __init__(
        self,
        message: str,
        exchange: str | None = None,
        order_id: str | None = None,
        raw: Any = None,
    ) -> None:
        super().__init__(message, exchange, raw)
        self.order_id = order_id


# === Network Errors ===


class NetworkError(PredictionMarketError):
    """Network-related error."""

    pass


class ConnectionError(NetworkError):
    """Failed to establish connection."""

    pass


class TimeoutError(NetworkError):
    """Request or operation timed out."""

    def __init__(
        self,
        message: str,
        exchange: str | None = None,
        timeout_seconds: float | None = None,
        raw: Any = None,
    ) -> None:
        super().__init__(message, exchange, raw)
        self.timeout_seconds = timeout_seconds


class WebSocketError(NetworkError):
    """WebSocket-specific error."""

    pass


class WebSocketConnectionError(WebSocketError):
    """WebSocket connection failed."""

    pass


class WebSocketDisconnectedError(WebSocketError):
    """WebSocket unexpectedly disconnected."""

    pass


class WebSocketSubscriptionError(WebSocketError):
    """Failed to subscribe to WebSocket channel."""

    def __init__(
        self,
        message: str,
        exchange: str | None = None,
        channel: str | None = None,
        raw: Any = None,
    ) -> None:
        super().__init__(message, exchange, raw)
        self.channel = channel


# === Rate Limiting ===


class RateLimitError(PredictionMarketError):
    """Rate limit exceeded."""

    def __init__(
        self,
        message: str,
        exchange: str | None = None,
        retry_after: float | None = None,
        raw: Any = None,
    ) -> None:
        super().__init__(message, exchange, raw)
        self.retry_after = retry_after  # Seconds until rate limit resets


# === Configuration Errors ===


class ConfigurationError(PredictionMarketError):
    """Invalid configuration."""

    pass


class UnsupportedExchangeError(ConfigurationError):
    """Exchange not supported."""

    def __init__(self, exchange_id: str) -> None:
        super().__init__(f"Exchange '{exchange_id}' is not supported")
        self.exchange_id = exchange_id


class UnsupportedFeatureError(PredictionMarketError):
    """Feature not supported by this exchange."""

    def __init__(
        self,
        feature: str,
        exchange: str | None = None,
    ) -> None:
        message = f"Feature '{feature}' is not supported"
        super().__init__(message, exchange)
        self.feature = feature
