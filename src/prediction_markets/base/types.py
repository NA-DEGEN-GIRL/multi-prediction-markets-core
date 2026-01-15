"""
Type definitions for prediction markets.

This module contains all dataclasses, enums, and type aliases used throughout the library.
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from enum import Enum
from typing import Any


class OrderSide(str, Enum):
    """Order side: buy or sell."""

    BUY = "buy"
    SELL = "sell"


class OutcomeSide(str, Enum):
    """Prediction market outcome side."""

    YES = "yes"
    NO = "no"


class OrderType(str, Enum):
    """Order type."""

    MARKET = "market"
    LIMIT = "limit"
    LIMIT_IOC = "limit_ioc"  # Immediate or Cancel
    LIMIT_FOK = "limit_fok"  # Fill or Kill
    LIMIT_GTD = "limit_gtd"  # Good Till Date


class SizeType(str, Enum):
    """Size specification type."""

    SHARES = "shares"  # Size in number of shares/contracts
    USD = "usd"  # Size in USD amount


class OrderStatus(str, Enum):
    """Order status."""

    PENDING = "pending"
    OPEN = "open"
    PARTIAL = "partial"
    FILLED = "filled"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    REJECTED = "rejected"


class MarketStatus(str, Enum):
    """Market status."""

    ACTIVE = "active"
    HALTED = "halted"
    CLOSED = "closed"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class EventStatus(str, Enum):
    """Event status."""

    ACTIVE = "active"
    HALTED = "halted"
    CLOSED = "closed"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"


class Resolution(str, Enum):
    """Market resolution outcome."""

    YES = "yes"
    NO = "no"
    INVALID = "invalid"
    PENDING = "pending"


@dataclass
class OrderBookLevel:
    """Single level in the orderbook."""

    price: Decimal
    size: Decimal


@dataclass
class OrderBook:
    """Orderbook for a market."""

    market_id: str
    bids: list[OrderBookLevel]  # Sorted by price descending
    asks: list[OrderBookLevel]  # Sorted by price ascending
    timestamp: datetime
    exchange: str

    @property
    def best_bid(self) -> Decimal | None:
        """Return best bid price."""
        return self.bids[0].price if self.bids else None

    @property
    def best_ask(self) -> Decimal | None:
        """Return best ask price."""
        return self.asks[0].price if self.asks else None

    @property
    def mid_price(self) -> Decimal | None:
        """Calculate mid price."""
        if self.best_bid is None and self.best_ask is None:
            return None
        if self.best_bid is None:
            return self.best_ask
        if self.best_ask is None:
            return self.best_bid
        return (self.best_bid + self.best_ask) / 2

    @property
    def spread(self) -> Decimal | None:
        """Calculate bid-ask spread."""
        if self.best_bid is None or self.best_ask is None:
            return None
        return self.best_ask - self.best_bid


@dataclass
class MarketPrice:
    """Current market price information."""

    market_id: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    mid_price: Decimal | None
    last_price: Decimal | None
    timestamp: datetime


@dataclass
class Market:
    """Market information."""

    id: str  # Primary identifier (e.g., conditionId for Polymarket)
    exchange: str  # Exchange name
    slug: str  # URL-friendly identifier
    title: str  # Human-readable title
    description: str
    category: str
    status: MarketStatus
    outcomes: list[str]  # ["Yes", "No"] or multiple outcomes
    end_date: datetime | None  # Betting end date
    resolution_date: datetime | None
    resolution_source: str | None
    volume_24h: Decimal | None
    liquidity: Decimal | None
    created_at: datetime | None
    raw: dict[str, Any] = field(default_factory=dict)  # Raw exchange response

    # Event association (optional)
    event_id: str | None = None  # Parent Event ID (slug)
    event_title: str | None = None  # Parent Event title (for convenience)


@dataclass
class Event:
    """
    Event groups multiple related markets.

    Example: "Bitcoin Price Predictions" Event contains:
        - "BTC > $100k by Jan?" Market
        - "BTC > $150k by March?" Market
    """

    id: str  # Primary identifier (typically slug for URL-friendly access)
    exchange: str  # Exchange name
    title: str  # Human-readable title
    description: str
    category: str
    status: EventStatus

    markets: list[Market] = field(default_factory=list)  # Child markets

    start_date: datetime | None = None
    end_date: datetime | None = None

    volume_24h: Decimal | None = None  # Total event volume
    liquidity: Decimal | None = None  # Total event liquidity

    image_url: str | None = None
    tags: list[str] = field(default_factory=list)

    created_at: datetime | None = None
    raw: dict[str, Any] = field(default_factory=dict)  # Raw exchange response


@dataclass
class Order:
    """Order information."""

    id: str  # Exchange order ID
    client_id: str | None  # Client-specified order ID
    market_id: str
    exchange: str
    side: OrderSide
    outcome: OutcomeSide
    order_type: OrderType
    price: Decimal | None  # None for market orders
    size: Decimal  # Size in shares
    filled_size: Decimal
    remaining_size: Decimal
    status: OrderStatus
    created_at: datetime
    updated_at: datetime | None
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def is_open(self) -> bool:
        """Check if order is still open."""
        return self.status in (OrderStatus.PENDING, OrderStatus.OPEN, OrderStatus.PARTIAL)

    @property
    def fill_percentage(self) -> float:
        """Calculate fill percentage."""
        if self.size == 0:
            return 0.0
        return float(self.filled_size / self.size * 100)


@dataclass
class Position:
    """Position information."""

    market_id: str
    exchange: str
    outcome: OutcomeSide
    size: Decimal  # Number of shares
    avg_price: Decimal  # Average entry price
    current_price: Decimal | None
    unrealized_pnl: Decimal | None
    realized_pnl: Decimal
    raw: dict[str, Any] = field(default_factory=dict)

    @property
    def market_value(self) -> Decimal | None:
        """Calculate current market value."""
        if self.current_price is None:
            return None
        return self.size * self.current_price


@dataclass
class PortfolioSummary:
    """
    Portfolio summary information.

    Required fields:
    - exchange: Exchange identifier
    - cash_balance: Available cash/collateral (USDC, USD, etc.)
    - total_value: Total portfolio value (cash + positions)

    Optional fields in additional_info (exchange-specific):
    - positions_value: Total positions value
    - unrealized_pnl: Unrealized profit/loss
    - realized_pnl: Realized profit/loss
    - positions_count: Number of open positions
    - positions: List of Position objects
    - allowance: Token allowance (for DeFi exchanges)
    """

    exchange: str
    cash_balance: Decimal  # Required: Available cash/collateral
    total_value: Decimal  # Required: Total portfolio value
    additional_info: dict[str, Any] = field(default_factory=dict)  # Exchange-specific data

    # Convenience properties for common fields
    @property
    def positions_value(self) -> Decimal:
        """Total positions value (from additional_info or calculated)."""
        return Decimal(str(self.additional_info.get("positions_value", self.total_value - self.cash_balance)))

    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized PnL (from additional_info or 0)."""
        return Decimal(str(self.additional_info.get("unrealized_pnl", 0)))

    @property
    def realized_pnl(self) -> Decimal:
        """Realized PnL (from additional_info or 0)."""
        return Decimal(str(self.additional_info.get("realized_pnl", 0)))

    @property
    def positions_count(self) -> int:
        """Number of positions (from additional_info or 0)."""
        return int(self.additional_info.get("positions_count", 0))


@dataclass
class FeeStructure:
    """Exchange fee structure."""

    exchange: str
    maker_fee: Decimal  # Maker fee rate (e.g., 0.001 = 0.1%)
    taker_fee: Decimal  # Taker fee rate
    settlement_fee: Decimal  # Fee on winning positions
    withdrawal_fee: Decimal | None  # Fixed withdrawal fee


@dataclass
class FeeBreakdown:
    """Calculated fee breakdown for an order."""

    trading_fee: Decimal
    is_maker: bool
    estimated_settlement_fee: Decimal | None  # If position wins
    total_estimated: Decimal


@dataclass
class Trade:
    """Trade/execution information."""

    id: str
    order_id: str
    market_id: str
    exchange: str
    side: OrderSide
    outcome: OutcomeSide
    price: Decimal
    size: Decimal
    fee: Decimal
    timestamp: datetime
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class BatchOrderError:
    """Failed order in batch operation."""

    index: int  # Position in original order list
    order_input: dict[str, Any]  # Original order dict
    error: Exception  # The exception that occurred
    error_message: str  # Human-readable error message


@dataclass
class BatchOrderResult:
    """Result of batch order operation.

    Example:
        ```python
        result = await exchange.create_order_batch(orders)

        print(f"Success: {len(result.successful)}/{result.total}")
        print(f"Failed: {len(result.failed)}/{result.total}")

        for error in result.failed:
            print(f"  Order {error.index}: {error.error_message}")
        ```
    """

    successful: list["Order"]
    failed: list[BatchOrderError]

    @property
    def total(self) -> int:
        """Total number of orders attempted."""
        return len(self.successful) + len(self.failed)

    @property
    def success_rate(self) -> float:
        """Success rate as percentage (0.0 - 100.0)."""
        if self.total == 0:
            return 0.0
        return len(self.successful) / self.total * 100

    @property
    def all_successful(self) -> bool:
        """Check if all orders succeeded."""
        return len(self.failed) == 0

    @property
    def all_failed(self) -> bool:
        """Check if all orders failed."""
        return len(self.successful) == 0


@dataclass
class ExchangeStatus:
    """Exchange connectivity status."""

    exchange: str
    status: str  # "online", "maintenance", "degraded"
    ws_connected: bool
    ws_last_message: datetime | None
    rest_latency_ms: float | None
    message: str | None
