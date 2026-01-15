"""
Polymarket 오더북 실시간 테스트

실행: python tests/test_polymarket_obook.py
"""

import asyncio
import os
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from prediction_markets import create_exchange
from prediction_markets.base.types import OutcomeSide


def clear_screen():
    """Clear terminal screen."""
    os.system("cls" if os.name == "nt" else "clear")


def print_orderbook(orderbook, title: str = "", outcome: str = ""):
    """Print orderbook in a nice format - asks on top, bids on bottom."""
    clear_screen()

    print(f"{'='*60}")
    print(f"  {title}")
    print(f"  Outcome: {outcome}")
    print(f"{'='*60}")

    # Get asks and bids
    asks = list(reversed(orderbook.asks[:8])) if orderbook.asks else []
    bids = orderbook.bids[:8] if orderbook.bids else []

    # Spread
    spread = None
    if orderbook.best_ask and orderbook.best_bid:
        spread = orderbook.best_ask - orderbook.best_bid

    # ASKS (top, high to low price) - cumulative USD from bottom up
    print()
    print(f"  {'ASKS (매도)':^40}")
    print(f"  {'Price':>15}  {'Size':>12}  {'Total($)':>10}")
    print(f"  {'-'*40}")

    if asks:
        # Calculate cumulative USD from bottom (best ask) to top
        cumulative_list = []
        cumulative = 0
        for ask in reversed(asks):
            cumulative += float(ask.price) * float(ask.size)
            cumulative_list.append(cumulative)
        cumulative_list.reverse()

        for i, ask in enumerate(asks):
            print(f"  {float(ask.price):>15.4f}  {float(ask.size):>12.2f}  {cumulative_list[i]:>10.2f}")
    else:
        print(f"  {'(no asks)':^40}")

    # SPREAD LINE
    print()
    spread_str = f"Spread: {float(spread):.4f}" if spread else "Spread: N/A"
    print(f"  {'>>> ' + spread_str + ' <<<':^40}")
    print()

    # BIDS (bottom, high to low price) - cumulative USD
    print(f"  {'Price':>15}  {'Size':>12}  {'Total($)':>10}")
    print(f"  {'-'*40}")

    if bids:
        cumulative = 0
        for bid in bids:
            cumulative += float(bid.price) * float(bid.size)
            print(f"  {float(bid.price):>15.4f}  {float(bid.size):>12.2f}  {cumulative:>10.2f}")
    else:
        print(f"  {'(no bids)':^40}")

    print(f"  {'BIDS (매수)':^40}")
    print()
    print(f"  [Ctrl+C to exit]")


async def main():
    import random
    from prediction_markets.base.types import MarketStatus

    print("Polymarket Orderbook Viewer")
    print("-" * 40)

    market_input = input(f"Market URL or ID (Enter for random): ").strip()

    # Initialize exchange
    exchange = create_exchange("polymarket")

    async with exchange:
        try:
            # If no input, pick random active market
            if not market_input:
                print(f"\nLoading events...")
                events = await exchange.load_events()
                all_markets = [m for e in events.values() for m in e.markets]
                active_markets = [m for m in all_markets if m.status == MarketStatus.ACTIVE]

                if not active_markets:
                    print("No active markets found")
                    return

                market = random.choice(active_markets)
                market_id = market.id
                title = market.title

                # Build URL
                slug = market.raw.get("market_slug") or market.raw.get("slug", "")
                event_slug = market.raw.get("event_slug", "")
                if event_slug and slug:
                    url = f"https://polymarket.com/event/{event_slug}/{slug}"
                else:
                    url = f"https://polymarket.com/market/{market_id}"

                print(f"\n[RANDOM] {title}")
                print(f"         {url}")

                # Cache tokens
                from prediction_markets.exchanges.polymarket.parser import parse_market_tokens
                tokens = parse_market_tokens(market.raw)
                if tokens:
                    exchange._market_tokens[market_id] = tokens

            else:
                market_id = market_input
                print(f"\nLoading market...")

                # Check if it's an event URL (no market slug)
                is_event_url = bool(re.search(r"polymarket\.com/event/[^/]+/?$", market_id))
                # Check if it's just a slug (no URL, no hex ID)
                is_slug = (
                    not market_id.startswith("http")
                    and not market_id.startswith("0x")
                    and len(market_id) < 66  # condition IDs are 66 chars
                )

                if is_event_url:
                    # Event URL - show market selection
                    event_data = await exchange.get_event_markets(market_id)
                    event_title = event_data["event_title"]
                    markets = event_data["markets"]

                    print(f"\n[EVENT] {event_title}")
                    print(f"        {len(markets)}개의 마켓:\n")

                    for i, m in enumerate(markets, 1):
                        question = m.get("question", "")
                        active = "Y" if m.get("active") else "N"
                        print(f"  {i}. [{active}] {question}")

                    # Select market
                    while True:
                        try:
                            choice = input(f"\n  마켓 번호 (1-{len(markets)}): ").strip()
                            idx = int(choice) - 1
                            if 0 <= idx < len(markets):
                                market_id = markets[idx].get("conditionId")
                                break
                        except ValueError:
                            pass

                elif is_slug:
                    # Slug - search and show selection
                    print(f"\n[SEARCH] '{market_id}' 검색 중...")
                    events = await exchange.search_events(keyword=market_id, limit=20)
                    results = [m for e in events for m in e.markets]

                    if not results:
                        print(f"검색 결과 없음")
                        return

                    # Filter by slug match or title match
                    slug_lower = market_id.lower()
                    matched = [
                        m for m in results
                        if slug_lower in (m.raw.get("slug", "") or "").lower()
                        or slug_lower in (m.raw.get("market_slug", "") or "").lower()
                        or slug_lower in m.title.lower()
                    ]

                    if not matched:
                        matched = results  # Show all if no exact match

                    print(f"\n[SEARCH] {len(matched)}개 마켓:\n")
                    for i, m in enumerate(matched[:10], 1):
                        active = "Y" if m.status.value == "active" else "N"
                        print(f"  {i}. [{active}] {m.title}")

                    # Select market
                    while True:
                        try:
                            choice = input(f"\n  마켓 번호 (1-{min(10, len(matched))}): ").strip()
                            idx = int(choice) - 1
                            if 0 <= idx < min(10, len(matched)):
                                selected = matched[idx]
                                market_id = selected.id
                                # Cache tokens
                                from prediction_markets.exchanges.polymarket.parser import parse_market_tokens
                                tokens = parse_market_tokens(selected.raw)
                                if tokens:
                                    exchange._market_tokens[market_id] = tokens
                                break
                        except ValueError:
                            pass

                # Get market (resolves URL to condition ID)
                market = await exchange.fetch_market(market_id)
                market_id = market.id  # Use resolved condition ID
                title = market.title

                print(f"\n[OK] {title}")
                print(f"     ID: {market_id}")

                # Cache tokens
                from prediction_markets.exchanges.polymarket.parser import parse_market_tokens
                tokens = parse_market_tokens(market.raw)
                if tokens:
                    exchange._market_tokens[market_id] = tokens

            # Select outcome
            outcome_input = input(f"\nOutcome (YES/NO, default YES): ").strip().upper()
            outcome = OutcomeSide.NO if outcome_input == "NO" else OutcomeSide.YES

            print(f"\nStarting orderbook stream...")
            print(f"(Press Ctrl+C to stop)\n")
            await asyncio.sleep(1)

            # Poll orderbook
            while True:
                try:
                    orderbook = await exchange.get_orderbook(market_id, outcome)
                    print_orderbook(orderbook, title, outcome.value)
                    await asyncio.sleep(0.01)
                except Exception as e:
                    print(f"Error: {e}")
                    await asyncio.sleep(2)

        except KeyboardInterrupt:
            print("\n\nStopping...")
        except Exception as e:
            print(f"Error: {e}")
            import traceback
            traceback.print_exc()


if __name__ == "__main__":
    asyncio.run(main())
