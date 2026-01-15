"""
Polymarket Trading 테스트

실행: python tests/polymarket/test_trading.py

순차 테스트 플로우:
1. 마켓 선택 & 아웃컴 선택
2. Limit 주문 → 10초 대기 → Open Orders 확인
3. 해당 Limit 주문 Cancel
4. Market 주문 → 10초 대기 → Position 확인
5. Close Position
"""

import asyncio
import re
import sys
from decimal import Decimal
from pathlib import Path

# Load .env from core folder
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from prediction_markets import (
    create_exchange,
    Market,
    OutcomeSide,
    OrderSide,
    OrderType,
    SizeType,
)
from prediction_markets.config import get_polymarket_config


def print_header(title: str):
    """Print header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_step(step: int, title: str):
    """Print step header."""
    print(f"\n{'-'*60}")
    print(f"  Step {step}: {title}")
    print(f"{'-'*60}")


def print_market(market: Market):
    """Print market info."""
    print(f"\n  Market: {market.title[:50]}...")
    print(f"  ID: {market.id[:40]}...")
    print(f"  Status: {market.status.value if market.status else 'N/A'}")
    if market.liquidity:
        print(f"  Liquidity: ${market.liquidity:,.2f}")


async def select_market_interactive(exchange) -> Market | None:
    """Interactive market selection."""
    print("\n  마켓 선택 방법:")
    print("  1. 키워드로 이벤트 검색")
    print("  2. URL 또는 ID 직접 입력")
    print("  0. 취소")

    choice = input("\n  선택: ").strip()

    if choice == "0":
        return None

    elif choice == "1":
        keyword = input("\n  검색어: ").strip()
        if not keyword:
            print("  [!] 검색어가 비어있습니다.")
            return None

        print(f"\n  '{keyword}' 검색 중...")
        events = await exchange.search_events(keyword, limit=10)

        if not events:
            print("  [!] 검색 결과 없음")
            return None

        print(f"\n  {len(events)}개 이벤트:\n")
        for i, event in enumerate(events, 1):
            status = event.status.value if event.status else "?"
            print(f"  {i:>2}. [{status}] {event.title[:45]}... ({len(event.markets)}개 마켓)")

        try:
            idx = int(input("\n  이벤트 번호 (0=취소): ").strip()) - 1
            if idx == -1:
                return None
            if not (0 <= idx < len(events)):
                print("  [!] 잘못된 선택")
                return None
        except ValueError:
            print("  [!] 잘못된 입력")
            return None

        selected_event = events[idx]

        print(f"\n  이벤트: {selected_event.title[:50]}...")
        print(f"  마켓 목록 ({len(selected_event.markets)}개):\n")

        for i, market in enumerate(selected_event.markets, 1):
            status = market.status.value if market.status else "?"
            print(f"  {i:>2}. [{status}] {market.title[:50]}...")

        try:
            idx = int(input("\n  마켓 번호 (0=취소): ").strip()) - 1
            if idx == -1:
                return None
            if not (0 <= idx < len(selected_event.markets)):
                print("  [!] 잘못된 선택")
                return None
        except ValueError:
            print("  [!] 잘못된 입력")
            return None

        return selected_event.markets[idx]

    elif choice == "2":
        url_or_id = input("\n  URL 또는 ID 입력: ").strip()
        if not url_or_id:
            print("  [!] 입력이 비어있습니다.")
            return None

        is_event_url = bool(re.search(r"polymarket\.com/event/[^/]+/?$", url_or_id))

        if is_event_url:
            print("\n  이벤트 로딩 중...")
            try:
                match = re.search(r"/event/([^/?]+)", url_or_id)
                if match:
                    slug = match.group(1)
                    event = await exchange.fetch_event(slug)

                    print(f"\n  이벤트: {event.title[:50]}...")
                    print(f"  마켓 목록 ({len(event.markets)}개):\n")

                    for i, market in enumerate(event.markets, 1):
                        status = market.status.value if market.status else "?"
                        print(f"  {i:>2}. [{status}] {market.title[:50]}...")

                    try:
                        idx = int(input("\n  마켓 번호 (0=취소): ").strip()) - 1
                        if idx == -1:
                            return None
                        if 0 <= idx < len(event.markets):
                            return event.markets[idx]
                    except ValueError:
                        pass
                    print("  [!] 잘못된 선택")
                    return None
            except Exception as e:
                print(f"  [!] 에러: {e}")
                return None
        else:
            print("\n  마켓 로딩 중...")
            try:
                market = await exchange.fetch_market(url_or_id)
                return market
            except Exception as e:
                print(f"  [!] 에러: {e}")
                return None

    return None


def select_outcome() -> OutcomeSide | None:
    """Select outcome (YES/NO)."""
    print("\n  아웃컴 선택:")
    print("  1. YES")
    print("  2. NO")

    choice = input("\n  선택: ").strip()
    if choice == "1":
        return OutcomeSide.YES
    elif choice == "2":
        return OutcomeSide.NO
    else:
        print("  [!] 잘못된 선택")
        return None


async def show_orderbook(exchange, market_id: str, outcome: OutcomeSide):
    """Show current orderbook."""
    try:
        orderbook = await exchange.get_orderbook(market_id, outcome)
        print(f"\n  현재 오더북 ({outcome.value}):")
        print(f"    Best Bid: {orderbook.best_bid or 'N/A'}")
        print(f"    Best Ask: {orderbook.best_ask or 'N/A'}")
        print(f"    Spread: {orderbook.spread or 'N/A'}")
        return orderbook
    except Exception as e:
        print(f"  [!] 오더북 조회 실패: {e}")
        return None


async def show_open_orders(exchange, market_id: str):
    """Show open orders and return them."""
    try:
        orders = await exchange.get_open_orders(market_id)
        print(f"\n  Open Orders ({len(orders)}개):")
        if not orders:
            print("    (없음)")
        for order in orders:
            print(f"    - {order.side.value} {order.outcome.value} @ {order.price}")
            print(f"      Size: {order.size}, Filled: {order.filled_size}")
            print(f"      Status: {order.status.value}, ID: {order.id[:20]}...")
        return orders
    except Exception as e:
        print(f"  [!] Open Orders 조회 실패: {e}")
        return []


async def show_position(exchange, market_id: str, outcome: OutcomeSide):
    """Show position."""
    try:
        position = await exchange.get_position(market_id, outcome)
        if position is None:
            print(f"\n  Position ({outcome.value}): 없음")
            return None
        print(f"\n  Position ({outcome.value}):")
        print(f"    Size: {position.size}")
        print(f"    Avg Price: {position.avg_price}")
        print(f"    Current Price: {position.current_price}")
        print(f"    Market Value: {position.market_value}")
        print(f"    Unrealized PnL: {position.unrealized_pnl}")
        print(f"    Realized PnL: {position.realized_pnl}")
        return position
    except Exception as e:
        print(f"  [!] Position 조회 실패: {e}")
        return None


async def run_buy_test(exchange, market: Market, outcome: OutcomeSide, size: Decimal):
    """Run the BUY trading test sequence."""

    # Step 1: Show orderbook
    print_step(1, "오더북 확인")
    orderbook = await show_orderbook(exchange, market.id, outcome)
    if not orderbook or not orderbook.best_bid:
        print("  [!] 오더북이 비어있어 테스트를 진행할 수 없습니다.")
        return

    # Calculate limit price (below best bid to ensure it doesn't fill immediately)
    limit_price = orderbook.best_bid - Decimal("0.01")
    if limit_price <= Decimal("0"):
        limit_price = Decimal("0.01")

    # Step 2: Place limit order
    print_step(2, "Limit BUY 주문")
    print(f"\n  주문 내용:")
    print(f"    방향: BUY {outcome.value}")
    print(f"    가격: {limit_price} (Best Bid - 0.01)")
    print(f"    금액: ${size} USD")

    try:
        limit_order = await exchange.create_order(
            market_id=market.id,
            side=OrderSide.BUY,
            outcome=outcome,
            size=size,
            price=limit_price,
            order_type=OrderType.LIMIT,
            size_type=SizeType.USD,
        )
        print(f"\n  ✅ Limit 주문 생성 성공!")
        print(f"    Order ID: {limit_order.id}")
        print(f"    Status: {limit_order.status.value}")
    except Exception as e:
        print(f"\n  ❌ Limit 주문 실패: {e}")
        return

    # Wait and show open orders
    print("\n  10초 대기 후 Open Orders 조회...")
    await asyncio.sleep(10)
    orders = await show_open_orders(exchange, market.id)

    # Step 3: Cancel limit order
    print_step(3, "Limit 주문 취소")
    if not orders:
        print("\n  [!] 취소할 주문이 없습니다.")
    else:
        try:
            order_ids = [o.id for o in orders]
            await exchange.cancel_orders(order_ids)
            print(f"\n  ✅ 주문 취소 성공!")
            print(f"    취소된 주문 수: {len(order_ids)}개")
        except Exception as e:
            print(f"\n  ❌ 주문 취소 실패: {e}")

    # Verify cancellation
    print("\n  취소 확인...")
    await asyncio.sleep(2)
    await show_open_orders(exchange, market.id)

    # Step 4: Place market order
    print_step(4, "Market BUY 주문")
    print(f"\n  주문 내용:")
    print(f"    방향: MARKET BUY {outcome.value}")
    print(f"    금액: ${size} USD")

    try:
        market_order = await exchange.create_order(
            market_id=market.id,
            side=OrderSide.BUY,
            outcome=outcome,
            size=size,
            order_type=OrderType.MARKET,
            size_type=SizeType.USD,
        )
        print(f"\n  ✅ Market 주문 생성 성공!")
        print(f"    Order ID: {market_order.id}")
        print(f"    Status: {market_order.status.value}")
        print(f"    Filled: {market_order.filled_size}")
    except Exception as e:
        print(f"\n  ❌ Market 주문 실패: {e}")
        return

    # Wait and show position
    print("\n  10초 대기 후 Position 조회...")
    await asyncio.sleep(10)
    position = await show_position(exchange, market.id, outcome)

    # Step 5: Close position
    print_step(5, "Position 청산")
    if position is None or position.size <= 0:
        print("\n  [!] 청산할 포지션이 없습니다.")
        return

    print(f"\n  청산 내용:")
    print(f"    아웃컴: {outcome.value}")
    print(f"    수량: 전량 ({position.size})")

    try:
        result = await exchange.close_position(market.id, outcome)
        print(f"\n  ✅ 청산 성공!")
        print(f"    결과: {result}")
    except Exception as e:
        print(f"\n  ❌ 청산 실패: {e}")

    # Show final position
    print("\n  최종 Position 확인...")
    await asyncio.sleep(2)
    await show_position(exchange, market.id, outcome)

    print_header("BUY 테스트 완료")


async def run_sell_test(exchange, market: Market, outcome: OutcomeSide, size: Decimal):
    """Run the SELL trading test sequence."""

    # Step 1: Check existing position
    print_step(1, "현재 포지션 확인")
    position = await show_position(exchange, market.id, outcome)
    if position is None or position.size <= 0:
        print("\n  [!] 매도할 포지션이 없습니다.")
        print("  [!] Split을 먼저 수행하거나 BUY 테스트를 진행해주세요.")
        return

    # Step 2: Show orderbook
    print_step(2, "오더북 확인")
    orderbook = await show_orderbook(exchange, market.id, outcome)
    if not orderbook or not orderbook.best_ask:
        print("  [!] 오더북이 비어있어 테스트를 진행할 수 없습니다.")
        return

    # Calculate limit price (above best ask to ensure it doesn't fill immediately)
    limit_price = orderbook.best_ask + Decimal("0.01")
    if limit_price >= Decimal("1"):
        limit_price = Decimal("0.99")

    # Step 3: Place limit sell order
    print_step(3, "Limit SELL 주문")
    print(f"\n  주문 내용:")
    print(f"    방향: SELL {outcome.value}")
    print(f"    가격: {limit_price} (Best Ask + 0.01)")
    print(f"    수량: {size} shares")

    try:
        limit_order = await exchange.create_order(
            market_id=market.id,
            side=OrderSide.SELL,
            outcome=outcome,
            size=size,
            price=limit_price,
            order_type=OrderType.LIMIT,
            size_type=SizeType.SHARES,
        )
        print(f"\n  ✅ Limit SELL 주문 생성 성공!")
        print(f"    Order ID: {limit_order.id}")
        print(f"    Status: {limit_order.status.value}")
    except Exception as e:
        print(f"\n  ❌ Limit SELL 주문 실패: {e}")
        return

    # Wait and show open orders
    print("\n  10초 대기 후 Open Orders 조회...")
    await asyncio.sleep(10)
    orders = await show_open_orders(exchange, market.id)

    # Step 4: Cancel limit order
    print_step(4, "Limit 주문 취소")
    if not orders:
        print("\n  [!] 취소할 주문이 없습니다.")
    else:
        try:
            order_ids = [o.id for o in orders]
            await exchange.cancel_orders(order_ids)
            print(f"\n  ✅ 주문 취소 성공!")
            print(f"    취소된 주문 수: {len(order_ids)}개")
        except Exception as e:
            print(f"\n  ❌ 주문 취소 실패: {e}")

    # Verify cancellation
    print("\n  취소 확인...")
    await asyncio.sleep(2)
    await show_open_orders(exchange, market.id)

    # Step 5: Place market sell order
    print_step(5, "Market SELL 주문")
    print(f"\n  주문 내용:")
    print(f"    방향: MARKET SELL {outcome.value}")
    print(f"    수량: {size} shares")

    try:
        market_order = await exchange.create_order(
            market_id=market.id,
            side=OrderSide.SELL,
            outcome=outcome,
            size=size,
            order_type=OrderType.MARKET,
            size_type=SizeType.SHARES,
        )
        print(f"\n  ✅ Market SELL 주문 생성 성공!")
        print(f"    Order ID: {market_order.id}")
        print(f"    Status: {market_order.status.value}")
        print(f"    Filled: {market_order.filled_size}")
    except Exception as e:
        print(f"\n  ❌ Market SELL 주문 실패: {e}")
        return

    # Wait and show position
    print("\n  10초 대기 후 Position 조회...")
    await asyncio.sleep(10)
    await show_position(exchange, market.id, outcome)

    print_header("SELL 테스트 완료")


async def main():
    print_header("Polymarket Trading 테스트")

    print("\n  [!] 이 테스트는 실제 자금을 사용합니다.")
    print("  테스트넷이 아닌 경우 실제 USDC가 소모됩니다.")

    async with create_exchange("polymarket", get_polymarket_config()) as exchange:
        # Check wallet
        if hasattr(exchange, 'address') and exchange.address:
            print(f"\n  지갑 주소: {exchange.address}")
        else:
            print("\n  [!] 지갑이 설정되지 않았습니다.")
            print("  POLYMARKET_PRIVATE_KEY 환경변수를 설정하세요.")
            return

        # Step 0: Select market
        print_step(0, "마켓 & 아웃컴 선택")
        market = await select_market_interactive(exchange)
        if market is None:
            print("\n  취소됨")
            return

        print_market(market)

        outcome = select_outcome()
        if outcome is None:
            print("\n  취소됨")
            return

        # Select test type
        print("\n  테스트 종류 선택:")
        print("  1. BUY 테스트 (매수)")
        print("  2. SELL 테스트 (매도)")
        print("     [!] SELL 테스트는 이미 포지션이 있어야 합니다 (Split 후 가능)")

        test_type = input("\n  선택: ").strip()
        if test_type not in ["1", "2"]:
            print("  [!] 잘못된 선택")
            return

        is_buy_test = test_type == "1"

        # Get test size
        if is_buy_test:
            size_str = input("\n  테스트 금액 (USD, 기본값=1): ").strip() or "1"
            size_label = "USD"
        else:
            size_str = input("\n  테스트 수량 (shares, 기본값=1): ").strip() or "1"
            size_label = "shares"

        try:
            size = Decimal(size_str)
            if size <= 0:
                print("  [!] 값은 0보다 커야 합니다.")
                return
        except:
            print("  [!] 잘못된 입력")
            return

        # Confirm
        test_name = "BUY" if is_buy_test else "SELL"
        print(f"\n  테스트 설정:")
        print(f"    테스트: {test_name}")
        print(f"    마켓: {market.title[:40]}...")
        print(f"    아웃컴: {outcome.value}")
        print(f"    수량: {size} {size_label}")

        confirm = input("\n  테스트를 시작하시겠습니까? (y/n): ").strip().lower()
        if confirm != "y":
            print("\n  취소됨")
            return

        # Run test sequence
        if is_buy_test:
            await run_buy_test(exchange, market, outcome, size)
        else:
            await run_sell_test(exchange, market, outcome, size)

    print("\n  종료")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n  중단됨")
