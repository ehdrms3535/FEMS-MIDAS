import streamlit as st


def temp_class(t):
    if t < -20:
        return "temp-cold"
    if t < -16:
        return "temp-ok"
    return "temp-warn"


def temp(data):
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
      <div class="card-label">실시간 내부 온도</div>

      <div>
        <span class="card-value {tc}">{t}</span>
        <span class="card-unit">°C</span>
      </div>

      <div style="margin-top:0.5rem;">
        <span class="badge {status_badge}">{status_text}</span>
      </div>

      <div class="card-delta" style="color:{delta_color};">
        {delta_str} (1시간 전 대비)
      </div>
    </div>
    """, unsafe_allow_html=True)