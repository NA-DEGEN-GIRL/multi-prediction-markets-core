"""
Basic usage example for multi-prediction-markets library.

This example demonstrates:
1. Creating an exchange instance
2. Loading markets
3. Getting orderbook and prices
4. Placing orders
5. Managing positions
"""

import asyncio
from decimal import Decimal

from prediction_markets import (
    Exchange,
    OrderSide,
    OutcomeSide,
    SizeType,
    create_exchange,
    get_supported_exchanges,
)


async def main() -> None:
    """Main example function."""

    # Check supported exchanges
    print("Supported exchanges:", get_supported_exchanges())

    # Create exchange instance
    # NOTE: Replace with your actual API credentials
    config = {
        "api_key": "your_api_key",
        "api_secret": "your_api_secret",
        "passphrase": "your_passphrase",
        "testnet": False,  # Use True for testing
        "ws_enabled": True,  # Enable WebSocket
    }

    # Using context manager (recommended)
    async with create_exchange("polymarket", config) as exchange:
        await demo_market_data(exchange)
        await demo_trading(exchange)
        await demo_account(exchange)


async def demo_market_data(exchange: Exchange) -> None:
    """Demonstrate market data operations."""
    print("\n=== Market Data ===")

    # Load all markets
    markets = await exchange.load_markets()
    print(f"Loaded {len(markets)} markets")

    # Get first active market
    active_markets = [m for m in markets.values() if m.status.value == "active"]
    if not active_markets:
        print("No active markets found")
        return

    market = active_markets[0]
    print(f"\nMarket: {market.title}")
    print(f"  ID: {market.id}")
    print(f"  Category: {market.category}")
    print(f"  Status: {market.status}")
    print(f"  End date: {market.end_date}")

    # Fetch orderbook
    orderbook = await exchange.fetch_orderbook(market.id, OutcomeSide.YES)
    print(f"\nOrderbook (YES) for {market.id}:")
    print(f"  Best bid: {orderbook.best_bid}")
    print(f"  Best ask: {orderbook.best_ask}")
    print(f"  Mid price: {orderbook.mid_price}")
    print(f"  Spread: {orderbook.spread}")

    # Fetch market price
    price = await exchange.fetch_market_price(market.id, OutcomeSide.YES)
    print(f"\nMarket price (YES):")
    print(f"  Mid: {price.mid_price}")
    print(f"  Implied probability: {exchange.price_to_probability(price.mid_price or Decimal(0)):.1%}")


async def demo_trading(exchange: Exchange) -> None:
    """Demonstrate trading operations."""
    print("\n=== Trading ===")

    # NOTE: This is example code - don't run with real funds without understanding!
    market_id = "example_market_id"

    # Example: Create limit order (10 shares of YES at $0.65)
    print("\nCreating limit order...")
    print("  Market:", market_id)
    print("  Side: BUY")
    print("  Outcome: YES")
    print("  Size: 10 shares")
    print("  Price: $0.65")

    # Uncomment to actually place order:
    # order = await exchange.create_order(
    #     market_id=market_id,
    #     side=OrderSide.BUY,
    #     outcome=OutcomeSide.YES,
    #     size=Decimal("10"),
    #     price=Decimal("0.65"),
    # )
    # print(f"  Order ID: {order.id}")
    # print(f"  Status: {order.status}")

    # Example: Create market order with USD amount
    print("\nCreating market order...")
    print("  Size: $100 worth")
    print("  Size type: USD")

    # Uncomment to actually place order:
    # order = await exchange.create_order(
    #     market_id=market_id,
    #     side=OrderSide.BUY,
    #     outcome=OutcomeSide.YES,
    #     size=Decimal("100"),
    #     size_type=SizeType.USD,
    # )

    # Example: Batch orders
    print("\nBatch order example:")
    print("  Would place multiple orders simultaneously")

    # orders = await exchange.create_order_batch([
    #     {"market_id": "m1", "side": "buy", "outcome": "yes", "size": 10, "price": 0.60},
    #     {"market_id": "m1", "side": "buy", "outcome": "yes", "size": 10, "price": 0.55},
    # ])

    # Example: Cancel orders
    print("\nCancel orders example:")
    print("  Would cancel all orders for a market")

    # cancelled = await exchange.cancel_orders(market_id=market_id)
    # print(f"  Cancelled {len(cancelled)} orders")


async def demo_account(exchange: Exchange) -> None:
    """Demonstrate account operations."""
    print("\n=== Account ===")

    # Fetch open orders
    print("\nOpen orders:")
    # orders = await exchange.fetch_open_orders()
    # for order in orders:
    #     print(f"  {order.id}: {order.side} {order.size} @ {order.price}")
    print("  (Example output)")

    # Fetch positions
    print("\nPositions:")
    # position = await exchange.fetch_position("market_id", OutcomeSide.YES)
    # if position:
    #     print(f"  Size: {position.size}")
    #     print(f"  Avg price: {position.avg_price}")
    #     print(f"  Unrealized PnL: {position.unrealized_pnl}")
    print("  (Example output)")

    # Fetch portfolio summary
    print("\nPortfolio summary:")
    # summary = await exchange.fetch_portfolio_summary()
    # print(f"  Total value: ${summary.total_value}")
    # print(f"  Cash balance: ${summary.cash_balance}")
    # print(f"  Unrealized PnL: ${summary.unrealized_pnl}")
    print("  (Example output)")

    # Get exchange status
    status = await exchange.get_status()
    print(f"\nExchange status:")
    print(f"  Status: {status.status}")
    print(f"  WebSocket connected: {status.ws_connected}")
    print(f"  REST latency: {status.rest_latency_ms}ms")


async def demo_fees(exchange: Exchange) -> None:
    """Demonstrate fee calculation."""
    print("\n=== Fees ===")

    # Get fee structure
    fees = exchange.get_fee_structure()
    print(f"Fee structure for {exchange.id}:")
    print(f"  Maker fee: {fees.maker_fee * 100}%")
    print(f"  Taker fee: {fees.taker_fee * 100}%")
    print(f"  Settlement fee: {fees.settlement_fee * 100}%")

    # Calculate fees for an order
    fee_breakdown = exchange.calculate_fees(
        side=OrderSide.BUY,
        size=Decimal("100"),
        price=Decimal("0.65"),
        is_maker=True,
    )
    print(f"\nFee breakdown for 100 shares @ $0.65:")
    print(f"  Trading fee: ${fee_breakdown.trading_fee}")
    print(f"  Est. settlement fee: ${fee_breakdown.estimated_settlement_fee}")
    print(f"  Total estimated: ${fee_breakdown.total_estimated}")


if __name__ == "__main__":
    asyncio.run(main())
