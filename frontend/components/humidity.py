import streamlit as st


def humidity(data):
    h = data["humidity"]

    if h < 30:
        status_text = "건조 주의"
        status_badge = "badge-warn"
    elif h <= 60:
        status_text = "정상 범위"
        status_badge = "badge-on"
    else:
        status_text = "습도 높음"
        status_badge = "badge-warn"

    st.markdown(f"""
    <div class="card">
      <div class="card-label">실시간 내부 습도</div>
      <div>
        <span class="card-value temp-ok">{h}</span>
        <span class="card-unit">%</span>
      </div>
      <div style="margin-top:0.5rem;">
        <span class="badge {status_badge}">{status_text}</span>
      </div>
      <div class="card-delta" style="visibility:hidden;">
        placeholder
      </div>
    </div>
    """, unsafe_allow_html=True)