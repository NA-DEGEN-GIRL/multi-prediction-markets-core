# Type System

This document describes all dataclasses and enums used in the library.

## Enums

### OrderSide

```python
class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"
```

### OutcomeSide

```python
class OutcomeSide(str, Enum):
    YES = "yes"
    NO = "no"
```

### OrderType

```python
class OrderType(str, Enum):
    MARKET = "market"       # Execute immediately at best price
    LIMIT = "limit"         # Good Till Cancelled (GTC)
    LIMIT_IOC = "limit_ioc" # Immediate or Cancel
    LIMIT_FOK = "limit_fok" # Fill or Kill
    LIMIT_GTD = "limit_gtd" # Good Till Date
```

### SizeType

```python
class SizeType(str, Enum):
    SHARES = "shares"  # Size in number of shares/contracts
    USD = "usd"        # Size in USD amount (auto-converted)
```

### OrderStatus

```python
class OrderStatus(str, Enum):
    PENDING = "pending"     # Submitted, not yet confirmed
    OPEN = "open"           # Active in orderbook
    PARTIAL = "partial"     # Partially filled
    FILLED = "filled"       # Completely filled
    CANCELLED = "cancelled" # Cancelled by user
    EXPIRED = "expired"     # Expired (GTD orders)
    REJECTED = "rejected"   # Rejected by exchange
```

### MarketStatus

```python
class MarketStatus(str, Enum):
    ACTIVE = "active"       # Trading allowed
    HALTED = "halted"       # Trading paused
    CLOSED = "closed"       # No more betting
    RESOLVED = "resolved"   # Outcome determined
    CANCELLED = "cancelled" # Market voided
```

### EventStatus

```python
class EventStatus(str, Enum):
    ACTIVE = "active"
    HALTED = "halted"
    CLOSED = "closed"
    RESOLVED = "resolved"
    CANCELLED = "cancelled"
```

### Resolution

```python
class Resolution(str, Enum):
    YES = "yes"           # YES outcome won
    NO = "no"             # NO outcome won
    INVALID = "invalid"   # Market voided/refunded
    PENDING = "pending"   # Not yet resolved
```

## Core Dataclasses

### Event

Groups related markets together.

```python
@dataclass
class Event:
    id: str                          # Primary identifier (slug)
    exchange: str                    # Exchange name
    title: str                       # Human-readable title
    description: str
    category: str
    status: EventStatus

    markets: list[Market] = []       # Child markets

    start_date: datetime | None = None
    end_date: datetime | None = None

    volume_24h: Decimal | None = None
    liquidity: Decimal | None = None

    image_url: str | None = None
    tags: list[str] = []

    created_at: datetime | None = None
    raw: dict[str, Any] = {}         # Original API response
```

**Example:**
```python
event = Event(
    id="bitcoin-price-predictions",
    exchange="polymarket",
    title="Bitcoin Price Predictions",
    description="Markets about Bitcoin's future price",
    category="crypto",
    status=EventStatus.ACTIVE,
    markets=[market1, market2, market3],
)

# Access child markets
for market in event.markets:
    print(f"  {market.title}")
```

### Market

Individual prediction market.

```python
@dataclass
class Market:
    id: str                          # Primary ID (conditionId for Polymarket)
    exchange: str
    slug: str                        # URL-friendly identifier
    title: str
    description: str
    category: str
    status: MarketStatus
    outcomes: list[str]              # ["Yes", "No"] or multiple
    end_date: datetime | None        # Betting end date
    resolution_date: datetime | None
    resolution_source: str | None
    volume_24h: Decimal | None
    liquidity: Decimal | None
    created_at: datetime | None
    raw: dict[str, Any] = {}

    # Parent event association
    event_id: str | None = None      # Parent Event ID (slug)
    event_title: str | None = None   # For convenience
```

**Example:**
```python
market = Market(
    id="0x1234567890abcdef...",
    exchange="polymarket",
    slug="btc-above-100k-january",
    title="Bitcoin above $100k in January?",
    description="Will BTC exceed $100,000 by end of January 2025?",
    category="crypto",
    status=MarketStatus.ACTIVE,
    outcomes=["Yes", "No"],
    end_date=datetime(2025, 1, 31),
    event_id="bitcoin-price-predictions",
    event_title="Bitcoin Price Predictions",
)
```

### OrderBook

Current state of bids and asks.

```python
@dataclass
class OrderBookLevel:
    price: Decimal
    size: Decimal

@dataclass
class OrderBook:
    market_id: str
    bids: list[OrderBookLevel]  # Sorted descending (highest first)
    asks: list[OrderBookLevel]  # Sorted ascending (lowest first)
    timestamp: datetime
    exchange: str

    # Computed properties
    @property
    def best_bid(self) -> Decimal | None: ...

    @property
    def best_ask(self) -> Decimal | None: ...

    @property
    def mid_price(self) -> Decimal | None: ...

    @property
    def spread(self) -> Decimal | None: ...
```

**Example:**
```python
orderbook = await exchange.fetch_orderbook(market_id, OutcomeSide.YES)

print(f"Best bid: {orderbook.best_bid}")   # Decimal("0.65")
print(f"Best ask: {orderbook.best_ask}")   # Decimal("0.67")
print(f"Mid price: {orderbook.mid_price}") # Decimal("0.66")
print(f"Spread: {orderbook.spread}")       # Decimal("0.02")

# Access full depth
for level in orderbook.bids[:5]:
    print(f"  Bid: {level.price} x {level.size}")
```

### MarketPrice

Simplified price information.

```python
@dataclass
class MarketPrice:
    market_id: str
    best_bid: Decimal | None
    best_ask: Decimal | None
    mid_price: Decimal | None
    last_price: Decimal | None  # Last trade price
    timestamp: datetime
```

### Order

Order information.

```python
@dataclass
class Order:
    id: str                      # Exchange order ID
    client_id: str | None        # Client-specified ID
    market_id: str
    exchange: str
    side: OrderSide              # BUY or SELL
    outcome: OutcomeSide         # YES or NO
    order_type: OrderType
    price: Decimal | None        # None for market orders
    size: Decimal                # Total size in shares
    filled_size: Decimal
    remaining_size: Decimal
    status: OrderStatus
    created_at: datetime
    updated_at: datetime | None
    raw: dict[str, Any] = {}

    # Computed properties
    @property
    def is_open(self) -> bool:
        """True if PENDING, OPEN, or PARTIAL."""

    @property
    def fill_percentage(self) -> float:
        """0.0 to 100.0"""
```

**Example:**
```python
order = await exchange.create_order(
    market_id=market_id,
    side=OrderSide.BUY,
    outcome=OutcomeSide.YES,
    size=Decimal("10"),
    price=Decimal("0.65"),
)

print(f"Order ID: {order.id}")
print(f"Status: {order.status}")           # OrderStatus.OPEN
print(f"Filled: {order.fill_percentage}%") # 0.0
print(f"Is open: {order.is_open}")         # True
```

### Position

Current position in a market.

```python
@dataclass
class Position:
    market_id: str
    exchange: str
    outcome: OutcomeSide         # YES or NO
    size: Decimal                # Number of shares
    avg_price: Decimal           # Average entry price
    current_price: Decimal | None
    unrealized_pnl: Decimal | None
    realized_pnl: Decimal
    raw: dict[str, Any] = {}

    # Computed property
    @property
    def market_value(self) -> Decimal | None:
        """size * current_price"""
```

**Example:**
```python
position = await exchange.fetch_position(market_id, OutcomeSide.YES)
if position:
    print(f"Size: {position.size}")
    print(f"Avg price: {position.avg_price}")
    print(f"Current price: {position.current_price}")
    print(f"Market value: {position.market_value}")
    print(f"Unrealized PnL: {position.unrealized_pnl}")
```

### PortfolioSummary

Overall account summary.

```python
@dataclass
class PortfolioSummary:
    exchange: str
    cash_balance: Decimal        # Available cash/collateral
    total_value: Decimal         # Cash + positions value
    additional_info: dict[str, Any] = {}  # Exchange-specific

    # Convenience properties (from additional_info)
    @property
    def positions_value(self) -> Decimal: ...

    @property
    def unrealized_pnl(self) -> Decimal: ...

    @property
    def realized_pnl(self) -> Decimal: ...

    @property
    def positions_count(self) -> int: ...
```

**Example:**
```python
summary = await exchange.fetch_portfolio_summary()

print(f"Cash: ${summary.cash_balance}")
print(f"Total: ${summary.total_value}")
print(f"Positions: {summary.positions_count}")
print(f"Unrealized PnL: ${summary.unrealized_pnl}")
```

### FeeStructure

Exchange fee rates.

```python
@dataclass
class FeeStructure:
    exchange: str
    maker_fee: Decimal       # Rate (e.g., Decimal("0.001") = 0.1%)
    taker_fee: Decimal
    settlement_fee: Decimal  # Fee on winning positions
    withdrawal_fee: Decimal | None  # Fixed amount
```

### FeeBreakdown

Calculated fees for an order.

```python
@dataclass
class FeeBreakdown:
    trading_fee: Decimal
    is_maker: bool
    estimated_settlement_fee: Decimal | None
    total_estimated: Decimal
```

**Example:**
```python
fees = exchange.calculate_fees(
    size=Decimal("100"),
    price=Decimal("0.65"),
    is_maker=True,
)

print(f"Trading fee: ${fees.trading_fee}")
print(f"Settlement (if win): ${fees.estimated_settlement_fee}")
print(f"Total estimated: ${fees.total_estimated}")
```

### Trade

Individual trade execution.

```python
@dataclass
class Trade:
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
    raw: dict[str, Any] = {}
```

### ExchangeStatus

Exchange connectivity status.

```python
@dataclass
class ExchangeStatus:
    exchange: str
    status: str             # "online", "maintenance", "degraded"
    ws_connected: bool
    ws_last_message: datetime | None
    rest_latency_ms: float | None
    message: str | None
```

## Type Relationships

```
                    Event
                      │
                      │ 1:N
                      ▼
                   Market ◄──────── Position
                      │                 │
                      │                 │
           ┌─────────┴─────────┐        │
           │                   │        │
           ▼                   ▼        │
       OrderBook            Order ◄─────┘
           │                   │
           │                   │
           ▼                   ▼
    OrderBookLevel          Trade
```

## Decimal Handling

All monetary values use `Decimal` for precision:

```python
from decimal import Decimal

# Correct
price = Decimal("0.65")
size = Decimal("100")

# Incorrect (float precision loss)
price = 0.65  # Don't do this

# Converting from API responses
raw_price = "0.65"
price = Decimal(str(raw_price))
```

## Raw Data Access

All dataclasses include a `raw` field with the original API response:

```python
market = await exchange.fetch_market(market_id)

# Access parsed data
print(market.title)

# Access raw API response
print(market.raw["conditionId"])
print(market.raw["minimum_tick_size"])
print(market.raw["neg_risk"])
```

This is useful for:
- Accessing exchange-specific fields
- Debugging
- Features not yet abstracted
