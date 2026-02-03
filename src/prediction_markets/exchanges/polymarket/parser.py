"""
Polymarket data parser.

Transforms Polymarket API responses into unified types.

API Response Sources:
- Gamma API: Market metadata (title, description, outcomes, tokens)
- CLOB API: Trading data (orderbooks, orders, trades)
- Data API: Portfolio data (positions, balances)
"""

from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from prediction_markets.common.utils import parse_datetime, parse_decimal
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
    Trade,
)


# === Helper Functions ===


def _parse_tags(tags: list[Any] | None) -> list[str]:
    """
    Parse tags from API response.

    Handles both formats:
    - List of strings: ["tag1", "tag2"]
    - List of dicts: [{"label": "tag1"}, {"slug": "tag2"}]

    Args:
        tags: Raw tags from API

    Returns:
        List of tag strings
    """
    if not tags:
        return []

    result = []
    for tag in tags:
        if isinstance(tag, str):
            result.append(tag)
        elif isinstance(tag, dict):
            # Try common key names for tag value
            tag_value = tag.get("label") or tag.get("slug") or tag.get("name") or tag.get("tag")
            if tag_value:
                result.append(str(tag_value))
    return result


# === Market Parsing (Gamma API) ===


def parse_market(data: dict[str, Any]) -> Market:
    """
    Parse Polymarket market response into Market object.

    Expected from Gamma API /markets endpoint.

    Args:
        data: Raw market data from Gamma API

    Returns:
        Parsed Market object
    """
    # Determine market status
    active = data.get("active", True)
    closed = data.get("closed", False)
    accepting_orders = data.get("accepting_orders", True)

    status = _parse_market_status(active, closed, accepting_orders)

    # Parse outcomes - Polymarket uses tokens array
    outcomes = data.get("outcomes", ["Yes", "No"])
    if isinstance(outcomes, str):
        # Sometimes comes as JSON string
        import json
        try:
            outcomes = json.loads(outcomes)
        except json.JSONDecodeError:
            outcomes = ["Yes", "No"]

    # conditionId is the actual market identifier used by CLOB API
    # API returns camelCase (conditionId) but some places use snake_case (condition_id)
    condition_id = data.get("conditionId", data.get("condition_id", data.get("id", "")))

    return Market(
        id=condition_id,
        exchange="polymarket",
        slug=data.get("slug", data.get("market_slug", "")),
        title=data.get("question", data.get("title", "")),
        description=data.get("description", ""),
        category=data.get("category", data.get("tags", [""])[0] if data.get("tags") else ""),
        status=status,
        outcomes=outcomes,
        end_date=parse_datetime(data.get("end_date_iso", data.get("endDate", data.get("end_date")))),
        resolution_date=parse_datetime(data.get("resolution_date")),
        resolution_source=data.get("resolution_source", data.get("oracle")),
        volume_24h=parse_decimal(data.get("volume24hr", data.get("volume_num_24hr", data.get("volume_24h")))),
        liquidity=parse_decimal(data.get("liquidity", data.get("spread_liquidity"))),
        created_at=parse_datetime(data.get("created_at")),
        raw=data,
    )


def parse_resolution(data: dict[str, Any]) -> Resolution | None:
    """
    Parse market resolution status.

    Args:
        data: Raw market data from Gamma/CLOB API

    Returns:
        Resolution (YES/NO/INVALID) or None if not resolved
    """
    if data.get("resolved") or data.get("winner"):
        return _parse_resolution(data.get("resolution", data.get("winner")))
    return None


def parse_market_tokens(data: dict[str, Any]) -> dict[str, str]:
    """
    Extract token IDs from market data.

    Args:
        data: Market data containing tokens array

    Returns:
        Dict mapping outcome to token_id: {"yes": "token_id", "no": "token_id"}
    """
    import json as json_module

    tokens = {}

    # Gamma API format - tokens array
    token_array = data.get("tokens", [])
    for token in token_array:
        outcome = token.get("outcome", "").lower()
        token_id = token.get("token_id", "")
        if outcome and token_id:
            tokens[outcome] = token_id

    # CLOB/Gamma API format (clobTokenIds) - can be string or list
    if not tokens:
        clob_token_ids = data.get("clobTokenIds", data.get("clob_token_ids", []))

        # Parse if string (JSON array as string)
        if isinstance(clob_token_ids, str):
            try:
                clob_token_ids = json_module.loads(clob_token_ids)
            except json_module.JSONDecodeError:
                # Might be comma-separated
                clob_token_ids = [tid.strip() for tid in clob_token_ids.split(",") if tid.strip()]

        if isinstance(clob_token_ids, list) and len(clob_token_ids) >= 2:
            tokens["yes"] = clob_token_ids[0]
            tokens["no"] = clob_token_ids[1]

    return tokens


def get_market_id_from_token(token_id: str, market_tokens: dict[str, dict[str, str]]) -> str | None:
    """
    Get market ID from a token ID.

    Args:
        token_id: Token ID to look up
        market_tokens: Dict of market_id -> {"yes": token_id, "no": token_id}

    Returns:
        Market ID if found, None otherwise
    """
    for market_id, tokens in market_tokens.items():
        if token_id in tokens.values():
            return market_id
    return None


def get_outcome_from_token(token_id: str, market_tokens: dict[str, dict[str, str]]) -> OutcomeSide | None:
    """
    Get outcome side from a token ID.

    Args:
        token_id: Token ID to look up
        market_tokens: Dict of market_id -> {"yes": token_id, "no": token_id}

    Returns:
        OutcomeSide if found, None otherwise
    """
    for _, tokens in market_tokens.items():
        if tokens.get("yes") == token_id:
            return OutcomeSide.YES
        if tokens.get("no") == token_id:
            return OutcomeSide.NO
    return None


# === Event Parsing (Gamma API) ===


def parse_event(data: dict[str, Any]) -> Event:
    """
    Parse Polymarket event response into Event object.

    Expected from Gamma API /events endpoint.

    Args:
        data: Raw event data from Gamma API

    Returns:
        Parsed Event object with markets
    """
    import json as json_module

    # Event status
    active = data.get("active", True)
    closed = data.get("closed", False)
    status = _parse_event_status(active, closed)

    # Parse markets array
    markets_data = data.get("markets", [])
    if isinstance(markets_data, str):
        try:
            markets_data = json_module.loads(markets_data)
        except json_module.JSONDecodeError:
            markets_data = []

    # Parse each market and set event association
    # Filter out closed/inactive markets (not needed in runtime cache)
    event_slug = data.get("slug", "")
    event_title = data.get("title", "")
    markets = []
    for m in markets_data:
        is_active = m.get("active", True)
        is_closed = m.get("closed", False)
        if is_active and not is_closed:
            market = parse_market(m)
            market.event_id = event_slug
            market.event_title = event_title
            markets.append(market)

    return Event(
        id=event_slug,
        exchange="polymarket",
        title=event_title,
        description=data.get("description", ""),
        category=data.get("category", ""),
        status=status,
        markets=markets,
        end_date=parse_datetime(data.get("end_date_iso", data.get("endDate"))),
        volume=parse_decimal(data.get("volume")),
        volume_24h=parse_decimal(data.get("volume24hr")),
        liquidity=parse_decimal(data.get("liquidity")),
        image_url=data.get("image"),
        tags=_parse_tags(data.get("tags", [])),
        created_at=parse_datetime(data.get("created_at")),
        raw=data,
    )


def parse_events(data: list[dict[str, Any]]) -> list[Event]:
    """
    Parse multiple events.

    Args:
        data: List of raw event data from Gamma API

    Returns:
        List of parsed Event objects
    """
    return [parse_event(e) for e in data]


def _parse_event_status(active: bool, closed: bool) -> EventStatus:
    """Convert Polymarket event flags to EventStatus."""
    if closed:
        return EventStatus.CLOSED
    if not active:
        return EventStatus.RESOLVED
    return EventStatus.ACTIVE


# === Orderbook Parsing (CLOB API) ===


def parse_orderbook(data: dict[str, Any], market_id: str) -> OrderBook:
    """
    Parse Polymarket orderbook response.

    Expected from CLOB API /book endpoint.

    Args:
        data: Raw orderbook data from CLOB API
        market_id: Market ID (condition_id)

    Returns:
        Parsed OrderBook object
    """
    bids = []
    asks = []

    # Parse bids - format: {"price": "0.50", "size": "100"}
    for level in data.get("bids", []):
        price = parse_decimal(level.get("price"))
        size = parse_decimal(level.get("size"))
        if price is not None and size is not None:
            bids.append(OrderBookLevel(price=price, size=size))

    # Parse asks
    for level in data.get("asks", []):
        price = parse_decimal(level.get("price"))
        size = parse_decimal(level.get("size"))
        if price is not None and size is not None:
            asks.append(OrderBookLevel(price=price, size=size))

    # Sort: bids descending, asks ascending
    bids.sort(key=lambda x: x.price, reverse=True)
    asks.sort(key=lambda x: x.price)

    # Get timestamp if available
    timestamp = parse_datetime(data.get("timestamp")) or datetime.now(tz=timezone.utc)

    return OrderBook(
        market_id=market_id,
        bids=bids,
        asks=asks,
        timestamp=timestamp,
        exchange="polymarket",
    )


def parse_market_price(
    data: dict[str, Any],
    market_id: str,
    last_trade: dict[str, Any] | None = None,
) -> MarketPrice:
    """
    Parse market price from various sources.

    Args:
        data: Orderbook or midpoint data
        market_id: Market ID
        last_trade: Optional last trade data

    Returns:
        MarketPrice object
    """
    # Get best bid/ask from orderbook
    best_bid = None
    best_ask = None

    if data.get("bids"):
        bids = sorted(data["bids"], key=lambda x: float(x.get("price", 0)), reverse=True)
        if bids:
            best_bid = parse_decimal(bids[0].get("price"))

    if data.get("asks"):
        asks = sorted(data["asks"], key=lambda x: float(x.get("price", 0)))
        if asks:
            best_ask = parse_decimal(asks[0].get("price"))

    # Or get from midpoint response
    if data.get("mid"):
        mid_price = parse_decimal(data["mid"])
    elif best_bid is not None and best_ask is not None:
        mid_price = (best_bid + best_ask) / 2
    else:
        mid_price = None

    # Last trade price
    last_price = None
    if last_trade:
        last_price = parse_decimal(last_trade.get("price"))

    return MarketPrice(
        market_id=market_id,
        best_bid=best_bid,
        best_ask=best_ask,
        mid_price=mid_price,
        last_price=last_price,
        timestamp=datetime.now(tz=timezone.utc),
    )


# === Order Parsing (CLOB API) ===


def parse_order(data: dict[str, Any]) -> Order:
    """
    Parse Polymarket order response.

    Expected from CLOB API /orders endpoint.

    Args:
        data: Raw order data from CLOB API

    Returns:
        Parsed Order object
    """
    # Parse side - CLOB uses "BUY"/"SELL" or 0/1
    side_raw = data.get("side", "BUY")
    if isinstance(side_raw, int):
        side = OrderSide.BUY if side_raw == 0 else OrderSide.SELL
    else:
        side = OrderSide.BUY if str(side_raw).upper() == "BUY" else OrderSide.SELL

    # Parse outcome from asset_id or outcome field
    outcome = _parse_outcome(data)

    # Parse sizes
    original_size = parse_decimal(data.get("original_size", data.get("size", "0"))) or Decimal("0")
    size_matched = parse_decimal(data.get("size_matched", data.get("filled_size", "0"))) or Decimal("0")
    remaining = original_size - size_matched

    # Parse status - CLOB uses LIVE, MATCHED, CANCELLED
    status = _parse_order_status(data.get("status", data.get("state", "LIVE")))

    # Parse order type
    order_type = _parse_order_type(data.get("order_type", data.get("type", "GTC")))

    return Order(
        id=data.get("id", data.get("orderID", data.get("orderId", data.get("order_id", "")))),
        client_id=data.get("client_order_id"),
        market_id=data.get("market", data.get("condition_id", "")),
        exchange="polymarket",
        side=side,
        outcome=outcome,
        order_type=order_type,
        price=parse_decimal(data.get("price")),
        size=original_size,
        filled_size=size_matched,
        remaining_size=remaining if remaining > 0 else Decimal("0"),
        status=status,
        created_at=parse_datetime(data.get("created_at", data.get("timestamp"))) or datetime.now(tz=timezone.utc),
        updated_at=parse_datetime(data.get("updated_at")),
        raw=data,
    )


def parse_orders(data: list[Any]) -> list[Order]:
    """Parse multiple orders, handling various formats."""
    orders = []
    for order in data:
        if isinstance(order, dict):
            orders.append(parse_order(order))
        # Skip non-dict items (strings, None, etc.)
    return orders


# === Position Parsing (Data API) ===


def parse_position(data: dict[str, Any]) -> Position:
    """
    Parse Polymarket position response.

    Expected from Data API /positions endpoint.

    Args:
        data: Raw position data from Data API

    Returns:
        Parsed Position object
    """
    # Parse outcome
    outcome = _parse_outcome(data)

    # Parse numeric values
    size = parse_decimal(data.get("size", data.get("quantity", "0"))) or Decimal("0")
    avg_price = parse_decimal(data.get("avgPrice", data.get("average_price", "0"))) or Decimal("0")
    current_price = parse_decimal(data.get("curPrice", data.get("current_price")))

    # Calculate PnL if possible
    unrealized_pnl = None
    if current_price is not None and size > 0:
        unrealized_pnl = (current_price - avg_price) * size

    realized_pnl = parse_decimal(data.get("realizedPnl", data.get("realized_pnl", "0"))) or Decimal("0")

    return Position(
        market_id=data.get("conditionId", data.get("condition_id", data.get("market", ""))),
        exchange="polymarket",
        outcome=outcome,
        size=size,
        avg_price=avg_price,
        current_price=current_price,
        unrealized_pnl=unrealized_pnl,
        realized_pnl=realized_pnl,
        raw=data,
    )


def parse_positions(data: list[dict[str, Any]]) -> list[Position]:
    """Parse multiple positions."""
    return [parse_position(pos) for pos in data]


def parse_portfolio_summary(
    positions: list[Position],
    balance: Decimal,
) -> PortfolioSummary:
    """
    Calculate portfolio summary from positions and balance.

    Args:
        positions: List of parsed positions
        balance: Cash balance (USDC)

    Returns:
        PortfolioSummary object with required fields and additional_info
    """
    positions_value = Decimal("0")
    unrealized_pnl = Decimal("0")
    realized_pnl = Decimal("0")

    for pos in positions:
        if pos.current_price is not None:
            positions_value += pos.size * pos.current_price
        else:
            # Use avg price if current not available
            positions_value += pos.size * pos.avg_price

        if pos.unrealized_pnl is not None:
            unrealized_pnl += pos.unrealized_pnl
        realized_pnl += pos.realized_pnl

    total_value = balance + positions_value

    return PortfolioSummary(
        exchange="polymarket",
        cash_balance=balance,
        total_value=total_value,
        additional_info={
            "positions_value": positions_value,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": realized_pnl,
            "positions_count": len(positions),
            "positions": positions,  # Full position list for Polymarket
        },
    )


# === Trade Parsing (CLOB API) ===


def parse_trade(data: dict[str, Any]) -> Trade:
    """
    Parse Polymarket trade response.

    Args:
        data: Raw trade data from CLOB API

    Returns:
        Parsed Trade object
    """
    # Parse side
    side_raw = data.get("side", "BUY")
    if isinstance(side_raw, int):
        side = OrderSide.BUY if side_raw == 0 else OrderSide.SELL
    else:
        side = OrderSide.BUY if str(side_raw).upper() == "BUY" else OrderSide.SELL

    # Parse outcome
    outcome = _parse_outcome(data)

    return Trade(
        id=data.get("id", data.get("trade_id", "")),
        order_id=data.get("order_id", data.get("maker_order_id", "")),
        market_id=data.get("market", data.get("condition_id", "")),
        exchange="polymarket",
        side=side,
        outcome=outcome,
        price=parse_decimal(data.get("price")) or Decimal("0"),
        size=parse_decimal(data.get("size", data.get("amount"))) or Decimal("0"),
        fee=parse_decimal(data.get("fee", data.get("trading_fee", "0"))) or Decimal("0"),
        timestamp=parse_datetime(data.get("timestamp", data.get("match_time"))) or datetime.now(tz=timezone.utc),
        raw=data,
    )


def parse_trades(data: list[dict[str, Any]]) -> list[Trade]:
    """Parse multiple trades."""
    return [parse_trade(trade) for trade in data]


# === Fee Parsing ===


def get_fee_structure() -> FeeStructure:
    """
    Get Polymarket fee structure.

    Returns:
        FeeStructure for Polymarket
    """
    return FeeStructure(
        exchange="polymarket",
        maker_fee=Decimal("0"),  # Polymarket has 0% maker fee
        taker_fee=Decimal("0"),  # 0% taker fee as of 2024
        settlement_fee=Decimal("0.02"),  # 2% on winning positions
        withdrawal_fee=None,  # Gas fees only
    )


def calculate_fee_breakdown(
    size: Decimal,
    price: Decimal,
    is_maker: bool = True,
) -> FeeBreakdown:
    """
    Calculate fee breakdown for an order.

    Args:
        size: Order size in shares
        price: Order price
        is_maker: Whether this is a maker order

    Returns:
        FeeBreakdown for the order
    """
    fees = get_fee_structure()

    # Trading fee (currently 0 for both maker/taker)
    fee_rate = fees.maker_fee if is_maker else fees.taker_fee
    notional = size * price
    trading_fee = notional * fee_rate

    # Estimated settlement fee (if position wins)
    # Settlement is 2% on payout, payout = size * 1 for winning
    estimated_settlement = size * fees.settlement_fee

    return FeeBreakdown(
        trading_fee=trading_fee,
        is_maker=is_maker,
        estimated_settlement_fee=estimated_settlement,
        total_estimated=trading_fee + estimated_settlement,
    )


# === Helper Functions ===


def _parse_market_status(active: bool, closed: bool, accepting_orders: bool = True) -> MarketStatus:
    """Convert Polymarket status flags to MarketStatus."""
    if closed:
        return MarketStatus.CLOSED
    if not active:
        return MarketStatus.RESOLVED
    if not accepting_orders:
        return MarketStatus.HALTED
    return MarketStatus.ACTIVE


def _parse_resolution(value: str | None) -> Resolution | None:
    """Parse resolution string to Resolution enum."""
    if value is None:
        return None
    value_lower = str(value).lower()
    if value_lower in ("yes", "1", "true", "p1"):
        return Resolution.YES
    if value_lower in ("no", "0", "false", "p2"):
        return Resolution.NO
    if value_lower in ("invalid", "void", "cancelled"):
        return Resolution.INVALID
    return Resolution.PENDING


def _parse_outcome(data: dict[str, Any]) -> OutcomeSide:
    """Parse outcome from various data formats."""
    # Direct outcome field
    outcome_str = data.get("outcome", data.get("asset_outcome", ""))
    if outcome_str:
        outcome_lower = str(outcome_str).lower()
        if outcome_lower in ("yes", "y", "1", "p1"):
            return OutcomeSide.YES
        if outcome_lower in ("no", "n", "0", "p2"):
            return OutcomeSide.NO

    # Token index (0 = YES, 1 = NO typically)
    token_index = data.get("token_index", data.get("outcome_index"))
    if token_index is not None:
        return OutcomeSide.YES if token_index == 0 else OutcomeSide.NO

    # Default to YES if unknown
    return OutcomeSide.YES


def _parse_order_type(value: str) -> OrderType:
    """Parse order type string to OrderType enum."""
    value_upper = str(value).upper()

    if value_upper in ("MARKET", "MKT"):
        return OrderType.MARKET
    if value_upper in ("IOC", "LIMIT_IOC", "IMMEDIATE_OR_CANCEL"):
        return OrderType.LIMIT_IOC
    if value_upper in ("FOK", "LIMIT_FOK", "FILL_OR_KILL"):
        return OrderType.LIMIT_FOK
    if value_upper in ("GTD", "LIMIT_GTD", "GOOD_TIL_DATE"):
        return OrderType.LIMIT_GTD

    # GTC (Good Till Cancelled) is default LIMIT
    return OrderType.LIMIT


def _parse_order_status(value: str) -> OrderStatus:
    """Parse order status string to OrderStatus enum."""
    status_map = {
        # CLOB API statuses
        "live": OrderStatus.OPEN,
        "open": OrderStatus.OPEN,
        "matched": OrderStatus.FILLED,
        "filled": OrderStatus.FILLED,
        "cancelled": OrderStatus.CANCELLED,
        "canceled": OrderStatus.CANCELLED,
        # Additional statuses
        "pending": OrderStatus.PENDING,
        "partial": OrderStatus.PARTIAL,
        "partially_filled": OrderStatus.PARTIAL,
        "expired": OrderStatus.EXPIRED,
        "rejected": OrderStatus.REJECTED,
        "failed": OrderStatus.REJECTED,
    }
    return status_map.get(str(value).lower(), OrderStatus.OPEN)
