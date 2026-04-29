import streamlit as st


def schedule(data):
    badge_map = {
        "on": ("badge-on", "ON"),
        "off": ("badge-off", "OFF"),
        "warn": ("badge-warn", "점검 필요"),
    }

    schedule_rows = ""

    for s in data["schedules"]:
        bcls, blabel = badge_map.get(s["status"], ("badge-off", "알 수 없음"))

        schedule_rows += f"""
<div class="sched-row">
  <div>
    <div class="sched-name">{s['name']}</div>
    <div class="sched-time">{s['time']}</div>
  </div>
  <span class="badge {bcls}">{blabel}</span>
</div>
"""

    st.markdown(
        f"""
<div class="card">
  <div class="card-label">현재 스케줄 상태</div>
  {schedule_rows}
</div>
""",
        unsafe_allow_html=True,
    )