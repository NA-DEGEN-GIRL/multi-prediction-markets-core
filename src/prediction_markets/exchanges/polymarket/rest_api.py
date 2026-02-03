"""
Polymarket REST API client implementation.

Handles communication with multiple Polymarket APIs:
- CLOB API: Trading, orderbooks, orders
- Gamma API: Market metadata, resolution status
- Data API: Positions, portfolio

API Documentation: https://docs.polymarket.com/
"""

import base64
import hashlib
import hmac
import json
import time
from dataclasses import dataclass
from typing import Any

import aiohttp
from eth_account import Account

from prediction_markets.common.exceptions import (
    AuthenticationError,
    ExchangeError,
    InsufficientFundsError,
    InvalidOrderError,
    MarketNotFoundError,
    RateLimitError,
)


@dataclass
class ApiCreds:
    """API credentials for L2 authentication."""

    api_key: str
    api_secret: str
    api_passphrase: str


@dataclass
class L1Headers:
    """L1 authentication headers."""

    POLY_ADDRESS: str
    POLY_SIGNATURE: str
    POLY_TIMESTAMP: str
    POLY_NONCE: str


@dataclass
class L2Headers:
    """L2 authentication headers."""

    POLY_ADDRESS: str
    POLY_SIGNATURE: str
    POLY_TIMESTAMP: str
    POLY_NONCE: str
    POLY_API_KEY: str
    POLY_PASSPHRASE: str
    POLY_SECRET: str


class PolymarketRestClient:
    """
    Polymarket REST API client supporting all three APIs.

    Supports three authentication levels:
    - L0: Public endpoints (no auth)
    - L1: Wallet signature (for API key creation)
    - L2: API credentials (for trading)

    Example:
        ```python
        client = PolymarketRestClient(private_key="0x...")
        await client.init()

        # L0: Public data
        markets = await client.get_markets()

        # L1: Create API credentials
        creds = await client.create_or_derive_api_creds()

        # L2: Trading
        await client.post_order(signed_order)

        await client.close()
        ```
    """

    # API Base URLs
    CLOB_URL = "https://clob.polymarket.com"
    GAMMA_URL = "https://gamma-api.polymarket.com"
    DATA_URL = "https://data-api.polymarket.com"

    # Chain IDs
    POLYGON_MAINNET = 137
    AMOY_TESTNET = 80002

    def __init__(
        self,
        private_key: str | None = None,
        chain_id: int = POLYGON_MAINNET,
        signature_type: int = 0,
        funder: str | None = None,
    ) -> None:
        """
        Initialize Polymarket REST client.

        Args:
            private_key: Wallet private key (hex string starting with 0x)
            chain_id: Chain ID (137 for Polygon mainnet)
            signature_type: 0=EOA, 1=Magic, 2=Proxy
            funder: Funder address for proxy wallets
        """
        self._private_key = private_key
        self._chain_id = chain_id
        self._signature_type = signature_type
        self._funder = funder

        self._session: aiohttp.ClientSession | None = None
        self._creds: ApiCreds | None = None

        # Derived from private key
        self._address: str | None = None
        if private_key:
            account = Account.from_key(private_key)
            self._address = account.address

    @property
    def address(self) -> str | None:
        """Get wallet address."""
        return self._address

    @property
    def has_l1_auth(self) -> bool:
        """Check if L1 auth is available."""
        return self._private_key is not None

    @property
    def has_l2_auth(self) -> bool:
        """Check if L2 auth is available."""
        return self._creds is not None

    # === Lifecycle ===

    async def init(self) -> None:
        """Initialize HTTP session."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=30.0)
            self._session = aiohttp.ClientSession(timeout=timeout)

    async def close(self) -> None:
        """Close HTTP session."""
        if self._session is not None:
            await self._session.close()
            self._session = None

    def set_api_creds(self, creds: ApiCreds) -> None:
        """Set API credentials for L2 auth."""
        self._creds = creds

    # === Authentication ===

    def _create_l1_headers(self, nonce: int | None = None) -> dict[str, str]:
        """
        Create L1 authentication headers using EIP-712 structured data signing.

        The signature proves wallet ownership for API key creation/derivation.
        """
        if not self._private_key or not self._address:
            raise AuthenticationError("Private key required for L1 auth", exchange="polymarket")

        timestamp = str(int(time.time()))
        nonce_val = nonce if nonce is not None else 0

        # EIP-712 structured data for L1 auth
        typed_data = {
            "types": {
                "EIP712Domain": [
                    {"name": "name", "type": "string"},
                    {"name": "version", "type": "string"},
                    {"name": "chainId", "type": "uint256"},
                ],
                "ClobAuth": [
                    {"name": "address", "type": "address"},
                    {"name": "timestamp", "type": "string"},
                    {"name": "nonce", "type": "uint256"},
                    {"name": "message", "type": "string"},
                ],
            },
            "primaryType": "ClobAuth",
            "domain": {
                "name": "ClobAuthDomain",
                "version": "1",
                "chainId": self._chain_id,
            },
            "message": {
                "address": self._address,
                "timestamp": timestamp,
                "nonce": nonce_val,
                "message": "This message attests that I control the given wallet",
            },
        }

        # Sign EIP-712 typed data
        account = Account.from_key(self._private_key)
        signed = account.sign_typed_data(full_message=typed_data)

        return {
            "POLY_ADDRESS": self._address,
            "POLY_SIGNATURE": "0x" + signed.signature.hex() if not signed.signature.hex().startswith("0x") else signed.signature.hex(),
            "POLY_TIMESTAMP": timestamp,
            "POLY_NONCE": str(nonce_val),
        }

    def _create_l2_headers(
        self,
        method: str,
        path: str,
        body: str = "",
    ) -> dict[str, str]:
        """Create L2 authentication headers using HMAC signature."""
        if not self._creds or not self._address:
            raise AuthenticationError("API credentials required for L2 auth", exchange="polymarket")

        timestamp = str(int(time.time()))

        # Build signature payload: timestamp + method + path + body
        message = f"{timestamp}{method}{path}"
        if body:
            # Replace single quotes with double quotes for consistency
            message += body.replace("'", '"')

        # HMAC-SHA256 signature with base64url encoding
        secret_bytes = base64.urlsafe_b64decode(self._creds.api_secret)
        signature = hmac.new(
            secret_bytes,
            message.encode("utf-8"),
            hashlib.sha256,
        ).digest()
        signature_b64 = base64.urlsafe_b64encode(signature).decode("utf-8")

        return {
            "POLY_ADDRESS": self._address,
            "POLY_SIGNATURE": signature_b64,
            "POLY_TIMESTAMP": timestamp,
            "POLY_API_KEY": self._creds.api_key,
            "POLY_PASSPHRASE": self._creds.api_passphrase,
        }

    # === HTTP Methods ===

    async def _request(
        self,
        method: str,
        url: str,
        params: dict[str, Any] | None = None,
        data: dict[str, Any] | None = None,
        auth_level: int = 0,
    ) -> Any:
        """
        Make HTTP request.

        Args:
            method: HTTP method
            url: Full URL
            params: Query parameters
            data: Request body
            auth_level: 0=none, 1=L1, 2=L2

        Returns:
            Parsed JSON response
        """
        if self._session is None:
            await self.init()

        headers: dict[str, str] = {"Content-Type": "application/json"}
        body_str = ""

        if data:
            body_str = json.dumps(data, separators=(",", ":"))

        # Add authentication headers
        if auth_level == 1:
            headers.update(self._create_l1_headers())
        elif auth_level == 2:
            # Extract path from URL
            from urllib.parse import urlparse
            parsed = urlparse(url)
            path = parsed.path
            if parsed.query:
                path += f"?{parsed.query}"
            headers.update(self._create_l2_headers(method, path, body_str))

        try:
            async with self._session.request(
                method,
                url,
                params=params,
                data=body_str if body_str else None,
                headers=headers,
            ) as response:
                response_data = await response.json() if response.content_type == "application/json" else await response.text()

                if response.status >= 400:
                    raise self._parse_error(response.status, response_data)

                return response_data

        except aiohttp.ClientError as e:
            raise ExchangeError(f"Network error: {e}", exchange="polymarket") from e

    def _parse_error(self, status: int, data: Any) -> Exception:
        """Parse error response into appropriate exception."""
        error_message = "Unknown error"

        if isinstance(data, dict):
            error_message = data.get("message", data.get("error", str(data)))
        elif isinstance(data, str):
            error_message = data

        if status == 401:
            return AuthenticationError(error_message, exchange="polymarket", raw=data)
        elif status == 403:
            return AuthenticationError(f"Forbidden: {error_message}", exchange="polymarket", raw=data)
        elif status == 404:
            return MarketNotFoundError(error_message, exchange="polymarket", raw=data)
        elif status == 429:
            return RateLimitError(error_message, exchange="polymarket", raw=data)
        elif status == 400:
            if "insufficient" in error_message.lower():
                return InsufficientFundsError(error_message, exchange="polymarket", raw=data)
            return InvalidOrderError(error_message, exchange="polymarket", raw=data)
        else:
            return ExchangeError(f"HTTP {status}: {error_message}", exchange="polymarket", raw=data)

    # === CLOB API Methods ===

    async def get_market_clob(self, condition_id: str) -> dict[str, Any]:
        """Get single market from CLOB API."""
        return await self._request("GET", f"{self.CLOB_URL}/markets/{condition_id}")

    async def get_orderbook(self, token_id: str) -> dict[str, Any]:
        """
        Get orderbook for a token.

        Args:
            token_id: Token ID (YES or NO token)

        Returns:
            Orderbook with bids and asks
        """
        return await self._request(
            "GET",
            f"{self.CLOB_URL}/book",
            params={"token_id": token_id},
        )

    # === CLOB API - Authentication (L1) ===

    async def create_api_key(self) -> ApiCreds:
        """
        Create new API key (L1 auth required).

        Returns:
            New API credentials
        """
        data = await self._request(
            "POST",
            f"{self.CLOB_URL}/auth/api-key",
            auth_level=1,
        )

        return ApiCreds(
            api_key=data["apiKey"],
            api_secret=data["secret"],
            api_passphrase=data["passphrase"],
        )

    async def derive_api_key(self) -> ApiCreds:
        """
        Derive existing API key (L1 auth required).

        Returns:
            Derived API credentials
        """
        data = await self._request(
            "GET",
            f"{self.CLOB_URL}/auth/derive-api-key",
            auth_level=1,
        )

        return ApiCreds(
            api_key=data["apiKey"],
            api_secret=data["secret"],
            api_passphrase=data["passphrase"],
        )

    async def create_or_derive_api_creds(self) -> ApiCreds:
        """
        Create or derive API credentials automatically.

        Tries to derive first, creates new if not found.

        Returns:
            API credentials
        """
        try:
            creds = await self.derive_api_key()
        except ExchangeError:
            creds = await self.create_api_key()

        self._creds = creds
        return creds

    # === CLOB API - Orders (L2) ===

    async def post_order(self, signed_order: dict[str, Any]) -> dict[str, Any]:
        """
        Post a signed order (L2 auth required).

        Args:
            signed_order: Order signed with OrderBuilder

        Returns:
            Order response
        """
        return await self._request(
            "POST",
            f"{self.CLOB_URL}/order",
            data=signed_order,
            auth_level=2,
        )

    async def cancel_order(self, order_id: str) -> dict[str, Any]:
        """Cancel single order (L2 auth required)."""
        return await self._request(
            "DELETE",
            f"{self.CLOB_URL}/order",
            data={"orderID": order_id},
            auth_level=2,
        )

    async def get_orders(
        self,
        market: str | None = None,
        asset_id: str | None = None,
        state: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Get orders (L2 auth required).

        Args:
            market: Filter by market/condition ID
            asset_id: Filter by asset/token ID
            state: Filter by state (LIVE, MATCHED, etc.)
        """
        params: dict[str, Any] = {}
        if market:
            params["market"] = market
        if asset_id:
            params["asset_id"] = asset_id
        if state:
            params["state"] = state

        response = await self._request(
            "GET",
            f"{self.CLOB_URL}/data/orders",
            params=params,
            auth_level=2,
        )

        # Handle various response formats
        if response is None:
            return []
        if isinstance(response, list):
            return response
        if isinstance(response, dict):
            # Response might be wrapped in a data field
            return response.get("data", response.get("orders", [response]))
        if isinstance(response, str):
            # Empty or error string
            return []
        return []

    # === Gamma API Methods ===

    async def get_markets_gamma(
        self,
        limit: int = 100,
        offset: int = 0,
        active: bool = True,
        closed: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Get markets from Gamma API with full metadata.

        Args:
            limit: Max results
            offset: Pagination offset
            active: Include active markets
            closed: Include closed markets
        """
        params = {
            "limit": limit,
            "offset": offset,
            "active": str(active).lower(),
            "closed": str(closed).lower(),
        }
        return await self._request("GET", f"{self.GAMMA_URL}/markets", params=params)

    async def get_market_gamma(self, condition_id: str) -> dict[str, Any]:
        """Get single market from Gamma API with full metadata."""
        return await self._request("GET", f"{self.GAMMA_URL}/markets/{condition_id}")

    async def get_events(
        self,
        limit: int = 100,
        offset: int = 0,
        active: bool = True,
        closed: bool = False,
    ) -> list[dict[str, Any]]:
        """
        Get events (groups of markets) from Gamma API.

        Each event contains multiple related markets.
        More efficient than fetching markets individually.

        Args:
            limit: Max events per request (default 100)
            offset: Pagination offset
            active: Include active events
            closed: Include closed events
        """
        params = {
            "limit": limit,
            "offset": offset,
            "active": str(active).lower(),
            "closed": str(closed).lower(),
        }
        return await self._request("GET", f"{self.GAMMA_URL}/events", params=params)

    async def filter_events(
        self,
        *,
        # Pagination & sorting
        limit: int = 100,
        offset: int = 0,
        order: str | None = None,
        ascending: bool = False,
        # Status filters
        active: bool | None = True,
        closed: bool | None = False,
        archived: bool | None = None,
        featured: bool | None = None,
        # Tag filters
        tag_id: int | None = None,
        tag_slug: str | None = None,
        exclude_tag_id: list[int] | None = None,
        related_tags: bool | None = None,
        # Value range filters
        liquidity_min: float | None = None,
        liquidity_max: float | None = None,
        volume_min: float | None = None,
        volume_max: float | None = None,
        # Date range filters (ISO format: "2026-01-01T00:00:00Z")
        start_date_min: str | None = None,
        start_date_max: str | None = None,
        end_date_min: str | None = None,
        end_date_max: str | None = None,
        # Other filters
        slug: list[str] | None = None,
        recurrence: str | None = None,
    ) -> list[dict[str, Any]]:
        """
        Filter events with advanced query parameters.

        Uses the Gamma API /events endpoint with comprehensive filtering options.

        Args:
            limit: Max events per request (default 100)
            offset: Pagination offset
            order: Comma-separated fields to order by (e.g., "volume", "liquidity")
            ascending: Sort order (default: descending)

            active: Filter active events (True/False/None for any)
            closed: Filter closed events
            archived: Filter archived events
            featured: Filter featured events

            tag_id: Filter by tag ID
            tag_slug: Filter by tag slug
            exclude_tag_id: Exclude specific tag IDs
            related_tags: Include related tags

            liquidity_min/max: Liquidity range filter
            volume_min/max: Volume range filter

            start_date_min/max: Start date range (ISO format)
            end_date_min/max: End date range (ISO format)

            slug: Filter by specific slugs
            recurrence: Filter by recurrence pattern

        Returns:
            List of event dicts from Gamma API

        Example:
            # High volume events
            events = await client.filter_events(
                active=True,
                volume_min=100000,
                order="volume",
                limit=20
            )

            # Events ending soon
            events = await client.filter_events(
                active=True,
                end_date_max="2026-02-10T00:00:00Z",
                order="endDate"
            )

            # Crypto events with high liquidity
            events = await client.filter_events(
                tag_slug="crypto",
                liquidity_min=50000,
                active=True
            )
        """
        params: dict[str, Any] = {
            "limit": limit,
            "offset": offset,
        }

        # Sorting
        if order:
            params["order"] = order
        if ascending:
            params["ascending"] = "true"

        # Status filters (only add if explicitly set)
        if active is not None:
            params["active"] = str(active).lower()
        if closed is not None:
            params["closed"] = str(closed).lower()
        if archived is not None:
            params["archived"] = str(archived).lower()
        if featured is not None:
            params["featured"] = str(featured).lower()

        # Tag filters
        if tag_id is not None:
            params["tag_id"] = tag_id
        if tag_slug:
            params["tag_slug"] = tag_slug
        if exclude_tag_id:
            params["exclude_tag_id"] = exclude_tag_id
        if related_tags is not None:
            params["related_tags"] = str(related_tags).lower()

        # Value range filters
        if liquidity_min is not None:
            params["liquidity_min"] = liquidity_min
        if liquidity_max is not None:
            params["liquidity_max"] = liquidity_max
        if volume_min is not None:
            params["volume_min"] = volume_min
        if volume_max is not None:
            params["volume_max"] = volume_max

        # Date range filters
        if start_date_min:
            params["start_date_min"] = start_date_min
        if start_date_max:
            params["start_date_max"] = start_date_max
        if end_date_min:
            params["end_date_min"] = end_date_min
        if end_date_max:
            params["end_date_max"] = end_date_max

        # Other filters
        if slug:
            params["slug"] = slug
        if recurrence:
            params["recurrence"] = recurrence

        return await self._request("GET", f"{self.GAMMA_URL}/events", params=params)

    async def get_event_by_slug(self, slug: str) -> dict[str, Any] | None:
        """
        Get event by slug from Gamma API.

        Args:
            slug: Event slug (e.g., "portugal-presidential-election")

        Returns:
            Event data with markets, or None if not found
        """
        # Gamma API supports /events?slug=xxx
        params = {"slug": slug}
        try:
            result = await self._request("GET", f"{self.GAMMA_URL}/events", params=params)
            if result and isinstance(result, list) and len(result) > 0:
                return result[0]
            return None
        except Exception:
            return None

    async def search_markets(
        self,
        keyword: str = "",
        limit: int = 20,
        page: int = 1,
        tag: str | None = None,
        keep_closed_markets: bool = False,
        events_status: str | None = None,
    ) -> dict[str, Any]:
        """
        Search markets using /public-search endpoint.

        Args:
            keyword: Search keyword (empty string to list all in a category)
            limit: Max results per type (limit_per_type)
            page: Page number for pagination (1-indexed)
            tag: Optional category/tag filter (slug from get_categories)
            keep_closed_markets: Include closed markets (default: False)
            events_status: Filter by event status (e.g., "active", "closed")

        Returns:
            Dict with 'events', 'tags', 'profiles', 'pagination' keys
        """
        # q is required, use space if empty to get category listings
        query = keyword if keyword.strip() else " "
        params: dict[str, Any] = {
            "q": query,
            "limit_per_type": limit,
            "page": page,
            "keep_closed_markets": 1 if keep_closed_markets else 0,
        }
        if tag:
            params["events_tag"] = tag
        if events_status:
            params["events_status"] = events_status
        return await self._request("GET", f"{self.GAMMA_URL}/public-search", params=params)

    async def get_categories(self, limit: int = 100) -> list[dict[str, Any]]:
        """
        Get all available categories (main categories like Crypto, Sports, Politics).

        Args:
            limit: Max categories to return
        """
        params = {"limit": limit}
        return await self._request("GET", f"{self.GAMMA_URL}/categories", params=params)

    # === Data API Methods ===

    async def get_positions(self, address: str | None = None) -> list[dict[str, Any]]:
        """
        Get positions from Data API.

        Args:
            address: Wallet address (uses connected wallet if not specified)
        """
        addr = address or self._address
        if not addr:
            raise AuthenticationError("Address required for positions", exchange="polymarket")

        return await self._request(
            "GET",
            f"{self.DATA_URL}/positions",
            params={"user": addr},
        )

    async def get_balance(self, asset_type: str = "COLLATERAL", token_id: str | None = None) -> dict[str, Any]:
        """
        Get balance and allowance from CLOB API.

        Args:
            asset_type: Asset type - "COLLATERAL" for USDC, "CONDITIONAL" for outcome tokens
            token_id: Required when asset_type is "CONDITIONAL"

        Returns:
            Dict with balance and allowance info
        """
        params: dict[str, Any] = {"asset_type": asset_type}

        # Add signature_type if using non-EOA wallet
        if self._signature_type:
            params["signature_type"] = self._signature_type

        # token_id required for CONDITIONAL assets
        if token_id:
            params["token_id"] = token_id
        elif asset_type == "CONDITIONAL":
            raise ValueError("token_id required for CONDITIONAL asset_type")

        return await self._request(
            "GET",
            f"{self.CLOB_URL}/balance-allowance",
            params=params,
            auth_level=2,
        )