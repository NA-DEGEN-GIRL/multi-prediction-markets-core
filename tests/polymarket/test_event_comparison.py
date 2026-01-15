"""
search_events vs fetch_event 데이터 비교 테스트

실행: python tests/polymarket/test_event_comparison.py

두 메서드가 반환하는 Event 객체의 필드 차이를 확인합니다.
"""

import asyncio
import sys
from pathlib import Path

# Load .env from core folder
from dotenv import load_dotenv
env_path = Path(__file__).resolve().parent.parent.parent / ".env"
load_dotenv(env_path)

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from prediction_markets import create_exchange, Event


def compare_events(search_event: Event, fetch_event: Event) -> dict:
    """Compare two Event objects and return differences."""
    differences = {}

    fields = [
        "id", "exchange", "title", "description", "category", "status",
        "start_date", "end_date", "volume_24h", "liquidity",
        "image_url", "tags", "created_at"
    ]

    for field in fields:
        search_val = getattr(search_event, field, None)
        fetch_val = getattr(fetch_event, field, None)

        if search_val != fetch_val:
            differences[field] = {
                "search": search_val,
                "fetch": fetch_val,
            }

    # Compare markets count
    search_market_count = len(search_event.markets)
    fetch_market_count = len(fetch_event.markets)
    if search_market_count != fetch_market_count:
        differences["markets_count"] = {
            "search": search_market_count,
            "fetch": fetch_market_count,
        }

    # Compare raw data keys
    search_keys = set(search_event.raw.keys())
    fetch_keys = set(fetch_event.raw.keys())
    if search_keys != fetch_keys:
        differences["raw_keys"] = {
            "only_in_search": search_keys - fetch_keys,
            "only_in_fetch": fetch_keys - search_keys,
        }

    return differences


def print_event(event: Event, label: str):
    """Print event details."""
    print(f"\n{'='*60}")
    print(f"  {label}")
    print(f"{'='*60}")
    print(f"  ID: {event.id}")
    print(f"  Title: {event.title[:50]}...")
    print(f"  Status: {event.status.value if event.status else 'N/A'}")
    print(f"  Category: {event.category or 'N/A'}")
    print(f"  Markets: {len(event.markets)}개")
    print(f"  Volume 24h: {f'${event.volume_24h:,.2f}' if event.volume_24h else 'N/A'}")
    print(f"  Liquidity: {f'${event.liquidity:,.2f}' if event.liquidity else 'N/A'}")
    print(f"  Tags: {event.tags or 'N/A'}")
    print(f"  End Date: {event.end_date or 'N/A'}")
    print(f"  Created At: {event.created_at or 'N/A'}")
    print(f"  Raw Keys: {list(event.raw.keys())}")

    if event.markets:
        print(f"\n  First Market:")
        m = event.markets[0]
        print(f"    ID: {m.id[:40]}...")
        print(f"    Title: {m.title[:40]}...")
        print(f"    Status: {m.status.value if m.status else 'N/A'}")
        print(f"    Raw Keys: {list(m.raw.keys())[:10]}...")


async def main():
    print("="*60)
    print("  search_events vs fetch_event 비교 테스트")
    print("="*60)

    keyword = input("\n검색어 입력 (Enter='bitcoin'): ").strip() or "bitcoin"

    async with create_exchange("polymarket") as exchange:
        # 1. Search events
        print(f"\n[1] search_events('{keyword}') 호출...")
        search_results = await exchange.search_events(keyword, limit=3)

        if not search_results:
            print("검색 결과 없음")
            return

        print(f"    → {len(search_results)}개 이벤트 반환")

        # 2. Pick first event
        search_event = search_results[0]
        event_id = search_event.id

        print_event(search_event, f"search_events 결과 (ID: {event_id})")

        # 3. Fetch same event
        print(f"\n[2] fetch_event('{event_id}') 호출...")
        try:
            fetch_event = await exchange.fetch_event(event_id)
            print_event(fetch_event, f"fetch_event 결과 (ID: {event_id})")
        except Exception as e:
            print(f"    → 에러: {e}")
            return

        # 4. Compare
        print(f"\n{'='*60}")
        print("  비교 결과")
        print(f"{'='*60}")

        differences = compare_events(search_event, fetch_event)

        if not differences:
            print("\n  ✅ 두 Event 객체가 동일합니다!")
        else:
            print(f"\n  ❌ {len(differences)}개 차이 발견:\n")
            for field, diff in differences.items():
                print(f"  [{field}]")
                if isinstance(diff, dict):
                    for k, v in diff.items():
                        # Truncate long values
                        v_str = str(v)
                        if len(v_str) > 60:
                            v_str = v_str[:60] + "..."
                        print(f"    {k}: {v_str}")
                print()

        # 5. Compare first market if exists
        if search_event.markets and fetch_event.markets:
            print(f"\n{'='*60}")
            print("  첫 번째 Market 비교")
            print(f"{'='*60}")

            sm = search_event.markets[0]
            fm = fetch_event.markets[0]

            market_fields = [
                "id", "slug", "title", "status", "category",
                "volume_24h", "liquidity", "end_date"
            ]

            market_diff = {}
            for field in market_fields:
                sv = getattr(sm, field, None)
                fv = getattr(fm, field, None)
                if sv != fv:
                    market_diff[field] = {"search": sv, "fetch": fv}

            # Raw keys comparison
            sm_keys = set(sm.raw.keys())
            fm_keys = set(fm.raw.keys())
            if sm_keys != fm_keys:
                market_diff["raw_keys"] = {
                    "only_in_search": sm_keys - fm_keys,
                    "only_in_fetch": fm_keys - sm_keys,
                }

            if not market_diff:
                print("\n  ✅ Market 객체도 동일합니다!")
            else:
                print(f"\n  ❌ Market에서 {len(market_diff)}개 차이:\n")
                for field, diff in market_diff.items():
                    print(f"  [{field}]")
                    for k, v in diff.items():
                        v_str = str(v)
                        if len(v_str) > 60:
                            v_str = v_str[:60] + "..."
                        print(f"    {k}: {v_str}")
                    print()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n\n중단됨")
