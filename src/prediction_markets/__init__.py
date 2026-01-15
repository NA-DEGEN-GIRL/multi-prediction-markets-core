"""
Multi-Prediction-Markets: Unified Python wrapper for prediction markets.

A ccxt-style library for interacting with prediction market exchanges
like Polymarket, Kalshi, and more.

Example:
    ```python
    from prediction_markets import create_exchange

    async def main():
        exchange = create_exchange("polymarket", {
            "api_key": "your_api_key",
        })

        async with exchange:
            events = await exchange.load_events()
            for event in events.values():
                print(f"{event.title}: {len(event.markets)} markets")

    asyncio.run(main())
    ```
"""

from prediction_markets.base.exchange import Exchange
from prediction_markets.base.types import (
    Event,
    EventStatus,
    FeeBreakdown,
    FeeStructure,
    Market,
    MarketPrice,
    MarketStatus,
    Order,
    OrderBook,
    OrderBookLevel,
    OrderSide,
    OrderStatus,
    OrderType,
    OutcomeSide,
    PortfolioSummary,
    Position,
    Resolution,
    SizeType,
    Trade,
    ExchangeStatus,
)
from prediction_markets.common.exceptions import (
    AuthenticationError,
    ConfigurationError,
    ConnectionError,
    ExchangeError,
    InsufficientFundsError,
    InvalidOrderError,
    MarketNotFoundError,
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
from prediction_markets.factory import (
    create_exchange,
    get_supported_exchanges,
    register_exchange,
)
from prediction_markets.config import (
    get_polymarket_config,
    get_test_config,
    load_env,
    PolymarketConfig,
    TestConfig,
)

__version__ = "0.1.0"

__all__ = [
    # Version
    "__version__",
    # Factory
    "create_exchange",
    "get_supported_exchanges",
    "register_exchange",
    # Base classes
    "Exchange",
    # Types
    "Event",
    "EventStatus",
    "Market",
    "MarketPrice",
    "MarketStatus",
    "Order",
    "OrderBook",
    "OrderBookLevel",
    "OrderSide",
    "OrderStatus",
    "OrderType",
    "OutcomeSide",
    "Position",
    "PortfolioSummary",
    "FeeStructure",
    "FeeBreakdown",
    "Trade",
    "Resolution",
    "SizeType",
    "ExchangeStatus",
    # Exceptions
    "PredictionMarketError",
    "ExchangeError",
    "AuthenticationError",
    "InsufficientFundsError",
    "InvalidOrderError",
    "MarketNotFoundError",
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
    # Config
    "get_polymarket_config",
    "get_test_config",
    "load_env",
    "PolymarketConfig",
    "TestConfig",
]
