import streamlit as st


def power_usage(data):
    st.markdown(f"""
    <div class="card power-card">
      <div class="card-label">24시간 사용량</div>
      <div>
        <span class="card-value" style="font-size:2rem;color:#1db86a">
          {data['power_24h']:,}
        </span>
        <span class="card-unit">kWh</span>
      </div>
      <div style="font-family:'DM Mono',monospace;font-size:0.65rem;color:#6b8299;margin-top:0.85rem;">
        ≈ ₩{int(data['power_24h'] * 130):,} 예상
      </div>
    </div>
    """, unsafe_allow_html=True)