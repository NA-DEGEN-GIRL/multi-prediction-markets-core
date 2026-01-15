# Architecture Overview

This document describes the architecture and design patterns used in the prediction-markets library.

## Design Philosophy

The library follows these principles:
1. **ccxt-inspired**: Familiar interface for crypto exchange users
2. **Async-first**: All I/O operations are async
3. **Type-safe**: Full type hints with dataclasses
4. **Layered abstraction**: Clear separation between base and implementations

## Module Structure

```
prediction_markets/
├── base/
│   ├── exchange.py      # Abstract base class (ExchangeBase + DefaultImplementationsMixin)
│   └── types.py         # All dataclasses and enums
├── common/
│   └── exceptions.py    # Exception hierarchy
├── exchanges/
│   └── polymarket/      # Exchange implementation
│       ├── polymarket.py    # Main exchange class
│       ├── rest_api.py      # REST client
│       ├── ws_client.py     # WebSocket client
│       ├── parser.py        # Response parsers
│       ├── signer.py        # Order signing
│       └── constants.py     # Contract addresses
└── factory.py           # create_exchange() factory
```

## Exchange Class Hierarchy

```
ExchangeBase (ABC)              # Abstract methods - MUST implement
       │
DefaultImplementationsMixin     # Default implementations - CAN override
       │
       ▼
   Exchange                     # Combined class for subclassing
       │
       ▼
   Polymarket                   # Concrete implementation
```

### ExchangeBase (Abstract)

Methods that EVERY exchange MUST implement:

```python
# Lifecycle
async def _init_rest_client(self) -> None
async def _close_rest_client(self) -> None
async def _init_websocket(self) -> None
async def _close_websocket(self) -> None

# Market Data
async def _fetch_events(self) -> list[Event]
async def _fetch_orderbook_rest(self, market_id: str, outcome: OutcomeSide) -> OrderBook
async def _fetch_resolution(self, market_id: str) -> Resolution | None

# WebSocket
async def _subscribe_orderbook(self, market_id: str) -> None
async def _unsubscribe_orderbook(self, market_id: str) -> None

# Trading
async def _create_order_impl(...) -> Order
async def _cancel_order_impl(self, order_id: str) -> bool
async def _fetch_open_orders(self, market_id: str | None) -> list[Order]

# Positions
async def _fetch_position(self, market_id: str, side: OutcomeSide | None) -> Position | None
async def _fetch_portfolio_summary(self) -> PortfolioSummary

# Fees
def _get_fee_structure(self) -> FeeStructure

# On-chain
async def split(self, market_id: str, amount: Decimal) -> dict[str, Any]
async def merge(self, market_id: str, amount: Decimal) -> dict[str, Any]
async def redeem(self, market_id: str) -> dict[str, Any]
```

### DefaultImplementationsMixin

Methods with default implementations that CAN be overridden:

```python
async def create_order_batch(self, orders: list[dict]) -> list[Order]
    # Default: asyncio.gather with individual create_order calls
    # Override if exchange has native batch API

async def close_position(self, market_id: str, outcome: OutcomeSide, size: Decimal | None) -> Order | None
    # Default: Places market sell order
    # Override if exchange has dedicated close API

def calculate_fees(self, size: Decimal, price: Decimal, is_maker: bool) -> FeeBreakdown
    # Default: Uses fee structure rates
    # Override for complex fee calculations
```

## Data Model Hierarchy

```
Event (1) ──────────> (*) Market
  │                       │
  │                       │
  │   ┌───────────────────┘
  │   │
  ▼   ▼
Runtime Caches:
  _events: dict[str, Event]      # event_id -> Event
  _markets: dict[str, Market]    # market_id -> Market (flat)
  _categories: list[dict]        # Category metadata
  _orderbooks: dict[str, dict[OutcomeSide, OrderBook]]
```

### Event-Market Relationship

- **Event**: Groups related markets (e.g., "Bitcoin Price Predictions")
- **Market**: Individual prediction (e.g., "BTC > $100k by Jan?")
- Each Market has `event_id` and `event_title` for back-reference
- `load_events()` populates both `_events` and `_markets` caches

## Feature Flags

### `has` Dictionary

Indicates which features are supported:

```python
has = {
    # Data loading
    "load_events": True,         # Load events with markets
    "search_events": True,       # Search by keyword

    # Data fetching (API calls)
    "fetch_event": False,        # Single event by ID (optional)
    "fetch_categories": False,   # Categories list (optional)
    "fetch_market_price": True,
    "fetch_market_resolution": True,
    "fetch_orderbook": True,
    "fetch_open_orders": True,
    "fetch_position": True,
    "fetch_portfolio_summary": True,
    "fetch_all_positions": False,  # Optional

    # Trading
    "create_order": True,
    "create_order_batch": True,
    "cancel_orders": True,
    "close_position": True,

    # On-chain operations
    "split": True,
    "merge": True,
    "redeem": True,

    "calculate_fees": True,
}
```

### `ws_supported` Dictionary

Indicates which features support real-time WebSocket updates:

```python
ws_supported = {
    "fetch_orderbook": True,      # Real-time orderbook
    "fetch_market_price": True,   # Derived from orderbook
    "fetch_open_orders": False,   # REST only
    "fetch_position": False,      # REST only
}
```

## Lifecycle Management

### Context Manager Pattern (Recommended)

```python
async with create_exchange("polymarket", config) as exchange:
    # exchange.init() called automatically
    events = await exchange.load_events()
    # exchange.close() called automatically
```

### Manual Lifecycle

```python
exchange = create_exchange("polymarket", config)
await exchange.init()  # Initialize connections
try:
    events = await exchange.load_events()
finally:
    await exchange.close()  # Clean up
```

### init() Sequence

1. `_init_rest_client()` - REST client setup
2. `load_events()` - Populate caches
3. WebSocket setup (lazy on first subscription)

## Caching Strategy

### Cache Types

| Cache | Key | Value | Populated By |
|-------|-----|-------|--------------|
| `_events` | event_id (slug) | Event | `load_events()`, `search_events()`, `fetch_event()` |
| `_markets` | market_id (conditionId) | Market | `load_events()`, `search_events()`, `fetch_market()` |
| `_categories` | (list) | dict | `fetch_categories()` |
| `_orderbooks` | market_id | {OutcomeSide: OrderBook} | WebSocket updates |

### Cache Access Patterns

```python
# Sync access (from cache)
event = exchange.get_event(event_id)      # Raises if not cached
market = exchange.get_market(market_id)   # Raises if not cached
events = exchange.get_events()            # Returns dict
markets = exchange.get_markets()          # Returns dict
categories = exchange.get_categories()    # Returns list

# Async fetch (API call, may cache)
event = await exchange.fetch_event(event_id)
market = await exchange.fetch_market(market_id)
categories = await exchange.fetch_categories()
```

## Error Handling

### Exception Hierarchy

```
PredictionMarketError (base)
├── ExchangeError
│   ├── AuthenticationError
│   ├── InsufficientFundsError
│   ├── InvalidOrderError
│   ├── MarketNotFoundError
│   ├── MultipleMarketsError
│   └── OrderNotFoundError
├── NetworkError
│   ├── ConnectionError
│   ├── TimeoutError
│   └── WebSocketError
│       ├── WebSocketConnectionError
│       ├── WebSocketDisconnectedError
│       └── WebSocketSubscriptionError
├── RateLimitError
└── ConfigurationError
    ├── UnsupportedExchangeError
    └── UnsupportedFeatureError
```

### Error Context

All exceptions include:
- `message`: Human-readable description
- `exchange`: Exchange ID (if applicable)
- `raw`: Raw error response from API

## WebSocket Architecture

### Lazy Initialization

WebSocket connects on first subscription, not at init():

```python
async def _subscribe_orderbook(self, market_id: str) -> None:
    if self._ws_client is None:
        await self._init_websocket()  # Lazy init
    await self._ws_client.subscribe_orderbook(token_ids)
```

### Fallback Pattern

WebSocket failures automatically fall back to REST:

```python
async def fetch_orderbook(self, market_id: str, outcome: OutcomeSide) -> OrderBook:
    if self.ws_enabled and self._ws_connected:
        try:
            # Try WebSocket
            cached = self._orderbooks.get(market_id, {}).get(outcome)
            if cached:
                return cached
        except WebSocketError:
            logger.warning("WS failed, using REST")

    # Fallback to REST
    return await self._fetch_orderbook_rest(market_id, outcome)
```

## Factory Pattern

### Auto-Registration

Exchanges auto-register on import:

```python
# factory.py
def _auto_register_exchanges() -> None:
    try:
        from prediction_markets.exchanges.polymarket import Polymarket
        register_exchange("polymarket", Polymarket)
    except ImportError:
        pass
```

### Usage

```python
from prediction_markets import create_exchange, get_supported_exchanges

# List available exchanges
print(get_supported_exchanges())  # ["polymarket"]

# Create instance
exchange = create_exchange("polymarket", config)
```

## Polymarket-Specific Architecture

### Three API Layers

```
┌─────────────────────────────────────────────────────────────┐
│                      Polymarket Class                        │
├─────────────────────────────────────────────────────────────┤
│  PolymarketRestClient                                        │
│  ├── CLOB API (clob.polymarket.com)                          │
│  │   └── Trading, orderbooks, orders                         │
│  ├── Gamma API (gamma-api.polymarket.com)                    │
│  │   └── Market metadata, events, resolution                 │
│  └── Data API (data-api.polymarket.com)                      │
│      └── Positions, portfolio                                │
├─────────────────────────────────────────────────────────────┤
│  PolymarketWebSocketClient                                   │
│  └── Real-time orderbook updates                             │
├─────────────────────────────────────────────────────────────┤
│  BuilderRelayerClient                                        │
│  └── Gasless split/merge/redeem operations                   │
└─────────────────────────────────────────────────────────────┘
```

### Market ID Resolution

Polymarket accepts multiple ID formats:

```python
# All resolve to the same market
await exchange.fetch_market("https://polymarket.com/event/.../...")  # URL
await exchange.fetch_market("0x1234...abcd")  # conditionId (66 chars)
await exchange.fetch_market("12345")  # Database ID
```

### Token ID Mapping

Polymarket uses token IDs for orderbooks (not market IDs):

```
Market (conditionId) ──> CachedTokens
                            ├── "yes" -> token_id
                            └── "no" -> token_id
```

Token cache has TTL (1 hour) to handle market updates.
