from fastapi import APIRouter, HTTPException, Query
from services.weather_service import fetch_today_forecast, fetch_tomorrow_forecast

router = APIRouter(prefix="/api/v1/weather", tags=["weather"])


@router.get("/today")
async def today_forecast(
    nx: int = Query(default=60, description="기상청 격자 X (기본: 서울)"),
    ny: int = Query(default=127, description="기상청 격자 Y (기본: 서울)"),
):
    try:
        data = await fetch_today_forecast(nx, ny)
        return {"date": "today", "forecasts": data}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"기상청 API 오류: {e}")


@router.get("/tomorrow")
async def tomorrow_forecast(
    nx: int = Query(default=60, description="기상청 격자 X (기본: 서울)"),
    ny: int = Query(default=127, description="기상청 격자 Y (기본: 서울)"),
):
    try:
        data = await fetch_tomorrow_forecast(nx, ny)
        return {"date": "tomorrow", "forecasts": data}
    except ValueError as e:
        raise HTTPException(status_code=503, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"기상청 API 오류: {e}")
