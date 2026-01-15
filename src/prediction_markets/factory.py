"""
Exchange factory for creating exchange instances.

This module provides the `create_exchange` function which is the main entry point
for instantiating exchange objects.

Example:
    ```python
    from prediction_markets import create_exchange

    # Create Polymarket instance
    exchange = create_exchange("polymarket", {
        "api_key": "your_api_key",
        "api_secret": "your_api_secret",
    })

    # Initialize and use
    await exchange.init()
    events = await exchange.load_events()
    await exchange.close()
    ```
"""

from typing import Any

from prediction_markets.base.exchange import Exchange
from prediction_markets.common.exceptions import UnsupportedExchangeError

# Registry of supported exchanges
# Maps exchange ID to exchange class
_EXCHANGES: dict[str, type[Exchange]] = {}


def register_exchange(exchange_id: str, exchange_class: type[Exchange]) -> None:
    """
    Register an exchange class.

    Args:
        exchange_id: Unique exchange identifier
        exchange_class: Exchange class to register
    """
    _EXCHANGES[exchange_id.lower()] = exchange_class


def get_supported_exchanges() -> list[str]:
    """
    Get list of supported exchange IDs.

    Returns:
        List of exchange ID strings
    """
    return list(_EXCHANGES.keys())


def create_exchange(exchange_id: str, config: dict[str, Any] | None = None) -> Exchange:
    """
    Create an exchange instance.

    This is the main factory function for instantiating exchange objects.
    The exchange is not initialized - call `await exchange.init()` to connect.

    Args:
        exchange_id: Exchange identifier (e.g., "polymarket", "kalshi")
        config: Exchange configuration dictionary containing:
            - api_key: API key for authentication
            - api_secret: API secret (if required)
            - passphrase: API passphrase (if required)
            - testnet: Use testnet/sandbox (default: False)
            - ws_enabled: Enable WebSocket (default: True)
            - Additional exchange-specific options

    Returns:
        Exchange instance (not yet initialized)

    Raises:
        UnsupportedExchangeError: If exchange_id is not supported

    Example:
        ```python
        # Basic usage
        exchange = create_exchange("polymarket", {"api_key": "..."})
        await exchange.init()

        # With context manager
        async with create_exchange("polymarket", config) as exchange:
            events = await exchange.load_events()

        # Check supported exchanges
        print(get_supported_exchanges())  # ["polymarket", "kalshi", ...]
        ```
    """
    exchange_id_lower = exchange_id.lower()

    if exchange_id_lower not in _EXCHANGES:
        supported = ", ".join(get_supported_exchanges()) or "none"
        raise UnsupportedExchangeError(
            f"Exchange '{exchange_id}' is not supported. Supported: {supported}"
        )

    exchange_class = _EXCHANGES[exchange_id_lower]
    return exchange_class(config or {})


# Auto-register exchanges on import
def _auto_register_exchanges() -> None:
    """Auto-register all available exchange implementations."""
    try:
        from prediction_markets.exchanges.polymarket import Polymarket
        register_exchange("polymarket", Polymarket)
    except ImportError:
        pass

    # Add more exchanges here as they are implemented
    # try:
    #     from prediction_markets.exchanges.kalshi import Kalshi
    #     register_exchange("kalshi", Kalshi)
    # except ImportError:
    #     pass


_auto_register_exchanges()
