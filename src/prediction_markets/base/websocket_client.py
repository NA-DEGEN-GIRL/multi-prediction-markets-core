"""
Base WebSocket client with automatic reconnection and subscription management.

Features:
- Automatic reconnection with exponential backoff
- Heartbeat/ping-pong handling
- Subscription management (subscribe/unsubscribe)
- Message queue for processing
- REST fallback trigger on persistent failures
"""

import asyncio
import logging
from abc import ABC, abstractmethod
from collections.abc import Callable, Coroutine
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any

import websockets
from websockets.client import WebSocketClientProtocol

from prediction_markets.common.exceptions import (
    WebSocketConnectionError,
    WebSocketDisconnectedError,
    WebSocketSubscriptionError,
)

logger = logging.getLogger(__name__)


class ConnectionState(Enum):
    """WebSocket connection state."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    RECONNECTING = "reconnecting"
    CLOSED = "closed"


@dataclass
class WebSocketConfig:
    """WebSocket client configuration."""

    url: str
    reconnect_attempts: int = 5
    reconnect_delay: float = 1.0  # Initial delay in seconds
    reconnect_delay_max: float = 60.0  # Maximum delay
    reconnect_multiplier: float = 2.0  # Exponential backoff multiplier
    heartbeat_interval: float = 30.0  # Seconds between heartbeats
    heartbeat_timeout: float = 10.0  # Timeout waiting for pong
    message_queue_size: int = 1000
    connect_timeout: float = 30.0


@dataclass
class Subscription:
    """Active subscription information."""

    channel: str
    params: dict[str, Any] = field(default_factory=dict)
    subscribed_at: datetime | None = None
    callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None


class BaseWebSocketClient(ABC):
    """
    Base WebSocket client with reconnection and subscription management.

    Subclasses must implement:
    - _build_subscribe_message(channel, params): Create subscription message
    - _build_unsubscribe_message(channel, params): Create unsubscribe message
    - _parse_message(raw_message): Parse incoming message
    - _is_heartbeat_response(message): Check if message is heartbeat response
    - _build_heartbeat_message(): Create heartbeat/ping message
    """

    def __init__(self, config: WebSocketConfig, exchange: str) -> None:
        self.config = config
        self.exchange = exchange

        self._ws: WebSocketClientProtocol | None = None
        self._state = ConnectionState.DISCONNECTED
        self._subscriptions: dict[str, Subscription] = {}
        self._message_queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(
            maxsize=config.message_queue_size
        )

        # Tasks
        self._receive_task: asyncio.Task[None] | None = None
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._process_task: asyncio.Task[None] | None = None

        # State tracking
        self._last_message_time: datetime | None = None
        self._reconnect_count = 0
        self._should_reconnect = True

        # Callbacks
        self._on_connect_callbacks: list[Callable[[], Coroutine[Any, Any, None]]] = []
        self._on_disconnect_callbacks: list[Callable[[Exception | None], Coroutine[Any, Any, None]]] = []
        self._on_message_callbacks: list[Callable[[dict[str, Any]], Coroutine[Any, Any, None]]] = []
        self._on_fallback_trigger: Callable[[], Coroutine[Any, Any, None]] | None = None

    @property
    def is_connected(self) -> bool:
        """Check if WebSocket is connected."""
        return self._state == ConnectionState.CONNECTED and self._ws is not None

    @property
    def state(self) -> ConnectionState:
        """Get current connection state."""
        return self._state

    @property
    def last_message_time(self) -> datetime | None:
        """Get timestamp of last received message."""
        return self._last_message_time

    # === Abstract Methods ===

    @abstractmethod
    def _build_subscribe_message(self, channel: str, params: dict[str, Any]) -> dict[str, Any]:
        """Build subscription message for the exchange."""
        pass

    @abstractmethod
    def _build_unsubscribe_message(self, channel: str, params: dict[str, Any]) -> dict[str, Any]:
        """Build unsubscribe message for the exchange."""
        pass

    @abstractmethod
    def _parse_message(self, raw_message: str | bytes) -> dict[str, Any]:
        """Parse raw WebSocket message into structured format."""
        pass

    @abstractmethod
    def _is_heartbeat_response(self, message: dict[str, Any]) -> bool:
        """Check if message is a heartbeat/pong response."""
        pass

    @abstractmethod
    def _build_heartbeat_message(self) -> dict[str, Any] | str | None:
        """Build heartbeat/ping message. Return None if exchange handles ping automatically."""
        pass

    @abstractmethod
    def _extract_channel_from_message(self, message: dict[str, Any]) -> str | None:
        """Extract channel/subscription identifier from incoming message."""
        pass

    # === Connection Management ===

    async def connect(self) -> None:
        """
        Establish WebSocket connection.

        Raises:
            WebSocketConnectionError: If connection fails after all retry attempts.
        """
        if self._state == ConnectionState.CONNECTED:
            return

        self._should_reconnect = True
        self._state = ConnectionState.CONNECTING

        try:
            self._ws = await asyncio.wait_for(
                websockets.connect(self.config.url),
                timeout=self.config.connect_timeout,
            )
            self._state = ConnectionState.CONNECTED
            self._reconnect_count = 0
            self._last_message_time = datetime.now()

            logger.info(f"[{self.exchange}] WebSocket connected to {self.config.url}")

            # Start background tasks
            self._receive_task = asyncio.create_task(self._receive_loop())
            self._heartbeat_task = asyncio.create_task(self._heartbeat_loop())
            self._process_task = asyncio.create_task(self._process_loop())

            # Notify callbacks
            for callback in self._on_connect_callbacks:
                await callback()

            # Resubscribe to all channels
            await self._resubscribe_all()

        except asyncio.TimeoutError as e:
            self._state = ConnectionState.DISCONNECTED
            raise WebSocketConnectionError(
                f"Connection timeout after {self.config.connect_timeout}s",
                exchange=self.exchange,
            ) from e
        except Exception as e:
            self._state = ConnectionState.DISCONNECTED
            raise WebSocketConnectionError(
                f"Failed to connect: {e}",
                exchange=self.exchange,
            ) from e

    async def disconnect(self) -> None:
        """Gracefully disconnect WebSocket."""
        self._should_reconnect = False
        self._state = ConnectionState.CLOSED

        # Cancel tasks
        for task in [self._receive_task, self._heartbeat_task, self._process_task]:
            if task is not None:
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass

        # Close WebSocket
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

        self._subscriptions.clear()
        logger.info(f"[{self.exchange}] WebSocket disconnected")

    async def _reconnect(self) -> None:
        """Attempt to reconnect with exponential backoff."""
        if not self._should_reconnect:
            return

        self._state = ConnectionState.RECONNECTING

        while self._reconnect_count < self.config.reconnect_attempts:
            delay = min(
                self.config.reconnect_delay * (self.config.reconnect_multiplier ** self._reconnect_count),
                self.config.reconnect_delay_max,
            )
            self._reconnect_count += 1

            logger.info(
                f"[{self.exchange}] Reconnecting in {delay:.1f}s "
                f"(attempt {self._reconnect_count}/{self.config.reconnect_attempts})"
            )

            await asyncio.sleep(delay)

            try:
                await self.connect()
                return
            except WebSocketConnectionError:
                continue

        # All attempts failed - trigger REST fallback
        logger.error(f"[{self.exchange}] All reconnection attempts failed, triggering REST fallback")
        self._state = ConnectionState.DISCONNECTED

        if self._on_fallback_trigger is not None:
            await self._on_fallback_trigger()

    # === Message Handling ===

    async def _receive_loop(self) -> None:
        """Receive messages from WebSocket."""
        if self._ws is None:
            return

        try:
            async for raw_message in self._ws:
                self._last_message_time = datetime.now()

                try:
                    message = self._parse_message(raw_message)

                    # Skip heartbeat responses
                    if self._is_heartbeat_response(message):
                        continue

                    # Route to subscription callback or general queue
                    channel = self._extract_channel_from_message(message)
                    if channel and channel in self._subscriptions:
                        sub = self._subscriptions[channel]
                        if sub.callback is not None:
                            await sub.callback(message)
                    else:
                        await self._message_queue.put(message)

                except Exception as e:
                    logger.warning(f"[{self.exchange}] Failed to parse message: {e}")

        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"[{self.exchange}] Connection closed: {e}")
            for callback in self._on_disconnect_callbacks:
                await callback(e)
            await self._reconnect()

    async def _process_loop(self) -> None:
        """Process messages from queue."""
        while True:
            message = await self._message_queue.get()
            for callback in self._on_message_callbacks:
                try:
                    await callback(message)
                except Exception as e:
                    logger.error(f"[{self.exchange}] Message callback error: {e}")

    async def _heartbeat_loop(self) -> None:
        """Send periodic heartbeats."""
        while self.is_connected:
            await asyncio.sleep(self.config.heartbeat_interval)

            heartbeat_msg = self._build_heartbeat_message()
            if heartbeat_msg is not None and self._ws is not None:
                try:
                    if isinstance(heartbeat_msg, dict):
                        import json
                        await self._ws.send(json.dumps(heartbeat_msg))
                    else:
                        await self._ws.send(heartbeat_msg)
                except Exception as e:
                    logger.warning(f"[{self.exchange}] Failed to send heartbeat: {e}")

    # === Subscription Management ===

    async def subscribe(
        self,
        channel: str,
        params: dict[str, Any] | None = None,
        callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]] | None = None,
    ) -> None:
        """
        Subscribe to a channel.

        Args:
            channel: Channel identifier (e.g., "orderbook", "trades")
            params: Channel-specific parameters (e.g., {"market_id": "..."})
            callback: Optional callback for this subscription's messages

        Raises:
            WebSocketSubscriptionError: If subscription fails
        """
        if not self.is_connected:
            raise WebSocketDisconnectedError(
                "Cannot subscribe: WebSocket not connected",
                exchange=self.exchange,
            )

        params = params or {}
        subscription_key = self._get_subscription_key(channel, params)

        if subscription_key in self._subscriptions:
            logger.debug(f"[{self.exchange}] Already subscribed to {subscription_key}")
            return

        message = self._build_subscribe_message(channel, params)

        try:
            import json
            await self._ws.send(json.dumps(message))  # type: ignore

            self._subscriptions[subscription_key] = Subscription(
                channel=channel,
                params=params,
                subscribed_at=datetime.now(),
                callback=callback,
            )
            logger.info(f"[{self.exchange}] Subscribed to {subscription_key}")

        except Exception as e:
            raise WebSocketSubscriptionError(
                f"Failed to subscribe to {channel}: {e}",
                exchange=self.exchange,
                channel=channel,
            ) from e

    async def unsubscribe(self, channel: str, params: dict[str, Any] | None = None) -> None:
        """
        Unsubscribe from a channel.

        Args:
            channel: Channel identifier
            params: Channel-specific parameters
        """
        if not self.is_connected:
            return

        params = params or {}
        subscription_key = self._get_subscription_key(channel, params)

        if subscription_key not in self._subscriptions:
            return

        message = self._build_unsubscribe_message(channel, params)

        try:
            import json
            await self._ws.send(json.dumps(message))  # type: ignore
            del self._subscriptions[subscription_key]
            logger.info(f"[{self.exchange}] Unsubscribed from {subscription_key}")
        except Exception as e:
            logger.warning(f"[{self.exchange}] Failed to unsubscribe from {channel}: {e}")

    async def _resubscribe_all(self) -> None:
        """Resubscribe to all channels after reconnection."""
        subscriptions = list(self._subscriptions.values())
        self._subscriptions.clear()

        for sub in subscriptions:
            try:
                await self.subscribe(sub.channel, sub.params, sub.callback)
            except WebSocketSubscriptionError as e:
                logger.error(f"[{self.exchange}] Failed to resubscribe to {sub.channel}: {e}")

    def _get_subscription_key(self, channel: str, params: dict[str, Any]) -> str:
        """Generate unique key for subscription."""
        if not params:
            return channel
        sorted_params = sorted(params.items())
        param_str = "&".join(f"{k}={v}" for k, v in sorted_params)
        return f"{channel}?{param_str}"

    # === Callback Registration ===

    def on_connect(self, callback: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Register callback for connection event."""
        self._on_connect_callbacks.append(callback)

    def on_disconnect(self, callback: Callable[[Exception | None], Coroutine[Any, Any, None]]) -> None:
        """Register callback for disconnection event."""
        self._on_disconnect_callbacks.append(callback)

    def on_message(self, callback: Callable[[dict[str, Any]], Coroutine[Any, Any, None]]) -> None:
        """Register callback for general messages."""
        self._on_message_callbacks.append(callback)

    def set_fallback_trigger(self, callback: Callable[[], Coroutine[Any, Any, None]]) -> None:
        """Set callback to trigger REST fallback mode."""
        self._on_fallback_trigger = callback

    # === Utility Methods ===

    async def send(self, message: dict[str, Any] | str) -> None:
        """Send a message through WebSocket."""
        if not self.is_connected or self._ws is None:
            raise WebSocketDisconnectedError(
                "Cannot send: WebSocket not connected",
                exchange=self.exchange,
            )

        if isinstance(message, dict):
            import json
            await self._ws.send(json.dumps(message))
        else:
            await self._ws.send(message)

    def get_subscriptions(self) -> list[str]:
        """Get list of active subscription keys."""
        return list(self._subscriptions.keys())
