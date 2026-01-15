"""
Polymarket exchange implementation.

Polymarket is a decentralized prediction market platform built on Polygon.

Example:
    ```python
    from prediction_markets import create_exchange

    exchange = create_exchange("polymarket", {
        "private_key": "0x...",  # Wallet private key
    })

    async with exchange:
        # Load events (with their markets)
        events = await exchange.load_events()
        print(f"Found {len(events)} events")

        # Get orderbook
        from prediction_markets import OutcomeSide
        ob = await exchange.get_orderbook("condition_id", OutcomeSide.YES)
        print(f"Best bid: {ob.best_bid}, Best ask: {ob.best_ask}")

        # Place order
        from decimal import Decimal
        from prediction_markets import OrderSide, OutcomeSide

        order = await exchange.create_order(
            market_id="condition_id",
            side=OrderSide.BUY,
            outcome=OutcomeSide.YES,
            size=Decimal("10"),
            price=Decimal("0.65"),
        )
    ```

Configuration:
    Required:
    - private_key: Wallet private key (hex string starting with 0x)

    Optional:
    - chain_id: Chain ID (137 for Polygon mainnet)
    - proxy_wallet: Proxy wallet address (from Polymarket settings)
    - ws_enabled: Enable WebSocket (default: True)

    For Split/Merge (gasless):
    - builder_api_key: Builder API key
    - builder_secret: Builder API secret
    - builder_passphrase: Builder API passphrase
"""

from prediction_markets.exchanges.polymarket.polymarket import Polymarket
from prediction_markets.exchanges.polymarket.rest_api import (
    ApiCreds,
    PolymarketRestClient,
)
from prediction_markets.exchanges.polymarket.signer import (
    CreateOrderOptions,
    OrderArgs,
    OrderSigner,
    Side,
    SignatureType,
    SignedOrder,
    get_order_signer,
)
from prediction_markets.exchanges.polymarket.ws_client import (
    Channel,
    PolymarketWebSocketClient,
)
from prediction_markets.exchanges.polymarket.builder_client import BuilderRelayerClient
from prediction_markets.exchanges.polymarket.constants import (
    MAINNET_CONTRACTS,
    TESTNET_CONTRACTS,
    POLYGON_MAINNET_CHAIN_ID,
    POLYGON_AMOY_CHAIN_ID,
    get_contracts,
)

__all__ = [
    # Main exchange class
    "Polymarket",
    # REST API
    "PolymarketRestClient",
    "ApiCreds",
    # Order signing
    "OrderSigner",
    "OrderArgs",
    "CreateOrderOptions",
    "SignedOrder",
    "Side",
    "SignatureType",
    "get_order_signer",
    # WebSocket
    "PolymarketWebSocketClient",
    "Channel",
    # On-chain operations (gasless via Builder Relayer)
    "BuilderRelayerClient",
    # Contract constants
    "MAINNET_CONTRACTS",
    "TESTNET_CONTRACTS",
    "POLYGON_MAINNET_CHAIN_ID",
    "POLYGON_AMOY_CHAIN_ID",
    "get_contracts",
]
