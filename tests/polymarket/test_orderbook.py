"""
Polymarket Orderbook 테스트

실행: python tests/polymarket/test_orderbook.py

기능:
1. 마켓 선택 (랜덤, 검색, 직접 ID 입력)
2. 아웃컴 선택 (YES/NO)
3. 오더북 출력 (asks 위, bids 아래)
4. 연속 새로고침 모드
"""

import asyncio
import os
import sys
import random
from pathlib import Path
from datetime import datetime
from decimal import Decimal

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from prediction_markets import create_exchange, OrderBook, OutcomeSide, MarketStatus, Market


def clear_screen():
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def format_price(price: Decimal | None) -> str:
    """Format price for display."""
    if price is None:
        return "N/A"
    return f"{float(price):.4f}"


def format_size(size: Decimal | None) -> str:
    """Format size for display."""
    if size is None:
        return "N/A"
    return f"{float(size):,.2f}"


def format_usd(price: Decimal, size: Decimal) -> str:
    """Format USD value for display."""
    usd = float(price) * float(size)
    return f"${usd:,.2f}"


def print_header(title: str, outcome: str, market: Market | None = None):
    """Print orderbook header."""
    print("=" * 70)
    print(f"  {title[:65]}")
    print(f"  Outcome: {outcome}")
    if market:
        status_str = market.status.value if market.status else "unknown"
        print(f"  Status: {status_str}")
        if market.volume_24h:
            print(f"  24h Volume: ${float(market.volume_24h):,.2f}")
    print("=" * 70)


def print_orderbook(orderbook: OrderBook, title: str, outcome: str, market: Market | None = None):
    """
    Print orderbook in a nice format.

    ASKS on top (high to low price - reversed so highest appears at top)
    BIDS on bottom (high to low price - sorted descending)
    """
    clear_screen()
    print_header(title, outcome, market)

    # Calculate totals
    total_ask_size = sum(ask.size for ask in orderbook.asks) if orderbook.asks else Decimal("0")
    total_bid_size = sum(bid.size for bid in orderbook.bids) if orderbook.bids else Decimal("0")

    # ASKS section (매도 - 팔려는 주문들)
    # Reverse asks so highest price is at top (visually makes sense)
    asks = list(reversed(orderbook.asks[:10])) if orderbook.asks else []

    print(f"\n  {'ASKS (매도)':^56}")
    print(f"  {'Price':>14}  {'Size':>14}  {'USD Value':>14}  {'Cumulative':>10}")
    print(f"  {'-' * 56}")

    if asks:
        # Calculate cumulative from bottom (best ask) to top
        cumulative_sizes = []
        cumsum = Decimal("0")
        for ask in reversed(asks):  # Start from best ask
            cumsum += ask.size
            cumulative_sizes.insert(0, cumsum)  # Insert at beginning

        for i, ask in enumerate(asks):
            usd_val = float(ask.price) * float(ask.size)
            cum_pct = (cumulative_sizes[i] / total_ask_size * 100) if total_ask_size > 0 else 0
            print(f"  {float(ask.price):>14.4f}  {float(ask.size):>14.2f}  ${usd_val:>13,.2f}  {cum_pct:>9.1f}%")
    else:
        print(f"  {'(no asks)':^56}")

    # Spread section
    spread = orderbook.spread
    spread_str = f"Spread: {float(spread):.4f}" if spread else "Spread: N/A"
    mid_price = orderbook.mid_price
    mid_str = f"Mid: {float(mid_price):.4f}" if mid_price else "Mid: N/A"

    print()
    print(f"  {'>>> ' + spread_str + ' | ' + mid_str + ' <<<':^56}")
    print()

    # BIDS section (매수 - 사려는 주문들)
    bids = orderbook.bids[:10] if orderbook.bids else []

    print(f"  {'Price':>14}  {'Size':>14}  {'USD Value':>14}  {'Cumulative':>10}")
    print(f"  {'-' * 56}")

    if bids:
        cumsum = Decimal("0")
        for bid in bids:
            cumsum += bid.size
            cum_pct = (cumsum / total_bid_size * 100) if total_bid_size > 0 else 0
            usd_val = float(bid.price) * float(bid.size)
            print(f"  {float(bid.price):>14.4f}  {float(bid.size):>14.2f}  ${usd_val:>13,.2f}  {cum_pct:>9.1f}%")
    else:
        print(f"  {'(no bids)':^56}")

    print(f"  {'BIDS (매수)':^56}")

    # Summary section
    print()
    print(f"  {'-' * 56}")
    print(f"  Best Bid: {format_price(orderbook.best_bid):>10}  |  Best Ask: {format_price(orderbook.best_ask):>10}")
    if orderbook.mid_price:
        implied_prob = float(orderbook.mid_price) * 100
        print(f"  Mid Price: {format_price(orderbook.mid_price):>10}  |  Implied Probability: {implied_prob:.1f}%")

    print(f"  Total Bid Size: {format_size(total_bid_size):>10}  |  Total Ask Size: {format_size(total_ask_size):>10}")

    # Timestamp
    print()
    print(f"  Last Updated: {orderbook.timestamp.strftime('%Y-%m-%d %H:%M:%S UTC')}")
    print("=" * 70)


def print_menu():
    """Print main menu."""
    print("\n" + "=" * 50)
    print("  Polymarket Orderbook Viewer")
    print("=" * 50)
    print()
    print("  1. Random market (from loaded markets)")
    print("  2. Search markets")
    print("  3. Enter market ID (conditionId)")
    print("  4. Enter Polymarket URL")
    print("  0. Exit")
    print()


def print_outcome_menu():
    """Print outcome selection menu."""
    print("\n  Select outcome:")
    print("  1. YES")
    print("  2. NO")
    print()


def print_refresh_menu():
    """Print refresh mode menu."""
    print("\n  Options:")
    print("  1. View once")
    print("  2. Continuous refresh (every 3 seconds)")
    print("  3. Back to menu")
    print()


async def select_random_market(exchange) -> Market | None:
    """Select a random market from loaded markets."""
    markets = list(exchange._markets.values())

    if not markets:
        print("\n  [!] No markets loaded. Loading events...")
        await exchange.load_events()
        markets = list(exchange._markets.values())

    # Filter active markets
    active_markets = [m for m in markets if m.status == MarketStatus.ACTIVE]

    if not active_markets:
        print("\n  [!] No active markets found.")
        return None

    market = random.choice(active_markets)
    print(f"\n  Selected: {market.title[:60]}...")
    return market


async def search_and_select_market(exchange) -> Market | None:
    """Search markets and let user select one."""
    keyword = input("\n  Enter search keyword: ").strip()
    if not keyword:
        print("  [!] Keyword cannot be empty.")
        return None

    print(f"\n  Searching for '{keyword}'...")

    try:
        events = await exchange.search_events(keyword, limit=20)
    except Exception as e:
        print(f"\n  [!] Search failed: {e}")
        return None

    if not events:
        print(f"\n  [!] No markets found for '{keyword}'")
        return None

    # Collect all markets from events
    all_markets = []
    for event in events:
        for market in event.markets:
            all_markets.append((event.title, market))

    if not all_markets:
        print(f"\n  [!] No markets found in events")
        return None

    # Display markets
    print(f"\n  Found {len(all_markets)} markets:\n")
    for i, (event_title, market) in enumerate(all_markets[:15], 1):
        status = market.status.value if market.status else "?"
        title_display = market.title[:45] if len(market.title) <= 45 else market.title[:42] + "..."
        print(f"  {i:>2}. [{status:>8}] {title_display}")

    if len(all_markets) > 15:
        print(f"\n  ... and {len(all_markets) - 15} more")

    # Let user select
    try:
        choice = input("\n  Select market number (or 0 to cancel): ").strip()
        idx = int(choice) - 1
        if idx == -1:
            return None
        if 0 <= idx < len(all_markets):
            _, market = all_markets[idx]
            print(f"\n  Selected: {market.title[:60]}...")
            return market
        else:
            print("  [!] Invalid selection.")
            return None
    except ValueError:
        print("  [!] Invalid input.")
        return None


async def get_market_by_id(exchange, market_id: str) -> Market | None:
    """Get market by condition ID or fetch it."""
    print(f"\n  Fetching market: {market_id[:40]}...")

    try:
        market = await exchange.fetch_market(market_id)
        print(f"  Found: {market.title[:60]}...")
        return market
    except Exception as e:
        print(f"\n  [!] Failed to fetch market: {e}")
        return None


async def view_orderbook_once(exchange, market: Market, outcome: OutcomeSide):
    """View orderbook once."""
    try:
        orderbook = await exchange.get_orderbook(market.id, outcome)
        outcome_str = "YES" if outcome == OutcomeSide.YES else "NO"
        print_orderbook(orderbook, market.title, outcome_str, market)
    except Exception as e:
        print(f"\n  [!] Failed to fetch orderbook: {e}")


async def view_orderbook_continuous(exchange, market: Market, outcome: OutcomeSide, interval: float = 3.0):
    """View orderbook with continuous refresh."""
    outcome_str = "YES" if outcome == OutcomeSide.YES else "NO"

    print("\n  Starting continuous refresh mode...")
    print("  Press Ctrl+C to stop.\n")

    try:
        while True:
            try:
                orderbook = await exchange.get_orderbook(market.id, outcome, use_cache=False)
                print_orderbook(orderbook, market.title, outcome_str, market)
                print(f"\n  [Refreshing in {interval:.0f} seconds... Press Ctrl+C to stop]")
                await asyncio.sleep(interval)
            except Exception as e:
                print(f"\n  [!] Error fetching orderbook: {e}")
                print("  Retrying in 5 seconds...")
                await asyncio.sleep(5)
    except KeyboardInterrupt:
        print("\n\n  Stopped continuous refresh.")


async def main():
    """Main interactive loop."""
    clear_screen()
    print("\n" + "=" * 50)
    print("  Polymarket Orderbook Tester")
    print("=" * 50)
    print()
    print("  Initializing exchange...")

    # Create exchange (no auth needed for orderbook viewing)
    exchange = create_exchange("polymarket", {
        "max_events": 100,  # Load fewer markets for faster startup
    })

    try:
        async with exchange:
            print(f"  Loaded {len(exchange._markets)} markets from {len(exchange._events)} events")

            while True:
                print_menu()
                choice = input("  Select option: ").strip()

                market = None

                if choice == "0":
                    print("\n  Goodbye!")
                    break

                elif choice == "1":
                    # Random market
                    market = await select_random_market(exchange)

                elif choice == "2":
                    # Search markets
                    market = await search_and_select_market(exchange)

                elif choice == "3":
                    # Enter market ID
                    market_id = input("\n  Enter conditionId (0x...): ").strip()
                    if market_id:
                        market = await get_market_by_id(exchange, market_id)

                elif choice == "4":
                    # Enter Polymarket URL
                    url = input("\n  Enter Polymarket URL: ").strip()
                    if url:
                        market = await get_market_by_id(exchange, url)
                else:
                    print("\n  [!] Invalid option.")
                    continue

                if market is None:
                    continue

                # Select outcome
                print_outcome_menu()
                outcome_choice = input("  Select outcome: ").strip()

                if outcome_choice == "1":
                    outcome = OutcomeSide.YES
                elif outcome_choice == "2":
                    outcome = OutcomeSide.NO
                else:
                    print("  [!] Invalid outcome selection.")
                    continue

                # View mode
                while True:
                    print_refresh_menu()
                    mode_choice = input("  Select mode: ").strip()

                    if mode_choice == "1":
                        # View once
                        await view_orderbook_once(exchange, market, outcome)
                        input("\n  Press Enter to continue...")

                    elif mode_choice == "2":
                        # Continuous refresh
                        interval_input = input("  Refresh interval in seconds (default 3): ").strip()
                        try:
                            interval = float(interval_input) if interval_input else 3.0
                            interval = max(1.0, min(60.0, interval))  # Clamp between 1 and 60
                        except ValueError:
                            interval = 3.0

                        await view_orderbook_continuous(exchange, market, outcome, interval)

                    elif mode_choice == "3":
                        # Back to menu
                        break
                    else:
                        print("  [!] Invalid mode selection.")
                        continue

    except KeyboardInterrupt:
        print("\n\n  Interrupted by user.")
    except Exception as e:
        print(f"\n  [!] Error: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
