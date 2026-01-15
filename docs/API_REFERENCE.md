# API Reference

This document describes the public API and naming conventions.

## Naming Conventions

### Method Prefixes

| Prefix | Sync/Async | Network | Cache | Use Case |
|--------|------------|---------|-------|----------|
| `get_*` | sync | No | Read-only | Access cached data instantly |
| `fetch_*` | async | Yes | May write | Retrieve from API |
| `load_*` | async | Yes | Must write | Bulk load + cache population |
| `search_*` | async | Yes | May write | Keyword-based search |
| `create_*` | async | Yes | No | Create resources |
| `cancel_*` | async | Yes | No | Cancel resources |
| `close_*` | async | Yes | No | Close positions |

### Examples

```python
# Sync (cache access) - instant, no await
event = exchange.get_event(event_id)
market = exchange.get_market(market_id)
events = exchange.get_events()
markets = exchange.get_markets()
categories = exchange.get_categories()
fee_structure = exchange.get_fee_structure()

# Async (API calls) - requires await
events = await exchange.load_events()
event = await exchange.fetch_event(event_id)
market = await exchange.fetch_market(market_id)
categories = await exchange.fetch_categories()
orderbook = await exchange.fetch_orderbook(market_id, outcome)
price = await exchange.fetch_market_price(market_id, outcome)
resolution = await exchange.fetch_market_resolution(market_id)
orders = await exchange.fetch_open_orders(market_id)
position = await exchange.fetch_position(market_id, outcome)
portfolio = await exchange.fetch_portfolio_summary()
events = await exchange.search_events(keyword)
```

## Complete API Surface

### Lifecycle Methods

```python
async def init() -> None
    """Initialize exchange connections. Called automatically by context manager."""

async def close() -> None
    """Close all connections. Called automatically by context manager."""

# Context manager support
async with create_exchange("polymarket", config) as exchange:
    pass  # init() and close() automatic
```

### Market Data - Sync (Cache Access)

```python
def get_event(event_id: str) -> Event
    """Get event from cache. Raises ValueError if not cached."""

def get_market(market_id: str) -> Market
    """Get market from cache. Raises MarketNotFoundError if not cached."""

def get_events() -> dict[str, Event]
    """Return all cached events. Call load_events() first."""

def get_markets() -> dict[str, Market]
    """Return all cached markets. Call load_events() first."""

def get_categories() -> list[dict[str, Any]]
    """Return cached categories. Call fetch_categories() first."""

def get_fee_structure() -> FeeStructure
    """Get exchange fee structure (sync, no API call)."""
```

### Market Data - Async (API Calls)

```python
async def load_events(reload: bool = False) -> dict[str, Event]
    """Load events from API into cache.

    Args:
        reload: Force reload even if cached

    Returns:
        Dict of event_id -> Event

    Note:
        Automatically populates _markets cache too.
    """

async def fetch_event(event_id: str) -> Event
    """Fetch single event by ID/slug from API.

    Optional feature - check has["fetch_event"].
    """

async def fetch_market(market_id: str) -> Market
    """Fetch single market from API.

    Args:
        market_id: URL, conditionId, or database ID
    """

async def fetch_categories(limit: int = 100) -> list[dict[str, Any]]
    """Fetch categories from API.

    Optional feature - check has["fetch_categories"].
    """

async def search_events(
    keyword: str,
    limit: int = 50,
    tag: str | None = None,
) -> list[Event]
    """Search events by keyword.

    Args:
        keyword: Search term
        limit: Max results
        tag: Optional category filter
    """

async def fetch_orderbook(
    market_id: str,
    outcome: OutcomeSide,
    use_cache: bool = True,
) -> OrderBook
    """Fetch orderbook for market outcome.

    Uses WebSocket cache if available, falls back to REST.
    """

async def fetch_market_price(
    market_id: str,
    outcome: OutcomeSide,
) -> MarketPrice
    """Fetch current market price (derived from orderbook)."""

async def fetch_market_resolution(market_id: str) -> Resolution | None
    """Fetch market resolution status.

    Returns:
        Resolution enum (YES, NO, INVALID, PENDING) or None
    """
```

### Trading

```python
async def create_order(
    market_id: str,
    side: OrderSide,              # BUY or SELL
    outcome: OutcomeSide,         # YES or NO
    size: Decimal,
    price: Decimal | None = None, # None = market order
    size_type: SizeType = SizeType.SHARES,  # SHARES or USD
    order_type: OrderType | None = None,    # Auto-detect from price
    client_id: str | None = None,
) -> Order
    """Create a new order.

    Args:
        market_id: Market identifier
        side: BUY or SELL
        outcome: YES or NO
        size: Order size
        price: Limit price (None for market orders)
        size_type: SHARES (default) or USD
        order_type: MARKET, LIMIT, LIMIT_IOC, LIMIT_FOK, LIMIT_GTD
        client_id: Optional client order ID

    Returns:
        Created Order object
    """

async def create_order_batch(orders: list[dict[str, Any]]) -> BatchOrderResult
    """Create multiple orders concurrently.

    Args:
        orders: List of order dicts with keys:
            - market_id, side, outcome, size
            - price (optional), size_type (optional)

    Returns:
        BatchOrderResult with:
            - successful: list[Order] - Successfully created orders
            - failed: list[BatchOrderError] - Failed orders with error details
            - total, success_rate, all_successful, all_failed properties

    Example:
        result = await exchange.create_order_batch(orders)
        if not result.all_successful:
            for err in result.failed:
                print(f"Order {err.index} failed: {err.error_message}")
    """

async def cancel_orders(
    market_id: str | None = None,
    order_ids: list[str] | None = None,
) -> list[str]
    """Cancel orders.

    Args:
        market_id: Cancel all orders for this market
        order_ids: Cancel specific order IDs
        (If neither provided, cancels ALL open orders)

    Returns:
        List of cancelled order IDs
    """

async def close_position(
    market_id: str,
    outcome: OutcomeSide,
    size: Decimal | None = None,  # None = entire position
) -> Order | None
    """Close a position at market price.

    Returns:
        Order if placed, None if no position
    """
```

### Account

```python
async def fetch_open_orders(market_id: str | None = None) -> list[Order]
    """Fetch open orders.

    Args:
        market_id: Filter by market (None = all markets)
    """

async def fetch_position(
    market_id: str,
    side: OutcomeSide | None = None,
) -> Position | None
    """Fetch position for a market.

    Args:
        market_id: Market identifier
        side: Filter by outcome (None = any)
    """

async def fetch_portfolio_summary() -> PortfolioSummary
    """Fetch portfolio summary with balance and positions."""
```

### On-Chain Operations (Polymarket)

```python
async def split(
    market_id: str,      # conditionId or URL
    amount: Decimal,     # USDC amount (e.g., Decimal("10"))
) -> dict[str, Any]
    """Split USDC into YES + NO tokens.

    Returns:
        {"tx_hash": str, "status": str, ...}
    """

async def merge(
    market_id: str,
    amount: Decimal,
) -> dict[str, Any]
    """Merge YES + NO tokens back into USDC.

    Requires equal amounts of YES and NO tokens.
    """

async def redeem(market_id: str) -> dict[str, Any]
    """Redeem winning positions after market resolution."""
```

### Fees

```python
def get_fee_structure() -> FeeStructure
    """Get exchange fee structure."""

def calculate_fees(
    size: Decimal,
    price: Decimal,
    is_maker: bool = False,
) -> FeeBreakdown
    """Calculate estimated fees for an order.

    Returns:
        FeeBreakdown with trading_fee, estimated_settlement_fee, total_estimated
    """
```

## Configuration Reference

### Required Configuration

```python
config = {
    "private_key": "0x...",  # 66 chars: 0x + 64 hex
}
```

### Optional Configuration

```python
config = {
    # Wallet
    "private_key": "0x...",
    "chain_id": 137,              # 137 = mainnet, 80002 = testnet
    "proxy_wallet": "0x...",      # Polymarket proxy/Magic wallet
    "funder": "0x...",            # Alias for proxy_wallet

    # Connection
    "testnet": False,
    "ws_enabled": True,

    # Performance
    "max_events": 200,            # Max events to load
    "concurrent_requests": 5,     # Parallel API calls

    # Builder API (for split/merge)
    "builder_api_key": "...",
    "builder_secret": "...",
    "builder_passphrase": "...",

    # Pre-existing credentials
    "api_creds": ApiCreds(...),   # Skip credential derivation
}
```

## Feature Detection

```python
# Check if feature is supported
if exchange.has["fetch_event"]:
    event = await exchange.fetch_event(event_id)

# Check WebSocket support
if exchange.ws_supported["fetch_orderbook"]:
    # Real-time updates available
    pass

# Check WebSocket status
if exchange.ws_enabled and exchange._ws_connected:
    # WebSocket is active
    pass
```

## Common Patterns

### Loading and Accessing Markets

```python
async with create_exchange("polymarket", config) as exchange:
    # load_events() is called by init()

    # Sync access (fast, from cache)
    market = exchange.get_market(market_id)

    # If not in cache, fetch from API
    try:
        market = exchange.get_market(market_id)
    except MarketNotFoundError:
        market = await exchange.fetch_market(market_id)
```

### Searching and Filtering

```python
# Search by keyword
events = await exchange.search_events("bitcoin", limit=10)
for event in events:
    print(f"{event.title}: {len(event.markets)} markets")

# Access cached results
all_events = exchange.get_events()
active = [e for e in all_events.values() if e.status == EventStatus.ACTIVE]
```

### Trading Flow

```python
# 1. Get orderbook
orderbook = await exchange.fetch_orderbook(market_id, OutcomeSide.YES)
print(f"Best bid: {orderbook.best_bid}, Best ask: {orderbook.best_ask}")

# 2. Place limit order
order = await exchange.create_order(
    market_id=market_id,
    side=OrderSide.BUY,
    outcome=OutcomeSide.YES,
    size=Decimal("10"),
    price=Decimal("0.65"),
)

# 3. Check open orders
orders = await exchange.fetch_open_orders(market_id)

# 4. Cancel if needed
cancelled = await exchange.cancel_orders(order_ids=[order.id])

# 5. Or place market order
order = await exchange.create_order(
    market_id=market_id,
    side=OrderSide.BUY,
    outcome=OutcomeSide.YES,
    size=Decimal("100"),
    size_type=SizeType.USD,  # $100 worth
)

# 6. Close position
closed = await exchange.close_position(market_id, OutcomeSide.YES)
```

### Split/Merge Flow (Polymarket)

```python
# Split: Convert USDC to YES + NO tokens
result = await exchange.split(market_id, Decimal("100"))
print(f"TX: {result['tx_hash']}, Status: {result['status']}")

# Now you have 100 YES + 100 NO tokens
# Sell one side if you have a directional view

# Merge: Convert YES + NO back to USDC
result = await exchange.merge(market_id, Decimal("50"))
# Requires 50 YES + 50 NO -> 50 USDC

# Redeem: After market resolves, claim winnings
result = await exchange.redeem(market_id)
```
