"""
Polymarket 검색 테스트

search_events() 테스트:
    - Event 객체 리스트 반환
    - 각 Event는 관련된 Market들을 그룹핑
    - 예: "US Presidential Election 2024" 이벤트에 여러 후보별 마켓 포함

실행: python tests/polymarket/test_search.py
"""

import asyncio
import sys
from pathlib import Path

# Load .env from core folder
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from prediction_markets import create_exchange, Event, Market
from prediction_markets.exchanges.polymarket import (
    get_15m_market_id,
    get_current_15m_market_id,
    get_next_15m_market_id,
)


def truncate(text: str, max_len: int = 50) -> str:
    """Truncate text with ellipsis if too long."""
    if len(text) <= max_len:
        return text
    return text[: max_len - 3] + "..."


def print_header(title: str, char: str = "=", width: int = 60):
    """Print a header with decorative lines."""
    print(f"\n{char * width}")
    print(f"  {title}")
    print(f"{char * width}")


def print_subheader(title: str, char: str = "-", width: int = 40):
    """Print a subheader with decorative lines."""
    print(f"\n{title}")
    print(char * width)


async def test_search_events(keyword: str = "bitcoin", limit: int = 5):
    """
    Test search_events functionality.

    search_events returns Event objects that group related markets together.
    """
    print(f"\n검색어: '{keyword}', limit: {limit}")
    print("=" * 60)

    async with create_exchange("polymarket") as exchange:
        print_subheader("[search_events] - Event 단위 그룹핑")

        events: list[Event] = await exchange.search_events(keyword, limit=limit)
        total_markets = sum(len(e.markets) for e in events)

        print(f"결과: {len(events)}개 이벤트, 총 {total_markets}개 마켓")
        print("\n구조: Event -> Markets (계층적)")

        for i, event in enumerate(events, 1):
            market_count = len(event.markets)
            status = event.status.value if event.status else "unknown"
            print(f"\n  [{i}] {truncate(event.title, 50)}")
            print(f"      ID: {event.id}")
            print(f"      상태: {status} | 마켓 수: {market_count}개")

            # Show first 3 markets in this event
            for market in event.markets[:3]:
                price_info = ""
                if market.liquidity:
                    price_info = f" | 유동성: ${market.liquidity:,.0f}"
                print(f"      |- {truncate(market.title, 45)}{price_info}")

            if market_count > 3:
                print(f"      |- ... (+{market_count - 3}개 마켓)")

        # Show event statistics
        print_subheader("\n[통계]")
        print(f"  총 이벤트: {len(events)}개")
        print(f"  총 마켓: {total_markets}개")
        if events:
            avg_markets = total_markets / len(events)
            print(f"  평균 마켓/이벤트: {avg_markets:.1f}개")


async def interactive_search():
    """
    Interactive search with event/market selection flow.

    Demonstrates the typical user flow:
    1. Search for events by keyword
    2. Select an event from results
    3. Browse markets within that event
    4. Select a specific market to view details
    """
    async with create_exchange("polymarket") as exchange:
        # Step 1: Get search keyword
        print_subheader("검색")
        keyword = input("검색어 입력: ").strip()
        if not keyword:
            print("검색어가 비어있습니다.")
            return

        # Step 2: Search for events
        print(f"\n'{keyword}' 검색 중...")
        events = await exchange.search_events(keyword, limit=10)

        if not events:
            print("검색 결과가 없습니다.")
            return

        # Step 3: Display event list
        total_markets = sum(len(e.markets) for e in events)
        print(f"\n검색 결과: {len(events)}개 이벤트 (총 {total_markets}개 마켓)")
        print_subheader("이벤트 선택")

        for i, event in enumerate(events, 1):
            market_count = len(event.markets)
            status = event.status.value if event.status else "unknown"
            print(f"  {i}. [{status}] {truncate(event.title, 45)} ({market_count}개 마켓)")

        # Step 4: Select event
        print()
        choice = input(f"이벤트 선택 (1-{len(events)}, q=종료): ").strip()
        if choice.lower() == "q":
            return

        try:
            event_idx = int(choice) - 1
            if not (0 <= event_idx < len(events)):
                print("잘못된 선택입니다.")
                return
        except ValueError:
            print("잘못된 입력입니다.")
            return

        selected_event = events[event_idx]

        # Step 5: Display markets in selected event
        print_subheader(f"이벤트: {truncate(selected_event.title, 40)}")
        print(f"  ID: {selected_event.id}")
        print(f"  상태: {selected_event.status.value if selected_event.status else 'N/A'}")
        print(f"  카테고리: {selected_event.category or 'N/A'}")
        print(f"\n마켓 목록 ({len(selected_event.markets)}개):")

        for i, market in enumerate(selected_event.markets, 1):
            status = market.status.value if market.status else "unknown"
            liquidity = f"${market.liquidity:,.0f}" if market.liquidity else "N/A"
            print(f"  {i}. [{status}] {truncate(market.title, 40)}")
            print(f"      유동성: {liquidity}")

        # Step 6: Select market
        if not selected_event.markets:
            print("\n이 이벤트에 마켓이 없습니다.")
            return

        print()
        choice = input(f"마켓 선택 (1-{len(selected_event.markets)}, q=종료): ").strip()
        if choice.lower() == "q":
            return

        try:
            market_idx = int(choice) - 1
            if not (0 <= market_idx < len(selected_event.markets)):
                print("잘못된 선택입니다.")
                return
        except ValueError:
            print("잘못된 입력입니다.")
            return

        selected_market = selected_event.markets[market_idx]

        # Step 7: Display market details
        print_subheader("마켓 상세 정보")
        print(f"""
  제목: {selected_market.title}

  기본 정보:
    - ID: {selected_market.id}
    - Slug: {selected_market.slug}
    - 상태: {selected_market.status.value if selected_market.status else 'N/A'}
    - 카테고리: {selected_market.category or 'N/A'}

  이벤트 정보:
    - 이벤트 ID: {selected_market.event_id or 'N/A'}
    - 이벤트 제목: {selected_market.event_title or 'N/A'}

  거래 정보:
    - 유동성: {f'${selected_market.liquidity:,.2f}' if selected_market.liquidity else 'N/A'}
    - 24h 거래량: {f'${selected_market.volume_24h:,.2f}' if selected_market.volume_24h else 'N/A'}
    - Outcomes: {selected_market.outcomes}

  날짜:
    - 종료일: {selected_market.end_date or 'N/A'}
    - 생성일: {selected_market.created_at or 'N/A'}

  설명:
    {truncate(selected_market.description, 200) if selected_market.description else 'N/A'}
""")


async def show_event_structure():
    """
    Educational display showing the Event -> Market hierarchy.
    """
    print_header("Event/Market 구조 설명")

    async with create_exchange("polymarket", {"max_events": 3}) as exchange:
        events = await exchange.load_events()

        print("""
  Polymarket의 데이터 구조:

  ┌─────────────────────────────────────────────────────────┐
  │  Exchange (Polymarket)                                  │
  │  └── Events (이벤트 목록)                               │
  │      ├── Event 1                                        │
  │      │   ├── title: "Bitcoin Price Predictions"         │
  │      │   ├── status: active                             │
  │      │   └── markets:                                   │
  │      │       ├── Market A: "BTC > $100k by Jan?"        │
  │      │       ├── Market B: "BTC > $150k by March?"      │
  │      │       └── Market C: "BTC > $200k by Dec?"        │
  │      │                                                  │
  │      └── Event 2                                        │
  │          ├── title: "US Election 2024"                  │
  │          └── markets:                                   │
  │              ├── Market X: "Will Biden win?"            │
  │              └── Market Y: "Will Trump win?"            │
  └─────────────────────────────────────────────────────────┘

  API 사용:
    - load_events()    : 모든 이벤트 로드 → dict[str, Event]
    - search_events()  : 키워드로 이벤트 검색 → list[Event]
    - get_market(id)   : 개별 마켓 조회 (캐시) → Market
""")

        print("\n실제 데이터 예시:")
        print("-" * 60)

        for event_id, event in list(events.items())[:3]:
            print(f"\n📁 Event: {truncate(event.title, 50)}")
            print(f"   ID: {event.id}")
            print(f"   Markets: {len(event.markets)}개")

            for market in event.markets[:2]:
                print(f"   └── 📊 {truncate(market.title, 45)}")

            if len(event.markets) > 2:
                print(f"   └── ... (+{len(event.markets) - 2}개)")


async def test_15m_market():
    """
    Test 15-minute up/down market lookup.

    Uses the utility functions to get current/next 15m market IDs
    and fetches the market data.
    """
    from datetime import datetime, timezone

    print_header("15분 마켓 조회")

    # Available coins
    coins = ["btc", "eth", "sol", "doge", "xrp"]

    print("\n지원 코인:")
    for i, coin in enumerate(coins, 1):
        print(f"  {i}. {coin.upper()}")
    print(f"  {len(coins) + 1}. 직접 입력")

    choice = input(f"\n코인 선택 (1-{len(coins) + 1}, Enter=btc): ").strip()

    if not choice:
        coin = "btc"
    elif choice == str(len(coins) + 1):
        coin = input("코인 심볼 입력: ").strip().lower()
    else:
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(coins):
                coin = coins[idx]
            else:
                coin = "btc"
        except ValueError:
            coin = "btc"

    # Show current time and market IDs
    now = datetime.now(timezone.utc)
    current_id = get_current_15m_market_id(coin)
    next_id = get_next_15m_market_id(coin)

    print(f"\n현재 UTC 시간: {now.strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"코인: {coin.upper()}")
    print(f"\n현재 15분 마켓 ID: {current_id}")
    print(f"다음 15분 마켓 ID: {next_id}")

    # Menu for which market to fetch
    print("\n조회 옵션:")
    print("  1. 현재 15분 마켓")
    print("  2. 다음 15분 마켓")
    print("  3. 특정 시간 마켓")

    fetch_choice = input("\n선택 (1-3, Enter=1): ").strip() or "1"

    if fetch_choice == "3":
        print("\n시간 입력 (UTC 기준)")
        try:
            year = int(input("  년 (Enter=2026): ").strip() or "2026")
            month = int(input("  월 (1-12): ").strip())
            day = int(input("  일 (1-31): ").strip())
            hour = int(input("  시 (0-23): ").strip())
            minute = int(input("  분 (0-59): ").strip())
            dt = datetime(year, month, day, hour, minute, tzinfo=timezone.utc)
            market_id = get_15m_market_id(coin, dt)
        except ValueError as e:
            print(f"잘못된 입력: {e}")
            return
    elif fetch_choice == "2":
        market_id = next_id
    else:
        market_id = current_id

    print(f"\n조회할 마켓 ID: {market_id}")
    print("-" * 50)

    # Fetch the market
    async with create_exchange("polymarket") as exchange:
        try:
            event = await exchange.fetch_event(market_id)

            print(f"\n📁 이벤트: {event.title}")
            print(f"   ID: {event.id}")
            print(f"   상태: {event.status.value if event.status else 'N/A'}")
            print(f"   카테고리: {event.category or 'N/A'}")

            if event.end_date:
                print(f"   종료: {event.end_date}")
            if event.volume_24h:
                print(f"   24h 거래량: ${event.volume_24h:,.2f}")
            if event.liquidity:
                print(f"   유동성: ${event.liquidity:,.2f}")

            print(f"\n   마켓 ({len(event.markets)}개):")
            for market in event.markets:
                status = market.status.value if market.status else "unknown"
                print(f"   └── [{status}] {market.title}")
                print(f"       ID: {market.id}")
                if market.liquidity:
                    print(f"       유동성: ${market.liquidity:,.2f}")

        except Exception as e:
            print(f"\n❌ 마켓 조회 실패: {e}")
            print("   (마켓이 아직 생성되지 않았거나 존재하지 않을 수 있습니다)")


async def main():
    """Main menu."""
    print_header("Polymarket 검색 테스트")

    print("""
  Event 기반 검색 테스트입니다.

  - search_events(): 키워드로 Event 검색 (Market들 그룹핑)
  - 15분 마켓: BTC/ETH/SOL 등의 15분 단위 Up/Down 마켓 조회
""")

    while True:
        print("\n선택:")
        print("  1. search_events() 테스트")
        print("  2. 대화형 검색 (이벤트 -> 마켓 선택)")
        print("  3. Event/Market 구조 설명")
        print("  4. 15분 마켓 조회 (BTC/ETH/SOL 등)")
        print("  q. 종료")

        choice = input("\n선택: ").strip().lower()

        try:
            if choice == "1":
                keyword = input("검색어 (Enter='bitcoin'): ").strip() or "bitcoin"
                limit_str = input("limit (Enter=5): ").strip() or "5"
                limit = int(limit_str)
                await test_search_events(keyword, limit)
            elif choice == "2":
                await interactive_search()
            elif choice == "3":
                await show_event_structure()
            elif choice == "4":
                await test_15m_market()
            elif choice == "q":
                break
            else:
                print("잘못된 선택입니다.")
        except KeyboardInterrupt:
            print("\n중단됨")
        except Exception as e:
            print(f"에러: {e}")
            import traceback
            traceback.print_exc()

    print("\n종료")


if __name__ == "__main__":
    asyncio.run(main())
