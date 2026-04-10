import os
import httpx
from datetime import datetime, timedelta

SKY_CODE = {"1": "맑음", "3": "구름많음", "4": "흐림"}
PTY_CODE = {"0": "", "1": "비", "2": "비/눈", "3": "눈", "4": "소나기"}

DEFAULT_NX = int(os.getenv("KMA_NX", 60))
DEFAULT_NY = int(os.getenv("KMA_NY", 127))


def _get_base_time() -> tuple[str, str]:
    now = datetime.now()
    hour = now.hour
    base_times = [2, 5, 8, 11, 14, 17, 20, 23]
    base_hour = max((t for t in base_times if t <= hour), default=23)

    if base_hour == 23 and hour < 2:
        base_date = (now - timedelta(days=1)).strftime("%Y%m%d")
    else:
        base_date = now.strftime("%Y%m%d")

    return base_date, f"{base_hour:02d}00"


def _parse_items(items: list, target_date: str) -> list[dict]:
    hourly = {}
    for item in items:
        if item["fcstDate"] == target_date and item["category"] in ("TMP", "SKY", "PTY"):
            h = item["fcstTime"][:2]
            if h not in hourly:
                hourly[h] = {"hour": h, "date": target_date}
            hourly[h][item["category"]] = item["fcstValue"]

    result = []
    for h in sorted(hourly.keys()):
        d = hourly[h]
        pty = PTY_CODE.get(d.get("PTY", "0"), "")
        sky = SKY_CODE.get(d.get("SKY", ""), "알 수 없음")
        result.append({
            "date": target_date,
            "hour": h,
            "temperature_c": float(d.get("TMP", 0)),
            "weather": pty if pty else sky,
        })
    return result


async def _fetch(nx: int, ny: int) -> list:
    api_key = os.getenv("KMA_API_KEY")
    api_url = os.getenv("KMA_API_URL", "https://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getVilageFcst")

    if not api_key:
        raise ValueError("KMA_API_KEY 환경변수가 설정되지 않았습니다.")

    base_date, base_time = _get_base_time()
    params = {
        "serviceKey": api_key,
        "numOfRows": "1000",
        "pageNo": "1",
        "dataType": "JSON",
        "base_date": base_date,
        "base_time": base_time,
        "nx": nx,
        "ny": ny,
    }

    async with httpx.AsyncClient() as client:
        response = await client.get(api_url, params=params, timeout=10)
        response.raise_for_status()

    return response.json()["response"]["body"]["items"]["item"]


async def fetch_today_forecast(nx: int = DEFAULT_NX, ny: int = DEFAULT_NY) -> list[dict]:
    today = datetime.now().strftime("%Y%m%d")
    items = await _fetch(nx, ny)
    return _parse_items(items, today)


async def fetch_tomorrow_forecast(nx: int = DEFAULT_NX, ny: int = DEFAULT_NY) -> list[dict]:
    tomorrow = (datetime.now() + timedelta(days=1)).strftime("%Y%m%d")
    items = await _fetch(nx, ny)
    return _parse_items(items, tomorrow)
