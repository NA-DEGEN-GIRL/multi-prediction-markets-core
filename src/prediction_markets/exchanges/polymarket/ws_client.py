"""
Polymarket WebSocket client implementation.

Handles real-time data streaming:
- Orderbook updates (book channel)
- Trade updates (trades channel)
- User events (user channel)

WebSocket endpoint: wss://ws-subscriptions-clob.polymarket.com/ws/
"""

import asyncio
import json
import logging
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import websockets
from websockets.client import WebSocketClientProtocol

logger = logging.getLogger(__name__)


class Channel(str, Enum):
    """WebSocket subscription channels."""

    MARKET = "market"  # Market-level updates (price changes)
    BOOK = "book"  # Orderbook updates
    TRADES = "trades"  # Trade executions
    USER = "user"  # User-specific events (orders, positions)
    TICKER = "ticker"  # Price ticker


class MessageType(str, Enum):
    """WebSocket message types."""

    SUBSCRIBE = "subscribe"
    UNSUBSCRIBE = "unsubscribe"
    PING = "ping"
    PONG = "pong"


@dataclass
class Subscription:
    """Active subscription info."""

    channel: Channel
    assets: list[str]  # Token IDs
    subscribed_at: datetime = field(default_factory=datetime.now)


class PolymarketWebSocketClient:
    """
    Polymarket WebSocket client for real-time data.

    Handles:
    - Automatic reconnection with exponential backoff
    - Subscription management
    - Message routing to callbacks
    - Heartbeat/ping-pong

    Example:
        ```python
        client = PolymarketWebSocketClient()

        @client.on_orderbook
        async def handle_orderbook(data):
            print(f"Orderbook update: {data}")

        await client.connect()
        await client.subscribe_orderbook(["token_id_1", "token_id_2"])

        # Keep running
        await client.run_forever()
        ```
    """

    WS_MARKET_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/market"
    WS_USER_URL = "wss://ws-subscriptions-clob.polymarket.com/ws/user"

    def __init__(
        self,
        url: str | None = None,
        reconnect_attempts: int = 5,
        reconnect_delay: float = 1.0,
        reconnect_max_delay: float = 60.0,
        ping_interval: float = 30.0,
    ) -> None:
        """
        Initialize WebSocket client.

        Args:
            url: WebSocket URL (uses default if not specified)
            reconnect_attempts: Max reconnection attempts
            reconnect_delay: Initial reconnect delay (seconds)
            reconnect_max_delay: Max reconnect delay (seconds)
            ping_interval: Interval between ping messages (seconds)
        """
        self._url = url or self.WS_MARKET_URL
        self._reconnect_attempts = reconnect_attempts
        self._reconnect_delay = reconnect_delay
        self._reconnect_max_delay = reconnect_max_delay
        self._ping_interval = ping_interval

        self._ws: WebSocketClientProtocol | None = None
        self._connected = False
        self._should_reconnect = True
        self._reconnect_count = 0

        # Subscriptions
        self._subscriptions: dict[str, Subscription] = {}

        # Callbacks
        self._orderbook_callbacks: list[Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]] = []
        self._trade_callbacks: list[Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]] = []
        self._user_callbacks: list[Callable[[dict[str, Any]], Coroutine[Any, Any, None]]] = []
        self._ticker_callbacks: list[Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]] = []
        self._raw_callbacks: list[Callable[[dict[str, Any]], Coroutine[Any, Any, None]]] = []

        # Tasks
        self._receive_task: asyncio.Task[None] | None = None
        self._ping_task: asyncio.Task[None] | None = None

        # State
        self._last_message_time: datetime | None = None
        self._orderbooks: dict[str, dict[str, Any]] = {}  # Cached orderbooks

    @property
    def is_connected(self) -> bool:
        """Check if connected."""
        return self._connected and self._ws is not None

    @property
    def last_message_time(self) -> datetime | None:
        """Get timestamp of last received message."""
        return self._last_message_time

    # === Connection Management ===

    async def connect(self) -> None:
        """
        Establish WebSocket connection.

        Raises:
            ConnectionError: If connection fails
        """
        if self._connected:
            return

        self._should_reconnect = True

        try:
            self._ws = await websockets.connect(
                self._url,
                ping_interval=None,  # We handle ping manually
                ping_timeout=None,
            )
            self._connected = True
            self._reconnect_count = 0
            self._last_message_time = datetime.now()

            print(f"[polymarket] WebSocket 연결됨: {self._url}")

            # Start background tasks
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._ping_task = asyncio.create_task(self._ping_loop())

            # Resubscribe if we have existing subscriptions
            await self._resubscribe_all()

        except Exception as e:
            print(f"[polymarket] WebSocket 연결 실패: {e}")
            raise ConnectionError(f"WebSocket connection failed: {e}") from e

    async def disconnect(self) -> None:
        """Disconnect WebSocket."""
        print("[polymarket] WebSocket 연결 해제 중...")
        self._should_reconnect = False
        self._connected = False

        # Cancel tasks
        for task in [self._receive_task, self._ping_task]:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close connection
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

        print("[polymarket] WebSocket 연결 해제 완료")

    async def _reconnect(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        if not self._should_reconnect:
            return

        self._connected = False

        while self._reconnect_count < self._reconnect_attempts:
            delay = min(
                self._reconnect_delay * (2 ** self._reconnect_count),
                self._reconnect_max_delay,
            )
            self._reconnect_count += 1

            logger.info(
                f"[polymarket] Reconnecting in {delay:.1f}s "
                f"(attempt {self._reconnect_count}/{self._reconnect_attempts})"
            )

            await asyncio.sleep(delay)

            try:
                await self.connect()
                return
            except ConnectionError:
                continue

        logger.error("[polymarket] All reconnection attempts failed")

    # === Message Handling ===

    async def _receive_loop(self) -> None:
        """Receive and process messages."""
        if self._ws is None:
            return

        try:
            async for raw_message in self._ws:
                self._last_message_time = datetime.now()

                try:
                    if isinstance(raw_message, bytes):
                        raw_message = raw_message.decode("utf-8")

                    # Skip empty messages
                    if not raw_message or not raw_message.strip():
                        continue

                    # Handle plain text messages (PONG, INVALID OPERATION, etc.)
                    if raw_message == "PONG":
                        continue  # Ping response, ignore
                    if raw_message.startswith("INVALID"):
                        # Server warning - no subscription yet, this is expected
                        continue

                    message = json.loads(raw_message)
                    await self._handle_message(message)

                except json.JSONDecodeError as e:
                    # Only warn for unexpected non-JSON messages
                    if raw_message and raw_message.strip() and not raw_message.startswith("INVALID"):
                        print(f"[polymarket] WebSocket 비-JSON 메시지: {raw_message[:100]}")

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"[polymarket] Connection closed: {e}")
            self._connected = False
            await self._reconnect()

    async def _handle_message(self, message: dict[str, Any]) -> None:
        """Route message to appropriate handler."""
        # Call raw callbacks first
        for callback in self._raw_callbacks:
            try:
                await callback(message)
            except Exception as e:
                logger.error(f"[polymarket] Raw callback error: {e}")

        # Skip non-dict messages (e.g. batch arrays)
        if not isinstance(message, dict):
            return

        # Handle pong
        if message.get("type") == "pong":
            return

        # Route by channel
        channel = message.get("channel")
        asset_id = message.get("asset_id") or message.get("market")

        if channel == Channel.BOOK.value:
            await self._handle_orderbook(asset_id, message)
        elif channel == Channel.TRADES.value:
            await self._handle_trade(asset_id, message)
        elif channel == Channel.USER.value:
            await self._handle_user(message)
        elif channel == Channel.TICKER.value:
            await self._handle_ticker(asset_id, message)

    async def _handle_orderbook(self, asset_id: str | None, message: dict[str, Any]) -> None:
        """Handle orderbook update."""
        if not asset_id:
            return

        # Update cached orderbook
        self._orderbooks[asset_id] = message

        for callback in self._orderbook_callbacks:
            try:
                await callback(asset_id, message)
            except Exception as e:
                logger.error(f"[polymarket] Orderbook callback error: {e}")

    async def _handle_trade(self, asset_id: str | None, message: dict[str, Any]) -> None:
        """Handle trade update."""
        if not asset_id:
            return

        for callback in self._trade_callbacks:
            try:
                await callback(asset_id, message)
            except Exception as e:
                logger.error(f"[polymarket] Trade callback error: {e}")

    async def _handle_user(self, message: dict[str, Any]) -> None:
        """Handle user event."""
        for callback in self._user_callbacks:
            try:
                await callback(message)
            except Exception as e:
                logger.error(f"[polymarket] User callback error: {e}")

    async def _handle_ticker(self, asset_id: str | None, message: dict[str, Any]) -> None:
        """Handle ticker update."""
        if not asset_id:
            return

        for callback in self._ticker_callbacks:
            try:
                await callback(asset_id, message)
            except Exception as e:
                logger.error(f"[polymarket] Ticker callback error: {e}")

    async def _ping_loop(self) -> None:
        """Send periodic ping messages (every 10 seconds as per Polymarket docs)."""
        while self._connected:
            await asyncio.sleep(10)  # Polymarket requires ping every 10 seconds

            if self._ws is not None and self._connected:
                try:
                    await self._ws.send("PING")  # Polymarket expects plain "PING" string
                except Exception as e:
                    print(f"[polymarket] Ping 실패: {e}")

    # === Subscription Management ===

    async def subscribe(
        self,
        channel: Channel,
        assets: list[str],
    ) -> None:
        """
        Subscribe to a channel.

        Args:
            channel: Channel to subscribe to
            assets: List of asset/token IDs
        """
        if not self._connected or self._ws is None:
            raise ConnectionError("WebSocket not connected")

        # Polymarket expects: {"assets_ids": [...], "type": "market"}
        message = {
            "assets_ids": assets,
            "type": "market",
        }

        await self._ws.send(json.dumps(message))

        # Track subscription
        key = f"{channel.value}:{','.join(sorted(assets))}"
        self._subscriptions[key] = Subscription(channel=channel, assets=assets)

        print(f"[polymarket] WebSocket 구독: {channel.value} ({len(assets)}개 자산)")

    async def unsubscribe(
        self,
        channel: Channel,
        assets: list[str],
    ) -> None:
        """
        Unsubscribe from a channel.

        Args:
            channel: Channel to unsubscribe from
            assets: List of asset/token IDs
        """
        if not self._connected or self._ws is None:
            return

        message = {
            "type": MessageType.UNSUBSCRIBE.value,
            "channel": channel.value,
            "assets_ids": assets,
        }

        await self._ws.send(json.dumps(message))

        # Remove subscription tracking
        key = f"{channel.value}:{','.join(sorted(assets))}"
        self._subscriptions.pop(key, None)

        logger.info(f"[polymarket] Unsubscribed from {channel.value}")

    async def _resubscribe_all(self) -> None:
        """Resubscribe to all channels after reconnection."""
        for sub in list(self._subscriptions.values()):
            try:
                await self.subscribe(sub.channel, sub.assets)
            except Exception as e:
                logger.error(f"[polymarket] Resubscribe failed: {e}")

    # === Convenience Methods ===

    async def subscribe_orderbook(self, token_ids: list[str]) -> None:
        """Subscribe to orderbook updates."""
        await self.subscribe(Channel.BOOK, token_ids)

    async def unsubscribe_orderbook(self, token_ids: list[str]) -> None:
        """Unsubscribe from orderbook updates."""
        await self.unsubscribe(Channel.BOOK, token_ids)

    async def subscribe_trades(self, token_ids: list[str]) -> None:
        """Subscribe to trade updates."""
        await self.subscribe(Channel.TRADES, token_ids)

    async def unsubscribe_trades(self, token_ids: list[str]) -> None:
        """Unsubscribe from trade updates."""
        await self.unsubscribe(Channel.TRADES, token_ids)

    async def subscribe_ticker(self, token_ids: list[str]) -> None:
        """Subscribe to ticker updates."""
        await self.subscribe(Channel.TICKER, token_ids)

    async def subscribe_user(self, address: str) -> None:
        """Subscribe to user events."""
        await self.subscribe(Channel.USER, [address])

    def get_cached_orderbook(self, token_id: str) -> dict[str, Any] | None:
        """Get cached orderbook for a token."""
        return self._orderbooks.get(token_id)

    # === Callback Registration ===

    def on_orderbook(
        self,
        callback: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]:
        """
        Register orderbook callback (can be used as decorator).

        Args:
            callback: Async function(asset_id, data)
        """
        self._orderbook_callbacks.append(callback)
        return callback

    def on_trade(
        self,
        callback: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]:
        """Register trade callback."""
        self._trade_callbacks.append(callback)
        return callback

    def on_user(
        self,
        callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> Callable[[dict[str, Any]], Coroutine[Any, Any, None]]:
        """Register user event callback."""
        self._user_callbacks.append(callback)
        return callback

    def on_ticker(
        self,
        callback: Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> Callable[[str, dict[str, Any]], Coroutine[Any, Any, None]]:
        """Register ticker callback."""
        self._ticker_callbacks.append(callback)
        return callback

    def on_raw(
        self,
        callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]],
    ) -> Callable[[dict[str, Any]], Coroutine[Any, Any, None]]:
        """Register raw message callback."""
        self._raw_callbacks.append(callback)
        return callback

    # === Run Forever ===

    async def run_forever(self) -> None:
        """Run client until disconnected."""
        if not self._connected:
            await self.connect()

        while self._connected and self._receive_task is not None:
            await asyncio.sleep(1)
