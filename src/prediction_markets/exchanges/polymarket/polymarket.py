"""
Polymarket exchange implementation.

Polymarket is a decentralized prediction market on Polygon.
Uses three APIs for different functionality:
- CLOB API: Trading, orderbooks, orders
- Gamma API: Market metadata, resolution status
- Data API: Positions, portfolio

API Documentation: https://docs.polymarket.com/
"""

import asyncio
import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


# Default TTL for token cache (1 hour)
TOKEN_CACHE_TTL_SECONDS = 3600


@dataclass
class CachedTokens:
    """Cached token IDs with TTL."""
    tokens: dict[str, str]  # {"yes": token_id, "no": token_id}
    cached_at: float = field(default_factory=time.time)

    def is_expired(self, ttl: float = TOKEN_CACHE_TTL_SECONDS) -> bool:
        """Check if cache entry has expired."""
        return (time.time() - self.cached_at) > ttl

from prediction_markets.base.exchange import Exchange
from prediction_markets.base.types import (
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
from prediction_markets.common.exceptions import (
    AuthenticationError,
    InvalidOrderError,
)
from prediction_markets.exchanges.polymarket.parser import (
    get_fee_structure,
    parse_market,
    parse_market_tokens,
    parse_order,
    parse_orderbook,
    parse_orders,
    parse_portfolio_summary,
    parse_position,
    parse_resolution,
    parse_positions,
)
from prediction_markets.exchanges.polymarket.builder_client import BuilderRelayerClient
from prediction_markets.exchanges.polymarket.rest_api import (
    ApiCreds,
    PolymarketRestClient,
)
from prediction_markets.exchanges.polymarket.signer import (
    CreateOrderOptions,
    OrderArgs,
    Side,
    SignatureType,
    get_order_signer,
)
from prediction_markets.exchanges.polymarket.ws_client import (
    PolymarketWebSocketClient,
)

logger = logging.getLogger(__name__)


class Polymarket(Exchange):
    """
    Polymarket exchange implementation.

    Polymarket is a decentralized prediction market on Polygon.
    Supports both REST and WebSocket APIs.

    Configuration:
        Required:
        - private_key: Wallet private key (hex string starting with 0x)

        Optional:
        - chain_id: Chain ID (137 for Polygon mainnet, 80002 for Amoy testnet)
        - funder: Funder address (proxy wallet address from Polymarket settings)
        - proxy_wallet: Same as funder (alias)
        - ws_enabled: Enable WebSocket (default: True)
        - api_creds: Pre-existing API credentials (ApiCreds object)

        For split/merge (gasless):
        - builder_api_key: Builder API key from polymarket.com/settings?tab=builder
        - builder_secret: Builder API secret
        - builder_passphrase: Builder API passphrase

    Example:
        ```python
        exchange = Polymarket({
            "private_key": "0x...",
        })

        async with exchange:
            # Get markets
            markets = await exchange.load_markets()

            # Get orderbook
            ob = await exchange.get_orderbook("condition_id", OutcomeSide.YES)

            # Place order
            order = await exchange.create_order(
                market_id="condition_id",
                side=OrderSide.BUY,
                outcome=OutcomeSide.YES,
                size=Decimal("10"),
                price=Decimal("0.65"),
            )
        ```
    """

    id = "polymarket"
    name = "Polymarket"
    ws_support = True

    # API endpoints
    CLOB_URL = "https://clob.polymarket.com"
    GAMMA_URL = "https://gamma-api.polymarket.com"
    DATA_URL = "https://data-api.polymarket.com"
    WS_MARKET_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    WS_USER_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"

    # Feature flags
    has = {
        "load_markets": True,
        "search_markets": True,
        "get_categories": True,
        "get_market_price": True,
        "get_orderbook": True,
        "create_order": True,
        "create_order_batch": True,
        "cancel_orders": True,
        "get_open_orders": True,
        "get_position": True,
        "close_position": True,
        "get_portfolio_summary": True,
        "get_market_resolution": True,
        "calculate_fees": True,
        "websocket": True,
        # On-chain CTF contract operations (requires web3)
        "merge_positions": True,
        "split_positions": True,
        "redeem_positions": True,
    }

    # WebSocket supported features - real-time updates without polling
    ws_supported = {
        "get_orderbook": True,  # Real-time orderbook via WS
        "get_market_price": True,  # Derived from orderbook
        "get_open_orders": False,  # REST only for now
        "get_position": False,  # REST only
    }

    def __init__(self, config: dict[str, Any]) -> None:
        """Initialize Polymarket exchange."""
        super().__init__(config)

        # Validate and extract config
        self._validate_config(config)

        # Wallet configuration
        self._private_key = config.get("private_key")
        self._chain_id = config.get("chain_id", 137)  # Polygon mainnet
        self._funder = config.get("funder") or config.get("proxy_wallet")
        self._proxy_wallet = config.get("proxy_wallet") or config.get("funder")

        # Builder credentials for gasless split/merge
        self._builder_api_key = config.get("builder_api_key")
        self._builder_secret = config.get("builder_secret")
        self._builder_passphrase = config.get("builder_passphrase")

        # Pre-existing API credentials (optional)
        self._api_creds: ApiCreds | None = config.get("api_creds")

        # Clients
        self._rest_client: PolymarketRestClient | None = None
        self._ws_client: PolymarketWebSocketClient | None = None
        self._builder_client: BuilderRelayerClient | None = None
        self._order_signer = None

        # Market token mapping with TTL: condition_id -> CachedTokens
        self._market_tokens: dict[str, CachedTokens] = {}

    def _validate_config(self, config: dict[str, Any]) -> None:
        """
        Validate configuration values.

        Raises:
            ValueError: If config values are invalid
        """
        # Validate private_key format if provided
        private_key = config.get("private_key")
        if private_key:
            if not isinstance(private_key, str):
                raise ValueError("private_key must be a string")
            if not private_key.startswith("0x"):
                raise ValueError("private_key must start with '0x'")
            if len(private_key) != 66:  # 0x + 64 hex chars
                raise ValueError("private_key must be 66 characters (0x + 64 hex)")

        # Validate chain_id
        chain_id = config.get("chain_id", 137)
        if chain_id not in (137, 80002):
            raise ValueError(f"Invalid chain_id: {chain_id}. Use 137 (mainnet) or 80002 (testnet)")

        # Validate proxy_wallet format if provided
        proxy_wallet = config.get("proxy_wallet")
        if proxy_wallet:
            if not isinstance(proxy_wallet, str):
                raise ValueError("proxy_wallet must be a string")
            if not proxy_wallet.startswith("0x"):
                raise ValueError("proxy_wallet must start with '0x'")
            if len(proxy_wallet) != 42:  # 0x + 40 hex chars
                raise ValueError("proxy_wallet must be 42 characters (0x + 40 hex)")

        # Validate builder credentials (all or none)
        builder_api_key = config.get("builder_api_key")
        builder_secret = config.get("builder_secret")
        builder_passphrase = config.get("builder_passphrase")

        builder_creds = [builder_api_key, builder_secret, builder_passphrase]
        if any(builder_creds) and not all(builder_creds):
            raise ValueError(
                "Builder credentials must be provided together: "
                "builder_api_key, builder_secret, builder_passphrase"
            )

    @property
    def address(self) -> str | None:
        """Get wallet address."""
        if self._rest_client:
            return self._rest_client.address
        return None

    # === Lifecycle Implementation ===

    async def _init_rest_client(self) -> None:
        """Initialize REST client."""
        print(f"[{self.id}] REST 클라이언트 초기화 중...")
        self._rest_client = PolymarketRestClient(
            private_key=self._private_key,
            chain_id=self._chain_id,
            signature_type=SignatureType.POLY_PROXY,
            funder=self._funder,
        )
        await self._rest_client.init()
        print(f"[{self.id}] REST 클라이언트 초기화 완료")

        # Set up API credentials for L2 auth (trading)
        if self._private_key:
            if self._api_creds:
                self._rest_client.set_api_creds(self._api_creds)
                print(f"[{self.id}] 기존 API credentials 설정됨")
            else:
                # Create or derive API credentials
                print(f"[{self.id}] API credentials 생성/파생 중...")
                try:
                    self._api_creds = await self._rest_client.create_or_derive_api_creds()
                    print(f"[{self.id}] API credentials 획득 완료 (L2 trading 활성화)")
                except Exception as e:
                    print(f"[{self.id}] API credentials 획득 실패 (trading 비활성화): {e}")

            # Initialize order signer (always use POLY_PROXY for Polymarket)
            self._order_signer = get_order_signer(
                private_key=self._private_key,
                chain_id=self._chain_id,
                signature_type=SignatureType.POLY_PROXY,
                funder=self._funder,
            )
            print(f"[{self.id}] Order signer 초기화 완료")

            # Initialize Builder client for gasless split/merge
            if self._builder_api_key and self._builder_secret and self._builder_passphrase:
                self._builder_client = BuilderRelayerClient(
                    private_key=self._private_key,
                    chain_id=self._chain_id,
                    builder_api_key=self._builder_api_key,
                    builder_secret=self._builder_secret,
                    builder_passphrase=self._builder_passphrase,
                    wallet_type="proxy",
                    proxy_wallet=self._proxy_wallet,
                )
                print(f"[{self.id}] Builder Relayer 클라이언트 초기화 완료 (가스 무료 split/merge)")
            else:
                print(f"[{self.id}] Split/Merge를 사용하려면 Builder 자격증명이 필요합니다.")
                print(f"[{self.id}] polymarket.com/settings?tab=builder 에서 API 키를 생성하세요.")

    async def _close_rest_client(self) -> None:
        """Close REST client."""
        if self._rest_client is not None:
            print(f"[{self.id}] REST 클라이언트 종료 중...")
            await self._rest_client.close()
            self._rest_client = None
            print(f"[{self.id}] REST 클라이언트 종료 완료")

    async def _init_websocket(self) -> None:
        """Initialize WebSocket connection."""
        print(f"[{self.id}] WebSocket 연결 중... ({self.WS_MARKET_URL})")
        self._ws_client = PolymarketWebSocketClient(url=self.WS_MARKET_URL)

        # Register callbacks
        @self._ws_client.on_orderbook
        async def handle_orderbook(asset_id: str, data: dict[str, Any]) -> None:
            await self._handle_orderbook_update(asset_id, data)

        await self._ws_client.connect()
        print(f"[{self.id}] WebSocket 연결 완료")

    async def _close_websocket(self) -> None:
        """Close WebSocket connection."""
        if self._ws_client is not None:
            await self._ws_client.disconnect()
            self._ws_client = None
        else:
            print(f"[{self.id}] WebSocket 클라이언트 없음 (이미 종료되었거나 비활성화됨)")

    # === Market Data Implementation ===

    async def _fetch_markets(self) -> list[Market]:
        """
        Fetch markets from Polymarket via Events endpoint.

        Uses Gamma API /events endpoint which is more efficient:
        - Each event contains multiple related markets
        - Fewer API calls needed
        - Better organized data
        - Parallel fetching for faster loading

        Note: Polymarket has 20,000+ markets. Use max_markets config to limit.
        """
        if self._rest_client is None:
            raise RuntimeError("REST client not initialized")

        max_markets = self.config.get("max_markets", 500)
        use_events = self.config.get("use_events", True)  # 기본값: Events 사용
        concurrent_requests = self.config.get("concurrent_requests", 5)  # 동시 요청 수

        print(f"[{self.id}] 최대 {max_markets}개 마켓 로드 중...")

        if use_events:
            return await self._load_markets_via_events(max_markets, concurrent_requests)
        else:
            return await self._load_markets_via_markets(max_markets, concurrent_requests)

    async def _load_markets_via_events(
        self, max_markets: int, concurrent_requests: int = 5
    ) -> list[Market]:
        """Load markets via Events endpoint with parallel fetching."""
        print(f"[{self.id}] Events 엔드포인트 사용 (병렬 로딩, {concurrent_requests}개 동시 요청)")

        events_limit = 50  # Events per request
        all_markets: list[Market] = []
        semaphore = asyncio.Semaphore(concurrent_requests)

        async def fetch_events_page(offset: int) -> list[dict[str, Any]]:
            """Fetch a single page of events."""
            async with semaphore:
                try:
                    return await self._rest_client.get_events(
                        limit=events_limit,
                        offset=offset,
                        active=True,
                        closed=False,
                    ) or []
                except Exception as e:
                    print(f"[{self.id}] Events fetch failed at offset {offset}: {e}")
                    return []

        # Estimate how many pages we need (conservative: assume ~3 markets per event)
        estimated_events_needed = max_markets // 3 + events_limit
        estimated_pages = (estimated_events_needed // events_limit) + 1

        # Fetch first page to check if there's data
        first_events = await fetch_events_page(0)
        if not first_events:
            print(f"[{self.id}] No events found")
            return []

        # Process first page
        self._process_events_batch(first_events, all_markets, max_markets)
        print(f"[{self.id}] {len(all_markets)}개 마켓 로드됨 (첫 페이지)...")

        if len(all_markets) >= max_markets or len(first_events) < events_limit:
            print(f"[{self.id}] 총 {len(all_markets)}개 마켓 로드 완료")
            return all_markets[:max_markets]

        # Fetch remaining pages in parallel
        offsets = list(range(events_limit, estimated_pages * events_limit, events_limit))
        tasks = [fetch_events_page(offset) for offset in offsets]
        results = await asyncio.gather(*tasks)

        for events in results:
            if not events:
                continue
            self._process_events_batch(events, all_markets, max_markets)
            if len(all_markets) >= max_markets:
                break

        print(f"[{self.id}] 총 {len(all_markets)}개 마켓 로드 완료 (병렬)")
        return all_markets[:max_markets]

    async def _load_markets_via_markets(
        self, max_markets: int, concurrent_requests: int = 5
    ) -> list[Market]:
        """Load markets via Markets endpoint with parallel fetching."""
        print(f"[{self.id}] Markets 엔드포인트 사용 (병렬 로딩, {concurrent_requests}개 동시 요청)")

        markets_limit = 100
        all_markets: list[Market] = []
        semaphore = asyncio.Semaphore(concurrent_requests)

        async def fetch_markets_page(offset: int) -> list[dict[str, Any]]:
            """Fetch a single page of markets."""
            async with semaphore:
                try:
                    return await self._rest_client.get_markets_gamma(
                        limit=markets_limit,
                        offset=offset,
                        active=True,
                        closed=False,
                    ) or []
                except Exception as e:
                    print(f"[{self.id}] Markets fetch failed at offset {offset}: {e}")
                    return []

        # Estimate pages needed
        estimated_pages = (max_markets // markets_limit) + 2

        # Fetch first page to check if there's data
        first_markets = await fetch_markets_page(0)
        if not first_markets:
            print(f"[{self.id}] No markets found")
            return []

        # Process first page
        for raw in first_markets:
            if len(all_markets) >= max_markets:
                break
            market = parse_market(raw)
            all_markets.append(market)
            tokens = parse_market_tokens(raw)
            if tokens:
                self._market_tokens[market.id] = CachedTokens(tokens=tokens)

        print(f"[{self.id}] {len(all_markets)}개 마켓 로드됨 (첫 페이지)...")

        if len(all_markets) >= max_markets or len(first_markets) < markets_limit:
            print(f"[{self.id}] 총 {len(all_markets)}개 마켓 로드 완료")
            return all_markets[:max_markets]

        # Fetch remaining pages in parallel
        offsets = list(range(markets_limit, estimated_pages * markets_limit, markets_limit))
        tasks = [fetch_markets_page(offset) for offset in offsets]
        results = await asyncio.gather(*tasks)

        for raw_markets in results:
            if not raw_markets:
                continue
            for raw in raw_markets:
                if len(all_markets) >= max_markets:
                    break
                market = parse_market(raw)
                all_markets.append(market)
                tokens = parse_market_tokens(raw)
                if tokens:
                    self._market_tokens[market.id] = CachedTokens(tokens=tokens)
            if len(all_markets) >= max_markets:
                break

        print(f"[{self.id}] 총 {len(all_markets)}개 마켓 로드 완료 (병렬)")
        return all_markets[:max_markets]

    def _process_events_batch(
        self,
        events: list[dict[str, Any]],
        all_markets: list[Market],
        max_markets: int,
    ) -> None:
        """Process a batch of events and extract markets."""
        import json as json_module

        for event in events:
            if len(all_markets) >= max_markets:
                break

            # Extract markets from event
            event_markets = event.get("markets", [])

            # Handle markets as string (JSON) or list
            if isinstance(event_markets, str):
                try:
                    event_markets = json_module.loads(event_markets)
                except json_module.JSONDecodeError:
                    event_markets = []

            for raw in event_markets:
                if len(all_markets) >= max_markets:
                    break

                # Skip closed markets
                if raw.get("closed", False) or not raw.get("active", True):
                    continue

                market = parse_market(raw)
                all_markets.append(market)

                # Cache token IDs with TTL
                tokens = parse_market_tokens(raw)
                if tokens:
                    self._market_tokens[market.id] = CachedTokens(tokens=tokens)

    async def _fetch_orderbook_rest(self, market_id: str, outcome: OutcomeSide) -> OrderBook:
        """
        Fetch orderbook via REST API.

        Note: Polymarket orderbooks are per-token, not per-market.
        """
        if self._rest_client is None:
            raise RuntimeError("REST client not initialized")

        token_id = self._get_token_id(market_id, outcome)
        raw_orderbook = await self._rest_client.get_orderbook(token_id)
        return parse_orderbook(raw_orderbook, market_id)

    def _get_cached_tokens(self, market_id: str) -> dict[str, str]:
        """
        Get cached tokens for a market.

        Returns empty dict if not cached or expired.
        Expired entries are removed from cache.
        """
        cached = self._market_tokens.get(market_id)
        if cached is None:
            return {}
        # Handle legacy: raw dict storage (e.g., from test code)
        if isinstance(cached, dict):
            return cached
        if cached.is_expired():
            del self._market_tokens[market_id]
            return {}
        return cached.tokens

    async def _subscribe_orderbook(self, market_id: str) -> None:
        """Subscribe to orderbook updates via WebSocket."""
        if not self.ws_enabled:
            return

        # Subscribe to both YES and NO tokens
        tokens = self._get_cached_tokens(market_id)
        token_ids = list(tokens.values())

        if not token_ids:
            return

        # Lazy init WebSocket on first subscription
        if self._ws_client is None:
            await self._init_websocket()

        await self._ws_client.subscribe_orderbook(token_ids)
        print(f"[{self.id}] 오더북 WebSocket 구독: {market_id[:20]}... ({len(token_ids)}개 토큰)")

    async def _unsubscribe_orderbook(self, market_id: str) -> None:
        """Unsubscribe from orderbook updates."""
        if self._ws_client is None:
            return

        tokens = self._get_cached_tokens(market_id)
        token_ids = list(tokens.values())

        if token_ids:
            await self._ws_client.unsubscribe_orderbook(token_ids)

    async def _handle_orderbook_update(self, asset_id: str, data: dict[str, Any]) -> None:
        """Handle orderbook update from WebSocket."""
        # Find market ID and outcome from token ID
        market_id = None
        outcome = None
        for mid, cached in self._market_tokens.items():
            tokens = cached.tokens if not cached.is_expired() else {}
            for outcome_str, token_id in tokens.items():
                if token_id == asset_id:
                    market_id = mid
                    outcome = OutcomeSide.YES if outcome_str == "YES" else OutcomeSide.NO
                    break
            if market_id:
                break

        if market_id and outcome:
            orderbook = parse_orderbook(data, market_id)
            self._update_orderbook_cache(market_id, outcome, orderbook)

    # === Trading Implementation ===

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
        """Create order on Polymarket."""
        if self._rest_client is None:
            raise RuntimeError("REST client not initialized")
        if self._order_signer is None:
            raise AuthenticationError("Order signer not initialized (private_key required)", exchange=self.id)
        if not self._rest_client.has_l2_auth:
            raise AuthenticationError("L2 auth required for trading", exchange=self.id)

        # Get token ID
        token_id = self._get_token_id(market_id, outcome)

        # Convert order side
        poly_side = Side.BUY if side == OrderSide.BUY else Side.SELL

        # Handle market orders - find price that can fill entire order
        if order_type == OrderType.MARKET or price is None:
            orderbook = await self.get_orderbook(market_id, outcome)
            if side == OrderSide.BUY:
                # BUY: sweep through asks to find price that fills order
                price = self._calculate_market_buy_price(orderbook.asks, orderbook.bids, size)
            else:
                # SELL: sweep through bids to find price that fills order
                price = self._calculate_market_sell_price(orderbook.bids, orderbook.asks, size)
            order_type = OrderType.MARKET
            print(f"[{self.id}] Market order: price = {price} for {size} shares")

        # Validate price for limit orders
        if order_type != OrderType.MARKET and price is None:
            raise InvalidOrderError("Price required for limit orders", exchange=self.id)

        # Get market for tick size
        market = self.get_market(market_id)
        # Use str() to avoid float precision issues (JSON parses 0.01 as float)
        # CLOB API uses "minimum_tick_size", Gamma API might use different field names
        raw_tick = market.raw.get("minimum_tick_size") or market.raw.get("tick_size") or "0.01"
        tick_size = Decimal(str(raw_tick))
        neg_risk = market.raw.get("neg_risk", market.raw.get("negRisk", False))

        # Create order options
        options = CreateOrderOptions(
            tick_size=tick_size,
            neg_risk=neg_risk,
        )

        # Create order args
        order_args = OrderArgs(
            token_id=token_id,
            side=poly_side,
            size=size,
            price=price,
        )

        # Sign order
        signed_order = self._order_signer.create_and_sign_order(order_args, options)

        # Convert order fields to strings as required by API
        order_data = signed_order.order.copy()
        order_data["tokenId"] = str(order_data["tokenId"])
        order_data["makerAmount"] = str(order_data["makerAmount"])
        order_data["takerAmount"] = str(order_data["takerAmount"])
        order_data["expiration"] = str(order_data["expiration"])
        order_data["nonce"] = str(order_data["nonce"])
        order_data["feeRateBps"] = str(order_data["feeRateBps"])
        # API expects "BUY"/"SELL" string, not numeric 0/1
        order_data["side"] = "BUY" if order_data["side"] == 0 else "SELL"
        order_data["signature"] = signed_order.signature  # signature is part of order object

        # Convert to API format
        # Note: "owner" is the API key, not the wallet address
        order_payload: dict[str, Any] = {
            "order": order_data,
            "owner": self._rest_client._creds.api_key,
            "orderType": self._map_order_type(order_type),
        }

        # Add client order ID if provided
        if client_id:
            order_payload["clientOrderId"] = client_id

        # Post order
        response = await self._rest_client.post_order(order_payload)
        return parse_order(response)

    async def _cancel_order_impl(self, order_id: str) -> bool:
        """Cancel order on Polymarket."""
        if self._rest_client is None:
            raise RuntimeError("REST client not initialized")
        if not self._rest_client.has_l2_auth:
            raise AuthenticationError("L2 auth required for trading", exchange=self.id)

        try:
            await self._rest_client.cancel_order(order_id)
            return True
        except Exception as e:
            msg = f"[{self.id}] Failed to cancel order {order_id}: {e}"
            logger.error(msg)
            print(msg)
            return False

    # === Account Implementation ===

    async def _fetch_open_orders(self, market_id: str | None) -> list[Order]:
        """Fetch open orders from Polymarket."""
        if self._rest_client is None:
            raise RuntimeError("REST client not initialized")
        if not self._rest_client.has_l2_auth:
            raise AuthenticationError("L2 auth required", exchange=self.id)

        raw_orders = await self._rest_client.get_orders(
            market=market_id,
            state="LIVE",
        )
        return parse_orders(raw_orders)

    async def _fetch_position(self, market_id: str, side: OutcomeSide | None) -> Position | None:
        """Fetch position from Polymarket."""
        if self._rest_client is None:
            raise RuntimeError("REST client not initialized")

        # Use proxy_wallet for Magic/Proxy users, otherwise use signing address
        position_address = self._proxy_wallet or self._rest_client._address

        # Get all positions
        raw_positions = await self._rest_client.get_positions(address=position_address)

        # Filter by market (check both camelCase and snake_case field names)
        for raw in raw_positions:
            pos_market = raw.get("conditionId", raw.get("condition_id", raw.get("market", "")))
            if pos_market == market_id:
                position = parse_position(raw)

                # Filter by side if specified
                if side is None or position.outcome == side:
                    return position

        return None

    async def get_all_positions(self) -> list[Position]:
        """Get all positions."""
        if self._rest_client is None:
            raise RuntimeError("REST client not initialized")

        # Use proxy_wallet for Magic/Proxy users, otherwise use signing address
        position_address = self._proxy_wallet or self._rest_client._address
        raw_positions = await self._rest_client.get_positions(address=position_address)
        return parse_positions(raw_positions)

    async def _fetch_portfolio_summary(self) -> PortfolioSummary:
        """Fetch portfolio summary from Polymarket."""
        if self._rest_client is None:
            raise RuntimeError("REST client not initialized")

        # Get balance from CLOB API balance-allowance endpoint
        try:
            balance_data = await self._rest_client.get_balance()
            # Response: {"balance": "...", "allowance": "..."}
            # USDC has 6 decimals, so divide by 10^6
            raw_balance = Decimal(str(balance_data.get("balance", 0)))
            balance = raw_balance / Decimal("1000000")
        except Exception as e:
            print(f"[{self.id}] Balance 조회 실패, 0으로 설정: {e}")
            balance = Decimal("0")

        # Get positions
        positions = await self.get_all_positions()

        return parse_portfolio_summary(positions, balance)

    async def fetch_market(self, market_id: str) -> Market:
        """
        Fetch market by URL, conditionId, or database ID.

        Resolves various input formats and returns a Market object.
        Also caches the market for subsequent get_market() calls.

        Args:
            market_id: One of:
                - Polymarket URL: https://polymarket.com/event/.../market-slug
                - conditionId: 0x... (66 chars)
                - database ID: numeric string

        Returns:
            Market object

        Example:
            ```python
            # By URL
            market = await exchange.fetch_market("https://polymarket.com/event/.../...")

            # By conditionId
            market = await exchange.fetch_market("0x1234...")
            ```
        """
        if self._rest_client is None:
            raise RuntimeError("REST client not initialized")

        # Handle Polymarket URL
        if market_id.startswith("https://polymarket.com/"):
            market_id = await self._resolve_market_url(market_id)

        # Check cache first
        if market_id in self._markets:
            return self._markets[market_id]

        # conditionId (0x...) - use CLOB API
        if market_id.startswith("0x") and len(market_id) == 66:
            try:
                raw_market = await self._rest_client.get_market_clob(market_id)
                market = parse_market(raw_market)
                self._markets[market_id] = market
                # Cache token IDs
                tokens = parse_market_tokens(raw_market)
                if tokens:
                    self._market_tokens[market_id] = CachedTokens(tokens=tokens)
                return market
            except Exception as e:
                print(f"[{self.id}] CLOB API failed for {market_id[:20]}...: {e}")

        # Fallback: database ID via Gamma API
        raw_market = await self._rest_client.get_market_gamma(market_id)
        market = parse_market(raw_market)
        self._markets[market.id] = market
        return market

    async def _fetch_resolution(self, market_id: str) -> Resolution | None:
        """Fetch market resolution status."""
        if self._rest_client is None:
            raise RuntimeError("REST client not initialized")

        # Handle Polymarket URL
        if market_id.startswith("https://polymarket.com/"):
            market_id = await self._resolve_market_url(market_id)

        # Try cached market first
        market = self._markets.get(market_id)
        if market and market.raw:
            db_id = market.raw.get("id")
            if db_id:
                raw_market = await self._rest_client.get_market_gamma(str(db_id))
                return parse_resolution(raw_market)

        # conditionId (0x...) - use CLOB API
        if market_id.startswith("0x") and len(market_id) == 66:
            try:
                clob_market = await self._rest_client.get_market_clob(market_id)
                return parse_resolution(clob_market)
            except Exception as e:
                print(f"[{self.id}] CLOB API failed for {market_id[:20]}...: {e}")

        # Fallback: database ID
        raw_market = await self._rest_client.get_market_gamma(market_id)
        return parse_resolution(raw_market)

    async def _resolve_market_url(self, url: str) -> str:
        """
        Resolve Polymarket URL to conditionId.

        URL format: https://polymarket.com/event/event-slug/market-slug

        For event-only URLs, use get_event_markets() instead.

        Args:
            url: Polymarket market URL

        Returns:
            conditionId (0x...)

        Raises:
            ValueError: If URL is invalid, event-only, or market not found
        """
        import re

        # Try to extract market slug (event + market)
        # https://polymarket.com/event/bitcoin-above-on-january-12/bitcoin-above-92k-on-january-12
        market_match = re.search(r"polymarket\.com/event/([^/]+)/([^/?]+)", url)

        if market_match:
            # Full URL with market slug
            market_slug = market_match.group(2)
            print(f"[{self.id}] Resolving market slug: {market_slug}")

            # Search for market by slug
            results = await self._rest_client.search_markets(keyword=market_slug, limit=10)
            events = results.get("events", [])

            for event in events:
                markets = event.get("markets", [])
                for market in markets:
                    slug = market.get("slug", "")
                    if slug == market_slug:
                        condition_id = market.get("conditionId")
                        if condition_id:
                            print(f"[{self.id}] Found conditionId: {condition_id}")
                            # Cache the market
                            parsed = parse_market(market)
                            self._markets[condition_id] = parsed
                            # Cache token IDs with TTL
                            tokens = parse_market_tokens(market)
                            if tokens:
                                self._market_tokens[condition_id] = CachedTokens(tokens=tokens)
                            return condition_id

            raise ValueError(f"Market not found for slug: {market_slug}")

        # Check if event-only URL
        event_match = re.search(r"polymarket\.com/event/([^/?]+)/?$", url)
        if event_match:
            raise ValueError(
                f"Event-only URL detected. Use get_event_markets() to list markets in this event."
            )

        raise ValueError(f"Invalid Polymarket URL: {url}")

    async def get_event_markets(self, url_or_slug: str) -> dict[str, Any]:
        """
        Get all markets in an event.

        Args:
            url_or_slug: Event URL or slug
                - URL: https://polymarket.com/event/portugal-presidential-election
                - Slug: portugal-presidential-election

        Returns:
            Dict with event info and markets:
            {
                "event_title": "Portugal Presidential Election",
                "event_slug": "portugal-presidential-election",
                "markets": [
                    {
                        "conditionId": "0x...",
                        "slug": "andre-ventura-wins",
                        "question": "André Ventura wins?",
                        "outcomes": ["Yes", "No"],
                        "active": True,
                        "volume24hr": "12345.67",
                    },
                    ...
                ]
            }
        """
        import re

        # Extract slug from URL if needed
        url_match = re.search(r"polymarket\.com/event/([^/?]+)", url_or_slug)
        if url_match:
            event_slug = url_match.group(1)
        else:
            event_slug = url_or_slug

        print(f"[{self.id}] Fetching event: {event_slug}")

        # Fetch event by slug
        event = await self._rest_client.get_event_by_slug(event_slug)

        if not event:
            raise ValueError(f"Event not found: {event_slug}")

        event_title = event.get("title", event_slug)
        markets = event.get("markets", [])

        # Parse markets
        market_list = []
        for m in markets:
            market_list.append({
                "conditionId": m.get("conditionId"),
                "slug": m.get("slug"),
                "question": m.get("question", m.get("title", "")),
                "outcomes": m.get("outcomes", ["Yes", "No"]),
                "active": m.get("active", True),
                "volume24hr": m.get("volume24hr"),
                "raw": m,
            })

        return {
            "event_title": event_title,
            "event_slug": event_slug,
            "markets": market_list,
        }

    async def _resolve_market_id(self, market_id: str) -> str:
        """Resolve market_id to conditionId (handles URLs and slugs)."""
        if market_id.startswith("https://polymarket.com/"):
            return await self._resolve_market_url(market_id)
        return market_id

    async def _get_market_neg_risk(self, condition_id: str) -> bool:
        """
        Get neg_risk flag for a market.

        Checks cached market first, then fetches from CLOB API if needed.
        Most active Polymarket markets are neg_risk=True.

        Args:
            condition_id: Market condition ID (or URL)

        Returns:
            True if market is neg_risk, False otherwise
        """
        # Resolve URL if needed
        if condition_id.startswith("https://"):
            condition_id = await self._resolve_market_id(condition_id)

        # Check cached market first
        market = self._markets.get(condition_id)
        if market and market.raw:
            neg_risk = market.raw.get("neg_risk")
            if neg_risk is not None:
                return neg_risk

        # Fetch from CLOB API
        if self._rest_client:
            try:
                clob_market = await self._rest_client.get_market_clob(condition_id)
                neg_risk = clob_market.get("neg_risk", False)
                # Cache the market and tokens
                parsed = parse_market(clob_market)
                self._markets[condition_id] = parsed
                tokens = parse_market_tokens(clob_market)
                if tokens:
                    self._market_tokens[condition_id] = CachedTokens(tokens=tokens)
                print(f"[{self.id}] Market {condition_id[:16]}... neg_risk={neg_risk} (from CLOB API)")
                return neg_risk
            except Exception as e:
                print(f"[{self.id}] Warning: Could not fetch market info: {e}")

        # Default to False if unknown (older markets)
        print(f"[{self.id}] Warning: neg_risk unknown for {condition_id[:16]}..., defaulting to False")
        return False

    # === On-chain CTF Operations (Split/Merge/Redeem) ===

    async def split_position(
        self,
        condition_id: str,
        amount: Decimal,
    ) -> dict[str, Any]:
        """
        Split USDC into YES + NO tokens (on-chain CTF operation).

        Requires MATIC in the signing wallet for gas fees.

        Args:
            condition_id: Market condition ID
            amount: Amount in USDC (e.g., Decimal("10") for $10)

        Returns:
            Transaction result with tx_hash, status, gas_used

        Example:
            ```python
            result = await exchange.split_position(
                condition_id="0x...",  # or Polymarket URL
                amount=Decimal("10"),  # Split $10 USDC
            )
            print(f"TX: {result['tx_hash']}")
            ```
        """
        # Resolve URL to conditionId if needed
        condition_id = await self._resolve_market_id(condition_id)

        # Get neg_risk flag from market
        neg_risk = await self._get_market_neg_risk(condition_id)

        # Convert USDC to wei (6 decimals)
        amount_wei = int(amount * Decimal("1000000"))

        # Use BuilderRelayerClient (gasless)
        if self._builder_client is not None:
            response = self._builder_client.split_position(
                condition_id=condition_id,
                amount=amount_wei,
                neg_risk=neg_risk,
            )
            # Wait for transaction to reach terminal state (run in thread to avoid blocking)
            response = await asyncio.to_thread(
                response.wait, timeout=60, poll_interval=2.0
            )

            if response.is_success():
                status = "success"
            elif response.is_failed():
                status = "failed"
            else:
                status = "pending"  # Timeout without terminal state

            return {
                "tx_hash": response.transaction_hash or response.transaction_id,
                "status": status,
                "transaction_id": response.transaction_id,
                "state": response.status,
            }
        else:
            raise RuntimeError(
                "split_position requires Builder credentials. "
                "Set POLYMARKET_BUILDER_API_KEY, POLYMARKET_BUILDER_SECRET, POLYMARKET_BUILDER_PASSPHRASE "
                "in your .env file. Get credentials at polymarket.com/settings?tab=builder"
            )

    async def merge_positions(
        self,
        condition_id: str,
        amount: Decimal,
    ) -> dict[str, Any]:
        """
        Merge YES + NO tokens back into USDC (on-chain CTF operation).

        You need equal amounts of YES and NO tokens to merge.
        Requires MATIC in the signing wallet for gas fees.

        Args:
            condition_id: Market condition ID
            amount: Amount of token pairs to merge (in USDC equivalent)

        Returns:
            Transaction result with tx_hash, status, gas_used

        Example:
            ```python
            result = await exchange.merge_positions(
                condition_id="0x...",  # or Polymarket URL
                amount=Decimal("10"),  # Merge 10 YES + 10 NO -> $10 USDC
            )
            print(f"TX: {result['tx_hash']}")
            ```
        """
        # Resolve URL to conditionId if needed
        condition_id = await self._resolve_market_id(condition_id)

        # Get neg_risk flag from market
        neg_risk = await self._get_market_neg_risk(condition_id)

        # Convert to wei (6 decimals)
        amount_wei = int(amount * Decimal("1000000"))

        # Use BuilderRelayerClient (gasless)
        if self._builder_client is not None:
            response = self._builder_client.merge_positions(
                condition_id=condition_id,
                amount=amount_wei,
                neg_risk=neg_risk,
            )
            # Wait for transaction to reach terminal state (run in thread to avoid blocking)
            response = await asyncio.to_thread(
                response.wait, timeout=60, poll_interval=2.0
            )

            if response.is_success():
                status = "success"
            elif response.is_failed():
                status = "failed"
            else:
                status = "pending"  # Timeout without terminal state

            return {
                "tx_hash": response.transaction_hash or response.transaction_id,
                "status": status,
                "transaction_id": response.transaction_id,
                "state": response.status,
            }
        else:
            raise RuntimeError(
                "merge_positions requires Builder credentials. "
                "Set POLYMARKET_BUILDER_API_KEY, POLYMARKET_BUILDER_SECRET, POLYMARKET_BUILDER_PASSPHRASE "
                "in your .env file. Get credentials at polymarket.com/settings?tab=builder"
            )

    async def redeem_positions(
        self,
        condition_id: str,
    ) -> dict[str, Any]:
        """
        Redeem winning positions after market resolution (on-chain CTF operation).

        After a market is resolved, winning tokens can be redeemed for USDC.
        Only winning tokens will return collateral.

        Args:
            condition_id: Market condition ID

        Returns:
            Transaction result with tx_hash, status, transaction_id, state
        """
        # Use BuilderRelayerClient (gasless)
        if self._builder_client is not None:
            response = self._builder_client.redeem_positions(
                condition_id=condition_id,
            )

            # Wait for confirmation
            print(f"[{self.id}] Redeem submitted, waiting for confirmation...")
            response.wait(timeout=60)

            status = "success" if response.is_success() else "pending" if response.is_pending() else "failed"
            return {
                "tx_hash": response.transaction_hash or response.transaction_id,
                "status": status,
                "transaction_id": response.transaction_id,
                "state": response.status,
            }
        else:
            raise RuntimeError(
                "redeem_positions requires Builder credentials. "
                "Set POLYMARKET_BUILDER_API_KEY, POLYMARKET_BUILDER_SECRET, POLYMARKET_BUILDER_PASSPHRASE "
                "in your .env file. Get credentials at polymarket.com/settings?tab=builder"
            )

    # === Fee Implementation ===

    def _get_fee_structure(self) -> FeeStructure:
        """Get Polymarket fee structure."""
        return get_fee_structure()

    # === Helper Methods ===

    def _get_token_id(self, market_id: str, outcome: OutcomeSide) -> str:
        """Get token ID for a market outcome."""
        tokens = self._get_cached_tokens(market_id)
        outcome_key = "yes" if outcome == OutcomeSide.YES else "no"

        token_id = tokens.get(outcome_key)
        if not token_id:
            raise ValueError(f"Token ID not found for {market_id} {outcome_key}. Try reloading markets.")

        return token_id

    def _calculate_market_buy_price(
        self,
        asks: list,
        bids: list,
        size: Decimal,
    ) -> Decimal:
        """
        Calculate the price needed to fill a market BUY order.

        Walks through asks from best (lowest) to worst (highest) price,
        accumulating size until we can fill the order.

        If no asks available, uses best bid + 0.01 or default 0.99.
        """
        if asks:
            accumulated_size = Decimal("0")
            worst_price = None

            # asks are sorted ascending (best/lowest first)
            for level in asks:
                accumulated_size += level.size
                worst_price = level.price
                if accumulated_size >= size:
                    return worst_price

            # Not enough liquidity - return worst ask price
            return worst_price

        # No asks - place competitive order based on best bid or default
        if bids:
            # Place just above best bid to be first in queue
            return min(bids[0].price + Decimal("0.01"), Decimal("0.99"))

        # Completely empty orderbook - use high price
        return Decimal("0.99")

    def _calculate_market_sell_price(
        self,
        bids: list,
        asks: list,
        size: Decimal,
    ) -> Decimal:
        """
        Calculate the price needed to fill a market SELL order.

        Walks through bids from best (highest) to worst (lowest) price,
        accumulating size until we can fill the order.

        If no bids available, uses best ask - 0.01 or default 0.01.
        """
        if bids:
            accumulated_size = Decimal("0")
            worst_price = None

            # bids are sorted descending (best/highest first)
            for level in bids:
                accumulated_size += level.size
                worst_price = level.price
                if accumulated_size >= size:
                    return worst_price

            # Not enough liquidity - return worst bid price
            return worst_price

        # No bids - place competitive order based on best ask or default
        if asks:
            # Place just below best ask to be first in queue
            return max(asks[0].price - Decimal("0.01"), Decimal("0.01"))

        # Completely empty orderbook - use low price
        return Decimal("0.01")

    def _map_order_type(self, order_type: OrderType) -> str:
        """Map OrderType to Polymarket order type string."""
        mapping = {
            OrderType.MARKET: "GTC",  # Market orders use GTC - fills what's available, rest stays as limit order
            OrderType.LIMIT: "GTC",  # Good Till Cancelled
            OrderType.LIMIT_IOC: "IOC",  # Immediate or Cancel
            OrderType.LIMIT_FOK: "FOK",  # Fill or Kill
            OrderType.LIMIT_GTD: "GTD",  # Good Till Date
        }
        return mapping.get(order_type, "GTC")


    async def search_markets(
        self, keyword: str, limit: int = 50, tag: str | None = None
    ) -> list[Market]:
        """
        Search markets by keyword.

        Args:
            keyword: Search keyword
            limit: Max results
            tag: Optional tag filter (slug, e.g., "crypto", "politics")

        Returns:
            List of matching markets

        Example:
            markets = await exchange.search_markets("bitcoin")
            markets = await exchange.search_markets("price", tag="crypto")
        """
        if self._rest_client is None:
            raise RuntimeError("REST client not initialized")

        response = await self._rest_client.search_markets(keyword=keyword, limit=limit, tag=tag)

        # /public-search returns {events: [...], tags: [...], profiles: [...]}
        events = response.get("events", []) or []

        markets = []
        for event in events:
            # Event contains nested markets array
            nested_markets = event.get("markets", [])

            if nested_markets:
                # Parse each market in the event
                for raw_market in nested_markets:
                    market = parse_market(raw_market)
                    markets.append(market)

                    # Add to _markets cache for orderbook/price lookups
                    self._markets[market.id] = market

                    # Cache token IDs with TTL
                    tokens = parse_market_tokens(raw_market)
                    if tokens:
                        self._market_tokens[market.id] = CachedTokens(tokens=tokens)
            else:
                # Fallback: event itself as a market (simple yes/no)
                market = parse_market(event)
                markets.append(market)

                # Add to _markets cache
                self._markets[market.id] = market

                tokens = parse_market_tokens(event)
                if tokens:
                    self._market_tokens[market.id] = CachedTokens(tokens=tokens)

        return markets

    async def get_categories(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Get all available categories (main categories like Crypto, Sports, Politics).

        Args:
            limit: Max categories to return

        Returns:
            List of categories with 'label', 'slug' fields

        Example:
            categories = await exchange.get_categories()
            for cat in categories:
                print(f"{cat['label']}: {cat['slug']}")
        """
        if self._rest_client is None:
            raise RuntimeError("REST client not initialized")

        return await self._rest_client.get_categories(limit=limit)
