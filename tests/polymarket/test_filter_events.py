"""
Polymarket filter_events 테스트

filter_events()로 다양한 조건으로 이벤트 필터링:
- 거래량/유동성 범위
- 날짜 범위
- 태그/카테고리
- 정렬

실행: python tests/polymarket/test_filter_events.py
"""

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load .env from core folder
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from prediction_markets import create_exchange, Event


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


def print_event_summary(events: list[Event], show_markets: bool = False):
    """Print event list summary."""
    if not events:
        print("  결과 없음")
        return

    for i, event in enumerate(events, 1):
        status = event.status.value if event.status else "N/A"
        volume = f"${event.volume:,.0f}" if event.volume else "N/A"
        volume24h = f"${event.volume_24h:,.0f}" if event.volume_24h else "N/A"
        liquidity = f"${event.liquidity:,.0f}" if event.liquidity else "N/A"
        end_date = event.end_date.strftime("%Y-%m-%d") if event.end_date else "N/A"

        print(f"\n  {i}. [{status}] {truncate(event.title, 45)}")
        print(f"     ID: {event.id}")
        print(f"     총 거래량: {volume} | 유동성: {liquidity}")
        print(f"     거래량 24h: {volume24h} | 유동성: {liquidity}")
        print(f"     종료일: {end_date} | 마켓: {len(event.markets)}개")

        if show_markets and event.markets:
            for market in event.markets[:3]:
                print(f"     └─ {truncate(market.title, 40)}")
            if len(event.markets) > 3:
                print(f"     └─ ... (+{len(event.markets) - 3}개)")

    print(f"\n  총 {len(events)}개 이벤트")


async def test_high_volume():
    """고거래량 이벤트 조회."""
    print_header("고거래량 이벤트 (volume_min=100000)")

    async with create_exchange("polymarket") as exchange:
        events = await exchange.filter_events(
            volume_min=100000,
            order="volume",
            limit=100
        )
        print_event_summary(events)


async def test_high_liquidity():
    """고유동성 이벤트 조회."""
    print_header("고유동성 이벤트 (liquidity_min=50000)")

    async with create_exchange("polymarket") as exchange:
        events = await exchange.filter_events(
            liquidity_min=50000,
            order="liquidity",
            limit=10
        )
        print_event_summary(events)


async def test_ending_soon():
    """곧 종료되는 이벤트 조회."""
    print_header("다음 7일 내 종료 이벤트")

    next_week = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()

    async with create_exchange("polymarket") as exchange:
        events = await exchange.filter_events(
            end_date_max=next_week,
            order="endDate",
            ascending=True,
            limit=10
        )
        print_event_summary(events)


async def test_by_tag():
    """태그별 이벤트 조회."""
    print_header("태그별 이벤트 필터링")

    tags = ["crypto", "politics", "sports"]

    print("\n사용 가능한 태그:")
    for i, tag in enumerate(tags, 1):
        print(f"  {i}. {tag}")
    print(f"  {len(tags) + 1}. 직접 입력")

    choice = input(f"\n선택 (1-{len(tags) + 1}, Enter=crypto): ").strip()

    if not choice:
        tag = "crypto"
    elif choice == str(len(tags) + 1):
        tag = input("태그 입력: ").strip()
    else:
        try:
            idx = int(choice) - 1
            tag = tags[idx] if 0 <= idx < len(tags) else "crypto"
        except ValueError:
            tag = "crypto"

    print(f"\n'{tag}' 태그 이벤트 검색 중...")

    async with create_exchange("polymarket") as exchange:
        events = await exchange.filter_events(
            tag_slug=tag,
            order="volume",
            limit=10
        )
        print_event_summary(events, show_markets=True)


async def test_date_range():
    """날짜 범위 이벤트 조회."""
    print_header("날짜 범위 필터링")

    print("\n날짜 범위 선택:")
    print("  1. 이번 주 종료")
    print("  2. 이번 달 종료")
    print("  3. 특정 날짜 범위")

    choice = input("\n선택 (1-3, Enter=1): ").strip() or "1"

    now = datetime.now(timezone.utc)

    if choice == "1":
        # This week
        days_until_sunday = 6 - now.weekday()
        end_date_max = (now + timedelta(days=days_until_sunday)).replace(
            hour=23, minute=59, second=59
        ).isoformat()
        title = "이번 주 종료 이벤트"
    elif choice == "2":
        # This month
        if now.month == 12:
            end_date_max = datetime(now.year + 1, 1, 1, tzinfo=timezone.utc).isoformat()
        else:
            end_date_max = datetime(now.year, now.month + 1, 1, tzinfo=timezone.utc).isoformat()
        title = "이번 달 종료 이벤트"
    else:
        # Custom range
        print("\n종료일 범위 입력 (ISO format 또는 YYYY-MM-DD)")
        end_min = input("  시작 (Enter=생략): ").strip() or None
        end_max = input("  끝 (Enter=생략): ").strip() or None

        if end_min and "T" not in end_min:
            end_min = f"{end_min}T00:00:00Z"
        if end_max and "T" not in end_max:
            end_max = f"{end_max}T23:59:59Z"

        end_date_max = end_max
        title = f"종료일 범위: {end_min or '∞'} ~ {end_max or '∞'}"

    print(f"\n{title}")

    async with create_exchange("polymarket") as exchange:
        events = await exchange.filter_events(
            end_date_max=end_date_max if choice != "3" else end_max,
            end_date_min=None if choice != "3" else (end_min if choice == "3" else None),
            order="endDate",
            ascending=True,
            limit=15
        )
        print_event_summary(events)


async def test_custom_filter():
    """커스텀 필터 조합."""
    print_header("커스텀 필터 조합")

    print("\n필터 옵션 설정:")

    # Volume
    vol_min = input("  최소 거래량 (Enter=생략): ").strip()
    vol_min = float(vol_min) if vol_min else None

    vol_max = input("  최대 거래량 (Enter=생략): ").strip()
    vol_max = float(vol_max) if vol_max else None

    # Liquidity
    liq_min = input("  최소 유동성 (Enter=생략): ").strip()
    liq_min = float(liq_min) if liq_min else None

    liq_max = input("  최대 유동성 (Enter=생략): ").strip()
    liq_max = float(liq_max) if liq_max else None

    # Start date range
    print("\n  시작일 범위 (YYYY-MM-DD 또는 ISO format):")
    start_min = input("    시작일 최소 (Enter=생략): ").strip() or None
    start_max = input("    시작일 최대 (Enter=생략): ").strip() or None

    if start_min and "T" not in start_min:
        start_min = f"{start_min}T00:00:00Z"
    if start_max and "T" not in start_max:
        start_max = f"{start_max}T23:59:59Z"

    # End date range
    print("\n  종료일 범위 (YYYY-MM-DD 또는 ISO format):")
    end_min = input("    종료일 최소 (Enter=생략): ").strip() or None
    end_max = input("    종료일 최대 (Enter=생략): ").strip() or None

    if end_min and "T" not in end_min:
        end_min = f"{end_min}T00:00:00Z"
    if end_max and "T" not in end_max:
        end_max = f"{end_max}T23:59:59Z"

    # Tag
    print("\n  태그 예시: crypto, politics, sports, pop-culture, science")
    tag = input("  태그 (Enter=생략): ").strip() or None

    # Order
    print("\n  정렬 기준:")
    print("    1. volume (총 거래량)")
    print("    2. volume24hr (24시간 거래량)")
    print("    3. liquidity (유동성)")
    print("    4. endDate (종료일)")
    print("    5. startDate (시작일)")
    order_choice = input("  선택 (1-5, Enter=1): ").strip() or "1"
    order_map = {"1": "volume", "2": "volume24hr", "3": "liquidity", "4": "endDate", "5": "startDate"}
    order = order_map.get(order_choice, "volume")

    # Ascending
    asc = input("  오름차순? (y/N): ").strip().lower() == "y"

    # Limit
    limit_str = input("  결과 수 (Enter=10): ").strip() or "10"
    limit = int(limit_str)

    # Summary
    print("\n적용 필터:")
    if vol_min or vol_max:
        print(f"  거래량: {vol_min or '∞'} ~ {vol_max or '∞'}")
    if liq_min or liq_max:
        print(f"  유동성: {liq_min or '∞'} ~ {liq_max or '∞'}")
    if start_min or start_max:
        print(f"  시작일: {start_min or '∞'} ~ {start_max or '∞'}")
    if end_min or end_max:
        print(f"  종료일: {end_min or '∞'} ~ {end_max or '∞'}")
    if tag:
        print(f"  태그: {tag}")
    print(f"  정렬: {order} ({'오름차순' if asc else '내림차순'})")

    print("\n검색 중...")

    async with create_exchange("polymarket") as exchange:
        events = await exchange.filter_events(
            volume_min=vol_min,
            volume_max=vol_max,
            liquidity_min=liq_min,
            liquidity_max=liq_max,
            start_date_min=start_min,
            start_date_max=start_max,
            end_date_min=end_min,
            end_date_max=end_max,
            tag_slug=tag,
            order=order,
            ascending=asc,
            limit=limit
        )
        print_event_summary(events, show_markets=True)


async def test_featured():
    """Featured 이벤트 조회."""
    print_header("Featured 이벤트")

    async with create_exchange("polymarket") as exchange:
        events = await exchange.filter_events(
            featured=True,
            order="volume",
            limit=10
        )
        print_event_summary(events, show_markets=True)


async def main():
    """Main menu."""
    print_header("Polymarket filter_events 테스트")

    print("""
  filter_events()로 다양한 조건으로 이벤트 필터링:
  - 거래량/유동성 범위
  - 날짜 범위 (종료일, 시작일)
  - 태그/카테고리
  - 정렬 옵션
""")

    while True:
        print("\n선택:")
        print("  1. 고거래량 이벤트")
        print("  2. 고유동성 이벤트")
        print("  3. 곧 종료되는 이벤트")
        print("  4. 태그별 이벤트")
        print("  5. 날짜 범위 필터")
        print("  6. 커스텀 필터 조합")
        print("  7. Featured 이벤트")
        print("  q. 종료")

        choice = input("\n선택: ").strip().lower()

        try:
            if choice == "1":
                await test_high_volume()
            elif choice == "2":
                await test_high_liquidity()
            elif choice == "3":
                await test_ending_soon()
            elif choice == "4":
                await test_by_tag()
            elif choice == "5":
                await test_date_range()
            elif choice == "6":
                await test_custom_filter()
            elif choice == "7":
                await test_featured()
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
