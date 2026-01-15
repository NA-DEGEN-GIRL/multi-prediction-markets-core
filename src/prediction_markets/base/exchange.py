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
    async def _fetch_markets(self) -> list[Market]:
        """Fetch all markets from exchange."""
        pass

    @abstractmethod
    async def search_markets(
        self, keyword: str, limit: int = 20, tag: str | None = None
    ) -> list[Market]:
        """Search markets by keyword."""
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
    async def split_position(self, market_id: str, amount: Decimal) -> dict[str, Any]:
        """Split collateral into YES + NO tokens."""
        pass

    @abstractmethod
    async def merge_positions(self, market_id: str, amount: Decimal) -> dict[str, Any]:
        """Merge YES + NO tokens back into collateral."""
        pass

    @abstractmethod
    async def redeem_positions(self, market_id: str) -> dict[str, Any]:
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
    ) -> list[Order]:
        """
        Create multiple orders concurrently.

        Default: Uses asyncio.gather with individual create_order calls.
        Override: If exchange supports native batch API for better performance.

        Args:
            orders: List of order dicts with keys:
                - market_id, side, outcome, size, price (optional), size_type (optional)

        Returns:
            List of created Order objects
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

        created_orders: list[Order] = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                logger.error(f"[{self.id}] Batch order {i} failed: {result}")
            else:
                created_orders.append(result)

        return created_orders

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
        position = await self.get_position(market_id, outcome)
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
            markets = await exchange.load_markets()
            order = await exchange.create_order(...)
        ```
    """

    # === Class Attributes (override in subclass) ===

    id: str = ""
    name: str = ""
    ws_support: bool = True

    has: dict[str, bool] = {
        "load_markets": True,
        "search_markets": True,
        "get_market_price": True,
        "get_orderbook": True,
        "get_market_resolution": True,
        "create_order": True,
        "create_order_batch": True,
        "cancel_orders": True,
        "get_open_orders": True,
        "get_position": True,
        "close_position": True,
        "get_portfolio_summary": True,
        "split_positions": True,
        "merge_positions": True,
        "redeem_positions": True,
        "calculate_fees": True,
    }

    ws_supported: dict[str, bool] = {
        "get_orderbook": False,
        "get_market_price": False,
        "get_open_orders": False,
        "get_position": False,
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
        self._markets: dict[str, Market] = {}
        self._markets_by_exchange_id: dict[str, str] = {}
        self._orderbooks: dict[str, dict[OutcomeSide, OrderBook]] = {}
        self._ws_connected = False

    # === Lifecycle ===

    async def init(self) -> None:
        """Initialize exchange connections."""
        if self._initialized:
            return

        print(f"[{self.id}] Initializing...")
        await self._init_rest_client()

        print(f"[{self.id}] Loading markets...")
        await self.load_markets()

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

    async def load_markets(self, reload: bool = False) -> dict[str, Market]:
        """
        Load markets from exchange.

        Note: For exchanges with many markets (e.g., Polymarket),
        this returns a subset of recent/active markets, not all markets.
        Use search_markets() for finding specific markets.

        Args:
            reload: Force reload even if already loaded

        Returns:
            Dict mapping market ID to Market object
        """
        if self._markets and not reload:
            return self._markets

        markets = await self._fetch_markets()

        self._markets.clear()
        self._markets_by_exchange_id.clear()

        for market in markets:
            self._markets[market.id] = market
            self._markets_by_exchange_id[market.exchange_id] = market.id

        return self._markets

    def get_market(self, market_id: str) -> Market:
        """Get market by ID."""
        if market_id not in self._markets:
            raise MarketNotFoundError(
                f"Market '{market_id}' not found",
                exchange=self.id,
                market_id=market_id,
            )
        return self._markets[market_id]

    async def get_orderbook(
        self,
        market_id: str,
        outcome: OutcomeSide,
        use_cache: bool = True,
    ) -> OrderBook:
        """Get orderbook for a market outcome."""
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

    async def get_market_price(self, market_id: str, outcome: OutcomeSide) -> MarketPrice:
        """Get current market price."""
        ob = await self.get_orderbook(market_id, outcome)

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

    async def get_market_resolution(self, market_id: str) -> Resolution | None:
        """Get market resolution status (YES/NO/INVALID or None if not resolved)."""
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

    async def get_open_orders(self, market_id: str | None = None) -> list[Order]:
        """Get open orders."""
        return await self._fetch_open_orders(market_id)

    async def get_position(self, market_id: str, side: OutcomeSide | None = None) -> Position | None:
        """Get position for a market."""
        return await self._fetch_position(market_id, side)

    async def get_portfolio_summary(self) -> PortfolioSummary:
        """Get portfolio summary."""
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
        price = await self.get_market_price(market_id, outcome)

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
