"""
Abstract Base Class for prediction market exchanges.

This module defines the unified interface that all exchange implementations must follow.

Structure:
- ExchangeBase: Abstract methods that MUST be implemented
- DefaultImplementationsMixin: Default implementations that CAN be overridden
- Exchange: Combined class for subclassing
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any

from prediction_markets.base.types import (
    BatchOrderError,
    BatchOrderResult,
    Event,
    FeeBreakdown,
    FeeStructure,
    Market,
    MarketPrice,
    Order,
    OrderBook,
    OrderSide,
    OrderType,
    OutcomeSide,
    PortfolioSummary,
    Position,
    Resolution,
    SizeType,
)
from prediction_markets.common.exceptions import (
    MarketNotFoundError,
    UnsupportedFeatureError,
    WebSocketError,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Abstract Base - Methods that MUST be implemented by each exchange
# =============================================================================


class ExchangeBase(ABC):
    """
    Abstract methods that every exchange MUST implement.

    These are the core methods required for any exchange to function.
    """

    # --- Lifecycle ---

    @abstractmethod
    async def _init_rest_client(self) -> None:
        """Initialize REST client. Called by init()."""
        pass

    @abstractmethod
    async def _close_rest_client(self) -> None:
        """Close REST client. Called by close()."""
        pass

    @abstractmethod
    async def _init_websocket(self) -> None:
        """Initialize WebSocket connection."""
        pass

    @abstractmethod
    async def _close_websocket(self) -> None:
        """Close WebSocket connection."""
        pass

    # --- Market Data ---

    @abstractmethod
    async def _fetch_events(self) -> list[Event]:
        """
        Fetch events (market groups) from exchange.

        For exchanges without native event support, return a single
        "all" event containing all markets.

        Returns:
            List of Event objects with their markets
        """
        pass

    @abstractmethod
    async def _fetch_orderbook_rest(self, market_id: str, outcome: OutcomeSide) -> OrderBook:
        """Fetch orderbook via REST API."""
        pass

    @abstractmethod
    async def _fetch_resolution(self, market_id: str) -> Resolution | None:
        """Fetch market resolution status from API."""
        pass

    # --- WebSocket ---

    @abstractmethod
    async def _subscribe_orderbook(self, market_id: str) -> None:
        """Subscribe to orderbook updates via WebSocket."""
        pass

    @abstractmethod
    async def _unsubscribe_orderbook(self, market_id: str) -> None:
        """Unsubscribe from orderbook updates."""
        pass

    # --- Trading ---

    @abstractmethod
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
        """Create order implementation."""
        pass

    @abstractmethod
    async def _cancel_order_impl(self, order_id: str) -> bool:
        """Cancel single order implementation."""
        pass

    @abstractmethod
    async def _fetch_open_orders(self, market_id: str | None) -> list[Order]:
        """Fetch open orders."""
        pass

    # --- Positions ---

    @abstractmethod
    async def _fetch_position(self, market_id: str, side: OutcomeSide | None) -> Position | None:
        """Fetch position for a market."""
        pass

    @abstractmethod
    async def _fetch_portfolio_summary(self) -> PortfolioSummary:
        """Fetch portfolio summary."""
        pass

    # --- Fees ---

    @abstractmethod
    def _get_fee_structure(self) -> FeeStructure:
        """Get exchange fee structure."""
        pass

    # --- On-chain Operations ---

    @abstractmethod
    async def split(self, market_id: str, amount: Decimal) -> dict[str, Any]:
        """Split collateral into YES + NO tokens."""
        pass

    @abstractmethod
    async def merge(self, market_id: str, amount: Decimal) -> dict[str, Any]:
        """Merge YES + NO tokens back into collateral."""
        pass

    @abstractmethod
    async def redeem(self, market_id: str) -> dict[str, Any]:
        """Redeem winning positions after market resolution."""
        pass


# =============================================================================
# Default Implementations Mixin - CAN be overridden by exchanges
# =============================================================================


class DefaultImplementationsMixin:
    """
    Default implementations that work for most exchanges.

    Exchanges can override these for optimized or exchange-specific behavior.
    """

    async def create_order_batch(
        self,
        orders: list[dict[str, Any]],
    ) -> BatchOrderResult:
        """
        Create multiple orders concurrently.

        Default: Uses asyncio.gather with individual create_order calls.
        Override: If exchange supports native batch API for better performance.

        Args:
            orders: List of order dicts with keys:
                - market_id, side, outcome, size, price (optional), size_type (optional)

        Returns:
            BatchOrderResult with successful orders and failed order details

        Example:
            ```python
            result = await exchange.create_order_batch([
                {"market_id": "m1", "side": "buy", "outcome": "yes", "size": 10, "price": 0.65},
                {"market_id": "m2", "side": "buy", "outcome": "no", "size": 5, "price": 0.40},
            ])

            print(f"Success: {len(result.successful)}/{result.total}")

            if not result.all_successful:
                for error in result.failed:
                    print(f"Order {error.index} failed: {error.error_message}")
            ```
        """
        tasks = [
            self.create_order(
                market_id=o["market_id"],
                side=OrderSide(o["side"]) if isinstance(o["side"], str) else o["side"],
                outcome=OutcomeSide(o["outcome"]) if isinstance(o["outcome"], str) else o["outcome"],
                size=Decimal(str(o["size"])),
                price=Decimal(str(o["price"])) if o.get("price") else None,
                size_type=SizeType(o.get("size_type", "shares")),
            )
            for o in orders
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        successful: list[Order] = []
        failed: list[BatchOrderError] = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                error = BatchOrderError(
                    index=i,
                    order_input=orders[i],
                    error=result,
                    error_message=str(result),
                )
                failed.append(error)
                logger.error(f"[{self.id}] Batch order {i} failed: {result}")
            else:
                successful.append(result)

        return BatchOrderResult(successful=successful, failed=failed)

    async def close_position(
        self,
        market_id: str,
        outcome: OutcomeSide,
        size: Decimal | None = None,
    ) -> Order | None:
        """
        Close a position at market price.

        Default: Places a market sell order for the position.
        Override: If exchange has a dedicated close position API.

        Args:
            market_id: Market ID
            outcome: YES or NO position to close
            size: Size to close (None = entire position)

        Returns:
            Order if placed, None if no position
        """
        position = await self.fetch_position(market_id, outcome)
        if not position or position.size <= 0:
            return None

        close_size = size if size is not None else position.size
        if close_size > position.size:
            raise ValueError(f"Close size ({close_size}) exceeds position ({position.size})")

        return await self.create_order(
            market_id=market_id,
            side=OrderSide.SELL,
            outcome=outcome,
            size=close_size,
        )

    def calculate_fees(
        self,
        size: Decimal,
        price: Decimal,
        is_maker: bool = False,
    ) -> FeeBreakdown:
        """
        Calculate estimated fees for an order.

        Default: Uses fee structure with maker/taker rates.
        Override: If exchange has complex fee calculations.

        Args:
            size: Order size in shares
            price: Order price
            is_maker: Whether this is a maker order

        Returns:
            FeeBreakdown with trading and settlement fees
        """
        fee_structure = self._get_fee_structure()
        notional = size * price

        fee_rate = fee_structure.maker_fee if is_maker else fee_structure.taker_fee
        trading_fee = notional * fee_rate

        potential_payout = size
        estimated_settlement = potential_payout * fee_structure.settlement_fee

        return FeeBreakdown(
            trading_fee=trading_fee,
            is_maker=is_maker,
            estimated_settlement_fee=estimated_settlement,
            total_estimated=trading_fee + estimated_settlement,
        )


# =============================================================================
# Exchange - Main class combining abstract + defaults
# =============================================================================


class Exchange(ExchangeBase, DefaultImplementationsMixin):
    """
    Abstract Base Class for prediction market exchanges.

    Subclasses must implement all abstract methods from ExchangeBase.
    Default implementations from DefaultImplementationsMixin can be overridden.

    Example:
        ```python
        exchange = create_exchange("polymarket", config)
        async with exchange:
            events = await exchange.load_events()
            order = await exchange.create_order(...)
        ```
    """

    # === Class Attributes (override in subclass) ===

    id: str = ""
    name: str = ""
    ws_support: bool = True

    has: dict[str, bool] = {
        "load_events": True,  # Load events with markets
        "search_events": True,  # Search events by keyword

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

        "split": True,
        "merge": True,
        "redeem": True,

        "calculate_fees": True,
        
        # === optional ===
        "fetch_event": False,  # Fetch single event by ID
        "fetch_categories": False,  # Fetch categories from exchange
        "fetch_all_positions": False,
    }

    ws_supported: dict[str, bool] = {
        "fetch_orderbook": False,
        "fetch_market_price": False,
        "fetch_open_orders": False,
        "fetch_position": False,
    }

    def __init__(self, config: dict[str, Any]) -> None:
        """
        Initialize exchange instance.

        Args:
            config: Exchange configuration dictionary

        Note:
            Call init() to establish connections.
        """
        self.config = config
        self.testnet = config.get("testnet", False)
        self.ws_enabled = config.get("ws_enabled", True) and self.ws_support

        self._initialized = False
        self._events: dict[str, Event] = {}  # event_id -> Event
        self._markets: dict[str, Market] = {}  # market_id -> Market (flat cache)
        self._categories: list[dict[str, Any]] = []  # category list cache
        self._orderbooks: dict[str, dict[OutcomeSide, OrderBook]] = {}
        self._ws_connected = False

    # === Lifecycle ===

    async def init(self) -> None:
        """Initialize exchange connections."""
        if self._initialized:
            return

        print(f"[{self.id}] Initializing...")
        await self._init_rest_client()

        print(f"[{self.id}] Loading events/markets...")
        await self.load_events()

        if self.ws_enabled:
            print(f"[{self.id}] WebSocket enabled (lazy connect)")

        self._initialized = True
        print(f"[{self.id}] Ready")

    async def close(self) -> None:
        """Close all connections."""
        print(f"[{self.id}] Closing...")
        await self._close_websocket()
        await self._close_rest_client()
        self._markets.clear()
        self._orderbooks.clear()
        self._initialized = False
        self._ws_connected = False

    async def __aenter__(self) -> "Exchange":
        await self.init()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        await self.close()

    # === Market Data ===

    async def load_events(self, reload: bool = False) -> dict[str, Event]:
        """
        Load events (market groups) from exchange.

        Events contain related markets. For exchanges without native
        event support, all markets are grouped under an "all" event.

        Args:
            reload: Force reload even if already loaded

        Returns:
            Dict mapping event ID to Event object

        Note:
            Only active events with active markets are loaded.
            Closed/resolved markets are filtered out as they are
            only needed for position redemption.
        """
        if self._events and not reload:
            return self._events

        events = await self._fetch_events()

        self._events.clear()
        self._markets.clear()

        for event in events:
            self._events[event.id] = event
            # Also populate flat market cache
            for market in event.markets:
                self._markets[market.id] = market

        return self._events

    def get_event(self, event_id: str) -> Event:
        """Get event by ID from cache."""
        if event_id not in self._events:
            raise ValueError(f"Event '{event_id}' not found in cache")
        return self._events[event_id]

    def get_market(self, market_id: str) -> Market:
        """Get market by ID."""
        if market_id not in self._markets:
            raise MarketNotFoundError(
                f"Market '{market_id}' not found",
                exchange=self.id,
                market_id=market_id,
            )
        return self._markets[market_id]

    def get_events(self) -> dict[str, Event]:
        """Return all cached events.

        Returns:
            dict[str, Event]: Event ID -> Event mapping

        Note:
            Call load_events() or search_events() first to populate cache.
        """
        return self._events

    def get_markets(self) -> dict[str, Market]:
        """Return all cached markets.

        Returns:
            dict[str, Market]: Market ID -> Market mapping

        Note:
            Call load_events() or search_events() first to populate cache.
        """
        return self._markets

    def get_categories(self) -> list[dict[str, Any]]:
        """Return cached categories.

        Returns:
            list[dict[str, Any]]: List of category dicts with 'label', 'slug' fields

        Note:
            Call fetch_categories() first to populate cache.
        """
        return self._categories

    async def search_events(
        self,
        keyword: str,
        limit: int = 50,
        tag: str | None = None,
    ) -> list[Event]:
        """
        Search events by keyword.

        Returns Event objects with their grouped markets.

        Args:
            keyword: Search keyword
            limit: Maximum events to return
            tag: Optional category tag filter

        Returns:
            List of Event objects with their markets

        Note:
            Only active events with active markets are returned.
            Closed/resolved markets are filtered out as they are
            only needed for position redemption.
        """
        self._check_feature("search_events")
        raise NotImplementedError("search_events not implemented for this exchange")

    async def fetch_event(self, event_id: str) -> Event:
        """
        Fetch single event by ID or slug from exchange.

        Args:
            event_id: Event ID or slug

        Returns:
            Event object with its markets

        Raises:
            UnsupportedFeatureError: If exchange doesn't support events
            ValueError: If event not found
        """
        self._check_feature("fetch_event")
        raise NotImplementedError("fetch_event not implemented for this exchange")

    async def fetch_categories(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Fetch categories from exchange and cache them.

        Args:
            limit: Maximum number of categories to fetch

        Returns:
            List of category dicts with 'label', 'slug' fields

        Note:
            Use get_categories() to access cached categories.
        """
        self._check_feature("fetch_categories")
        raise NotImplementedError("fetch_categories not implemented for this exchange")

    async def fetch_orderbook(
        self,
        market_id: str,
        outcome: OutcomeSide,
        use_cache: bool = True,
    ) -> OrderBook:
        """Fetch orderbook for a market outcome."""
        self.get_market(market_id)

        if self.ws_enabled and self._ws_connected:
            if use_cache:
                cached = self._orderbooks.get(market_id, {}).get(outcome)
                if cached:
                    return cached

            try:
                await self._subscribe_orderbook(market_id)
                await asyncio.sleep(0.5)
                cached = self._orderbooks.get(market_id, {}).get(outcome)
                if cached:
                    return cached
            except WebSocketError as e:
                logger.warning(f"[{self.id}] WS failed, using REST: {e}")
                print(f"[{self.id}] WS failed, using REST: {e}")

        return await self._fetch_orderbook_rest(market_id, outcome)

    async def fetch_market_price(self, market_id: str, outcome: OutcomeSide) -> MarketPrice:
        """Fetch current market price."""
        ob = await self.fetch_orderbook(market_id, outcome)

        mid_price = None
        if ob.best_bid is not None and ob.best_ask is not None:
            mid_price = (ob.best_bid + ob.best_ask) / 2
        elif ob.best_bid is not None:
            mid_price = ob.best_bid
        elif ob.best_ask is not None:
            mid_price = ob.best_ask

        return MarketPrice(
            market_id=market_id,
            best_bid=ob.best_bid,
            best_ask=ob.best_ask,
            mid_price=mid_price,
            last_price=None,
            timestamp=ob.timestamp,
        )

    async def fetch_market_resolution(self, market_id: str) -> Resolution | None:
        """Fetch market resolution status (YES/NO/INVALID or None if not resolved)."""
        return await self._fetch_resolution(market_id)

    # === Trading ===

    async def create_order(
        self,
        market_id: str,
        side: OrderSide,
        outcome: OutcomeSide,
        size: Decimal,
        price: Decimal | None = None,
        size_type: SizeType = SizeType.SHARES,
        order_type: OrderType | None = None,
        client_id: str | None = None,
    ) -> Order:
        """Create a new order."""
        self.get_market(market_id)  # Validate market exists

        if order_type is None:
            order_type = OrderType.LIMIT if price is not None else OrderType.MARKET

        if size_type == SizeType.USD:
            size = await self._convert_usd_to_shares(market_id, size, side, outcome)

        logger.info(f"[{self.id}] Order: {side.value} {size} {outcome.value} @ {price or 'MARKET'}")

        return await self._create_order_impl(
            market_id=market_id,
            side=side,
            outcome=outcome,
            size=size,
            price=price,
            order_type=order_type,
            client_id=client_id,
        )

    async def cancel_orders(
        self,
        market_id: str | None = None,
        order_ids: list[str] | None = None,
    ) -> list[str]:
        """Cancel orders."""
        if order_ids:
            cancelled: list[str] = []
            for order_id in order_ids:
                try:
                    if await self._cancel_order_impl(order_id):
                        cancelled.append(order_id)
                except Exception as e:
                    logger.error(f"[{self.id}] Cancel failed {order_id}: {e}")
            return cancelled
        elif market_id:
            open_orders = await self._fetch_open_orders(market_id)
            return await self.cancel_orders(order_ids=[o.id for o in open_orders])
        else:
            open_orders = await self._fetch_open_orders(None)
            return await self.cancel_orders(order_ids=[o.id for o in open_orders])

    # === Account ===

    async def fetch_open_orders(self, market_id: str | None = None) -> list[Order]:
        """Fetch open orders."""
        return await self._fetch_open_orders(market_id)

    async def fetch_position(self, market_id: str, side: OutcomeSide | None = None) -> Position | None:
        """Fetch position for a market."""
        return await self._fetch_position(market_id, side)

    async def fetch_portfolio_summary(self) -> PortfolioSummary:
        """Fetch portfolio summary."""
        return await self._fetch_portfolio_summary()

    # === Fees ===

    def get_fee_structure(self) -> FeeStructure:
        """Get exchange fee structure."""
        return self._get_fee_structure()

    # === Internal Helpers ===

    async def _convert_usd_to_shares(
        self,
        market_id: str,
        usd_amount: Decimal,
        side: OrderSide,
        outcome: OutcomeSide,
    ) -> Decimal:
        """Convert USD to shares based on current price."""
        price = await self.fetch_market_price(market_id, outcome)

        if side == OrderSide.BUY:
            ref_price = price.best_ask or price.mid_price
        else:
            ref_price = price.best_bid or price.mid_price

        if ref_price is None or ref_price == 0:
            raise ValueError(f"Cannot determine price for {market_id}")

        return (usd_amount / ref_price).quantize(Decimal("0.01"))

    def _check_feature(self, feature: str) -> None:
        """Check if feature is supported."""
        if not self.has.get(feature, False):
            raise UnsupportedFeatureError(feature, exchange=self.id)

    def _update_orderbook_cache(self, market_id: str, outcome: OutcomeSide, orderbook: OrderBook) -> None:
        """Update cached orderbook."""
        if market_id not in self._orderbooks:
            self._orderbooks[market_id] = {}
        self._orderbooks[market_id][outcome] = orderbook
