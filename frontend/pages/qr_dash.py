import streamlit as st
import streamlit.components.v1 as components
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import qrcode
from io import BytesIO
import base64

st.set_page_config(
    page_title="냉동 공장 전력 가시화",
    page_icon="❄️",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown("""
<style>
 @import url('https://fonts.googleapis.com/css2?family=Julius+Sans+One&family=Noto+Sans+KR:wght@100..900&display=swap');

  :root {
    --bg:        #f0f4f8;
    --surface:   #ffffff;
    --surface2:  #e4ecf4;
    --border:    #c8d9ec;
    --accent:    #0077cc;
    --accent2:   #005fa3;
    --cold:      #0099bb;
    --warm:      #e05252;
    --ok:        #1db86a;
    --warn:      #e07b20;
    --text:      #1a2b3c;
    --muted:     #6b8299;
    --font-head: 'Syne', sans-serif;
    --font-mono: 'DM Mono', monospace;
    --font-body: 'Inter', sans-serif;
  }

  html, body, [class*="css"] {
    background-color: var(--bg) !important;
    color: var(--text) !important;
    font-family: var(--font-body) !important;
  }

  #MainMenu, footer, header { visibility: hidden; }
  .block-container { padding: 1.2rem 1rem 2rem !important; max-width: 480px !important; margin: auto; }

  .dashboard-title {
    font-family: var(--font-head);
    font-size: 1.7rem;
    font-weight: 800;
    letter-spacing: -0.02em;
    color: black;
    line-height: 1.1;
    margin-bottom: 0.15rem;
  }
  .dashboard-sub {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: black;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    margin-bottom: 1.4rem;
  }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 16px;
    padding: 1.1rem 1.2rem;
    margin-bottom: 1rem;
    position: relative;
    overflow: hidden;
    box-shadow: 0 2px 12px rgba(0,80,160,0.07);
  }
  .card::before {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, var(--accent), transparent);
  }
  .card-label {
    font-family: var(--font-mono);
    font-size: 0.8rem;
    color: black
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 0.5rem;
  }
  .card-value {
    font-family: var(--font-head);
    font-size: 2.8rem;
    font-weight: 800;
    line-height: 1;
    letter-spacing: -0.03em;
  }
  .card-unit {
    font-family: var(--font-mono);
    font-size: 1rem;
    color: black
    margin-left: 0.2rem;
  }
  .card-delta {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    margin-top: 0.35rem;
  }

  .temp-cold  { color: var(--cold); }
  .temp-ok    { color: var(--ok); }
  .temp-warn  { color: var(--warm); }

  .badge {
    display: inline-block;
    padding: 0.22rem 0.75rem;
    border-radius: 999px;
    font-family: var(--font-mono);
    font-size: 0.65rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    font-weight: 500;
  }
  .badge-on   { background: rgba(29,184,106,.12); color: var(--ok);   border: 1px solid rgba(29,184,106,.3); }
  .badge-off  { background: rgba(107,130,153,.10); color: var(--muted); border: 1px solid var(--border); }
  .badge-warn { background: rgba(224,82,82,.10);  color: var(--warm); border: 1px solid rgba(224,82,82,.3); }

  .sched-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 0.65rem 0;
    border-bottom: 1px solid var(--border);
    font-size: 0.82rem;
  }
  .sched-row:last-child { border-bottom: none; }
  .sched-name { font-weight: 500; color: var(--text); }
  .sched-time { font-family: var(--font-mono); font-size: 0.7rem; color: var(--muted); margin-top: 0.15rem; }

  .power-bar-bg {
    background: var(--surface2);
    border-radius: 6px;
    height: 8px;
    margin-top: 0.5rem;
    overflow: hidden;
  }
  .power-bar-fill {
    height: 100%;
    border-radius: 6px;
    background: linear-gradient(90deg, var(--accent2), var(--accent));
    transition: width 0.6s ease;
  }

  .qr-wrap {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.6rem;
    padding: 1rem 0 0.5rem;
  }
  .qr-wrap img { border-radius: 12px; border: 3px solid var(--border); }
  .qr-id {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--accent);
    letter-spacing: 0.12em;
  }

  hr { border-color: var(--border) !important; margin: 1rem 0; }

  .js-plotly-plot .plotly { background: transparent !important; }

  div[data-testid="stSelectbox"] label,
  div[data-testid="stSlider"] label { color: var(--muted) !important; font-size: 0.75rem !important; }

  ::-webkit-scrollbar { width: 4px; }
  ::-webkit-scrollbar-thumb { background: var(--border); border-radius: 4px; }

  @keyframes pulse { 0%,100%{opacity:1;transform:scale(1)} 50%{opacity:.5;transform:scale(1.4)} }
  .live-dot {
    display: inline-block;
    width: 7px; height: 7px;
    background: var(--ok);
    border-radius: 50%;
    animation: pulse 1.8s ease-in-out infinite;
    margin-right: 6px;
    vertical-align: middle;
  }
</style>
""", unsafe_allow_html=True)


#임시데이터
@st.cache_data(ttl=5)
def get_factory_data(factory_id: str):
    """공장별 시뮬레이션 데이터 생성"""
    rng = np.random.default_rng(seed=abs(hash(factory_id)) % (2**31))

    # 실시간 온도
    base_temp = -18.0 + rng.uniform(-2, 2)
    current_temp = round(base_temp + rng.uniform(-0.5, 0.5), 1)

    # 24시간 온도 추이
    now = datetime.now()
    times = [now - timedelta(hours=23 - i) for i in range(24)]
    temps = []
    t = -13
    for _ in range(24):
        t += rng.uniform(-0.5, 0.5)
        t = np.clip(t, -22, -13)
        temps.append(round(t, 1))

    # 전력 사용량
    power_now  = round(rng.uniform(42, 68), 1)
    power_max  = 80.0
    power_24h  = round(rng.uniform(900, 1200), 0)

    # 스케줄
    schedules = [
        {"name": "압축기 A-1",  "time": "00:00 – 06:00", "status": "on"},
        {"name": "압축기 A-2",  "time": "06:00 – 12:00", "status": "off"},
        {"name": "냉각팬 B",    "time": "전일 가동",      "status": "on"},
        {"name": "제상 사이클", "time": "04:00 / 16:00",  "status": "warn"},
        {"name": "보조 히터",   "time": "비활성",         "status": "off"},
    ]

    return {
        "temp_now": current_temp,
        "times": times,
        "temps": temps,
        "power_now": power_now,
        "power_max": power_max,
        "power_24h": int(power_24h),
        "schedules": schedules,
        "updated": now.strftime("%H:%M:%S"),
    }


def temp_class(t):
    if t < -20: return "temp-cold"
    if t < -16: return "temp-ok"
    return "temp-warn"

def make_qr(url: str) -> str:
    qr = qrcode.QRCode(box_size=6, border=2,
                       error_correction=qrcode.constants.ERROR_CORRECT_M)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0077cc", back_color="#ffffff")
    buf = BytesIO()
    img.save(buf, format="PNG")
    return base64.b64encode(buf.getvalue()).decode()

factory_id = "FCT-001"
factory_name = "경산 냉동창고 F1"
data = get_factory_data(factory_id)

st.markdown("""<meta http-equiv="refresh" content="30">""", unsafe_allow_html=True)

st.markdown(f"""
<div class="dashboard-title">❄️ {factory_name}</div>
<div class="dashboard-sub">
  <span class="live-dot"></span>LIVE · {factory_id} · {data['updated']}
</div>
""", unsafe_allow_html=True)

t = data["temp_now"]
delta = round(t - data["temps"][-2], 1)
delta_str = f"▲ +{delta}°C 상승" if delta > 0 else f"▼ {delta}°C 하강"
delta_color = "#e05252" if delta > 0 else "#0099bb"

tc = temp_class(t)
if tc == "temp-cold":
    status_text = "과냉각 주의"
    status_badge = "badge-warn"
elif tc == "temp-ok":
    status_text = "정상 범위"
    status_badge = "badge-on"
else:
    status_text = "온도 이상 경보"
    status_badge = "badge-warn"

st.markdown(f"""
<div class="card">
  <div class="card-label">🌡 실시간 내부 온도</div>
  <div>
    <span class="card-value {tc}">{t}</span>
    <span class="card-unit">°C</span>
    &nbsp;&nbsp;
    <span class="badge {status_badge}">{status_text}</span>
  </div>
  <div class="card-delta" style="color:{delta_color};">{delta_str} (1h 전 대비)</div>
</div>
""", unsafe_allow_html=True)

fig = go.Figure()

fig.add_hrect(
    y0=-16, y1=-13,
    fillcolor="rgba(255,107,107,0.08)",
    line_width=0,
    annotation_text="경보 구간",
    annotation_position="top right",
    annotation_font=dict(size=9, color="#ff6b6b")
)

fig.add_hline(
    y=-18,
    line_dash="dot",
    line_color="#c8d9ec",
    annotation_text="-18°C 목표",
    annotation_position="bottom right",
    annotation_font=dict(size=9, color="#6b8299")
)

fig.add_trace(go.Scatter(
    x=data["times"], y=data["temps"],
    mode="lines",
    line=dict(color="#0077cc", width=2.5, shape="spline"),
    fill="tozeroy",
    fillcolor="rgba(0,119,204,0.08)",
    hovertemplate="%{x|%H:%M}<br><b>%{y}°C</b><extra></extra>",
    showlegend=False,
))

fig.add_trace(go.Scatter(
    x=[data["times"][-1]], y=[data["temps"][-1]],
    mode="markers",
    marker=dict(color="#0077cc", size=9, line=dict(color="#ffffff", width=2)),
    showlegend=False,
    hoverinfo="skip",
))

fig.update_layout(
    paper_bgcolor="#ffffff",
    plot_bgcolor="#ffffff",
    margin=dict(l=18, r=10, t=6, b=10),
    height=230,
    showlegend=False,
    xaxis=dict(
        title=None,                
        showgrid=False,
        zeroline=False,
        showline=False,            
        ticks="",
        tickmode="array",
        tickvals=[
            data["times"][0],
            data["times"][6],
            data["times"][12],
            data["times"][18]
        ],
        ticktext=["00시", "06시", "12시", "18시"],
        tickfont=dict(
            family="DM Mono",
            size=9,
            color="#6b8299"
        ),
    ),
    yaxis=dict(
        title=None,                 
        showgrid=True,
        gridcolor="rgba(200,217,236,0.7)",
        gridwidth=1,
        zeroline=False,
        showline=False,            
        ticks="",
        tickmode="array",
        tickvals=[-20, -15, -10, -5],
        ticktext=["-20°", "-15°", "-10°", "-5°"],
        tickfont=dict(
            family="DM Mono",
            size=9,
            color="#6b8299"
        ),
        range=[-21, -4],
    ),
)

chart_html = fig.to_html(include_plotlyjs="cdn", full_html=False)

components.html(f"""
<html>
<head>
<style>
  body {{
    margin: 0;
    padding: 0;
    background: transparent;
    font-family: Inter, sans-serif;
  }}
  .card {{
    background: #ffffff;
    border: 1px solid #c8d9ec;
    border-radius: 16px;
    padding: 1.1rem 1.2rem;
    margin-bottom: 1rem;
    position: relative;
    overflow: hidden;
    box-shadow: 0 2px 12px rgba(0,80,160,0.07);
  }}
  .card::before {{
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: linear-gradient(90deg, #0077cc, transparent);
  }}
  .card-label {{
    font-family: 'DM Mono', monospace;
    font-size: 13px;
    color: black;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    margin-bottom: 0.5rem;
  }}
  .js-plotly-plot .plotly {{
    background: transparent !important;
  }}
</style>
</head>
<body>
  <div class="card">
    <div class="card-label">24시간 온도 추이</div>
    {chart_html}
  </div>
</body>
</html>
""", height=290, scrolling=False)

pw = data["power_now"]
pw_pct = int(pw / data["power_max"] * 100)
pw_color = "#e07b20" if pw_pct > 80 else "#0077cc"

col1, col2 = st.columns(2)
with col1:
    st.markdown(f"""
    <div class="card" style="margin-bottom:0">
      <div class="card-label">⚡ 현재 전력</div>
      <div>
        <span class="card-value" style="font-size:2rem;color:{pw_color}">{pw}</span>
        <span class="card-unit">kW</span>
      </div>
      <div class="power-bar-bg">
        <div class="power-bar-fill" style="width:{pw_pct}%;background:linear-gradient(90deg,{pw_color}99,{pw_color});"></div>
      </div>
      <div style="font-family:'DM Mono',monospace;font-size:0.65rem;color:#6b8299;margin-top:0.3rem;">{pw_pct}% / 정격 {int(data['power_max'])}kW</div>
    </div>
    """, unsafe_allow_html=True)

with col2:
    st.markdown(f"""
    <div class="card" style="margin-bottom:0">
      <div class="card-label">🔋 24h 사용량</div>
      <div>
        <span class="card-value" style="font-size:2rem;color:#1db86a">{data['power_24h']:,}</span>
        <span class="card-unit">kWh</span>
      </div>
      <div style="font-family:'DM Mono',monospace;font-size:0.65rem;color:#6b8299;margin-top:0.85rem;">≈ ₩{int(data['power_24h']*130):,} 예상</div>
    </div>
    """, unsafe_allow_html=True)

st.markdown("<div style='height:1rem'></div>", unsafe_allow_html=True)


badge_map = {
    "on":   ("badge-on",   "가동중"),
    "off":  ("badge-off",  "정지"),
    "warn": ("badge-warn", "점검 필요"),
}

schedule_rows = ""
for s in data["schedules"]:
    bcls, blabel = badge_map[s["status"]]
    schedule_rows += f"""<div class="sched-row">
<div>
<div class="sched-name">{s['name']}</div>
<div class="sched-time">{s['time']}</div>
</div>
<span class="badge {bcls}">{blabel}</span>
</div>"""

st.markdown(f"""<div class="card">
<div class="card-label">현재 스케줄 상태</div>
{schedule_rows}
</div>""", unsafe_allow_html=True)


qr_url = f"http://localhost:8501/?factory={factory_id}"
qr_b64 = make_qr(qr_url)

# st.markdown(f"""
# <div class="card">
#   <div class="card-label">공장 QR 코드</div>
#   <div class="qr-wrap">
#     <img src="data:image/png;base64,{qr_b64}" width="160" alt="QR Code">
#     <div class="qr-id">{factory_id}</div>
#     <div style="font-family:'Inter',sans-serif;font-size:0.72rem;color:#6b8299;text-align:center;">
#       스캔하면 이 대시보드로 바로 이동합니다
#     </div>
#   </div>
# </div>
# """, unsafe_allow_html=True)


st.markdown(f"""
<div style="text-align:center;padding:1.5rem 0 0.5rem;font-family:'DM Mono',monospace;font-size:0.62rem;color:#a0b8cc;letter-spacing:0.1em;">
  {datetime.now().strftime('%Y')} · AUTO REFRESH 30s
</div>
""", unsafe_allow_html=True)