"""
Base classes for prediction markets.

This module contains:
- Exchange: Abstract base class for all exchanges
- BaseWebSocketClient: WebSocket client with reconnection
- BaseRestClient: REST client with rate limiting
- Type definitions (dataclasses, enums)
"""

from prediction_markets.base.exchange import Exchange
from prediction_markets.base.rest_client import BaseRestClient, RestConfig, RestResponse
from prediction_markets.base.types import (
    ExchangeStatus,
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
)
from prediction_markets.base.websocket_client import (
    BaseWebSocketClient,
    ConnectionState,
    Subscription,
    WebSocketConfig,
)

__all__ = [
    # Exchange
    "Exchange",
    # WebSocket
    "BaseWebSocketClient",
    "WebSocketConfig",
    "ConnectionState",
    "Subscription",
    # REST
    "BaseRestClient",
    "RestConfig",
    "RestResponse",
    # Types
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
]
