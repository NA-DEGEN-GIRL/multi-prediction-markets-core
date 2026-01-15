"""
Polymarket Event 테스트

실행: python tests/polymarket/test_events.py

이 스크립트는 Event 관련 기능을 대화형으로 테스트합니다:
1. load_events() - 이벤트 로드
2. search_events(keyword) - 키워드로 이벤트 검색
3. fetch_event(slug) - 단일 이벤트 조회
4. get_event(id) - 캐시에서 이벤트 조회
"""

import asyncio
import sys
from pathlib import Path

# Load .env from core folder
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(env_path)

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from prediction_markets import create_exchange, Event, EventStatus


def print_separator(title: str = "", char: str = "=", width: int = 60) -> None:
    """Print a separator line with optional title."""
    if title:
        print(f"\n{char * width}")
        print(f"  {title}")
        print(f"{char * width}")
    else:
        print(char * width)


def print_event_summary(event: Event, index: int | None = None) -> None:
    """Print a single event summary."""
    prefix = f"{index}. " if index is not None else ""
    status_str = f"[{event.status.value}]" if event.status else "[unknown]"

    # Truncate title if too long
    max_title_len = 50
    title = event.title[:max_title_len] + "..." if len(event.title) > max_title_len else event.title

    print(f"  {prefix}{status_str} {title}")
    print(f"     |-- 마켓 수: {len(event.markets)}개")
    print(f"     |-- 카테고리: {event.category or 'N/A'}")
    print(f"     |-- ID: {event.id}")
    if event.volume_24h:
        print(f"     |-- 24h 거래량: ${event.volume_24h:,.2f}")


def print_event_detail(event: Event) -> None:
    """Print detailed event information."""
    print(f"\n이벤트: {event.title}")
    print(f"  ID: {event.id}")
    print(f"  상태: {event.status.value}")
    print(f"  카테고리: {event.category or 'N/A'}")

    if event.description:
        desc = event.description[:200] + "..." if len(event.description) > 200 else event.description
        print(f"  설명: {desc}")

    if event.start_date:
        print(f"  시작일: {event.start_date}")
    if event.end_date:
        print(f"  종료일: {event.end_date}")
    if event.volume_24h:
        print(f"  24h 거래량: ${event.volume_24h:,.2f}")
    if event.liquidity:
        print(f"  유동성: ${event.liquidity:,.2f}")
    if event.tags:
        print(f"  태그: {', '.join(event.tags)}")

    print(f"\n  마켓 목록 ({len(event.markets)}개):")
    for i, market in enumerate(event.markets, 1):
        max_title_len = 50
        title = market.title[:max_title_len] + "..." if len(market.title) > max_title_len else market.title
        status_str = f"[{market.status.value}]" if market.status else ""
        print(f"    {i}. {status_str} {title}")
        print(f"       ID: {market.id[:30]}...")
        if market.volume_24h:
            print(f"       24h 거래량: ${market.volume_24h:,.2f}")


async def test_load_events() -> dict[str, Event] | None:
    """
    load_events() 테스트

    이벤트를 로드하고 결과를 표시합니다.
    """
    print_separator("1. load_events() 테스트")

    # Ask for max_events
    max_events_input = input("\n로드할 이벤트 수 (Enter for 10): ").strip()
    max_events = int(max_events_input) if max_events_input.isdigit() else 10

    print(f"\n{max_events}개 이벤트 로드 중...")

    async with create_exchange("polymarket", {"max_events": max_events}) as exchange:
        events = await exchange.load_events()

        print(f"\n로드된 이벤트: {len(events)}개\n")

        if not events:
            print("  이벤트 없음")
            return None

        for i, (event_id, event) in enumerate(events.items(), 1):
            print_event_summary(event, i)
            if i >= 20:  # Limit display to 20
                remaining = len(events) - 20
                if remaining > 0:
                    print(f"\n  ... 외 {remaining}개 이벤트")
                break

        return events


async def test_search_events() -> list[Event] | None:
    """
    search_events() 테스트

    키워드로 이벤트를 검색하고 결과를 표시합니다.
    """
    print_separator("2. search_events() 테스트")

    keyword = input("\n검색어 입력 (Enter for 'bitcoin'): ").strip() or "bitcoin"
    limit_input = input("결과 제한 (Enter for 10): ").strip()
    limit = int(limit_input) if limit_input.isdigit() else 10

    async with create_exchange("polymarket") as exchange:
        print(f"\n'{keyword}' 검색 중...")

        try:
            events = await exchange.search_events(keyword, limit=limit)

            print(f"\n검색 결과: {len(events)}개 이벤트\n")

            if not events:
                print("  검색 결과 없음")
                return None

            for i, event in enumerate(events, 1):
                print_event_summary(event, i)

            return events

        except Exception as e:
            print(f"\n검색 에러: {e}")
            return None


async def test_fetch_event(slug: str | None = None) -> Event | None:
    """
    fetch_event() 테스트

    단일 이벤트를 slug로 조회하고 상세 정보를 표시합니다.
    """
    print_separator("3. fetch_event() 테스트")

    if not slug:
        slug = input("\nEvent slug 입력 (예: bitcoin-above-on-january-12): ").strip()

    if not slug:
        print("slug 없음, 스킵")
        return None

    async with create_exchange("polymarket") as exchange:
        print(f"\n'{slug}' 이벤트 조회 중...")

        try:
            event = await exchange.fetch_event(slug)
            print_event_detail(event)
            return event

        except ValueError as e:
            print(f"\n이벤트를 찾을 수 없음: {e}")
            return None
        except Exception as e:
            print(f"\n에러: {e}")
            import traceback
            traceback.print_exc()
            return None


async def test_get_event_from_cache() -> None:
    """
    get_event() 캐시 테스트

    load_events()로 이벤트를 로드한 후 캐시에서 조회합니다.
    """
    print_separator("4. get_event() 캐시 테스트")

    async with create_exchange("polymarket", {"max_events": 5}) as exchange:
        # First load events
        print("\n이벤트 로드 중...")
        events = await exchange.load_events()

        if not events:
            print("이벤트 없음")
            return

        print(f"{len(events)}개 이벤트 로드됨\n")

        # Get first event from cache (sync method)
        first_id = list(events.keys())[0]
        first_event = events[first_id]

        print(f"테스트할 이벤트: {first_event.title[:50]}...")
        print(f"  ID: {first_id}")

        # Test cache retrieval
        print("\n캐시에서 조회 테스트:")
        try:
            cached = exchange.get_event(first_id)
            print(f"  성공: {cached.title[:50]}...")
            print(f"  ID 일치: {cached.id == first_id}")
            print(f"  제목 일치: {cached.title == first_event.title}")
        except Exception as e:
            print(f"  실패: {e}")

        # Test non-existent ID
        print("\n존재하지 않는 ID 조회 테스트:")
        try:
            exchange.get_event("non-existent-event-slug-12345")
            print("  예상치 못한 성공 (에러가 발생해야 함)")
        except ValueError as e:
            print(f"  예상대로 예외 발생: {type(e).__name__}")
            print(f"  메시지: {e}")


async def test_all() -> None:
    """
    모든 테스트 실행
    """
    print_separator("전체 테스트 실행")

    # 1. Load events
    events = await test_load_events()

    # 2. Search events
    await test_search_events()

    # 3. Fetch single event
    if events:
        # Get first event ID (slug)
        first_event = list(events.values())[0]
        event_id = first_event.id
        print(f"\n첫 번째 이벤트 ID 사용: {event_id}")
        await test_fetch_event(event_id)
    else:
        await test_fetch_event()

    # 4. Cache test
    await test_get_event_from_cache()


async def main() -> None:
    """Main interactive menu."""
    print_separator("Polymarket Event 테스트")

    print("""
이 스크립트는 Polymarket Event API를 대화형으로 테스트합니다.

테스트 가능한 기능:
- load_events(): 이벤트 목록 로드
- search_events(): 키워드로 이벤트 검색
- fetch_event(): 단일 이벤트 상세 조회
- get_event(): 캐시에서 이벤트 조회
""")

    while True:
        print("\n" + "-" * 40)
        print("테스트 선택:")
        print("  1. load_events() - 이벤트 로드")
        print("  2. search_events() - 이벤트 검색")
        print("  3. fetch_event() - 단일 이벤트 조회")
        print("  4. get_event() - 캐시 조회 테스트")
        print("  5. 전체 테스트")
        print("  q. 종료")
        print("-" * 40)

        choice = input("\n선택: ").strip().lower()

        try:
            if choice == "1":
                await test_load_events()
            elif choice == "2":
                await test_search_events()
            elif choice == "3":
                await test_fetch_event()
            elif choice == "4":
                await test_get_event_from_cache()
            elif choice == "5":
                await test_all()
            elif choice == "q" or choice == "quit" or choice == "exit":
                break
            else:
                print("잘못된 선택입니다. 1-5 또는 q를 입력하세요.")

        except KeyboardInterrupt:
            print("\n\n중단됨 (Ctrl+C)")
        except Exception as e:
            print(f"\n에러 발생: {e}")
            import traceback
            traceback.print_exc()

            retry = input("\n계속하시겠습니까? (y/n): ").strip().lower()
            if retry != "y":
                break

    print("\n" + "=" * 60)
    print("  테스트 종료")
    print("=" * 60 + "\n")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n종료됨")
