"""
Polymarket Split/Merge/Redeem 테스트

실행: python tests/polymarket/test_split_merge_redeem.py

기능:
1. 이벤트 검색 또는 URL 입력으로 마켓 선택
2. Split: 담보를 YES + NO 토큰으로 분할
3. Merge: YES + NO 토큰을 담보로 합치기
4. Redeem: 해결된 마켓에서 승리 포지션 정산
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
print(env_path)

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from prediction_markets import create_exchange, Event, Market, MarketStatus
from prediction_markets.config import get_polymarket_config


def print_header(title: str):
    """Print header."""
    print(f"\n{'='*60}")
    print(f"  {title}")
    print(f"{'='*60}")


def print_market(market: Market):
    """Print market info."""
    print(f"\n  Market: {market.title[:50]}...")
    print(f"  ID: {market.id[:40]}...")
    print(f"  Status: {market.status.value if market.status else 'N/A'}")
    if market.liquidity:
        print(f"  Liquidity: ${market.liquidity:,.2f}")


async def select_market_interactive(exchange) -> Market | None:
    """Interactive market selection."""
    print_header("마켓 선택")
    print("\n  1. 키워드로 이벤트 검색")
    print("  2. URL 또는 ID 직접 입력")
    print("  0. 취소")

    choice = input("\n  선택: ").strip()

    if choice == "0":
        return None

    elif choice == "1":
        # Search events
        keyword = input("\n  검색어: ").strip()
        if not keyword:
            print("  [!] 검색어가 비어있습니다.")
            return None

        print(f"\n  '{keyword}' 검색 중...")
        events = await exchange.search_events(keyword, limit=10)

        if not events:
            print("  [!] 검색 결과 없음")
            return None

        # Display events
        print(f"\n  {len(events)}개 이벤트:\n")
        for i, event in enumerate(events, 1):
            status = event.status.value if event.status else "?"
            print(f"  {i:>2}. [{status}] {event.title[:45]}... ({len(event.markets)}개 마켓)")

        # Select event
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

        # Display markets
        print(f"\n  이벤트: {selected_event.title[:50]}...")
        print(f"  마켓 목록 ({len(selected_event.markets)}개):\n")

        for i, market in enumerate(selected_event.markets, 1):
            status = market.status.value if market.status else "?"
            print(f"  {i:>2}. [{status}] {market.title[:50]}...")

        # Select market
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
        # Direct input
        url_or_id = input("\n  URL 또는 ID 입력: ").strip()
        if not url_or_id:
            print("  [!] 입력이 비어있습니다.")
            return None

        # Check if it's an event URL (no market slug)
        is_event_url = bool(re.search(r"polymarket\.com/event/[^/]+/?$", url_or_id))

        if is_event_url:
            # Fetch event and select market
            print("\n  이벤트 로딩 중...")
            try:
                # Extract slug from URL
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
            # Direct market fetch
            print("\n  마켓 로딩 중...")
            try:
                market = await exchange.fetch_market(url_or_id)
                return market
            except Exception as e:
                print(f"  [!] 에러: {e}")
                return None

    return None


async def test_split(exchange, market: Market):
    """Test split operation."""
    print_header("Split 테스트")
    print_market(market)

    amount_str = input("\n  Split 금액 (USDC): ").strip()
    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            print("  [!] 금액은 0보다 커야 합니다.")
            return
    except:
        print("  [!] 잘못된 금액")
        return

    print(f"\n  {amount} USDC를 YES + NO 토큰으로 분할합니다...")
    confirm = input("  계속하시겠습니까? (y/n): ").strip().lower()
    if confirm != "y":
        print("  취소됨")
        return

    try:
        result = await exchange.split(market.id, amount)
        print(f"\n  ✅ Split 성공!")
        print(f"  결과: {result}")
    except Exception as e:
        print(f"\n  ❌ Split 실패: {e}")


async def test_merge(exchange, market: Market):
    """Test merge operation."""
    print_header("Merge 테스트")
    print_market(market)

    amount_str = input("\n  Merge 금액 (토큰 수량): ").strip()
    try:
        amount = Decimal(amount_str)
        if amount <= 0:
            print("  [!] 금액은 0보다 커야 합니다.")
            return
    except:
        print("  [!] 잘못된 금액")
        return

    print(f"\n  {amount} YES + NO 토큰을 USDC로 합칩니다...")
    confirm = input("  계속하시겠습니까? (y/n): ").strip().lower()
    if confirm != "y":
        print("  취소됨")
        return

    try:
        result = await exchange.merge(market.id, amount)
        print(f"\n  ✅ Merge 성공!")
        print(f"  결과: {result}")
    except Exception as e:
        print(f"\n  ❌ Merge 실패: {e}")


async def test_redeem(exchange, market: Market):
    """Test redeem operation."""
    print_header("Redeem 테스트")
    print_market(market)

    if market.status != MarketStatus.RESOLVED:
        print(f"\n  [!] 마켓이 해결되지 않았습니다. (현재 상태: {market.status.value})")
        print("  Redeem은 해결된 마켓에서만 가능합니다.")
        confirm = input("\n  그래도 시도하시겠습니까? (y/n): ").strip().lower()
        if confirm != "y":
            return

    print(f"\n  승리 포지션을 정산합니다...")
    confirm = input("  계속하시겠습니까? (y/n): ").strip().lower()
    if confirm != "y":
        print("  취소됨")
        return

    try:
        result = await exchange.redeem(market.id)
        print(f"\n  ✅ Redeem 성공!")
        print(f"  결과: {result}")
    except Exception as e:
        print(f"\n  ❌ Redeem 실패: {e}")


async def main():
    print_header("Polymarket Split/Merge/Redeem 테스트")

    # Check for credentials
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

        while True:
            # Select market
            market = await select_market_interactive(exchange)
            if market is None:
                break

            print_market(market)

            # Select operation
            print("\n  작업 선택:")
            print("  1. Split (담보 → YES + NO)")
            print("  2. Merge (YES + NO → 담보)")
            print("  3. Redeem (승리 포지션 정산)")
            print("  0. 다른 마켓 선택")

            op_choice = input("\n  선택: ").strip()

            if op_choice == "1":
                await test_split(exchange, market)
            elif op_choice == "2":
                await test_merge(exchange, market)
            elif op_choice == "3":
                await test_redeem(exchange, market)
            elif op_choice == "0":
                continue
            else:
                print("  [!] 잘못된 선택")

            # Continue or exit
            cont = input("\n  계속하시겠습니까? (y/n): ").strip().lower()
            if cont != "y":
                break

    print("\n  종료")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n  중단됨")
