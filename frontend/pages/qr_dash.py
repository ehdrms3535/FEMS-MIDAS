import streamlit as st
from datetime import datetime, timedelta
from pathlib import Path
import sys
import requests

BASE_DIR = Path(__file__).resolve().parent.parent
sys.path.append(str(BASE_DIR))

from components.temperature import temp
from components.humidity import humidity
from components.tempchart import temp_chart
from components.power import power
from components.powerusage import power_usage
from components.schedule import schedule


st.set_page_config(
    page_title="냉동 공장 전력 가시화",
    page_icon="❄️",
    layout="wide",
    initial_sidebar_state="collapsed",
)


def load_css(file_path):
    with open(file_path, "r", encoding="utf-8") as f:
        st.markdown(f"<style>{f.read()}</style>", unsafe_allow_html=True)


CSS_PATH = BASE_DIR / "styles" / "qr.css"
load_css(CSS_PATH)


API_BASE_URL = "http://localhost:8000"


@st.cache_data(ttl=5)
def get_factory_data(token: str):
    url = f"{API_BASE_URL}/api/v1/readonly/{token}"

    response = requests.get(url, timeout=5)
    response.raise_for_status()

    result = response.json()

    if not result["success"]:
        raise Exception(result["error"]["message"])

    api_data = result["data"]

    now = datetime.now()
    times = [now - timedelta(hours=23 - i) for i in range(24)]
    temps = [api_data["temperature_c"] for _ in range(24)]

    return {
        "factory_id": api_data["factory_id"],
        "factory_name": api_data["factory_name"],
        "status": api_data["status"],
        "temp_now": api_data["temperature_c"],
        "humidity": api_data["humidity_pct"],
        "updated": api_data["last_updated_at"][11:19],
        "times": times,
        "temps": temps,
        "power_now": 0,
        "power_max": 80.0,
        "power_24h": 0,
        "schedules": [
            {
                "name": "현재 스케줄 모드",
                "time": "",
                "status": "on" if api_data["current_schedule_mode"] == "ON" else "off",
            },
            {
                "name": "다음 스케줄",
                "time": f"{api_data['next_schedule']['start_at'][11:16]} - {api_data['next_schedule']['end_at'][11:16]}",
                "status": "on" if api_data["next_schedule"]["mode"] == "ON" else "off",
            },
        ],
    }


token = st.query_params.get("token", "rdonly_test_1")

try:
    data = get_factory_data(token)
except Exception as e:
    st.error("데이터를 불러오지 못했습니다.")
    st.caption(str(e))
    st.stop()

factory_name = data["factory_name"]

status_map = {
    "NORMAL": "정상",
    "WARNING": "주의",
    "ERROR": "이상",
}

status_badge_map = {
    "NORMAL": "badge-on",
    "WARNING": "badge-warn",
    "ERROR": "badge-warn",
}

status_text = status_map.get(data["status"], data["status"])

st.markdown("""<meta http-equiv="refresh" content="30">""", unsafe_allow_html=True)

st.markdown(
    f"""
<div class="dashboard-title">
  {factory_name}
  <span class="badge badge-on" style="vertical-align:middle; margin-left:0.4rem;">
    {status_text}
  </span>
</div>
<div class="dashboard-sub">
  <span class="live-dot"></span>LIVE · {data['updated']}
</div>
""",
    unsafe_allow_html=True,
)

# 정상 뱃지 하단 ver 
# st.markdown(
#     f"""
# <div class="dashboard-title">{factory_name}</div>
# <div class="dashboard-sub">
#   <span class="live-dot"></span>LIVE · {factory_id} · {data['updated']}
#   &nbsp; <span class="badge badge-on">{status}</span>
# </div>
# """,
#     unsafe_allow_html=True,
# )


col1, col2 = st.columns(2)

with col1:
    temp(data)

with col2:
    humidity(data)


temp_chart(data)


col1, col2 = st.columns(2)

with col1:
    power(data)

with col2:
    power_usage(data)


schedule(data)


st.markdown(
    f"""
<div style="text-align:center;padding:1.5rem 0 0.5rem;font-family:'DM Mono',monospace;font-size:0.62rem;color:#a0b8cc;letter-spacing:0.1em;">
  {datetime.now().strftime('%Y')} · AUTO REFRESH 30s
</div>
""",
    unsafe_allow_html=True,
)