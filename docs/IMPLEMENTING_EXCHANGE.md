# Implementing a New Exchange

This guide explains how to add support for a new prediction market exchange.

## Directory Structure

Create a new package under `exchanges/`:

```
exchanges/
└── kalshi/                    # New exchange
    ├── __init__.py            # Public exports
    ├── kalshi.py              # Main exchange class
    ├── rest_api.py            # REST client
    ├── ws_client.py           # WebSocket client (if supported)
    ├── parser.py              # Response parsers
    ├── constants.py           # API URLs, contract addresses
    └── signer.py              # Auth/signing (if needed)
```

## Step 1: Create the Main Exchange Class

```python
# exchanges/kalshi/kalshi.py

from decimal import Decimal
from typing import Any

from prediction_markets.base.exchange import Exchange
from prediction_markets.base.types import (
    Event,
    FeeStructure,
    Market,
    Order,
    OrderBook,
    OrderSide,
    OrderType,
    OutcomeSide,
    PortfolioSummary,
    Position,
    Resolution,
)


class Kalshi(Exchange):
    """Kalshi exchange implementation."""

    # Required class attributes
    id = "kalshi"
    name = "Kalshi"
    ws_support = True  # Set False if no WebSocket support

    # Feature flags - set True for supported features
    has = {
        "load_events": True,
        "search_events": True,
        "fetch_event": True,           # Optional
        "fetch_categories": False,     # Optional
        "fetch_market_price": True,
        "fetch_market_resolution": True,
        "fetch_orderbook": True,
        "fetch_open_orders": True,
        "fetch_position": True,
        "fetch_portfolio_summary": True,
        "create_order": True,
        "create_order_batch": True,
        "cancel_orders": True,
        "close_position": True,
        "split": False,                # Kalshi doesn't have on-chain ops
        "merge": False,
        "redeem": False,
        "calculate_fees": True,
    }

    # WebSocket-supported features
    ws_supported = {
        "fetch_orderbook": True,
        "fetch_market_price": True,
        "fetch_open_orders": False,
        "fetch_position": False,
    }

    def __init__(self, config: dict[str, Any]) -> None:
        super().__init__(config)

        # Extract and validate config
        self._api_key = config.get("api_key")
        self._api_secret = config.get("api_secret")

        # Initialize client references
        self._rest_client = None
        self._ws_client = None
```

## Step 2: Implement Lifecycle Methods

```python
class Kalshi(Exchange):
    # ... (previous code)

    async def _init_rest_client(self) -> None:
        """Initialize REST client."""
        from .rest_api import KalshiRestClient

        self._rest_client = KalshiRestClient(
            api_key=self._api_key,
            api_secret=self._api_secret,
        )
        await self._rest_client.init()

    async def _close_rest_client(self) -> None:
        """Close REST client."""
        if self._rest_client:
            await self._rest_client.close()
            self._rest_client = None

    async def _init_websocket(self) -> None:
        """Initialize WebSocket connection."""
        if not self.ws_support:
            return

        from .ws_client import KalshiWebSocketClient

        self._ws_client = KalshiWebSocketClient(
            api_key=self._api_key,
        )

        # Register callbacks
        @self._ws_client.on_orderbook
        async def handle_orderbook(market_id: str, data: dict) -> None:
            orderbook = self._parse_ws_orderbook(data)
            self._update_orderbook_cache(market_id, orderbook.outcome, orderbook)

        await self._ws_client.connect()

    async def _close_websocket(self) -> None:
        """Close WebSocket connection."""
        if self._ws_client:
            await self._ws_client.disconnect()
            self._ws_client = None
```

## Step 3: Implement Market Data Methods

```python
class Kalshi(Exchange):
    # ... (previous code)

    async def _fetch_events(self) -> list[Event]:
        """Fetch events from Kalshi API."""
        from .parser import parse_event

        raw_events = await self._rest_client.get_events()
        events = []

        for raw in raw_events:
            event = parse_event(raw)
            events.append(event)

        return events

    async def _fetch_orderbook_rest(
        self,
        market_id: str,
        outcome: OutcomeSide,
    ) -> OrderBook:
        """Fetch orderbook via REST."""
        from .parser import parse_orderbook

        raw = await self._rest_client.get_orderbook(market_id)
        return parse_orderbook(raw, market_id, outcome)

    async def _fetch_resolution(self, market_id: str) -> Resolution | None:
        """Fetch market resolution status."""
        raw = await self._rest_client.get_market(market_id)

        result = raw.get("result")
        if result == "yes":
            return Resolution.YES
        elif result == "no":
            return Resolution.NO
        elif result == "invalid":
            return Resolution.INVALID

        return None
```

## Step 4: Implement WebSocket Methods

```python
class Kalshi(Exchange):
    # ... (previous code)

    async def _subscribe_orderbook(self, market_id: str) -> None:
        """Subscribe to orderbook updates."""
        if self._ws_client is None:
            await self._init_websocket()

        await self._ws_client.subscribe(
            channel="orderbook",
            market_id=market_id,
        )

    async def _unsubscribe_orderbook(self, market_id: str) -> None:
        """Unsubscribe from orderbook updates."""
        if self._ws_client:
            await self._ws_client.unsubscribe(
                channel="orderbook",
                market_id=market_id,
            )
```

## Step 5: Implement Trading Methods

```python
class Kalshi(Exchange):
    # ... (previous code)

    async def _create_order_impl(
        self,
        market_id: str,
        side: OrderSide,
        outcome: OutcomeSide,
        size: Decimal,
        price: Decimal | None,
        order_type: OrderType,
        client_id: str | None,
    ) -> Order:
        """Create order on Kalshi."""
        from .parser import parse_order

        # Convert to Kalshi's API format
        order_data = {
            "ticker": market_id,
            "action": "buy" if side == OrderSide.BUY else "sell",
            "side": "yes" if outcome == OutcomeSide.YES else "no",
            "count": int(size),
            "type": "limit" if price else "market",
        }

        if price:
            # Kalshi uses cents (0-100)
            order_data["yes_price"] = int(price * 100)

        if client_id:
            order_data["client_order_id"] = client_id

        response = await self._rest_client.create_order(order_data)
        return parse_order(response)

    async def _cancel_order_impl(self, order_id: str) -> bool:
        """Cancel order on Kalshi."""
        try:
            await self._rest_client.cancel_order(order_id)
            return True
        except Exception:
            return False

    async def _fetch_open_orders(self, market_id: str | None) -> list[Order]:
        """Fetch open orders."""
        from .parser import parse_orders

        raw = await self._rest_client.get_orders(
            ticker=market_id,
            status="active",
        )
        return parse_orders(raw)
```

## Step 6: Implement Position Methods

```python
class Kalshi(Exchange):
    # ... (previous code)

    async def _fetch_position(
        self,
        market_id: str,
        side: OutcomeSide | None,
    ) -> Position | None:
        """Fetch position for a market."""
        from .parser import parse_position

        positions = await self._rest_client.get_positions(ticker=market_id)

        for raw in positions:
            position = parse_position(raw)
            if side is None or position.outcome == side:
                return position

        return None

    async def _fetch_portfolio_summary(self) -> PortfolioSummary:
        """Fetch portfolio summary."""
        balance = await self._rest_client.get_balance()
        positions = await self._rest_client.get_positions()

        return PortfolioSummary(
            exchange=self.id,
            cash_balance=Decimal(str(balance["balance"])),
            total_value=Decimal(str(balance["portfolio_value"])),
            additional_info={
                "positions_count": len(positions),
            },
        )
```

## Step 7: Implement Fee Methods

```python
class Kalshi(Exchange):
    # ... (previous code)

    def _get_fee_structure(self) -> FeeStructure:
        """Get Kalshi fee structure."""
        return FeeStructure(
            exchange=self.id,
            maker_fee=Decimal("0"),        # Kalshi: no maker fee
            taker_fee=Decimal("0.01"),     # 1% taker fee
            settlement_fee=Decimal("0"),   # No settlement fee
            withdrawal_fee=None,
        )
```

## Step 8: Handle Unsupported Features

For features not supported by the exchange, raise `NotImplementedError`:

```python
class Kalshi(Exchange):
    # ... (previous code)

    async def split(self, market_id: str, amount: Decimal) -> dict[str, Any]:
        """Not supported by Kalshi."""
        raise NotImplementedError("Kalshi does not support split operations")

    async def merge(self, market_id: str, amount: Decimal) -> dict[str, Any]:
        """Not supported by Kalshi."""
        raise NotImplementedError("Kalshi does not support merge operations")

    async def redeem(self, market_id: str) -> dict[str, Any]:
        """Not supported by Kalshi."""
        raise NotImplementedError("Kalshi does not support redeem operations")
```

## Step 9: Create Parsers

```python
# exchanges/kalshi/parser.py

from datetime import datetime
from decimal import Decimal

from prediction_markets.base.types import (
    Event,
    EventStatus,
    Market,
    MarketStatus,
    Order,
    OrderBook,
    OrderBookLevel,
    OrderSide,
    OrderStatus,
    OrderType,
    OutcomeSide,
    Position,
)


def parse_event(raw: dict) -> Event:
    """Parse raw event data into Event object."""
    markets = [parse_market(m) for m in raw.get("markets", [])]

    return Event(
        id=raw["event_ticker"],
        exchange="kalshi",
        title=raw["title"],
        description=raw.get("description", ""),
        category=raw.get("category", ""),
        status=_parse_event_status(raw.get("status")),
        markets=markets,
        raw=raw,
    )


def parse_market(raw: dict) -> Market:
    """Parse raw market data into Market object."""
    return Market(
        id=raw["ticker"],
        exchange="kalshi",
        slug=raw["ticker"],
        title=raw["title"],
        description=raw.get("description", ""),
        category=raw.get("category", ""),
        status=_parse_market_status(raw.get("status")),
        outcomes=["Yes", "No"],
        end_date=_parse_datetime(raw.get("close_time")),
        resolution_date=_parse_datetime(raw.get("result_time")),
        resolution_source=raw.get("result_source"),
        volume_24h=Decimal(str(raw.get("volume_24h", 0))),
        liquidity=None,
        created_at=_parse_datetime(raw.get("created_time")),
        event_id=raw.get("event_ticker"),
        raw=raw,
    )


def parse_orderbook(raw: dict, market_id: str, outcome: OutcomeSide) -> OrderBook:
    """Parse raw orderbook data."""
    bids = [
        OrderBookLevel(
            price=Decimal(str(level["price"])) / 100,  # Cents to dollars
            size=Decimal(str(level["count"])),
        )
        for level in raw.get("yes" if outcome == OutcomeSide.YES else "no", {}).get("bids", [])
    ]

    asks = [
        OrderBookLevel(
            price=Decimal(str(level["price"])) / 100,
            size=Decimal(str(level["count"])),
        )
        for level in raw.get("yes" if outcome == OutcomeSide.YES else "no", {}).get("asks", [])
    ]

    return OrderBook(
        market_id=market_id,
        bids=sorted(bids, key=lambda x: x.price, reverse=True),
        asks=sorted(asks, key=lambda x: x.price),
        timestamp=datetime.utcnow(),
        exchange="kalshi",
    )


def _parse_market_status(status: str | None) -> MarketStatus:
    """Convert Kalshi status to MarketStatus."""
    mapping = {
        "active": MarketStatus.ACTIVE,
        "closed": MarketStatus.CLOSED,
        "settled": MarketStatus.RESOLVED,
    }
    return mapping.get(status, MarketStatus.ACTIVE)


def _parse_datetime(value: str | None) -> datetime | None:
    """Parse ISO datetime string."""
    if not value:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))
```

## Step 10: Register the Exchange

```python
# exchanges/kalshi/__init__.py

from prediction_markets.exchanges.kalshi.kalshi import Kalshi

__all__ = ["Kalshi"]
```

```python
# factory.py - add to _auto_register_exchanges()

def _auto_register_exchanges() -> None:
    try:
        from prediction_markets.exchanges.polymarket import Polymarket
        register_exchange("polymarket", Polymarket)
    except ImportError:
        pass

    # Add Kalshi
    try:
        from prediction_markets.exchanges.kalshi import Kalshi
        register_exchange("kalshi", Kalshi)
    except ImportError:
        pass
```

## Step 11: Write Tests

```python
# tests/test_kalshi.py

import pytest
from decimal import Decimal

from prediction_markets import create_exchange, OutcomeSide


@pytest.fixture
async def exchange():
    config = {
        "api_key": "test_key",
        "api_secret": "test_secret",
    }
    async with create_exchange("kalshi", config) as ex:
        yield ex


@pytest.mark.asyncio
async def test_load_events(exchange):
    events = await exchange.load_events()
    assert len(events) > 0


@pytest.mark.asyncio
async def test_fetch_orderbook(exchange):
    events = exchange.get_events()
    market = list(events.values())[0].markets[0]

    orderbook = await exchange.fetch_orderbook(market.id, OutcomeSide.YES)
    assert orderbook.market_id == market.id
```

## Checklist

Before submitting:

- [ ] All abstract methods implemented
- [ ] Feature flags (`has`, `ws_supported`) correctly set
- [ ] Parsers handle all fields
- [ ] Error handling for API failures
- [ ] Tests for all supported features
- [ ] Documentation updated
- [ ] Exchange registered in factory

## Common Patterns

### Price Conversion

Different exchanges use different price formats:

```python
# Polymarket: 0.0 - 1.0 (probability)
price = Decimal("0.65")

# Kalshi: 0 - 100 (cents)
price = 65

# Convert: cents to probability
price_decimal = Decimal(str(price_cents)) / 100
```

### Market ID Resolution

Handle multiple ID formats:

```python
async def fetch_market(self, market_id: str) -> Market:
    # Handle URL
    if market_id.startswith("https://"):
        market_id = self._parse_url(market_id)

    # Handle different ID types
    if market_id.startswith("0x"):
        # Blockchain ID
        return await self._fetch_by_condition_id(market_id)
    else:
        # Database/ticker ID
        return await self._fetch_by_ticker(market_id)
```

### WebSocket Reconnection

Handle disconnections gracefully:

```python
async def _init_websocket(self) -> None:
    self._ws_client = WebSocketClient(...)

    @self._ws_client.on_disconnect
    async def handle_disconnect():
        self._ws_connected = False
        # Attempt reconnect
        await asyncio.sleep(5)
        await self._init_websocket()

    await self._ws_client.connect()
    self._ws_connected = True
```
