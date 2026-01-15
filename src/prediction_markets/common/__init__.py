"""
Common utilities and exceptions for prediction markets.
"""

from prediction_markets.common.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ConnectionError,
    ExchangeError,
    InsufficientFundsError,
    InvalidOrderError,
    MarketNotFoundError,
    MultipleMarketsError,
    NetworkError,
    OrderNotFoundError,
    PredictionMarketError,
    RateLimitError,
    TimeoutError,
    UnsupportedExchangeError,
    UnsupportedFeatureError,
    WebSocketConnectionError,
    WebSocketDisconnectedError,
    WebSocketError,
    WebSocketSubscriptionError,
)
from prediction_markets.common.utils import (
    format_datetime,
    parse_datetime,
    parse_decimal,
)

__all__ = [
    # Exceptions
    "PredictionMarketError",
    "ExchangeError",
    "AuthenticationError",
    "InsufficientFundsError",
    "InvalidOrderError",
    "MarketNotFoundError",
    "MultipleMarketsError",
    "OrderNotFoundError",
    "NetworkError",
    "ConnectionError",
    "TimeoutError",
    "WebSocketError",
    "WebSocketConnectionError",
    "WebSocketDisconnectedError",
    "WebSocketSubscriptionError",
    "RateLimitError",
    "ConfigurationError",
    "UnsupportedExchangeError",
    "UnsupportedFeatureError",
    # Utilities
    "parse_datetime",
    "format_datetime",
    "parse_decimal",
]
